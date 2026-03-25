from __future__ import annotations

import queue
import sys
import threading
import time
from collections.abc import Callable
from collections import deque
from dataclasses import dataclass, field
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING

import grpc

from hackarena3.game_token import GameTokenError
from hackarena3.proto.race.v1 import race_pb2
from hackarena3.runtime_common import (
    AUTH_CODES,
    REQUESTED_HZ,
    RETRY_BACKOFF_SECONDS,
    TRANSIENT_CODES,
    RuntimeErrorWrapper,
)
from hackarena3.runtime_convert import build_car_dimensions, build_race_snapshot
from hackarena3.types import (
    _BotContextActions,
    Controls,
    GearShift,
    RaceSnapshot,
    TireType,
)

if TYPE_CHECKING:
    from hackarena3.game_token import GameTokenProvider
    from hackarena3.runtime_race import RaceApi
    from hackarena3.types import BotContext, BotProtocol


StreamMetadataProvider = Callable[[], tuple[tuple[str, str], ...]]


_RUNTIME_POLL_SECONDS = 0.2
_TOKEN_REFRESH_SKEW_SECONDS = 30
_ACK_LATENCY_WARN_THRESHOLD_S = 2.0 / float(REQUESTED_HZ)


def _resolve_wrapper_version() -> str:
    try:
        return importlib_metadata.version("hackarena3")
    except importlib_metadata.PackageNotFoundError:
        return "dev"


_WRAPPER_VERSION = _resolve_wrapper_version()


@dataclass(slots=True)
class _PendingAck:
    started_monotonic: float


@dataclass(slots=True)
class _PendingCommandAck:
    started_monotonic: float
    command_kind: str


@dataclass(slots=True)
class _OutboundCommand:
    kind: str
    next_tire_type: int | None = None


@dataclass(slots=True)
class _SessionState:
    stop_event: threading.Event = field(default_factory=threading.Event)
    snapshot_event: threading.Event = field(default_factory=threading.Event)
    outbound_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    latest_snapshot: RaceSnapshot | None = None
    latest_snapshot_version: int = 0
    desired_controls: Controls | None = None
    controls_dirty: bool = False
    pending_commands: deque[_OutboundCommand] = field(default_factory=deque)
    next_client_seq: int = 0
    pending_acks: dict[int, _PendingAck] = field(default_factory=dict[int, _PendingAck])
    pending_command_acks: dict[int, _PendingCommandAck] = field(
        default_factory=dict[int, _PendingCommandAck]
    )
    stream_error: grpc.RpcError | None = None
    fatal_error: RuntimeErrorWrapper | None = None


class _OutboundMessageIterator:
    def __init__(self) -> None:
        self._queue: queue.Queue[race_pb2.ParticipantClientMessage | None] = (
            queue.Queue()
        )
        self._closed = False
        self._lock = threading.Lock()

    def put(self, message: race_pb2.ParticipantClientMessage) -> None:
        with self._lock:
            if self._closed:
                return
        self._queue.put(message)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._queue.put(None)

    def __iter__(self) -> _OutboundMessageIterator:
        return self

    def __next__(self) -> race_pb2.ParticipantClientMessage:
        item = self._queue.get()
        if item is None:
            raise StopIteration
        return item


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_controls(controls: Controls) -> Controls:
    try:
        throttle = float(controls.throttle)
        brake = float(controls.brake)
        steering = float(controls.steering)
        brake_balancer = float(controls.brake_balancer)
        differential_lock = float(controls.differential_lock)
    except (TypeError, ValueError) as exc:
        raise RuntimeErrorWrapper(
            "set_controls received non-numeric value; throttle/brake/steer/brake_balancer/differential_lock must be floats."
        ) from exc

    clamped = Controls(
        throttle=_clamp(throttle, 0.0, 1.0),
        brake=_clamp(brake, 0.0, 1.0),
        steering=_clamp(steering, -1.0, 1.0),
        gear_shift=controls.gear_shift,
        brake_balancer=_clamp(brake_balancer, 0.0, 1.0),
        differential_lock=_clamp(differential_lock, 0.0, 1.0),
    )
    if (
        clamped.throttle != throttle
        or clamped.brake != brake
        or clamped.steering != steering
        or clamped.brake_balancer != brake_balancer
        or clamped.differential_lock != differential_lock
    ):
        print(
            "[ha3-wrapper] Bot set_controls out-of-range values were clamped "
            f"(thr={throttle}, brk={brake}, str={steering}, bb={brake_balancer}, dl={differential_lock}).",
            file=sys.stderr,
        )
    return clamped


def _normalize_gear_shift(gear_shift: GearShift) -> int:
    try:
        return int(GearShift(gear_shift))
    except Exception:
        print(
            "[ha3-wrapper] Invalid gear_shift in set_controls; using GEAR_SHIFT_NONE.",
            file=sys.stderr,
        )
        return int(race_pb2.GEAR_SHIFT_NONE)


def _set_desired_controls(
    state: _SessionState,
    controls: Controls,
) -> None:
    with state.lock:
        state.desired_controls = controls
        state.controls_dirty = True
    state.outbound_event.set()


def _enqueue_command(state: _SessionState, command: _OutboundCommand) -> None:
    with state.lock:
        state.pending_commands.append(command)
    state.outbound_event.set()


def _handle_ack(state: _SessionState, ack: race_pb2.ParticipantControlsAck) -> None:
    pending: _PendingAck | None
    with state.lock:
        pending = state.pending_acks.pop(int(ack.client_seq), None)
    if pending is None:
        return

    elapsed_s = max(0.0, time.monotonic() - pending.started_monotonic)
    if elapsed_s > _ACK_LATENCY_WARN_THRESHOLD_S:
        print(
            "[ha3-wrapper] Controls ack latency warning: "
            f"seq={int(ack.client_seq)} "
            f"rtt_ms={elapsed_s * 1000.0:.1f} "
            f"threshold_ms={_ACK_LATENCY_WARN_THRESHOLD_S * 1000.0:.1f}",
            file=sys.stderr,
        )


def _enum_name(enum_obj: object, value: int) -> str:
    try:
        return str(getattr(enum_obj, "Name")(value))
    except Exception:
        return str(value)


def _handle_command_ack(
    state: _SessionState,
    ack: race_pb2.ParticipantCommandAck,
) -> None:
    pending: _PendingCommandAck | None
    client_seq = int(ack.client_seq)
    with state.lock:
        pending = state.pending_command_acks.pop(client_seq, None)

    if pending is None:
        return

    elapsed_s = max(0.0, time.monotonic() - pending.started_monotonic)
    if elapsed_s > _ACK_LATENCY_WARN_THRESHOLD_S:
        print(
            "[ha3-wrapper] Command ack latency warning: "
            f"seq={client_seq} command={pending.command_kind} "
            f"rtt_ms={elapsed_s * 1000.0:.1f} "
            f"threshold_ms={_ACK_LATENCY_WARN_THRESHOLD_S * 1000.0:.1f}",
            file=sys.stderr,
        )

    if int(ack.status) == int(race_pb2.PARTICIPANT_COMMAND_STATUS_REJECTED):
        command_type = _enum_name(
            race_pb2.ParticipantCommandType, int(ack.command_type)
        )
        rejected_reason = _enum_name(
            race_pb2.ParticipantCommandRejectReason,
            int(ack.rejected_reason),
        )
        cooldown_remaining_ms = int(ack.cooldown_remaining_ms)
        print(
            "[ha3-wrapper] Participant command rejected: "
            f"seq={client_seq} command={pending.command_kind} "
            f"command_type={command_type} reason={rejected_reason} "
            f"cooldown_remaining_ms={cooldown_remaining_ms}",
            file=sys.stderr,
        )


def _reader_loop(
    stream_call: grpc.Call,
    state: _SessionState,
    ctx: BotContext,
    expected_map_id: str | None = None,
) -> None:
    last_effective_hz: int | None = None
    last_map_id: str | None = None
    try:
        for event in stream_call:
            if state.stop_event.is_set():
                break
            payload_name = event.WhichOneof("payload")
            if payload_name == "settings":
                effective_hz = int(event.settings.effective_hz)
                ctx.effective_hz = effective_hz if effective_hz > 0 else None
                stream_map_id = event.settings.map_id.strip()
                if stream_map_id:
                    if (
                        expected_map_id is not None
                        and expected_map_id.strip()
                        and stream_map_id != expected_map_id
                    ):
                        state.fatal_error = RuntimeErrorWrapper(
                            "Stream map_id mismatch: "
                            f"prepared={expected_map_id!r}, stream={stream_map_id!r}."
                        )
                        state.stop_event.set()
                        break
                    ctx.map_id = stream_map_id
                if last_effective_hz != ctx.effective_hz or last_map_id != ctx.map_id:
                    map_suffix = f" map_id={ctx.map_id}" if ctx.map_id else ""
                    print(
                        f"[ha3-wrapper] Stream settings: effective_hz={ctx.effective_hz}{map_suffix}",
                        file=sys.stderr,
                    )
                    last_effective_hz = ctx.effective_hz
                    last_map_id = ctx.map_id
                continue

            if payload_name == "ack":
                _handle_ack(state, event.ack)
                continue

            if payload_name == "command_ack":
                _handle_command_ack(state, event.command_ack)
                continue

            if payload_name == "bootstrap":
                ctx.car_dimensions = build_car_dimensions(event.bootstrap.car_dimensions)
                print(
                    "[ha3-wrapper] Stream bootstrap: "
                    f"car_width_m={ctx.car_dimensions.width_m:.3f} "
                    f"car_depth_m={ctx.car_dimensions.depth_m:.3f}",
                    file=sys.stderr,
                )
                continue

            if payload_name != "snapshot":
                continue

            snapshot = build_race_snapshot(event.snapshot)
            with state.lock:
                state.latest_snapshot = snapshot
                state.latest_snapshot_version += 1
            state.snapshot_event.set()
    except grpc.RpcError as exc:
        if not state.stop_event.is_set():
            state.stream_error = exc
            state.stop_event.set()
    except Exception as exc:
        if not state.stop_event.is_set():
            state.fatal_error = RuntimeErrorWrapper(f"Reader loop failed: {exc}")
            state.stop_event.set()
    else:
        if not state.stop_event.is_set():
            state.fatal_error = RuntimeErrorWrapper(
                "Participant stream ended unexpectedly."
            )
            state.stop_event.set()
    finally:
        state.snapshot_event.set()
        state.outbound_event.set()


def _callback_loop(
    bot: BotProtocol,
    state: _SessionState,
    ctx: BotContext,
) -> None:
    processed_version = 0
    while not state.stop_event.is_set():
        state.snapshot_event.wait(_RUNTIME_POLL_SECONDS)
        state.snapshot_event.clear()
        if state.stop_event.is_set():
            break

        with state.lock:
            snapshot = state.latest_snapshot
            snapshot_version = state.latest_snapshot_version

        if snapshot is None or snapshot_version == processed_version:
            continue
        processed_version = snapshot_version
        ctx.tick = snapshot.tick
        ctx.car_id = snapshot.car.car_id

        try:
            result = bot.on_tick(snapshot, ctx)
        except Exception as exc:
            if not state.stop_event.is_set():
                state.fatal_error = RuntimeErrorWrapper(f"Bot on_tick failed: {exc}")
                state.stop_event.set()
            break

        if result is not None:
            if not state.stop_event.is_set():
                state.fatal_error = RuntimeErrorWrapper(
                    "Bot on_tick must return None. Use ctx.set_controls(...)."
                )
                state.stop_event.set()
            break


def _writer_loop(
    outbound: _OutboundMessageIterator,
    state: _SessionState,
) -> None:
    while not state.stop_event.is_set():
        state.outbound_event.wait(_RUNTIME_POLL_SECONDS)
        state.outbound_event.clear()
        if state.stop_event.is_set():
            break

        while not state.stop_event.is_set():
            message: race_pb2.ParticipantClientMessage | None = None
            with state.lock:
                if state.pending_commands:
                    command = state.pending_commands.popleft()
                    state.next_client_seq += 1
                    client_seq = state.next_client_seq
                    state.pending_command_acks[client_seq] = _PendingCommandAck(
                        started_monotonic=time.monotonic(),
                        command_kind=command.kind,
                    )
                    if command.kind == "emergency_pitstop":
                        message = race_pb2.ParticipantClientMessage(
                            emergency_pitstop=race_pb2.ParticipantEmergencyPitstopCommand(
                                client_seq=client_seq
                            )
                        )
                    elif command.kind == "back_to_track":
                        message = race_pb2.ParticipantClientMessage(
                            back_to_track=race_pb2.ParticipantBackToTrackCommand(
                                client_seq=client_seq
                            )
                        )
                    elif command.kind == "set_next_pit_tire_type":
                        if command.next_tire_type is None:
                            if not state.stop_event.is_set():
                                state.fatal_error = RuntimeErrorWrapper(
                                    "Missing next_tire_type for set_next_pit_tire_type command."
                                )
                                state.stop_event.set()
                            break
                        message = race_pb2.ParticipantClientMessage(
                            set_next_pit_tire_type=race_pb2.ParticipantSetNextPitTireTypeCommand(
                                client_seq=client_seq,
                                next_tire_type=command.next_tire_type,
                            )
                        )
                    else:
                        if not state.stop_event.is_set():
                            state.fatal_error = RuntimeErrorWrapper(
                                f"Unsupported participant command kind: {command.kind}"
                            )
                            state.stop_event.set()
                        break
                else:
                    controls = state.desired_controls
                    if controls is None:
                        break
                    if not state.controls_dirty:
                        break
                    state.controls_dirty = False
                    state.next_client_seq += 1
                    client_seq = state.next_client_seq
                    send_controls = controls

                    try:
                        normalized = _normalize_controls(send_controls)
                    except RuntimeErrorWrapper as exc:
                        if not state.stop_event.is_set():
                            state.fatal_error = exc
                            state.stop_event.set()
                        break

                    message = race_pb2.ParticipantClientMessage(
                        controls=race_pb2.ParticipantControlsInput(
                            client_seq=client_seq,
                            throttle=normalized.throttle,
                            brake=normalized.brake,
                            steering=normalized.steering,
                            gear_shift=_normalize_gear_shift(normalized.gear_shift),
                            brake_balancer=normalized.brake_balancer,
                            differential_lock=normalized.differential_lock,
                        )
                    )
                    state.pending_acks[client_seq] = _PendingAck(
                        started_monotonic=time.monotonic(),
                    )

            if message is None:
                break
            if state.stop_event.is_set():
                break
            outbound.put(message)

            with state.lock:
                if state.pending_commands or state.controls_dirty:
                    state.outbound_event.set()


def _stream_init_message() -> race_pb2.ParticipantClientMessage:
    return race_pb2.ParticipantClientMessage(
        init=race_pb2.ParticipantStreamInit(
            wrapper_type=race_pb2.PARTICIPANT_WRAPPER_TYPE_PYTHON,
            wrapper_version=_WRAPPER_VERSION,
        )
    )


def _open_participant_stream(
    api: RaceApi,
    outbound: _OutboundMessageIterator,
    *,
    metadata: tuple[tuple[str, str], ...],
    stream_method: str | None,
) -> grpc.Call:
    if stream_method is None:
        return api.participant.Stream(  # type: ignore
            outbound,
            metadata=metadata,
        )

    stream_rpc = api.channel.stream_stream(
        stream_method,
        request_serializer=race_pb2.ParticipantClientMessage.SerializeToString,
        response_deserializer=race_pb2.ParticipantServerEvent.FromString,
    )
    return stream_rpc(
        outbound,
        metadata=metadata,
    )


def run_participant_loop(
    bot: BotProtocol,
    api: RaceApi,
    ctx: BotContext,
    *,
    metadata_provider: StreamMetadataProvider,
    token_provider: GameTokenProvider | None = None,
    allow_auth_refresh: bool = True,
    stream_method: str | None = None,
    expected_map_id: str | None = None,
) -> None:
    if allow_auth_refresh and token_provider is None:
        raise RuntimeErrorWrapper(
            "Internal error: token_provider is required when allow_auth_refresh=True."
        )

    retry_attempt = 0
    latest_controls: Controls | None = None

    while True:
        state = _SessionState(
            desired_controls=latest_controls,
            controls_dirty=latest_controls is not None,
        )

        def _set_controls_impl(controls: Controls) -> None:
            nonlocal latest_controls
            latest_controls = controls
            _set_desired_controls(state, controls)

        def _request_back_to_track_impl(state_ref: _SessionState = state) -> None:
            _enqueue_command(state_ref, _OutboundCommand(kind="back_to_track"))

        def _request_emergency_pitstop_impl(state_ref: _SessionState = state) -> None:
            _enqueue_command(state_ref, _OutboundCommand(kind="emergency_pitstop"))

        def _set_next_pit_tire_type_impl(
            tire_type: TireType,
            state_ref: _SessionState = state,
        ) -> None:
            _enqueue_command(
                state_ref,
                _OutboundCommand(
                    kind="set_next_pit_tire_type",
                    next_tire_type=int(tire_type),
                ),
            )

        ctx._actions = _BotContextActions(
            set_controls=_set_controls_impl,
            request_back_to_track=_request_back_to_track_impl,
            request_emergency_pitstop=_request_emergency_pitstop_impl,
            set_next_pit_tire_type=_set_next_pit_tire_type_impl,
        )
        if state.controls_dirty:
            state.outbound_event.set()

        outbound = _OutboundMessageIterator()
        outbound.put(_stream_init_message())

        try:
            stream_metadata = metadata_provider()
        except RuntimeError as exc:
            raise RuntimeErrorWrapper(
                f"Failed to prepare stream metadata: {exc}"
            ) from exc

        try:
            stream_call = _open_participant_stream(
                api,
                outbound,
                metadata=stream_metadata,
                stream_method=stream_method,
            )
        except grpc.RpcError as exc:
            method_label = stream_method or "/race.v1.RaceParticipantService/Stream"
            raise RuntimeErrorWrapper(
                f"Race participant stream open failed ({method_label}): "
                f"{exc.code().name} {exc.details()}"
            ) from exc

        reader = threading.Thread(
            target=_reader_loop,
            args=(stream_call, state, ctx, expected_map_id),
            name="ha3-reader-loop",
            daemon=True,
        )
        callback = threading.Thread(
            target=_callback_loop,
            args=(bot, state, ctx),
            name="ha3-callback-loop",
            daemon=True,
        )
        writer = threading.Thread(
            target=_writer_loop,
            args=(outbound, state),
            name="ha3-writer-loop",
            daemon=True,
        )
        reader.start()
        callback.start()
        writer.start()

        token_rotated = False
        try:
            while not state.stop_event.wait(_RUNTIME_POLL_SECONDS):
                if not allow_auth_refresh or token_provider is None:
                    continue
                if token_provider.ensure_fresh(_TOKEN_REFRESH_SKEW_SECONDS):
                    token_rotated = True
                    state.stop_event.set()
                    break
        except GameTokenError as exc:
            state.fatal_error = RuntimeErrorWrapper(f"Game token refresh failed: {exc}")
            state.stop_event.set()
        finally:
            outbound.close()
            try:
                stream_call.cancel()
            except Exception:
                pass
            reader.join(timeout=1.0)
            writer.join(timeout=1.0)
            callback.join()

        if state.fatal_error is not None:
            raise state.fatal_error

        if token_rotated:
            retry_attempt = 0
            continue

        stream_error = state.stream_error
        if stream_error is None:
            raise RuntimeErrorWrapper("Participant stream stopped unexpectedly.")

        code = stream_error.code()
        details = stream_error.details()

        if code == grpc.StatusCode.UNIMPLEMENTED:
            raise RuntimeErrorWrapper(
                "Required participant stream method is unavailable (UNIMPLEMENTED)."
            ) from stream_error

        if code in AUTH_CODES:
            if not allow_auth_refresh or token_provider is None:
                raise RuntimeErrorWrapper(
                    f"Authentication failed ({code.name}): {details or 'no details'}"
                ) from stream_error
            try:
                token_provider.refresh()
            except GameTokenError as refresh_exc:
                raise RuntimeErrorWrapper(
                    f"Authentication failed ({code.name}) and token refresh failed: {refresh_exc}"
                ) from refresh_exc
            retry_attempt = 0
            continue

        if code in TRANSIENT_CODES and retry_attempt < len(RETRY_BACKOFF_SECONDS):
            delay = RETRY_BACKOFF_SECONDS[retry_attempt]
            retry_attempt += 1
            time.sleep(delay)
            continue

        raise RuntimeErrorWrapper(
            f"gRPC error {code.name}: {details}"
        ) from stream_error

from __future__ import annotations

import queue
import sys
import threading
import time
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
from hackarena3.runtime_convert import build_race_snapshot
from hackarena3.runtime_race import race_metadata
from hackarena3.types import (
    Controls,
    GearShift,
    NotSupportedError,
    RaceSnapshot,
)

if TYPE_CHECKING:
    from hackarena3.game_token import GameTokenProvider
    from hackarena3.runtime_race import RaceApi
    from hackarena3.types import BotContext, BotProtocol


_RUNTIME_POLL_SECONDS = 0.2
_TOKEN_REFRESH_SKEW_SECONDS = 30
_PIT_NOT_SUPPORTED_MESSAGE = "request_pit is not supported by current backend proto."
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
class _SessionState:
    stop_event: threading.Event = field(default_factory=threading.Event)
    snapshot_event: threading.Event = field(default_factory=threading.Event)
    controls_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    latest_snapshot: RaceSnapshot | None = None
    latest_snapshot_version: int = 0
    desired_controls: Controls | None = None
    controls_dirty: bool = False
    next_client_seq: int = 0
    pending_acks: dict[int, _PendingAck] = field(default_factory=dict)
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
    except (TypeError, ValueError) as exc:
        raise RuntimeErrorWrapper(
            "set_controls received non-numeric value; throttle/brake/steer must be floats."
        ) from exc

    clamped = Controls(
        throttle=_clamp(throttle, 0.0, 1.0),
        brake=_clamp(brake, 0.0, 1.0),
        steering=_clamp(steering, -1.0, 1.0),
        gear_shift=controls.gear_shift,
    )
    if (
        clamped.throttle != throttle
        or clamped.brake != brake
        or clamped.steering != steering
    ):
        print(
            "[ha3-wrapper] Bot set_controls out-of-range values were clamped "
            f"(thr={throttle}, brk={brake}, str={steering}).",
            file=sys.stderr,
        )
    return clamped


def _normalize_gear_shift(gear_shift: GearShift | None) -> int:
    if gear_shift is None:
        return int(race_pb2.GEAR_SHIFT_NONE)
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
    state.controls_event.set()


def _unsupported_request_pit(*_args: object, **_kwargs: object) -> None:
    raise NotSupportedError(_PIT_NOT_SUPPORTED_MESSAGE)


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


def _reader_loop(
    stream_call: grpc.Call,
    state: _SessionState,
    ctx: BotContext,
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
                if event.settings.map_id:
                    ctx.map_id = event.settings.map_id
                if (
                    last_effective_hz != ctx.effective_hz
                    or last_map_id != ctx.map_id
                ):
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
            state.fatal_error = RuntimeErrorWrapper("Participant stream ended unexpectedly.")
            state.stop_event.set()
    finally:
        state.snapshot_event.set()
        state.controls_event.set()


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

        try:
            result = bot.on_tick(snapshot, ctx)
        except NotSupportedError as exc:
            if not state.stop_event.is_set():
                state.fatal_error = RuntimeErrorWrapper(str(exc))
                state.stop_event.set()
            break
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
        state.controls_event.wait(_RUNTIME_POLL_SECONDS)
        state.controls_event.clear()
        if state.stop_event.is_set():
            break

        with state.lock:
            controls = state.desired_controls
            if controls is None:
                continue
            send_controls = controls
            if send_controls.gear_shift is not None:
                controls = Controls(
                    throttle=controls.throttle,
                    brake=controls.brake,
                    steering=controls.steering,
                    gear_shift=None,
                )
                state.desired_controls = controls
            if not state.controls_dirty and send_controls.gear_shift is None:
                continue
            state.controls_dirty = False
            state.next_client_seq += 1
            client_seq = state.next_client_seq

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
            )
        )
        with state.lock:
            state.pending_acks[client_seq] = _PendingAck(
                started_monotonic=time.monotonic(),
            )
        outbound.put(message)


def _stream_init_message() -> race_pb2.ParticipantClientMessage:
    return race_pb2.ParticipantClientMessage(
        init=race_pb2.ParticipantStreamInit(
            wrapper_type=race_pb2.PARTICIPANT_WRAPPER_TYPE_PYTHON,
            wrapper_version=_WRAPPER_VERSION,
        )
    )


def run_participant_loop(
    bot: BotProtocol,
    api: RaceApi,
    token_provider: GameTokenProvider,
    ctx: BotContext,
) -> None:
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

        ctx._set_controls_impl = _set_controls_impl
        ctx._request_pit_impl = _unsupported_request_pit
        if state.controls_dirty:
            state.controls_event.set()

        outbound = _OutboundMessageIterator()
        outbound.put(_stream_init_message())

        try:
            stream_call = api.participant.Stream(  # type: ignore
                outbound,
                metadata=race_metadata(token_provider),
            )
        except grpc.RpcError as exc:
            raise RuntimeErrorWrapper(
                f"Race participant stream open failed: {exc.code().name} {exc.details()}"
            ) from exc

        reader = threading.Thread(
            target=_reader_loop,
            args=(stream_call, state, ctx),
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

        raise RuntimeErrorWrapper(f"gRPC error {code.name}: {details}") from stream_error

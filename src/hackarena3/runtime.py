from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import grpc

from hackarena3.auth import AuthError, fetch_member_jwt
from hackarena3.config import OfficialRuntimeConfig
from hackarena3.game_token import GameTokenError, GameTokenProvider
from hackarena3.proto.race.v1 import race_pb2
from hackarena3.runtime_common import (
    REQUESTED_HZ,
    RPC_TIMEOUT_SECONDS,
    RuntimeErrorWrapper,
)
from hackarena3.runtime_convert import build_track_layout
from hackarena3.runtime_discovery import (
    choose_sandbox,
    create_broker_api,
    discover_team_sandboxes,
)
from hackarena3.runtime_loop import run_participant_loop
from hackarena3.runtime_race import (
    create_backend_api,
    create_official_backend_api,
    fetch_track_data,
    fetch_track_data_official,
    prepare_official_join,
    race_metadata,
    race_metadata_official,
)
from hackarena3.types import BotContext, CarDimensions

if TYPE_CHECKING:
    from hackarena3.runtime_discovery import BrokerApi
    from hackarena3.runtime_race import RaceApi
    from hackarena3.types import BotProtocol, RuntimeConfig


_OFFICIAL_STREAM_SUFFIX = "/race.v1.RaceParticipantService/Stream"


def _official_stream_method(rpc_prefix: str) -> str:
    prefix = rpc_prefix.strip().rstrip("/")
    if not prefix or prefix == "/":
        raise RuntimeErrorWrapper(
            "Official rpc_prefix is empty; cannot build stream RPC method."
        )
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return f"{prefix}{_OFFICIAL_STREAM_SUFFIX}"


def run_runtime(
    bot: BotProtocol,
    config: RuntimeConfig,
    *,
    official_config: OfficialRuntimeConfig | None = None,
) -> None:
    if official_config is not None:
        _run_runtime_official(bot, official_config)
        return
    _run_runtime_sandbox(bot, config)


def _run_runtime_sandbox(bot: BotProtocol, config: RuntimeConfig) -> None:
    broker_api: BrokerApi | None = None
    api: RaceApi | None = None
    token_provider: GameTokenProvider | None = None

    try:
        try:
            member_jwt = fetch_member_jwt(ha_auth_bin=config.ha_auth_bin)
        except AuthError as exc:
            raise RuntimeErrorWrapper(str(exc)) from exc

        broker_api = create_broker_api(config)
        discovered = discover_team_sandboxes(broker_api, member_jwt)
        selected = choose_sandbox(discovered, sandbox_id=config.sandbox_id)

        token_provider = GameTokenProvider(
            api_addr=config.api_addr,
            member_jwt=member_jwt,
        )
        try:
            token_provider.refresh()
        except GameTokenError as exc:
            raise RuntimeErrorWrapper(
                f"Failed to obtain game token before LocalSandboxJoin: {exc}"
            ) from exc

        api = create_backend_api(selected.backend)

        try:
            join_response = api.participant.LocalSandboxJoin(  # type: ignore
                race_pb2.LocalSandboxJoinRequest(sandbox_id=selected.sandbox_id),
                metadata=race_metadata(token_provider),
                timeout=RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.UNIMPLEMENTED:
                raise RuntimeErrorWrapper(
                    "LocalSandboxJoin unavailable (UNIMPLEMENTED). Check backend/api compatibility."
                ) from exc
            raise RuntimeErrorWrapper(
                f"LocalSandboxJoin failed: {exc.code().name} {exc.details()}"
            ) from exc

        assert isinstance(join_response, race_pb2.LocalSandboxJoinResponse)

        track = fetch_track_data(api, token_provider, join_response.map_id)
        try:
            track_layout = build_track_layout(track)
        except ValueError as exc:
            raise RuntimeErrorWrapper(str(exc)) from exc
        pit_count = (
            len(track_layout.pitstop.enter)
            + len(track_layout.pitstop.fix)
            + len(track_layout.pitstop.exit)
        )
        pit_length = track_layout.pitstop.length_m
        print(
            f"[ha3-wrapper] Loaded track data: map_id={track.map_id} "
            f"samples={len(track.centerline_samples)} lap_length_m={track.lap_length_m:.2f} "
            f"pit_samples={pit_count} pit_length_m={pit_length:.2f}",
            file=sys.stderr,
        )

        ctx = BotContext(
            car_id=join_response.car_id,
            map_id=join_response.map_id,
            car_dimensions=CarDimensions(width_m=0.0, depth_m=0.0),
            requested_hz=REQUESTED_HZ,
            track=track_layout,
            effective_hz=None,
            tick=0,
        )

        def _metadata_provider() -> tuple[tuple[str, str], ...]:
            assert token_provider is not None
            return race_metadata(token_provider)

        run_participant_loop(
            bot,
            api,
            ctx,
            metadata_provider=_metadata_provider,
            token_provider=token_provider,
            allow_auth_refresh=True,
        )
    finally:
        if token_provider is not None:
            token_provider.close()
        if api is not None:
            api.channel.close()
        if broker_api is not None:
            broker_api.channel.close()


def _run_runtime_official(bot: BotProtocol, config: OfficialRuntimeConfig) -> None:
    api: RaceApi | None = None

    try:
        api = create_official_backend_api(config.grpc_target)
        metadata = race_metadata_official(config.team_token, config.auth_token)
        prepare_response = prepare_official_join(
            api,
            rpc_prefix=config.rpc_prefix,
            metadata=metadata,
        )
        track = fetch_track_data_official(
            api,
            rpc_prefix=config.rpc_prefix,
            metadata=metadata,
            map_id=prepare_response.map_id,
        )
        try:
            track_layout = build_track_layout(track)
        except ValueError as exc:
            raise RuntimeErrorWrapper(str(exc)) from exc

        pit_count = (
            len(track_layout.pitstop.enter)
            + len(track_layout.pitstop.fix)
            + len(track_layout.pitstop.exit)
        )
        pit_length = track_layout.pitstop.length_m
        stream_method = _official_stream_method(config.rpc_prefix)
        print(
            "[ha3-wrapper] Official mode prepared: "
            f"car_id={prepare_response.car_id} map_id={prepare_response.map_id} "
            f"target={config.grpc_target} rpc_prefix={config.rpc_prefix} "
            f"samples={len(track.centerline_samples)} lap_length_m={track.lap_length_m:.2f} "
            f"pit_samples={pit_count} pit_length_m={pit_length:.2f}",
            file=sys.stderr,
        )

        ctx = BotContext(
            car_id=prepare_response.car_id,
            map_id=prepare_response.map_id,
            car_dimensions=CarDimensions(width_m=0.0, depth_m=0.0),
            requested_hz=REQUESTED_HZ,
            track=track_layout,
            effective_hz=None,
            tick=0,
        )

        def _metadata_provider() -> tuple[tuple[str, str], ...]:
            return metadata

        run_participant_loop(
            bot,
            api,
            ctx,
            metadata_provider=_metadata_provider,
            token_provider=None,
            allow_auth_refresh=False,
            stream_method=stream_method,
            expected_map_id=prepare_response.map_id,
        )
    finally:
        if api is not None:
            api.channel.close()

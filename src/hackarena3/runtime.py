from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import grpc

from hackarena3.auth import AuthError, fetch_member_jwt
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
from hackarena3.runtime_race import create_backend_api, fetch_track_data, race_metadata
from hackarena3.types import BotContext

if TYPE_CHECKING:
    from hackarena3.runtime_discovery import BrokerApi
    from hackarena3.runtime_race import RaceApi
    from hackarena3.types import BotProtocol, RuntimeConfig


def run_runtime(bot: BotProtocol, config: RuntimeConfig) -> None:
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
            requested_hz=REQUESTED_HZ,
            track_data=track,
            track=track_layout,
            effective_hz=None,
            tick=0,
            raw={},
        )
        run_participant_loop(bot, api, token_provider, ctx)
    finally:
        if token_provider is not None:
            token_provider.close()
        if api is not None:
            api.channel.close()
        if broker_api is not None:
            broker_api.channel.close()

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import grpc

from hackarena3.proto.race.v1 import race_pb2_grpc, track_pb2, track_pb2_grpc
from hackarena3.runtime_common import (
    RPC_TIMEOUT_SECONDS,
    RuntimeErrorWrapper,
    open_insecure_channel,
)

if TYPE_CHECKING:
    from hackarena3.game_token import GameTokenProvider
    from hackarena3.runtime_discovery import BackendTarget


@dataclass(slots=True)
class RaceApi:
    channel: grpc.Channel
    race: race_pb2_grpc.RaceServiceStub
    participant: race_pb2_grpc.RaceParticipantServiceStub
    track: track_pb2_grpc.TrackServiceStub


def create_backend_api(backend: BackendTarget) -> RaceApi:
    # Broker endpoints represent teammate backend listeners (not central API gateway).
    # MVP: backend endpoints are plain gRPC.
    channel = open_insecure_channel(backend.target)
    return RaceApi(
        channel=channel,
        race=race_pb2_grpc.RaceServiceStub(channel),
        participant=race_pb2_grpc.RaceParticipantServiceStub(channel),
        track=track_pb2_grpc.TrackServiceStub(channel),
    )


def race_metadata(
    token_provider: GameTokenProvider,
) -> tuple[tuple[str, str], ...]:
    return token_provider.member_auth_metadata() + token_provider.grpc_metadata()


def fetch_track_data(
    api: RaceApi,
    token_provider: GameTokenProvider,
    map_id: str,
) -> track_pb2.TrackData:
    if not map_id.strip():
        raise RuntimeErrorWrapper(
            "QuickJoinDev returned empty map_id; cannot fetch track data."
        )

    request = track_pb2.GetTrackDataRequest(map_id=map_id)
    try:
        response = api.track.GetTrackData(  # type: ignore
            request,
            metadata=race_metadata(token_provider),
            timeout=RPC_TIMEOUT_SECONDS,
        )
    except grpc.RpcError as exc:
        raise RuntimeErrorWrapper(
            f"GetTrackData failed: {exc.code().name} {exc.details()}"
        ) from exc

    if not response.HasField("track"):
        raise RuntimeErrorWrapper(
            f"GetTrackData returned empty track payload for map_id={map_id!r}."
        )
    return response.track

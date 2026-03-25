from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import grpc

from hackarena3.proto.race.v1 import race_pb2, race_pb2_grpc, track_pb2, track_pb2_grpc
from hackarena3.runtime_common import (
    RPC_TIMEOUT_SECONDS,
    RuntimeErrorWrapper,
    open_insecure_channel,
    open_secure_channel,
)

if TYPE_CHECKING:
    from hackarena3.game_token import GameTokenProvider
    from hackarena3.runtime_discovery import BackendTarget

_PREPARE_OFFICIAL_JOIN_SUFFIX = "/race.v1.RaceParticipantService/PrepareOfficialJoin"
_GET_TRACK_DATA_SUFFIX = "/race.v1.TrackService/GetTrackData"


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


def create_official_backend_api(grpc_target: str) -> RaceApi:
    channel = open_secure_channel(grpc_target)
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


def race_metadata_official(team_token: str) -> tuple[tuple[str, str], ...]:
    token = team_token.strip()
    if not token:
        raise RuntimeErrorWrapper("Team token is empty; cannot build stream metadata.")
    return (("x-ha3-game-token", token),)


def _prefixed_method(rpc_prefix: str, suffix: str) -> str:
    prefix = rpc_prefix.strip().rstrip("/")
    if not prefix or prefix == "/":
        raise RuntimeErrorWrapper("Official rpc_prefix is empty; cannot build RPC method.")
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    return f"{prefix}{suffix}"


def prepare_official_join(
    api: RaceApi,
    *,
    rpc_prefix: str,
    metadata: tuple[tuple[str, str], ...],
) -> race_pb2.PrepareOfficialJoinResponse:
    method = _prefixed_method(rpc_prefix, _PREPARE_OFFICIAL_JOIN_SUFFIX)
    rpc = api.channel.unary_unary(
        method,
        request_serializer=race_pb2.PrepareOfficialJoinRequest.SerializeToString,
        response_deserializer=race_pb2.PrepareOfficialJoinResponse.FromString,
    )
    try:
        response = rpc(
            race_pb2.PrepareOfficialJoinRequest(),
            metadata=metadata,
            timeout=RPC_TIMEOUT_SECONDS,
        )
    except grpc.RpcError as exc:
        if exc.code() == grpc.StatusCode.UNIMPLEMENTED:
            raise RuntimeErrorWrapper(
                "PrepareOfficialJoin unavailable (UNIMPLEMENTED). "
                "Official mode requires backend with PrepareOfficialJoin support."
            ) from exc
        raise RuntimeErrorWrapper(
            f"PrepareOfficialJoin failed: {exc.code().name} {exc.details()}"
        ) from exc
    assert isinstance(response, race_pb2.PrepareOfficialJoinResponse)
    if not response.map_id.strip():
        raise RuntimeErrorWrapper(
            "PrepareOfficialJoin returned empty map_id; cannot preload TrackData."
        )
    return response


def fetch_track_data(
    api: RaceApi,
    token_provider: GameTokenProvider,
    map_id: str,
) -> track_pb2.TrackData:
    if not map_id.strip():
        raise RuntimeErrorWrapper(
            "LocalSandboxJoin returned empty map_id; cannot fetch track data."
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

    assert isinstance(response, track_pb2.GetTrackDataResponse)
    return response.track


def fetch_track_data_official(
    api: RaceApi,
    *,
    rpc_prefix: str,
    metadata: tuple[tuple[str, str], ...],
    map_id: str,
) -> track_pb2.TrackData:
    if not map_id.strip():
        raise RuntimeErrorWrapper(
            "PrepareOfficialJoin returned empty map_id; cannot fetch track data."
        )

    method = _prefixed_method(rpc_prefix, _GET_TRACK_DATA_SUFFIX)
    rpc = api.channel.unary_unary(
        method,
        request_serializer=track_pb2.GetTrackDataRequest.SerializeToString,
        response_deserializer=track_pb2.GetTrackDataResponse.FromString,
    )
    request = track_pb2.GetTrackDataRequest(map_id=map_id)
    try:
        response = rpc(
            request,
            metadata=metadata,
            timeout=RPC_TIMEOUT_SECONDS,
        )
    except grpc.RpcError as exc:
        raise RuntimeErrorWrapper(
            f"GetTrackData (official) failed: {exc.code().name} {exc.details()}"
        ) from exc

    assert isinstance(response, track_pb2.GetTrackDataResponse)
    return response.track

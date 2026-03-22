from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import grpc

from hackarena3.proto.hackarena.broker.v1 import broker_pb2
from hackarena3.proto.hackarena.connect.v1 import connect_pb2, connect_pb2_grpc
from hackarena3.proto.race.v1 import runtime_local_pb2
from hackarena3.runtime_common import (
    BROKER_GET_TEAM_BACKENDS_METHOD,
    RPC_TIMEOUT_SECONDS,
    RuntimeErrorWrapper,
    normalize_api_target,
    open_insecure_channel,
    open_secure_channel,
)

if TYPE_CHECKING:
    from hackarena3.types import RuntimeConfig

CONNECT_PROTOCOL_VERSION = "1"
CONNECT_VALIDATE_TIMEOUT_SECONDS = 2.0
LOCAL_RUNTIME_STATE_METHOD = "/race.v1.LocalSandboxAdminService/GetLocalRuntimeState"


@dataclass(slots=True)
class BackendTarget:
    backend_id: str
    user_id: str
    user_name: str | None
    host: str
    port: int
    transport: int

    @property
    def target(self) -> str:
        host = self.host.strip()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{host}:{self.port}"

    @property
    def label(self) -> str:
        return f"{self.user_id}/{self.backend_id}/{self.host}:{self.port}"

    @property
    def user_display(self) -> str:
        value = (self.user_name or "").strip()
        return value or "-"


@dataclass(slots=True)
class DiscoveredSandbox:
    sandbox_id: str
    sandbox_name: str
    map_id: str
    active_player_count: int
    backend: BackendTarget


@dataclass(slots=True)
class BrokerApi:
    channel: grpc.Channel
    target: str
    get_team_backends: Callable[..., Any]


def _auth_metadata(member_jwt: str) -> tuple[tuple[str, str], ...]:
    return (("cookie", f"auth_token={member_jwt}"),)


def create_broker_api(config: RuntimeConfig) -> BrokerApi:
    target = normalize_api_target(config.api_addr)
    channel = open_secure_channel(target)
    return BrokerApi(
        channel=channel,
        target=target,
        get_team_backends=channel.unary_unary(
            BROKER_GET_TEAM_BACKENDS_METHOD,
            request_serializer=broker_pb2.GetTeamBackendsRequest.SerializeToString,
            response_deserializer=broker_pb2.GetTeamBackendsResponse.FromString,
        ),
    )


def _fetch_team_backends(
    broker_api: BrokerApi,
    member_jwt: str,
) -> list[broker_pb2.BackendInfo]:
    try:
        response = broker_api.get_team_backends(
            broker_pb2.GetTeamBackendsRequest(),
            metadata=_auth_metadata(member_jwt),
            timeout=RPC_TIMEOUT_SECONDS,
        )
    except grpc.RpcError as exc:
        raise RuntimeErrorWrapper(
            f"GetTeamBackends failed: {exc.code().name} {exc.details() or 'no details'}"
        ) from exc
    return list(response.backends)


def _backend_target_from_endpoint(
    backend_info: broker_pb2.BackendInfo,
    endpoint: broker_pb2.Endpoint,
) -> BackendTarget | None:
    host = endpoint.host.strip()
    port = int(endpoint.port)
    if not host or port <= 0:
        return None
    return BackendTarget(
        backend_id=backend_info.backend_id,
        user_id=backend_info.user_id,
        user_name=str(getattr(backend_info, "user_display_name", "")).strip() or None,
        host=host,
        port=port,
        transport=int(endpoint.transport),
    )


def _connect_status_name(value: int) -> str:
    try:
        return connect_pb2.ConnectStatus.Name(value)  # type: ignore
    except ValueError:
        return str(value)


def _validate_backend_connection(
    backend: BackendTarget,
    member_jwt: str,
) -> bool:
    channel = open_insecure_channel(backend.target)
    try:
        connect_api = connect_pb2_grpc.ConnectServiceStub(channel)
        nonce = os.urandom(16)
        response = connect_api.ValidateConnection(  # type: ignore
            connect_pb2.ValidateConnectionRequest(
                backend_id=backend.backend_id,
                protocol_version=CONNECT_PROTOCOL_VERSION,
                nonce=nonce,
            ),
            metadata=_auth_metadata(member_jwt),
            timeout=CONNECT_VALIDATE_TIMEOUT_SECONDS,
        )
    except grpc.RpcError as exc:
        print(
            "[ha3-wrapper] Endpoint probe failed: "
            f"{backend.label}; code={exc.code().name}; details={exc.details() or 'no details'}",
            file=sys.stderr,
        )
        return False
    finally:
        channel.close()

    assert isinstance(response, connect_pb2.ValidateConnectionResponse)

    if response.status != connect_pb2.CONNECT_STATUS_OK:
        print(
            "[ha3-wrapper] Endpoint probe rejected: "
            f"{backend.label}; status={_connect_status_name(int(response.status))} "
            f"message={response.message!r}",
            file=sys.stderr,
        )
        return False
    if response.backend_id != backend.backend_id:
        print(
            "[ha3-wrapper] Endpoint probe rejected: "
            f"{backend.label}; backend_id mismatch "
            f"(expected={backend.backend_id!r}, got={response.backend_id!r})",
            file=sys.stderr,
        )
        return False
    if response.nonce_echo != nonce:
        print(
            "[ha3-wrapper] Endpoint probe rejected: "
            f"{backend.label}; nonce echo mismatch",
            file=sys.stderr,
        )
        return False

    return True


def _resolve_reachable_backend(
    backend_info: broker_pb2.BackendInfo,
    member_jwt: str,
) -> BackendTarget | None:
    if not backend_info.endpoints:
        return None

    for endpoint in backend_info.endpoints:
        backend = _backend_target_from_endpoint(backend_info, endpoint)
        if backend is None:
            print(
                "[ha3-wrapper] Broker endpoint skipped (invalid host/port): "
                f"user={backend_info.user_id} backend_id={backend_info.backend_id} "
                f"host={endpoint.host!r} port={endpoint.port}",
                file=sys.stderr,
            )
            continue
        if _validate_backend_connection(backend, member_jwt):
            return backend
    return None


def _fetch_local_runtime_sandboxes(
    backend: BackendTarget,
    member_jwt: str,
) -> list[DiscoveredSandbox]:
    channel = open_insecure_channel(backend.target)
    get_local_runtime_state = channel.unary_unary(
        LOCAL_RUNTIME_STATE_METHOD,
        request_serializer=runtime_local_pb2.GetLocalRuntimeStateRequest.SerializeToString,
        response_deserializer=runtime_local_pb2.GetLocalRuntimeStateResponse.FromString,
    )
    try:
        response = get_local_runtime_state(
            runtime_local_pb2.GetLocalRuntimeStateRequest(),
            metadata=_auth_metadata(member_jwt),
            timeout=RPC_TIMEOUT_SECONDS,
        )
    finally:
        channel.close()

    discovered: list[DiscoveredSandbox] = []
    for sandbox in response.state.active_sandboxes:
        discovered.append(
            DiscoveredSandbox(
                sandbox_id=sandbox.sandbox_id,
                sandbox_name=sandbox.sandbox_name,
                map_id=sandbox.map_id,
                active_player_count=int(sandbox.active_player_count),
                backend=backend,
            )
        )
    return discovered


def discover_team_sandboxes(
    broker_api: BrokerApi,
    member_jwt: str,
) -> list[DiscoveredSandbox]:
    print("[ha3-wrapper] Fetching team backends via BrokerService...", file=sys.stderr)
    backends = _fetch_team_backends(broker_api, member_jwt)
    if not backends:
        raise RuntimeErrorWrapper("Broker returned no team backends.")

    discovered: list[DiscoveredSandbox] = []
    for backend_info in backends:
        backend = _resolve_reachable_backend(backend_info, member_jwt)
        if backend is None:
            print(
                "[ha3-wrapper] Broker backend skipped (no reachable endpoint after probe): "
                f"user={backend_info.user_id} backend_id={backend_info.backend_id}",
                file=sys.stderr,
            )
            continue

        try:
            sandboxes = _fetch_local_runtime_sandboxes(backend, member_jwt)
        except grpc.RpcError as exc:
            print(
                "[ha3-wrapper] Backend skipped (GetLocalRuntimeState failed): "
                f"{backend.label}; code={exc.code().name}; details={exc.details() or 'no details'}",
                file=sys.stderr,
            )
            continue
        except Exception as exc:
            print(
                "[ha3-wrapper] Backend skipped (runtime fetch error): "
                f"{backend.label}; details={exc}",
                file=sys.stderr,
            )
            continue

        discovered.extend(sandboxes)

    if not discovered:
        raise RuntimeErrorWrapper("No active sandboxes found in team backends.")
    return discovered


def choose_sandbox(
    discovered: list[DiscoveredSandbox],
    sandbox_id: str | None = None,
) -> DiscoveredSandbox:
    configured_sandbox_id = str(sandbox_id or "").strip()
    if configured_sandbox_id:
        selected = next(
            (item for item in discovered if item.sandbox_id == configured_sandbox_id),
            None,
        )
        if selected is None:
            available = ", ".join(item.sandbox_id for item in discovered)
            raise RuntimeErrorWrapper(
                f"--sandbox_id={configured_sandbox_id!r} not found in active team sandboxes. "
                f"Available sandbox IDs: {available}"
            )
        print(
            "[ha3-wrapper] Using sandbox selected by --sandbox_id: "
            f"{selected.sandbox_id} ({selected.backend.label})",
            file=sys.stderr,
        )
        return selected

    print("[ha3-wrapper] Active team sandboxes (broker):")
    for idx, entry in enumerate(discovered, start=1):
        print(
            f"[ha3-wrapper] {idx}. {entry.sandbox_name} | id={entry.sandbox_id} "
            f"| user={entry.backend.user_display} "
            f"| map={entry.map_id} | players={entry.active_player_count} "
            f"| endpoint={entry.backend.host}:{entry.backend.port}"
        )

    if not sys.stdin.isatty():
        available = ", ".join(item.sandbox_id for item in discovered)
        raise RuntimeErrorWrapper(
            "Non-interactive mode requires --sandbox_id. "
            f"Available sandbox IDs: {available}"
        )

    while True:
        raw = input(f"Select sandbox [1-{len(discovered)}] (default 1): ").strip()
        if not raw:
            return discovered[0]
        try:
            index = int(raw)
        except ValueError:
            print("[ha3-wrapper] Invalid number. Try again.")
            continue
        if 1 <= index <= len(discovered):
            return discovered[index - 1]
        print("[ha3-wrapper] Selection out of range. Try again.")

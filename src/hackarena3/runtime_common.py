from __future__ import annotations

from urllib.parse import urlparse

import grpc

TRANSIENT_CODES = {
    grpc.StatusCode.DEADLINE_EXCEEDED,
    grpc.StatusCode.UNAVAILABLE,
}
AUTH_CODES = {
    grpc.StatusCode.UNAUTHENTICATED,
    grpc.StatusCode.PERMISSION_DENIED,
}
RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
REQUESTED_HZ = 60
BROKER_GET_TEAM_BACKENDS_METHOD = (
    "/broker/hackarena.broker.v1.BrokerService/GetTeamBackends"
)
RPC_TIMEOUT_SECONDS = 10
CHANNEL_OPTIONS = (("grpc.enable_http_proxy", 0),)


class RuntimeErrorWrapper(RuntimeError):
    pass


def normalize_api_target(api_addr: str) -> str:
    parsed = urlparse(api_addr.strip())
    if parsed.scheme != "https":
        raise RuntimeErrorWrapper(
            "Invalid api_addr URL scheme. Expected https://."
        )
    if not parsed.hostname:
        raise RuntimeErrorWrapper(f"Invalid api_addr URL: {api_addr!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeErrorWrapper(f"Invalid api_addr port in URL: {api_addr!r}") from exc
    if port is None:
        port = 443
    target = f"{parsed.hostname}:{port}"
    return target


def open_secure_channel(target: str) -> grpc.Channel:
    credentials = grpc.ssl_channel_credentials()
    return grpc.secure_channel(target, credentials, options=CHANNEL_OPTIONS)


def open_insecure_channel(target: str) -> grpc.Channel:
    return grpc.insecure_channel(target, options=CHANNEL_OPTIONS)

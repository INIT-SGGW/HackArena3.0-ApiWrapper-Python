from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from hackarena3.types import RuntimeConfig

ENV_API_URL = "HA3_WRAPPER_API_URL"
ENV_HA_AUTH_BIN = "HA3_WRAPPER_HA_AUTH_BIN"
ENV_BACKEND_ENDPOINT = "HA3_WRAPPER_BACKEND_ENDPOINT"
ENV_TEAM_TOKEN = "HA3_WRAPPER_TEAM_TOKEN"
ENV_AUTH_TOKEN = "HA3_WRAPPER_AUTH_TOKEN"
DEFAULT_API_URL = "https://ha3-api.hackarena.pl"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OfficialRuntimeConfig:
    grpc_target: str
    rpc_prefix: str
    team_token: str
    auth_token: str


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _load_dotenv_if_present() -> None:
    dotenv_path = Path.cwd() / "user" / ".env"
    if not dotenv_path.is_file():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        os.environ.setdefault(key, _strip_quotes(value.strip()))


def _required_api_addr() -> str:
    api_url = str(os.environ.get(ENV_API_URL, "")).strip()
    if api_url:
        return api_url
    return DEFAULT_API_URL


def _optional_api_addr() -> str:
    api_url = str(os.environ.get(ENV_API_URL, "")).strip()
    if api_url:
        return api_url
    return DEFAULT_API_URL


def load_runtime_config(*, require_api_addr: bool = True) -> RuntimeConfig:
    _load_dotenv_if_present()

    api_addr = _required_api_addr() if require_api_addr else _optional_api_addr()
    ha_auth_bin = str(os.environ.get(ENV_HA_AUTH_BIN, "")).strip() or None

    return RuntimeConfig(api_addr=api_addr, ha_auth_bin=ha_auth_bin)


def load_official_runtime_config() -> OfficialRuntimeConfig:
    _load_dotenv_if_present()

    endpoint = str(os.environ.get(ENV_BACKEND_ENDPOINT, "")).strip()
    if not endpoint:
        raise ConfigError(f"Missing required runtime env: {ENV_BACKEND_ENDPOINT}")

    team_token = str(os.environ.get(ENV_TEAM_TOKEN, "")).strip()
    if not team_token:
        raise ConfigError(f"Missing required runtime env: {ENV_TEAM_TOKEN}")
    auth_token = str(os.environ.get(ENV_AUTH_TOKEN, "")).strip()
    if not auth_token:
        raise ConfigError(f"Missing required runtime env: {ENV_AUTH_TOKEN}")

    parsed = urlparse(endpoint)
    if parsed.scheme != "https":
        raise ConfigError(
            f"Invalid {ENV_BACKEND_ENDPOINT}: expected https:// URL."
        )
    if not parsed.hostname:
        raise ConfigError(
            f"Invalid {ENV_BACKEND_ENDPOINT}: missing host in URL {endpoint!r}."
        )
    if parsed.query or parsed.fragment or parsed.params:
        raise ConfigError(
            f"Invalid {ENV_BACKEND_ENDPOINT}: query/fragment/params are not supported."
        )

    path = parsed.path.strip()
    if not path or path == "/":
        raise ConfigError(
            f"Invalid {ENV_BACKEND_ENDPOINT}: non-root path prefix is required (for example /backend)."
        )
    rpc_prefix = path.rstrip("/")
    if not rpc_prefix.startswith("/"):
        rpc_prefix = f"/{rpc_prefix}"

    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigError(
            f"Invalid {ENV_BACKEND_ENDPOINT}: invalid port in URL {endpoint!r}."
        ) from exc
    if port is None:
        port = 443

    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    grpc_target = f"{host}:{port}"
    return OfficialRuntimeConfig(
        grpc_target=grpc_target,
        rpc_prefix=rpc_prefix,
        team_token=team_token,
        auth_token=auth_token,
    )

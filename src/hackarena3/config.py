from __future__ import annotations

import os
from pathlib import Path

from hackarena3.types import RuntimeConfig

ENV_API_URL = "HA3_WRAPPER_API_URL"
ENV_HA_AUTH_BIN = "HA3_WRAPPER_HA_AUTH_BIN"


class ConfigError(RuntimeError):
    pass


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
    raise ConfigError(f"Missing required runtime env: {ENV_API_URL}")


def load_runtime_config() -> RuntimeConfig:
    _load_dotenv_if_present()

    api_addr = _required_api_addr()
    ha_auth_bin = str(os.environ.get(ENV_HA_AUTH_BIN, "")).strip() or None

    return RuntimeConfig(api_addr=api_addr, ha_auth_bin=ha_auth_bin)

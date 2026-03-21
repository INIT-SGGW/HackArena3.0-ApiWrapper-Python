from __future__ import annotations

import os

from hackarena3.types import RuntimeConfig

ENV_API_ADDR = "HA3_WRAPPER_API_ADDR"
ENV_HA_AUTH_BIN = "HA3_WRAPPER_HA_AUTH_BIN"


class ConfigError(RuntimeError):
    pass


def _required_env(name: str) -> str:
    value = str(os.environ.get(name, "")).strip()
    if not value:
        raise ConfigError(f"Missing required runtime env: {name}")
    return value


def load_runtime_config() -> RuntimeConfig:
    api_addr = _required_env(ENV_API_ADDR)
    ha_auth_bin = str(os.environ.get(ENV_HA_AUTH_BIN, "")).strip() or None

    return RuntimeConfig(api_addr=api_addr, ha_auth_bin=ha_auth_bin)

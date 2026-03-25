from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hackarena3.config import (
    ConfigError,
    OfficialRuntimeConfig,
    load_official_runtime_config,
    load_runtime_config,
)

if TYPE_CHECKING:
    from hackarena3.types import BotProtocol, RuntimeConfig

_SANDBOX_FLAG = "--sandbox_id"
_OFFICIAL_FLAG = "--official"


@dataclass(frozen=True, slots=True)
class _CliOverrides:
    sandbox_id: str | None
    official: bool


def _parse_cli_overrides() -> _CliOverrides:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument(_SANDBOX_FLAG, dest="sandbox_id")
    parser.add_argument(_OFFICIAL_FLAG, action="store_true", dest="official")
    try:
        parsed, remaining = parser.parse_known_args(sys.argv[1:])
    except argparse.ArgumentError as exc:
        raise ConfigError(f"Invalid CLI arguments: {exc}") from exc

    sandbox_id = str(parsed.sandbox_id or "").strip()
    if parsed.sandbox_id is not None:
        if not sandbox_id:
            raise ConfigError(f"Empty value for {_SANDBOX_FLAG}.")
    if parsed.official and parsed.sandbox_id is not None:
        raise ConfigError(
            f"Conflicting CLI flags: {_OFFICIAL_FLAG} cannot be used together with {_SANDBOX_FLAG}."
        )

    sys.argv = [sys.argv[0], *remaining]
    return _CliOverrides(
        sandbox_id=sandbox_id or None,
        official=bool(parsed.official),
    )


def run_bot(bot: BotProtocol, config: RuntimeConfig | None = None) -> int:
    try:
        from hackarena3.runtime import run_runtime

        cli_overrides = _parse_cli_overrides()
        runtime_config = (
            config
            if config is not None
            else load_runtime_config(require_api_addr=not cli_overrides.official)
        )
        official_config: OfficialRuntimeConfig | None = None
        if cli_overrides.official:
            official_config = load_official_runtime_config()
        if cli_overrides.sandbox_id is not None:
            runtime_config.sandbox_id = cli_overrides.sandbox_id
        run_runtime(bot, runtime_config, official_config=official_config)
        return 0
    except KeyboardInterrupt:
        return 130
    except ModuleNotFoundError as exc:
        if exc.name == "grpc":
            print(
                "[ha3-wrapper] Missing dependency `grpcio`. Install package dependencies first.",
                file=sys.stderr,
            )
            return 1
        raise
    except (ConfigError, RuntimeError) as exc:
        print(f"[ha3-wrapper] {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"[ha3-wrapper] Unexpected error: {exc}", file=sys.stderr)
        return 1

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING

from hackarena3.config import (
    ConfigError,
    OfficialRuntimeConfig,
    StandaloneRuntimeConfig,
    load_official_runtime_config,
    load_runtime_config,
)

if TYPE_CHECKING:
    from hackarena3.types import BotProtocol, RuntimeConfig

_SANDBOX_FLAG = "--sandbox_id"
_OFFICIAL_FLAG = "--official"
_STANDALONE_RACE_FLAG = "--standalone-race"
_STANDALONE_SANDBOX_FLAG = "--standalone-sandbox"
_STANDALONE_ENDPOINT_FLAG = "--endpoint"
_STANDALONE_DISPLAY_NAME_FLAG = "--display-name"
_DEFAULT_STANDALONE_ENDPOINT = "localhost:50051"


@dataclass(frozen=True, slots=True)
class _CliOverrides:
    sandbox_id: str | None
    official: bool
    standalone_race: bool
    standalone_sandbox: bool
    standalone_endpoint: str | None
    standalone_display_name: str | None


def _parse_cli_overrides() -> _CliOverrides:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument(_SANDBOX_FLAG, dest="sandbox_id")
    parser.add_argument(_OFFICIAL_FLAG, action="store_true", dest="official")
    parser.add_argument(
        _STANDALONE_RACE_FLAG, action="store_true", dest="standalone_race"
    )
    parser.add_argument(
        _STANDALONE_SANDBOX_FLAG, action="store_true", dest="standalone_sandbox"
    )
    parser.add_argument(_STANDALONE_ENDPOINT_FLAG, dest="standalone_endpoint")
    parser.add_argument(_STANDALONE_DISPLAY_NAME_FLAG, dest="standalone_display_name")
    try:
        parsed, remaining = parser.parse_known_args(sys.argv[1:])
    except argparse.ArgumentError as exc:
        raise ConfigError(f"Invalid CLI arguments: {exc}") from exc

    sandbox_id = str(parsed.sandbox_id or "").strip()
    standalone_endpoint = parsed.standalone_endpoint
    standalone_display_name = parsed.standalone_display_name
    if parsed.sandbox_id is not None:
        if not sandbox_id:
            raise ConfigError(f"Empty value for {_SANDBOX_FLAG}.")
    if standalone_endpoint is not None:
        standalone_endpoint = str(standalone_endpoint).strip()
        if not standalone_endpoint:
            raise ConfigError(f"Empty value for {_STANDALONE_ENDPOINT_FLAG}.")

    standalone_direct = bool(parsed.standalone_race or parsed.standalone_sandbox)

    if parsed.standalone_race and parsed.standalone_sandbox:
        raise ConfigError(
            f"Conflicting CLI flags: {_STANDALONE_RACE_FLAG} cannot be used together with {_STANDALONE_SANDBOX_FLAG}."
        )
    if parsed.official and standalone_direct:
        conflicting_flag = (
            _STANDALONE_RACE_FLAG
            if parsed.standalone_race
            else _STANDALONE_SANDBOX_FLAG
        )
        raise ConfigError(
            f"Conflicting CLI flags: {_OFFICIAL_FLAG} cannot be used together with {conflicting_flag}."
        )
    if parsed.standalone_race and parsed.sandbox_id is not None:
        raise ConfigError(
            f"Conflicting CLI flags: {_STANDALONE_RACE_FLAG} cannot be used together with {_SANDBOX_FLAG}."
        )
    if parsed.official and parsed.sandbox_id is not None:
        raise ConfigError(
            f"Conflicting CLI flags: {_OFFICIAL_FLAG} cannot be used together with {_SANDBOX_FLAG}."
        )
    if parsed.standalone_sandbox and standalone_display_name is not None:
        raise ConfigError(
            f"Standalone local sandbox mode does not support {_STANDALONE_DISPLAY_NAME_FLAG}."
        )
    if not standalone_direct:
        if standalone_endpoint is not None:
            raise ConfigError(
                f"Standalone CLI flag {_STANDALONE_ENDPOINT_FLAG} requires {_STANDALONE_RACE_FLAG} or {_STANDALONE_SANDBOX_FLAG}."
            )
        if standalone_display_name is not None:
            raise ConfigError(
                f"Standalone CLI flag {_STANDALONE_DISPLAY_NAME_FLAG} requires {_STANDALONE_RACE_FLAG}."
            )

    sys.argv = [sys.argv[0], *remaining]
    return _CliOverrides(
        sandbox_id=sandbox_id or None,
        official=bool(parsed.official),
        standalone_race=bool(parsed.standalone_race),
        standalone_sandbox=bool(parsed.standalone_sandbox),
        standalone_endpoint=standalone_endpoint,
        standalone_display_name=standalone_display_name,
    )


def run_bot(bot: BotProtocol, config: RuntimeConfig | None = None) -> int:
    try:
        from hackarena3.runtime import run_runtime

        cli_overrides = _parse_cli_overrides()
        runtime_config = (
            config
            if config is not None
            else load_runtime_config(
                require_api_addr=not (
                    cli_overrides.official
                    or cli_overrides.standalone_race
                    or cli_overrides.standalone_sandbox
                )
            )
        )
        official_config: OfficialRuntimeConfig | None = None
        standalone_config: StandaloneRuntimeConfig | None = None
        if cli_overrides.official:
            official_config = load_official_runtime_config()
        if cli_overrides.standalone_race:
            standalone_config = StandaloneRuntimeConfig(
                grpc_target=cli_overrides.standalone_endpoint
                or _DEFAULT_STANDALONE_ENDPOINT,
                mode="race",
                display_name=cli_overrides.standalone_display_name or "",
            )
        if cli_overrides.standalone_sandbox:
            standalone_config = StandaloneRuntimeConfig(
                grpc_target=cli_overrides.standalone_endpoint
                or _DEFAULT_STANDALONE_ENDPOINT,
                mode="sandbox",
                sandbox_id=cli_overrides.sandbox_id,
            )
        if cli_overrides.sandbox_id is not None and standalone_config is None:
            runtime_config.sandbox_id = cli_overrides.sandbox_id
        run_runtime(
            bot,
            runtime_config,
            official_config=official_config,
            standalone_config=standalone_config,
        )
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

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from hackarena3.config import ConfigError, load_runtime_config

if TYPE_CHECKING:
    from hackarena3.types import BotProtocol, RuntimeConfig

_SANDBOX_FLAG = "--sandbox_id"


def _parse_cli_sandbox_override() -> str | None:
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument(_SANDBOX_FLAG, dest="sandbox_id")
    try:
        parsed, remaining = parser.parse_known_args(sys.argv[1:])
    except argparse.ArgumentError as exc:
        raise ConfigError(f"Invalid CLI arguments: {exc}") from exc

    sandbox_id = str(parsed.sandbox_id or "").strip()
    if parsed.sandbox_id is not None:
        if not sandbox_id:
            raise ConfigError(f"Empty value for {_SANDBOX_FLAG}.")

    sys.argv = [sys.argv[0], *remaining]
    return sandbox_id or None


def run_bot(bot: BotProtocol, config: RuntimeConfig | None = None) -> int:
    try:
        from hackarena3.runtime import run_runtime

        cli_sandbox_id = _parse_cli_sandbox_override()
        runtime_config = config if config is not None else load_runtime_config()
        if cli_sandbox_id is not None:
            runtime_config.sandbox_id = cli_sandbox_id
        run_runtime(bot, runtime_config)
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

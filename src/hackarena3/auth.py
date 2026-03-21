from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hackarena3.config import ENV_HA_AUTH_BIN


class AuthError(RuntimeError):
    pass


def _login_hint(binary: str) -> str:
    return f"Run `hackarena auth login` or `{binary} login`."


def _resolve_from_candidate(candidate: str | None) -> str | None:
    if not candidate:
        return None
    candidate_path = Path(candidate).expanduser()
    if candidate_path.is_file():
        return str(candidate_path.resolve())
    resolved = shutil.which(candidate)
    if resolved:
        return str(Path(resolved).resolve())
    return None


def resolve_ha_auth_binary(ha_auth_bin: str | None = None) -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    xdg_data_home = os.environ.get("XDG_DATA_HOME", "").strip() or str(
        Path("~/.local/share").expanduser()
    )

    candidates = [
        ha_auth_bin,
        os.environ.get(ENV_HA_AUTH_BIN),
    ]
    if local_app_data:
        candidates.append(
            str(Path(local_app_data) / "HackArena" / "bin" / "ha-auth.exe")
        )
    candidates.extend(
        [
            str(Path(xdg_data_home) / "hackarena" / "bin" / "ha-auth"),
            str(Path("~/.local/share/hackarena/bin/ha-auth").expanduser()),
            "ha-auth",
        ]
    )

    for candidate in candidates:
        resolved = _resolve_from_candidate(candidate)
        if resolved:
            return resolved

    raise AuthError(
        "Cannot find `ha-auth` binary. Run `hackarena install auth` or set "
        "HA3_WRAPPER_HA_AUTH_BIN."
    )


def _run_ha_auth_json(
    binary: str,
    args: list[str],
) -> tuple[dict[str, Any], int, str]:
    try:
        process = subprocess.run(
            [binary, *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise AuthError(f"Failed to run `{binary}`: {exc}") from exc

    command_display = f"{binary} {' '.join(args)}"
    stdout = process.stdout.strip()
    stderr = process.stderr.strip()
    if not stdout:
        if process.returncode != 0:
            return {}, process.returncode, stderr
        raise AuthError(f"`{command_display}` returned empty stdout.")

    try:
        payload: dict[str, Any] = json.loads(stdout)
    except json.JSONDecodeError as exc:
        if process.returncode != 0:
            return {}, process.returncode, stderr
        raise AuthError(f"`{command_display}` did not return valid JSON.") from exc
    return payload, process.returncode, stderr


def fetch_member_jwt(ha_auth_bin: str | None = None) -> str:
    binary = resolve_ha_auth_binary(ha_auth_bin)
    token_payload, token_code, token_stderr = _run_ha_auth_json(binary, ["token", "-q"])
    if token_code == 2:
        raise AuthError(f"Auth login required. {_login_hint(binary)}")
    if token_code != 0:
        details = f" stderr: {token_stderr}" if token_stderr else ""
        raise AuthError(
            f"Auth token retrieval failed with exit code {token_code}. "
            f"{_login_hint(binary)} "
            f"Check auth CLI diagnostics.{details}"
        )

    jwt = token_payload.get("token")

    if not isinstance(jwt, str) or not jwt.strip():
        raise AuthError("Auth token response is missing `token` field.")
    return jwt.strip()

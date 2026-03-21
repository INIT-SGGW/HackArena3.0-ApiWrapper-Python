from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import grpc

from hackarena3.proto.auth.v1 import game_token_issuer_pb2

_RPC_TIMEOUT_SECONDS = 10
_CHANNEL_OPTIONS = (("grpc.enable_http_proxy", 0),)
_ISSUE_METHOD = "/gametoken/auth.v1.GameTokenIssuerService/IssueGameToken"


class GameTokenError(RuntimeError):
    pass


@dataclass(slots=True)
class GameToken:
    token: str
    exp: int
    kid: str | None = None


def _normalize_grpc_target(api_addr: str) -> str:
    parsed = urlparse(api_addr.strip())
    if parsed.scheme != "https":
        raise GameTokenError(
            "Invalid api_addr URL scheme. Expected https://."
        )
    if not parsed.hostname:
        raise GameTokenError(f"Invalid api_addr URL: {api_addr!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise GameTokenError(f"Invalid api_addr port in URL: {api_addr!r}") from exc
    if port is None:
        port = 443
    target = f"{parsed.hostname}:{port}"
    return target


def _extract_exp_epoch(response: game_token_issuer_pb2.IssueGameTokenResponse) -> int:
    if response.HasField("token") and response.token.HasField("exp_utc"):
        exp_seconds = int(response.token.exp_utc.seconds)
        if exp_seconds > 0:
            return exp_seconds
    raise GameTokenError(
        "Game token response is missing a valid token.exp_utc timestamp."
    )


class GameTokenProvider:
    _member_jwt: str
    _target: str
    _channel: grpc.Channel
    _issue_game_token: grpc.UnaryUnaryMultiCallable[Any, Any]
    _request_info_logged: bool
    _current: GameToken | None

    def __init__(self, api_addr: str, member_jwt: str) -> None:
        jwt = member_jwt.strip()
        if not jwt:
            raise GameTokenError("member_jwt is empty; cannot request game token.")

        target = _normalize_grpc_target(api_addr)
        self._member_jwt = jwt
        self._target = target
        channel_credentials = grpc.ssl_channel_credentials()
        self._channel = grpc.secure_channel(
            target,
            channel_credentials,
            options=_CHANNEL_OPTIONS,
        )
        self._issue_game_token = self._channel.unary_unary(
            _ISSUE_METHOD,
            request_serializer=game_token_issuer_pb2.IssueGameTokenRequest.SerializeToString,
            response_deserializer=game_token_issuer_pb2.IssueGameTokenResponse.FromString,
        )
        self._request_info_logged = False
        self._current: GameToken | None = None

    def close(self) -> None:
        self._channel.close()

    def _request_game_token(self) -> GameToken:
        request = game_token_issuer_pb2.IssueGameTokenRequest(
            token_type=game_token_issuer_pb2.GAME_TOKEN_ISSUE_TYPE_TEAM_BOT_DEV
        )
        metadata = (
            ("authorization", f"Bearer {self._member_jwt}"),
            ("cookie", f"auth_token={self._member_jwt}"),
        )
        if not self._request_info_logged:
            print(
                f"[ha3-wrapper] Requesting game token via gRPC: "
                f"target={self._target} method={_ISSUE_METHOD}",
                file=sys.stderr,
            )
            self._request_info_logged = True
        try:
            response = self._issue_game_token(
                request,
                metadata=metadata,
                timeout=_RPC_TIMEOUT_SECONDS,
            )
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.UNIMPLEMENTED:
                raise GameTokenError(
                    "Game token service unavailable (UNIMPLEMENTED)."
                ) from exc
            raise GameTokenError(
                "Game token gRPC request failed: "
                f"{_ISSUE_METHOD}; code={exc.code().name}; details={exc.details() or 'no details'}"
            ) from exc

        if not response.HasField("token"):
            raise GameTokenError("Game token gRPC response is missing `token` payload.")

        token_jwt = response.token.jwt.strip()
        if not token_jwt:
            raise GameTokenError("Game token gRPC response has empty `token.jwt`.")

        exp_epoch = _extract_exp_epoch(response)
        kid = response.token.kid.strip() or None
        return GameToken(token=token_jwt, exp=exp_epoch, kid=kid)

    def _now_epoch(self) -> int:
        return int(datetime.now(tz=timezone.utc).timestamp())

    def refresh(self) -> GameToken:
        self._current = self._request_game_token()
        return self._current

    def get(self) -> GameToken:
        if self._current is None:
            return self.refresh()
        return self._current

    def ensure_fresh(self, refresh_skew_seconds: int = 30) -> bool:
        token = self.get()
        if self._now_epoch() >= token.exp - refresh_skew_seconds:
            previous = token.token
            refreshed = self.refresh()
            return refreshed.token != previous
        return False

    def grpc_metadata(self) -> tuple[tuple[str, str], ...]:
        token = self.get()
        return (("x-ha3-game-token", token.token),)

    def member_auth_metadata(self) -> tuple[tuple[str, str], ...]:
        return (("cookie", f"auth_token={self._member_jwt}"),)

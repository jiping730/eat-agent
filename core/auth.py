"""Small-platform authentication primitives.

The application supports anonymous development mode, service API keys, and
signed JWTs for platform users. User identity is always taken from the
verified token when JWT authentication is enabled.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from werkzeug.security import check_password_hash, generate_password_hash

from config import settings


class AuthenticationError(Exception):
    """Raised when an access credential is missing or invalid."""


class ConflictError(Exception):
    """Raised when a user or other unique resource already exists."""


@dataclass(frozen=True)
class AuthPrincipal:
    user_id: str
    roles: tuple[str, ...] = ()
    auth_type: str = "anonymous"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": "Bearer",
            "expires_in": self.expires_in,
        }


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self) -> None:
        self.secret = settings.jwt_secret

    @property
    def jwt_enabled(self) -> bool:
        return bool(self.secret) and (
            settings.auth_mode in {"jwt", "hybrid"}
            or (settings.auth_mode == "auto" and bool(settings.jwt_secret))
        )

    def hash_password(self, password: str) -> str:
        return generate_password_hash(password, method="scrypt")

    def verify_password(self, password_hash: str, password: str) -> bool:
        return check_password_hash(password_hash, password)

    def issue_tokens(self, user_id: str, roles: tuple[str, ...] = ()) -> TokenPair:
        if not self.secret:
            raise AuthenticationError("JWT_SECRET 未配置")
        now = datetime.now(timezone.utc)
        expires_in = max(60, settings.jwt_access_ttl_minutes * 60)
        payload = {
            "sub": user_id,
            "roles": list(roles),
            "iss": settings.jwt_issuer,
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
        }
        access_token = jwt.encode(payload, self.secret, algorithm="HS256")
        refresh_token = secrets.token_urlsafe(48)
        return TokenPair(access_token, refresh_token, expires_in)

    def decode_access_token(self, token: str) -> AuthPrincipal:
        if not self.secret:
            raise AuthenticationError("JWT_SECRET 未配置")
        try:
            payload = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                issuer=settings.jwt_issuer,
                options={"require": ["sub", "iss", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("登录状态无效或已过期") from exc
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise AuthenticationError("登录身份无效")
        roles = payload.get("roles", [])
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            roles = []
        return AuthPrincipal(user_id=user_id, roles=tuple(roles), auth_type="jwt")

    def authenticate(self, authorization: str | None, api_key: str | None) -> AuthPrincipal | None:
        mode = settings.auth_mode.lower().strip()
        if mode == "none":
            return None

        if authorization and authorization.lower().startswith("bearer "):
            if mode not in {"auto", "jwt", "hybrid"}:
                raise AuthenticationError("当前服务不接受 Bearer Token")
            return self.decode_access_token(authorization[7:].strip())

        if api_key and settings.app_api_key and secrets.compare_digest(api_key, settings.app_api_key):
            if mode in {"auto", "api_key", "hybrid"}:
                return AuthPrincipal(user_id="service", roles=("service",), auth_type="api_key")

        if mode == "auto" and not settings.app_api_key and not self.jwt_enabled:
            return None
        raise AuthenticationError("未授权")

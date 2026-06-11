from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)
user_bearer_security = Security(bearer_scheme)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: UUID
    organization_id: UUID | None
    roles: list[str]


async def require_service_api_key(api_key: str | None = Security(api_key_header)) -> str:
    if api_key and api_key in get_settings().service_api_keys:
        return api_key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid service API key.",
    )


async def require_user_jwt(
    credentials: HTTPAuthorizationCredentials | None = user_bearer_security,
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token.",
        )
    try:
        payload = verify_jwt(credentials.credentials, get_settings())
        return AuthenticatedUser(
            user_id=UUID(payload["sub"]),
            organization_id=UUID(payload["org"]) if payload.get("org") else None,
            roles=list(payload.get("roles", [])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token.",
        ) from exc


def create_jwt(
    subject: str,
    settings: Settings,
    expires_in_seconds: int = 3600,
    extra_claims: dict | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": subject,
        "iat": now,
        "exp": now + expires_in_seconds,
        **(extra_claims or {}),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{b64url_json(header)}.{b64url_json(payload)}"
    signature = sign_hs256(signing_input, settings.jwt_signing_key)
    return f"{signing_input}.{signature}"


def verify_jwt(token: str, settings: Settings) -> dict:
    try:
        encoded_header, encoded_payload, signature = token.split(".")
    except ValueError as exc:
        raise ValueError("JWT must have three segments.") from exc
    header = json.loads(b64url_decode(encoded_header))
    if header.get("alg") != "HS256":
        raise ValueError("Unsupported JWT algorithm.")
    signing_input = f"{encoded_header}.{encoded_payload}"
    expected_signature = sign_hs256(signing_input, settings.jwt_signing_key)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("Invalid JWT signature.")
    payload = json.loads(b64url_decode(encoded_payload))
    now = int(time.time())
    if payload.get("iss") != settings.jwt_issuer or payload.get("aud") != settings.jwt_audience:
        raise ValueError("Invalid JWT issuer or audience.")
    if int(payload.get("exp", 0)) < now:
        raise ValueError("JWT has expired.")
    return payload


def sign_hs256(signing_input: str, secret: str) -> str:
    digest = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return b64url_encode(digest)


def b64url_json(payload: dict) -> str:
    return b64url_encode(json.dumps(payload, separators=(",", ":")).encode())


def b64url_encode(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).rstrip(b"=").decode()


def b64url_decode(payload: str) -> bytes:
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(payload + padding)

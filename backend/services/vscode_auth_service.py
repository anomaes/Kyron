from __future__ import annotations

import hashlib
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import AuthenticatedUser
from backend.config import Settings
from backend.db.models import (
    ProviderIdentity,
    User,
    VsCodeClientSession,
    VsCodeDeviceAuthorization,
)

DEVICE_CODE_PREFIX = "kyr_dc_"
ACCESS_TOKEN_PREFIX = "kyr_at_"  # noqa: S105 - non-secret token type marker
REFRESH_TOKEN_PREFIX = "kyr_rt_"  # noqa: S105 - non-secret token type marker
USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _token(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(48)}"


@dataclass(frozen=True, slots=True)
class IssuedDeviceCode:
    device_code: str
    user_code: str
    expires_in: int
    interval: int


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class VsCodeAuthorizationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class VsCodeAuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def issue_device_code(self) -> IssuedDeviceCode:
        raw_device_code = _token(DEVICE_CODE_PREFIX)
        user_code = await self._unique_user_code()
        ttl = self.settings.VSCODE_DEVICE_CODE_TTL_SECONDS
        self.session.add(
            VsCodeDeviceAuthorization(
                device_code_hash=token_hash(raw_device_code),
                user_code=user_code,
                status="PENDING",
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
            )
        )
        await self.session.commit()
        return IssuedDeviceCode(
            device_code=raw_device_code,
            user_code=user_code,
            expires_in=ttl,
            interval=self.settings.VSCODE_DEVICE_POLL_INTERVAL_SECONDS,
        )

    async def get_pending_device(self, user_code: str) -> VsCodeDeviceAuthorization:
        row = await self.session.scalar(
            select(VsCodeDeviceAuthorization).where(
                VsCodeDeviceAuthorization.user_code == self.normalize_user_code(user_code)
            )
        )
        return self._require_pending_device(row)

    @staticmethod
    def _require_pending_device(
        row: VsCodeDeviceAuthorization | None,
    ) -> VsCodeDeviceAuthorization:
        if row is None or _aware(row.expires_at) <= datetime.now(UTC):
            raise VsCodeAuthorizationError("expired_token", "Connection code is invalid or expired")
        if row.status != "PENDING":
            raise VsCodeAuthorizationError(
                "invalid_request", "Connection code has already been used"
            )
        return row

    async def approve_device(
        self, user_code: str, user: AuthenticatedUser
    ) -> VsCodeDeviceAuthorization:
        row = self._require_pending_device(
            await self.session.scalar(
                select(VsCodeDeviceAuthorization)
                .where(
                    VsCodeDeviceAuthorization.user_code
                    == self.normalize_user_code(user_code)
                )
                .with_for_update()
            )
        )
        identity = await self.session.scalar(
            select(ProviderIdentity).where(
                ProviderIdentity.provider == user.provider,
                ProviderIdentity.provider_user_id == user.provider_user_id,
            )
        )
        if identity is None:
            raise RuntimeError("Authenticated user has no provider identity")
        row.status = "APPROVED"
        row.user_id = user.id
        row.provider_identity_id = identity.id
        row.approved_at = datetime.now(UTC)
        await self.session.commit()
        return row

    async def exchange_device_code(self, device_code: str) -> IssuedTokens:
        row = await self.session.scalar(
            select(VsCodeDeviceAuthorization)
            .where(VsCodeDeviceAuthorization.device_code_hash == token_hash(device_code))
            .with_for_update()
        )
        now = datetime.now(UTC)
        if row is None or _aware(row.expires_at) <= now:
            raise VsCodeAuthorizationError("expired_token", "Device code is invalid or expired")
        if row.status == "PENDING":
            raise VsCodeAuthorizationError(
                "authorization_pending", "The user has not approved this connection yet"
            )
        if row.status != "APPROVED" or row.user_id is None or row.provider_identity_id is None:
            raise VsCodeAuthorizationError("invalid_grant", "Device code has already been used")
        issued = self._new_session(row.user_id, row.provider_identity_id, now)
        row.status = "CONSUMED"
        row.consumed_at = now
        await self.session.commit()
        return issued

    async def refresh(self, refresh_token: str) -> IssuedTokens:
        row = await self.session.scalar(
            select(VsCodeClientSession)
            .where(VsCodeClientSession.refresh_token_hash == token_hash(refresh_token))
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            row is None
            or row.revoked_at is not None
            or _aware(row.refresh_expires_at) <= now
        ):
            raise VsCodeAuthorizationError("invalid_grant", "Refresh token is invalid or expired")
        access_token = _token(ACCESS_TOKEN_PREFIX)
        replacement_refresh_token = _token(REFRESH_TOKEN_PREFIX)
        row.access_token_hash = token_hash(access_token)
        row.refresh_token_hash = token_hash(replacement_refresh_token)
        row.access_expires_at = now + timedelta(
            seconds=self.settings.VSCODE_ACCESS_TOKEN_TTL_SECONDS
        )
        row.refresh_expires_at = now + timedelta(
            days=self.settings.VSCODE_REFRESH_TOKEN_TTL_DAYS
        )
        row.last_used_at = now
        await self.session.commit()
        return IssuedTokens(
            access_token=access_token,
            refresh_token=replacement_refresh_token,
            expires_in=self.settings.VSCODE_ACCESS_TOKEN_TTL_SECONDS,
        )

    async def revoke(self, refresh_token: str) -> None:
        row = await self.session.scalar(
            select(VsCodeClientSession)
            .where(VsCodeClientSession.refresh_token_hash == token_hash(refresh_token))
            .with_for_update()
        )
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self.session.commit()

    async def identity_for_access_token(self, access_token: str) -> AuthenticatedUser:
        result = await self.session.execute(
            select(VsCodeClientSession, User, ProviderIdentity)
            .join(User, User.id == VsCodeClientSession.user_id)
            .join(
                ProviderIdentity,
                ProviderIdentity.id == VsCodeClientSession.provider_identity_id,
            )
            .where(VsCodeClientSession.access_token_hash == token_hash(access_token))
        )
        record = result.one_or_none()
        now = datetime.now(UTC)
        if record is None:
            raise VsCodeAuthorizationError("invalid_token", "Access token is invalid")
        client_session, user, identity = record
        if (
            client_session.revoked_at is not None
            or _aware(client_session.access_expires_at) <= now
            or not user.is_active
        ):
            raise VsCodeAuthorizationError("invalid_token", "Access token is invalid or expired")
        last_used = client_session.last_used_at
        if (
            last_used is None
            or now - _aware(last_used)
            >= timedelta(seconds=self.settings.AUTH_USER_TOUCH_INTERVAL_SECONDS)
        ):
            client_session.last_used_at = now
            await self.session.commit()
        return AuthenticatedUser(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            provider=identity.provider,
            provider_user_id=identity.provider_user_id,
            provider_username=identity.username,
            is_system_admin=user.is_system_admin,
        )

    def _new_session(
        self, user_id: uuid.UUID, provider_identity_id: uuid.UUID, now: datetime
    ) -> IssuedTokens:
        access_token = _token(ACCESS_TOKEN_PREFIX)
        refresh_token = _token(REFRESH_TOKEN_PREFIX)
        self.session.add(
            VsCodeClientSession(
                user_id=user_id,
                provider_identity_id=provider_identity_id,
                access_token_hash=token_hash(access_token),
                refresh_token_hash=token_hash(refresh_token),
                access_expires_at=now
                + timedelta(seconds=self.settings.VSCODE_ACCESS_TOKEN_TTL_SECONDS),
                refresh_expires_at=now
                + timedelta(days=self.settings.VSCODE_REFRESH_TOKEN_TTL_DAYS),
                last_used_at=now,
            )
        )
        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.settings.VSCODE_ACCESS_TOKEN_TTL_SECONDS,
        )

    async def _unique_user_code(self) -> str:
        for _ in range(10):
            raw = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
            code = f"{raw[:4]}-{raw[4:]}"
            exists = await self.session.scalar(
                select(VsCodeDeviceAuthorization.id).where(
                    VsCodeDeviceAuthorization.user_code == code
                )
            )
            if exists is None:
                return code
        raise RuntimeError("Could not allocate a unique VS Code connection code")

    @staticmethod
    def normalize_user_code(value: str) -> str:
        allowed = string.ascii_uppercase + string.digits
        cleaned = "".join(character for character in value.upper() if character in allowed)
        return f"{cleaned[:4]}-{cleaned[4:]}" if len(cleaned) == 8 else value.upper()

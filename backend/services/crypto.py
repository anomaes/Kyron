from __future__ import annotations

import re
from collections.abc import Iterable

from cryptography.fernet import Fernet, InvalidToken

CREDENTIAL_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
COMMON_SECRET_PATTERNS = (
    re.compile(r"glpat-[A-Za-z0-9_-]+"),
    re.compile(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@"),
    re.compile(r"(?i)(api[_-]?key|token|secret)(\s*[=:]\s*)[^\s,;]+"),
)


class EncryptionError(RuntimeError):
    pass


class SecretCipher:
    def __init__(self, key: str | bytes, key_version: int = 1) -> None:
        if not key:
            raise EncryptionError("Credential encryption key is not configured")
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (TypeError, ValueError) as exc:
            raise EncryptionError("Credential encryption key is invalid") from exc
        self.key_version = key_version

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise EncryptionError("Stored credential cannot be decrypted") from exc


class SecretRedactor:
    def __init__(self, exact_values: Iterable[str] = ()) -> None:
        self._values = sorted({value for value in exact_values if value}, key=len, reverse=True)

    def redact(self, text: str) -> str:
        safe = text
        for value in self._values:
            safe = safe.replace(value, "[REDACTED]")
        for pattern in COMMON_SECRET_PATTERNS:
            if pattern.groups == 2:
                safe = pattern.sub(r"\1\2[REDACTED]", safe)
            elif pattern.groups == 1:
                safe = pattern.sub(r"\1[REDACTED]@", safe)
            else:
                safe = pattern.sub("[REDACTED]", safe)
        return safe

    def clear(self) -> None:
        self._values.clear()

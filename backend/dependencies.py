from typing import Annotated

from fastapi import Depends

from backend.config import Settings, get_settings
from backend.services.crypto import SecretCipher


def get_cipher(settings: Annotated[Settings, Depends(get_settings)]) -> SecretCipher:
    return SecretCipher(
        settings.CREDENTIALS_ENCRYPTION_KEY,
        settings.CREDENTIALS_ENCRYPTION_KEY_VERSION,
    )


Cipher = Annotated[SecretCipher, Depends(get_cipher)]

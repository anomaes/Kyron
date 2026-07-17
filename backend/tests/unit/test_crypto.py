from cryptography.fernet import Fernet

from backend.services.crypto import SecretCipher, SecretRedactor


def test_ciphertext_round_trip_does_not_contain_plaintext() -> None:
    cipher = SecretCipher(Fernet.generate_key())
    ciphertext = cipher.encrypt("sensitive-value")
    assert b"sensitive-value" not in ciphertext
    assert cipher.decrypt(ciphertext) == "sensitive-value"


def test_redactor_handles_exact_common_and_authenticated_url_values() -> None:
    redactor = SecretRedactor(["exact-secret"])
    safe = redactor.redact(
        "exact-secret glpat-abc_123 https://oauth2:password@example.com API_KEY=provider-key"
    )
    assert "exact-secret" not in safe
    assert "glpat-abc_123" not in safe
    assert "password" not in safe
    assert "provider-key" not in safe
    assert safe.count("[REDACTED]") == 4

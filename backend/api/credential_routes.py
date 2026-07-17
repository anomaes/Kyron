import uuid

from fastapi import APIRouter, HTTPException, Response, status

from backend.auth.dependencies import CurrentUser, DbSession
from backend.dependencies import Cipher
from backend.schemas.credential import CredentialCreate, CredentialResponse, CredentialUpdate
from backend.services.credential_service import CredentialService

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.get("", response_model=list[CredentialResponse])
async def list_credentials(
    user: CurrentUser, db: DbSession, cipher: Cipher
) -> list[CredentialResponse]:
    credentials = await CredentialService(db, cipher).list_for_user(user.id)
    return [CredentialResponse.model_validate(item) for item in credentials]


@router.post("", response_model=CredentialResponse, status_code=status.HTTP_201_CREATED)
async def create_credential(
    request: CredentialCreate, user: CurrentUser, db: DbSession, cipher: Cipher
) -> CredentialResponse:
    credential = await CredentialService(db, cipher).create(user.id, request)
    await db.commit()
    return CredentialResponse.model_validate(credential)


@router.put("/{credential_id}", response_model=CredentialResponse)
async def update_credential(
    credential_id: uuid.UUID,
    request: CredentialUpdate,
    user: CurrentUser,
    db: DbSession,
    cipher: Cipher,
) -> CredentialResponse:
    try:
        credential = await CredentialService(db, cipher).update(user.id, credential_id, request)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return CredentialResponse.model_validate(credential)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: uuid.UUID, user: CurrentUser, db: DbSession, cipher: Cipher
) -> Response:
    try:
        await CredentialService(db, cipher).delete(user.id, credential_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

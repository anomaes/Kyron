from fastapi import APIRouter

from backend.auth.dependencies import CurrentUser
from backend.schemas.auth import UserResponse

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.get("/me", response_model=UserResponse)
async def current_user(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)

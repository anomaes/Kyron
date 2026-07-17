from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import database_is_healthy, get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    database: str
    worker_mode: str = "in_process_single_worker"


@router.get("/health", response_model=HealthResponse)
async def health(
    response: Response, db: Annotated[AsyncSession, Depends(get_session)]
) -> HealthResponse:
    healthy = await database_is_healthy(db)
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        database="ok" if healthy else "error",
    )

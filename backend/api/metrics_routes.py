from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from backend.auth.dependencies import CurrentUser
from backend.config import Settings, get_settings
from backend.services.storage_metrics import measure_storage_roots, prometheus_storage_metrics

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=Response)
async def metrics(
    _: CurrentUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    usages = await asyncio.to_thread(measure_storage_roots, settings)
    return Response(
        prometheus_storage_metrics(usages),
        media_type="text/plain; version=0.0.4",
    )

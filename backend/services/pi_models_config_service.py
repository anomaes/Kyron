from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import Settings
from backend.db.models import PiModelsConfigRevision, PiModelsConfigState
from backend.engine.pi.models_config import (
    inspect_models_config,
    load_models_config,
    provider_catalog,
    validate_models_document,
)


@dataclass(frozen=True, slots=True)
class ResolvedPiModelsConfig:
    source: str
    document: dict[str, Any] | None
    revision_id: uuid.UUID | None = None
    version: int | None = None


def catalog_payload(document: dict[str, Any] | None) -> list[dict[str, Any]]:
    if document is None:
        return []
    return [
        {
            "id": item.id,
            "models": list(item.models),
            "required_credentials": list(item.required_credentials),
        }
        for item in provider_catalog(document)
    ]


class PiModelsConfigService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def resolve(self) -> ResolvedPiModelsConfig:
        state = await self.session.get(PiModelsConfigState, 1)
        if state is not None and state.active_revision_id is not None:
            revision = await self.session.get(PiModelsConfigRevision, state.active_revision_id)
            if revision is not None:
                return ResolvedPiModelsConfig(
                    source="database",
                    document=revision.document,
                    revision_id=revision.id,
                    version=revision.version,
                )
        # PI_MODELS_CONFIG_PATH is an optional bootstrap/fallback. Deployments do not
        # need to populate it once an administrator activates a database revision.
        if self.settings.PI_MODELS_CONFIG_PATH is not None:
            return ResolvedPiModelsConfig(
                source="file",
                document=load_models_config(self.settings.PI_MODELS_CONFIG_PATH),
            )
        return ResolvedPiModelsConfig(source="builtin", document=None)

    async def validate(self, document: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
        required = sorted(inspect_models_config(document))
        await validate_models_document(document)
        return catalog_payload(document), required

    async def create_and_activate(
        self, document: dict[str, Any], actor_id: uuid.UUID
    ) -> PiModelsConfigRevision:
        catalog, required = await self.validate(document)
        current_version = await self.session.scalar(
            select(func.max(PiModelsConfigRevision.version))
        )
        revision = PiModelsConfigRevision(
            version=(current_version or 0) + 1,
            document=document,
            provider_catalog=catalog,
            required_credentials=required,
            created_by=actor_id,
        )
        self.session.add(revision)
        await self.session.flush()
        await self._set_active(revision.id, actor_id)
        return revision

    async def activate(self, revision_id: uuid.UUID, actor_id: uuid.UUID) -> PiModelsConfigRevision:
        revision = await self.session.get(PiModelsConfigRevision, revision_id)
        if revision is None:
            raise LookupError("Pi models configuration revision does not exist")
        await self.validate(revision.document)
        await self._set_active(revision.id, actor_id)
        return revision

    async def deactivate(self, actor_id: uuid.UUID) -> None:
        await self._set_active(None, actor_id)

    async def revisions(self) -> list[PiModelsConfigRevision]:
        return list(
            await self.session.scalars(
                select(PiModelsConfigRevision).order_by(PiModelsConfigRevision.version.desc())
            )
        )

    async def _set_active(self, revision_id: uuid.UUID | None, actor_id: uuid.UUID) -> None:
        state = await self.session.get(PiModelsConfigState, 1)
        if state is None:
            state = PiModelsConfigState(id=1, active_revision_id=revision_id, updated_by=actor_id)
            self.session.add(state)
        else:
            state.active_revision_id = revision_id
            state.updated_by = actor_id

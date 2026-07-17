from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import WebhookDelivery


@dataclass(slots=True)
class DeliveryReservation:
    delivery: WebhookDelivery
    created: bool


class WebhookDeliveryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def try_begin(
        self,
        delivery_key: str,
        event_name: str,
        gitlab_project_id: int | None = None,
    ) -> DeliveryReservation:
        delivery = WebhookDelivery(
            delivery_key=delivery_key,
            event_name=event_name,
            gitlab_project_id=gitlab_project_id,
        )
        nested = await self.session.begin_nested()
        try:
            self.session.add(delivery)
            await self.session.flush()
        except IntegrityError:
            await nested.rollback()
            existing = await self.session.scalar(
                select(WebhookDelivery).where(WebhookDelivery.delivery_key == delivery_key)
            )
            if existing is None:
                raise
            return DeliveryReservation(existing, created=False)
        else:
            await nested.commit()
            return DeliveryReservation(delivery, created=True)

    async def finish(
        self, delivery_id: object, status: str, result: dict[str, Any]
    ) -> WebhookDelivery:
        delivery = (
            await self.session.execute(
                update(WebhookDelivery)
                .where(WebhookDelivery.id == delivery_id)
                .values(status=status, result=result, processed_at=datetime.now(UTC))
                .returning(WebhookDelivery)
            )
        ).scalar_one()
        return delivery

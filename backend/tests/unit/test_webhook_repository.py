from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.repositories.webhooks import WebhookDeliveryRepository


async def test_delivery_key_is_reserved_once(db_session: AsyncSession) -> None:
    repository = WebhookDeliveryRepository(db_session)
    first = await repository.try_begin("delivery-1", "Note Hook", 10)
    second = await repository.try_begin("delivery-1", "Note Hook", 10)
    assert first.created is True
    assert second.created is False
    assert second.delivery.id == first.delivery.id

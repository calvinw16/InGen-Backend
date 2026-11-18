"""Deliver signed outbox messages on a separate asynchronous loop."""

import asyncio
import hmac
import logging
import random
from datetime import UTC, datetime, timedelta

import httpx
import sqlalchemy as sa

from app.core.config import settings
from app.models import telemetry as db
from app.services.telemetry_store import engine

log = logging.getLogger(__name__)


def claim(now: datetime):
    c = db.outbox.c
    with engine().begin() as conn:
        candidate = (
            sa.select(c.id)
            .where(c.due <= now)
            .order_by(c.due, c.id)
            .limit(1)
            .scalar_subquery()
        )
        row = (
            conn.execute(
                db.outbox.update()
                .where(c.id == candidate, c.due <= now)
                .values(due=now + timedelta(seconds=30))
                .returning(*c)
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        subscriber = (
            conn.execute(
                sa.select(db.subscribers).where(
                    db.subscribers.c.id == row.subscriber_id
                )
            )
            .mappings()
            .one()
        )
        return row, subscriber


def settle(row, error: str | None, now: datetime) -> None:
    c = db.outbox.c
    attempts = row.attempts + 1
    with engine().begin() as conn:
        owned = (c.id == row.id, c.due == row.due)
        if error is not None and attempts <= settings.webhook_max_retries:
            delay = min(30, 2 ** (attempts - 1)) * random.uniform(0.75, 1.25)
            conn.execute(
                db.outbox.update()
                .where(*owned)
                .values(attempts=attempts, due=now + timedelta(seconds=delay))
            )
        else:
            removed = conn.execute(db.outbox.delete().where(*owned))
            if error is not None and removed.rowcount:
                conn.execute(
                    db.dead_letters.insert().values(
                        id=row.id,
                        event_id=row.event_id,
                        subscriber_id=row.subscriber_id,
                        attempts=attempts,
                        error=error,
                        failed_at=now,
                    )
                )


async def deliver_one(client: httpx.AsyncClient, now: datetime | None = None) -> bool:
    item = await asyncio.to_thread(claim, now or datetime.now(UTC))
    if item is None:
        return False
    row, subscriber = item
    error = None
    if subscriber.url not in settings.webhook_allowed_urls:
        error = "destination_not_allowed"
    else:
        body = row.body.encode("utf-8")
        signature = hmac.digest(subscriber.secret.encode(), body, "sha256").hex()
        try:
            async with asyncio.timeout(5), client.stream(
                "POST",
                subscriber.url,
                content=body,
                follow_redirects=False,
                headers={
                    "Content-Type": "application/json",
                    "X-InGen-Signature": "sha256=" + signature,
                    "X-InGen-Delivery": row.id,
                },
            ) as response:
                if not response.is_success:
                    error = f"http_{response.status_code}"
        except (httpx.RequestError, TimeoutError):
            error = "transport_failure"
    await asyncio.to_thread(settle, row, error, now or datetime.now(UTC))
    return True


async def webhook_loop(stop: asyncio.Event) -> None:
    async with httpx.AsyncClient(trust_env=False, timeout=5) as client:
        while not stop.is_set():
            try:
                if await deliver_one(client):
                    continue
            except Exception:
                log.exception("webhook_worker_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.5)
            except TimeoutError:
                pass

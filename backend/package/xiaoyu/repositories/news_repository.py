from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select, and_

from xiaoyu.storage.postgres.manager import pg_manager
from xiaoyu.storage.postgres.models_news import NewsDigest, NewsSchedule
from xiaoyu.utils import logger


class NewsScheduleRepository:
    async def get_by_id(self, schedule_id: str) -> NewsSchedule | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(NewsSchedule).where(NewsSchedule.id == schedule_id)
            )
            return result.scalar_one_or_none()

    async def list_by_user(self, created_by: str | None = None) -> list[NewsSchedule]:
        async with pg_manager.get_async_session_context() as session:
            stmt = select(NewsSchedule).order_by(NewsSchedule.created_at.desc())
            if created_by:
                stmt = stmt.where(NewsSchedule.created_by == created_by)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_enabled(self) -> list[NewsSchedule]:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(NewsSchedule)
                .where(NewsSchedule.enabled.is_(True))
                .order_by(NewsSchedule.trigger_time)
            )
            return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> NewsSchedule:
        async with pg_manager.get_async_session_context() as session:
            record = NewsSchedule(**data)
            session.add(record)
            await session.flush()
            await session.refresh(record)
            return record

    async def update(self, schedule_id: str, data: dict[str, Any]) -> NewsSchedule | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(NewsSchedule).where(NewsSchedule.id == schedule_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            for key, value in data.items():
                setattr(record, key, value)
            await session.flush()
            await session.refresh(record)
            return record

    async def delete(self, schedule_id: str) -> bool:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                delete(NewsSchedule).where(NewsSchedule.id == schedule_id)
            )
            return result.rowcount > 0


class NewsDigestRepository:
    async def get_by_id(self, digest_id: str) -> NewsDigest | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(NewsDigest).where(NewsDigest.id == digest_id)
            )
            return result.scalar_one_or_none()

    async def list_digests(
        self,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[NewsDigest], int]:
        async with pg_manager.get_async_session_context() as session:
            stmt = select(NewsDigest)
            count_stmt = select(NewsDigest.id)

            if status:
                stmt = stmt.where(NewsDigest.status == status)
                count_stmt = count_stmt.where(NewsDigest.status == status)
            if date_from:
                stmt = stmt.where(NewsDigest.digest_date >= date_from)
                count_stmt = count_stmt.where(NewsDigest.digest_date >= date_from)
            if date_to:
                stmt = stmt.where(NewsDigest.digest_date <= date_to)
                count_stmt = count_stmt.where(NewsDigest.digest_date <= date_to)
            if created_by:
                stmt = stmt.where(NewsDigest.created_by == created_by)
                count_stmt = count_stmt.where(NewsDigest.created_by == created_by)

            from sqlalchemy import func

            total = await session.execute(
                select(func.count()).select_from(count_stmt.subquery())
            )
            total_count = total.scalar() or 0

            offset = (page - 1) * page_size
            stmt = stmt.order_by(NewsDigest.created_at.desc()).offset(offset).limit(page_size)
            result = await session.execute(stmt)
            records = list(result.scalars().all())
            return records, total_count

    async def create(self, data: dict[str, Any]) -> NewsDigest:
        async with pg_manager.get_async_session_context() as session:
            record = NewsDigest(**data)
            session.add(record)
            await session.flush()
            await session.refresh(record)
            return record

    async def update(self, digest_id: str, data: dict[str, Any]) -> NewsDigest | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(NewsDigest).where(NewsDigest.id == digest_id)
            )
            record = result.scalar_one_or_none()
            if record is None:
                return None
            for key, value in data.items():
                setattr(record, key, value)
            await session.flush()
            await session.refresh(record)
            return record

    async def update_progress(self, digest_id: str, stage: str, percent: float) -> None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(NewsDigest).where(NewsDigest.id == digest_id)
            )
            record = result.scalar_one_or_none()
            if record:
                record.progress_stage = stage
                record.progress_percent = percent

    async def delete(self, digest_id: str) -> bool:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                delete(NewsDigest).where(NewsDigest.id == digest_id)
            )
            return result.rowcount > 0

    async def find_running_or_completed(
        self, schedule_id: str, digest_date: date, language: str
    ) -> NewsDigest | None:
        async with pg_manager.get_async_session_context() as session:
            result = await session.execute(
                select(NewsDigest).where(
                    and_(
                        NewsDigest.schedule_id == schedule_id,
                        NewsDigest.digest_date == digest_date,
                        NewsDigest.language == language,
                        NewsDigest.status.in_(["running", "completed"]),
                    )
                )
            )
            return result.scalar_one_or_none()
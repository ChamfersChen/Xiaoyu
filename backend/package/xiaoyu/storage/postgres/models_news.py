"""PostgreSQL 数据模型 — 新闻摘要与调度配置"""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from xiaoyu.storage.postgres.models_business import Base
from xiaoyu.utils.datetime_utils import format_utc_datetime, utc_now_naive


class NewsSchedule(Base):
    """新闻定时调度配置"""

    __tablename__ = "news_schedules"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(100), default="default")
    enabled = Column(Boolean, default=True)
    trigger_time = Column(String(5), default="08:00")
    model_spec = Column(String, nullable=True)
    language = Column(String(5), default="zh")
    source_config = Column(JSONB, default=dict)
    ai_score_threshold = Column(Float, default=5.0)
    webhook_config = Column(JSONB, nullable=True)
    created_by = Column(String(64), nullable=True, index=True)
    last_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    __table_args__ = (
        UniqueConstraint("name", "created_by", name="uq_news_schedule_name_created_by"),
    )

    digests = relationship("NewsDigest", back_populates="schedule", lazy="selectin")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "trigger_time": self.trigger_time,
            "model_spec": self.model_spec,
            "language": self.language,
            "source_config": self.source_config,
            "ai_score_threshold": self.ai_score_threshold,
            "webhook_config": self.webhook_config,
            "created_by": self.created_by,
            "last_run_at": format_utc_datetime(self.last_run_at),
            "last_run_status": self.last_run_status,
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }


class NewsDigest(Base):
    """新闻摘要记录"""

    __tablename__ = "news_digests"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    schedule_id = Column(
        String(64), ForeignKey("news_schedules.id", ondelete="SET NULL"), nullable=True
    )
    title = Column(String(500), nullable=False)
    digest_date = Column(DateTime, nullable=False, index=True)
    language = Column(String(5), default="zh")
    status = Column(String(20), default="pending")
    trigger_type = Column(String(20), default="manual")
    total_fetched = Column(Integer, default=0)
    total_selected = Column(Integer, default=0)
    progress_stage = Column(String(30), nullable=True)
    progress_percent = Column(Float, default=0.0)
    items = Column(JSONB, default=list)
    md_bucket = Column(String, nullable=True)
    md_object_name = Column(String, nullable=True)
    md_file_url = Column(String, nullable=True)
    raw_markdown = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    model_spec = Column(String, nullable=True)
    source_config = Column(JSONB, nullable=True)
    webhook_config = Column(JSONB, nullable=True)
    webhook_status = Column(String(20), nullable=True)
    webhook_error = Column(Text, nullable=True)
    created_by = Column(String(64), nullable=True, index=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)
    updated_at = Column(DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    schedule = relationship("NewsSchedule", back_populates="digests")

    __table_args__ = (
        Index("idx_news_digests_date", "digest_date"),
        Index("idx_news_digests_status", "status"),
        Index("idx_news_digests_created_by", "created_by"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schedule_id": self.schedule_id,
            "title": self.title,
            "digest_date": self.digest_date.isoformat() if self.digest_date else None,
            "language": self.language,
            "status": self.status,
            "trigger_type": self.trigger_type,
            "total_fetched": self.total_fetched,
            "total_selected": self.total_selected,
            "progress_stage": self.progress_stage,
            "progress_percent": self.progress_percent,
            "items": self.items,
            "md_file_url": self.md_file_url,
            "raw_markdown": self.raw_markdown,
            "error_message": self.error_message,
            "model_spec": self.model_spec,
            "webhook_status": self.webhook_status,
            "webhook_error": self.webhook_error,
            "created_by": self.created_by,
            "started_at": format_utc_datetime(self.started_at),
            "finished_at": format_utc_datetime(self.finished_at),
            "created_at": format_utc_datetime(self.created_at),
            "updated_at": format_utc_datetime(self.updated_at),
        }
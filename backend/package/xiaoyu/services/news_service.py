"""News digest service — orchestrates Horizon pipeline, persistence, and webhook delivery."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timezone
from datetime import datetime


from xiaoyu.horizon.ai.client import XiaoyuAIClient
from xiaoyu.horizon.ai.summarizer import DailySummarizer
from xiaoyu.horizon.models import Config, SourcesConfig, FilteringConfig, AIConfig, AIProvider
from xiaoyu.horizon.orchestrator import HorizonOrchestrator
from xiaoyu.horizon.services.webhook import WebhookNotifier
from xiaoyu.repositories.news_repository import NewsDigestRepository, NewsScheduleRepository
from xiaoyu.services.run_queue_service import (
    clear_cancel_signal,
    get_arq_pool,
    has_cancel_signal,
    publish_cancel_signal,
)
from xiaoyu.storage.minio.client import MinIOClient
from xiaoyu.utils.datetime_utils import utc_now_naive
from xiaoyu.utils import logger

NEWS_BUCKET = "news-summaries"

_progress_stages = [
    ("fetching", 10),
    ("analyzing", 30),
    ("deduplicating", 50),
    ("enriching", 70),
    ("summarizing", 90),
    ("completed", 100),
]


def _build_source_config(raw: dict | None) -> SourcesConfig:
    if not raw:
        return SourcesConfig()
    return SourcesConfig(**raw)


def _build_ai_config(model_spec: str | None, languages:list[str]=['zh']) -> AIConfig:
    return AIConfig(
        provider=AIProvider.OPENAI,
        model="unused",
        api_key_env="UNUSED",
        base_url="http://localhost",
        languages=languages
    )


def _render_markdown_from_items(items: list[dict], metadata: dict) -> str:
    summarizer = DailySummarizer()
    from xiaoyu.horizon.models import ContentItem

    content_items = []
    for raw in items:
        item = ContentItem(**{k: v for k, v in raw.items() if k in ContentItem.model_fields})
        content_items.append(item)

    language = metadata.get("language", "zh")
    digest_date = metadata.get("digest_date", date.today().isoformat())
    total_fetched = metadata.get("total_fetched", len(content_items))
    return summarizer.generate_summary(content_items, digest_date, total_fetched, language=language)


def _content_item_to_dict(item) -> dict:
    data = item.metadata
    for key, value in data.items():
        if isinstance(value, datetime):
            data[key] = value.isoformat()
    return data


class NewsService:
    def __init__(self):
        self.digest_repo = NewsDigestRepository()
        self.schedule_repo = NewsScheduleRepository()

    async def trigger_run(
        self,
        *,
        model_spec: str | None = None,
        source_config: dict | None = None,
        language: str = "zh",
        schedule_id: str | None = None,
        webhook_config: dict | None = None,
        created_by: str | None = None,
    ) -> dict:
        title = f"News Digest - {date.today().isoformat()}"
        if language == "zh":
            title = f"新闻速递 - {date.today().isoformat()}"

        digest = await self.digest_repo.create(
            {
                "id": str(uuid.uuid4()),
                "title": title,
                "digest_date": utc_now_naive(),
                "language": language,
                "status": "pending",
                "trigger_type": "manual",
                "model_spec": model_spec,
                "source_config": source_config,
                "webhook_config": webhook_config,
                "created_by": created_by,
            }
        )

        if schedule_id:
            await self.digest_repo.update(digest.id, {"schedule_id": schedule_id})

        return digest.to_dict()

    async def trigger_run_from_schedule(self, schedule: dict) -> dict | None:
        schedule_id = schedule["id"]
        language = schedule.get("language", "zh")

        existing = await self.digest_repo.find_running_or_completed(schedule_id, date.today(), language)
        if existing:
            logger.info(f"Digest already exists for schedule {schedule_id} today, skipping")
            return None

        title = f"News Digest - {date.today().isoformat()}"
        if language == "zh":
            title = f"新闻速递 - {date.today().isoformat()}"

        digest = await self.digest_repo.create(
            {
                "id": str(uuid.uuid4()),
                "schedule_id": schedule_id,
                "title": title,
                "digest_date": date.today(),
                "language": language,
                "status": "pending",
                "trigger_type": "scheduled",
                "model_spec": schedule.get("model_spec"),
                "source_config": schedule.get("source_config"),
                "webhook_config": schedule.get("webhook_config"),
                "created_by": schedule.get("created_by"),
            }
        )

        return digest.to_dict()

    async def execute_run(self, ctx: dict, digest_id: str) -> None:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest:
            logger.error(f"Digest {digest_id} not found")
            return

        if digest.status not in ("pending", "running"):
            if digest.status == "cancelled":
                await clear_cancel_signal(digest_id)
            logger.info(f"Digest {digest_id} already in status {digest.status}, skipping")
            return

        if await has_cancel_signal(digest_id):
            logger.info(f"Digest {digest_id} cancelled via signal, skipping")
            await clear_cancel_signal(digest_id)
            return

        try:
            await self._update_status(digest_id, "running", started_at=utc_now_naive())
            await self._update_progress(digest_id, "fetching", 5)

            model_spec = digest.model_spec
            source_config = digest.source_config or {}
            language = digest.language or "zh"
            ai_score_threshold = 5.0

            if digest.schedule_id:
                schedule = await self.schedule_repo.get_by_id(digest.schedule_id)
                if schedule:
                    ai_score_threshold = schedule.ai_score_threshold or 5.0

            def ai_client_factory(json_mode: bool = False) -> XiaoyuAIClient:
                spec = model_spec or "openai:gpt-4o"
                return XiaoyuAIClient(model_spec=spec, json_mode=json_mode)

            hor_config = Config(
                ai=_build_ai_config(model_spec, languages=[language]),
                sources=_build_source_config(source_config),
                filtering=FilteringConfig(ai_score_threshold=ai_score_threshold),
            )

            webhook_notifier = None
            webhook_cfg = digest.webhook_config
            if webhook_cfg and webhook_cfg.get("enabled"):
                from xiaoyu.horizon.models import WebhookConfig

                wc = WebhookConfig(
                    url_env="NEWS_WEBHOOK_URL",
                    request_body=webhook_cfg.get("request_body"),
                    headers=webhook_cfg.get("headers"),
                    delivery=webhook_cfg.get("delivery", "summary"),
                    platform=webhook_cfg.get("platform", "generic"),
                    layout=webhook_cfg.get("layout", "markdown"),
                    enabled=True,
                )
                if webhook_cfg.get("url"):
                    import os

                    os.environ["NEWS_WEBHOOK_URL"] = webhook_cfg["url"]
                webhook_notifier = WebhookNotifier(wc)

            orchestrator = HorizonOrchestrator(
                config=hor_config,
                ai_client_factory=ai_client_factory,
                webhook_notifier=webhook_notifier,
            )

            await self._update_progress(digest_id, "analyzing", 25)

            run_task = asyncio.create_task(orchestrator.run())

            while True:
                done, _ = await asyncio.wait([run_task], timeout=2)
                if run_task in done:
                    break
                if await has_cancel_signal(digest_id):
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass
                    logger.info(f"Digest {digest_id} cancelled during execution")
                    return

            result = run_task.result()

            await self._update_progress(digest_id, "summarizing", 85)

            summaries = result.get("summaries", {})
            important_items = result.get("important_items", [])
            all_items_count = result.get("all_items_count", 0)
            digest_date = result.get("date", date.today().isoformat())

            markdown = summaries.get(language, summaries.get("en", ""))
            if not markdown and important_items:
                markdown = DailySummarizer().generate_summary(
                    important_items, digest_date, all_items_count, language=language
                )

            items_data = [_content_item_to_dict(item) for item in important_items]

            md_object_name = f"news/{digest_id}/{digest_date}-{language}.md"
            try:
                minio = MinIOClient()
                upload_result = await minio.aupload_file(
                    bucket_name=NEWS_BUCKET,
                    object_name=md_object_name,
                    data=markdown.encode("utf-8"),
                    content_type="text/markdown",
                )
                md_bucket = upload_result.bucket_name
                md_file_url = upload_result.url
            except Exception as e:
                logger.warning(f"Failed to upload markdown to MinIO: {e}")
                md_bucket = None
                md_object_name = None
                md_file_url = None

            await self.digest_repo.update(
                digest_id,
                {
                    "status": "completed",
                    "total_fetched": all_items_count,
                    "total_selected": len(important_items),
                    "items": items_data,
                    "raw_markdown": markdown,
                    "md_bucket": md_bucket,
                    "md_object_name": md_object_name,
                    "md_file_url": md_file_url,
                    "progress_stage": "completed",
                    "progress_percent": 100.0,
                    "finished_at": utc_now_naive(),
                    # "finished_at": datetime.now(timezone.utc),
                },
            )

            if digest.schedule_id:
                await self.schedule_repo.update(
                    digest.schedule_id,
                    {
                        "last_run_at": utc_now_naive(),
                        "last_run_status": "completed",
                    },
                )

        except Exception as e:
            logger.error(f"News digest pipeline failed for {digest_id}: {e}", exc_info=True)
            await self.digest_repo.update(
                digest_id,
                {
                    "status": "failed",
                    "error_message": str(e),
                    "progress_stage": "failed",
                    "finished_at": utc_now_naive(),
                },
            )
            if digest.schedule_id:
                await self.schedule_repo.update(
                    digest.schedule_id,
                    {
                        "last_run_at": utc_now_naive(),
                        "last_run_status": "failed",
                    },
                )
            raise
        finally:
            await clear_cancel_signal(digest_id)

    async def update_item(self, digest_id: str, item_index: int, updates: dict) -> dict | None:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest or not digest.items:
            return None

        items = digest.items
        if item_index < 0 or item_index >= len(items):
            return None

        for key, value in updates.items():
            if key in ("summary", "background", "tags", "title"):
                items[item_index][key] = value
        items[item_index]["is_edited"] = True

        await self.digest_repo.update(digest_id, {"items": items})
        return items[item_index]

    async def delete_item(self, digest_id: str, item_index: int) -> dict | None:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest or not digest.items:
            return None

        items = digest.items
        if item_index < 0 or item_index >= len(items):
            return None

        removed = items.pop(item_index)
        await self.digest_repo.update(digest_id, {"items": items})
        return removed

    async def update_markdown(self, digest_id: str, raw_markdown: str | None) -> str | None:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest:
            return None

        await self.digest_repo.update(digest_id, {"raw_markdown": raw_markdown})
        return raw_markdown

    async def regenerate_markdown(self, digest_id: str) -> str | None:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest or not digest.items:
            return None

        metadata = {
            "language": digest.language,
            "digest_date": digest.digest_date.isoformat() if digest.digest_date else date.today().isoformat(),
            "total_fetched": digest.total_fetched,
        }
        markdown = _render_markdown_from_items(digest.items, metadata)
        await self.digest_repo.update(digest_id, {"raw_markdown": markdown})
        return markdown

    async def download_markdown(self, digest_id: str) -> str | None:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest:
            return None

        if digest.raw_markdown:
            return digest.raw_markdown

        if digest.md_bucket and digest.md_object_name:
            try:
                minio = MinIOClient()
                content = await minio.adownload_file(
                    bucket_name=digest.md_bucket,
                    object_name=digest.md_object_name,
                )
                return content.decode("utf-8") if isinstance(content, bytes) else content
            except Exception as e:
                logger.warning(f"Failed to download markdown from MinIO: {e}")

        return None

    async def cancel_digest(self, digest_id: str) -> bool:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest:
            return False

        await self.digest_repo.update(digest_id, {"status": "cancelled"})
        await publish_cancel_signal(digest_id)

        try:
            pool = await get_arq_pool()
            await pool.cancel_job(f"news:{digest_id}")
        except Exception:
            pass

        return True

    async def delete_digest(self, digest_id: str) -> bool:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest:
            return False

        if digest.md_bucket and digest.md_object_name:
            try:
                minio = MinIOClient()
                await minio.adelete_file(
                    bucket_name=digest.md_bucket,
                    object_name=digest.md_object_name,
                )
            except Exception as e:
                logger.warning(f"Failed to delete MinIO file for digest {digest_id}: {e}")

        return await self.digest_repo.delete(digest_id)

    async def deliver_webhook(self, digest_id: str) -> dict | None:
        digest = await self.digest_repo.get_by_id(digest_id)
        if not digest:
            return None

        webhook_cfg = digest.webhook_config
        if not webhook_cfg or not webhook_cfg.get("enabled"):
            await self.digest_repo.update(
                digest_id,
                {
                    "webhook_status": "skipped",
                    "webhook_error": None,
                },
            )
            return {"status": "skipped", "error": "Webhook not enabled"}

        try:
            from xiaoyu.horizon.models import WebhookConfig as HWConfig, ContentItem

            wc = HWConfig(
                url_env="NEWS_WEBHOOK_URL",
                request_body=webhook_cfg.get("request_body"),
                headers=webhook_cfg.get("headers"),
                delivery=webhook_cfg.get("delivery", "summary"),
                platform=webhook_cfg.get("platform", "generic"),
                layout=webhook_cfg.get("layout", "markdown"),
                enabled=True,
            )
            if webhook_cfg.get("url"):
                import os

                os.environ["NEWS_WEBHOOK_URL"] = webhook_cfg["url"]

            notifier = WebhookNotifier(wc)

            items = []
            for raw_item in digest.items or []:
                try:
                    item = ContentItem(**{k: v for k, v in raw_item.items() if k in ContentItem.model_fields})
                    items.append(item)
                except Exception:
                    continue

            summarizer = DailySummarizer()
            await notifier.send_daily_summary(
                summary=digest.raw_markdown or "",
                important_items=items,
                all_items_count=digest.total_fetched or 0,
                date=digest.digest_date.isoformat() if digest.digest_date else date.today().isoformat(),
                lang=digest.language or "zh",
                summarizer=summarizer,
            )

            await self.digest_repo.update(
                digest_id,
                {
                    "webhook_status": "success",
                    "webhook_error": None,
                },
            )
            return {"status": "success"}

        except Exception as e:
            logger.error(f"Webhook delivery failed for digest {digest_id}: {e}", exc_info=True)
            await self.digest_repo.update(
                digest_id,
                {
                    "webhook_status": "failed",
                    "webhook_error": str(e),
                },
            )
            return {"status": "failed", "error": str(e)}

    async def _update_status(self, digest_id: str, status: str, **kwargs) -> None:
        data = {"status": status, **kwargs}
        await self.digest_repo.update(digest_id, data)

    async def _update_progress(self, digest_id: str, stage: str, percent: float) -> None:
        await self.digest_repo.update_progress(digest_id, stage, percent)

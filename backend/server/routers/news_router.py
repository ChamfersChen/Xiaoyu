"""News digest and schedule management router."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from server.utils.auth_middleware import get_db, get_required_user
from xiaoyu.repositories.news_repository import NewsDigestRepository, NewsScheduleRepository
from xiaoyu.services.news_service import NewsService
from xiaoyu.services.run_queue_service import get_arq_pool
from xiaoyu.services.run_worker import process_horizon_run
from xiaoyu.storage.postgres.models_business import User
from xiaoyu.utils import logger

news = APIRouter(prefix="/news", tags=["news"])


class TriggerDigestPayload(BaseModel):
    model_spec: str | None = Field(None, description="LLM 模型标识，如 openai:gpt-4o")
    language: str = Field("zh", description="摘要语言")
    source_config: dict | None = Field(None, description="Horizon 源配置 JSON")
    webhook_config: dict | None = Field(None, description="Webhook 投递配置")
    schedule_id: str | None = Field(None, description="关联的定时调度 ID")


class UpdateItemPayload(BaseModel):
    summary: str | None = None
    background: str | None = None
    tags: list[str] | None = None
    title: str | None = None


class UpdateMarkdownPayload(BaseModel):
    raw_markdown: str | None = None


class CreateSchedulePayload(BaseModel):
    name: str = Field("default", description="调度名称")
    enabled: bool = Field(True, description="是否启用")
    trigger_time: str = Field("08:00", description="每日触发时间 HH:MM")
    model_spec: str | None = Field(None, description="LLM 模型标识")
    language: str = Field("zh", description="摘要语言")
    source_config: dict | None = Field(None, description="Horizon 源配置 JSON")
    ai_score_threshold: float = Field(5.0, description="AI 评分阈值")
    webhook_config: dict | None = Field(None, description="Webhook 投递配置")


class UpdateSchedulePayload(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    trigger_time: str | None = None
    model_spec: str | None = None
    language: str | None = None
    source_config: dict | None = None
    ai_score_threshold: float | None = None
    webhook_config: dict | None = None


# ── Digest endpoints ──────────────────────────────────────────


@news.get("/digests")
async def list_digests(
    status: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_required_user),
):
    """分页查询新闻摘要列表"""
    repo = NewsDigestRepository()
    records, total = await repo.list_digests(
        status=status,
        date_from=date_from,
        date_to=date_to,
        created_by=current_user.uid,
        page=page,
        page_size=page_size,
    )
    return {
        "success": True,
        "data": [r.to_dict() for r in records],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@news.get("/digests/{digest_id}")
async def get_digest(
    digest_id: str,
    current_user: User = Depends(get_required_user),
):
    """获取新闻摘要详情"""
    repo = NewsDigestRepository()
    record = await repo.get_by_id(digest_id)
    if not record:
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"success": True, "data": record.to_dict()}

@news.post("/digests/trigger-test")
async def trigger_digest_test(
    payload: TriggerDigestPayload,
    current_user: User = Depends(get_required_user),
):
    """手动触发新闻摘要生成"""
    service = NewsService()
    result = await service.trigger_run(
        model_spec=payload.model_spec,
        source_config=payload.source_config,
        language=payload.language,
        schedule_id=payload.schedule_id,
        webhook_config=payload.webhook_config,
        created_by=current_user.uid,
    )

    digest_id = result["id"]
    await process_horizon_run(None, digest_id)
    return {"success": True, "data": result}

@news.post("/digests/trigger")
async def trigger_digest(
    payload: TriggerDigestPayload,
    current_user: User = Depends(get_required_user),
):
    """手动触发新闻摘要生成"""
    service = NewsService()
    result = await service.trigger_run(
        model_spec=payload.model_spec,
        source_config=payload.source_config,
        language=payload.language,
        schedule_id=payload.schedule_id,
        webhook_config=payload.webhook_config,
        created_by=current_user.uid,
    )

    digest_id = result["id"]
    pool = await get_arq_pool()
    await pool.enqueue_job("process_horizon_run", digest_id, _job_id=f"news:{digest_id}")

    return {"success": True, "data": result}


@news.get("/digests/{digest_id}/download")
async def download_digest_markdown(
    digest_id: str,
    current_user: User = Depends(get_required_user),
):
    """下载新闻摘要 Markdown"""
    service = NewsService()
    markdown = await service.download_markdown(digest_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="Digest or markdown not found")
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse(content=markdown, media_type="text/markdown")


@news.put("/digests/{digest_id}/items/{item_index}")
async def update_digest_item(
    digest_id: str,
    item_index: int,
    payload: UpdateItemPayload,
    current_user: User = Depends(get_required_user),
):
    """编辑摘要中的单个条目"""
    service = NewsService()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    result = await service.update_item(digest_id, item_index, updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Digest or item not found")
    return {"success": True, "data": result}


@news.delete("/digests/{digest_id}/items/{item_index}")
async def delete_digest_item(
    digest_id: str,
    item_index: int,
    current_user: User = Depends(get_required_user),
):
    """删除摘要中的单个条目"""
    service = NewsService()
    result = await service.delete_item(digest_id, item_index)
    if result is None:
        raise HTTPException(status_code=404, detail="Digest or item not found")
    return {"success": True, "data": result}


@news.put("/digests/{digest_id}/markdown")
async def update_digest_markdown(
    digest_id: str,
    payload: UpdateMarkdownPayload,
    current_user: User = Depends(get_required_user),
):
    """保存编辑后的 Markdown 内容"""
    service = NewsService()
    result = await service.update_markdown(digest_id, payload.raw_markdown)
    if result is None:
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"success": True, "data": {"raw_markdown": result}}


@news.post("/digests/{digest_id}/cancel")
async def cancel_digest(
    digest_id: str,
    current_user: User = Depends(get_required_user),
):
    """取消并删除运行中的新闻摘要"""
    service = NewsService()
    cancelled = await service.cancel_digest(digest_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"success": True}


@news.delete("/digests/{digest_id}")
async def delete_digest(
    digest_id: str,
    current_user: User = Depends(get_required_user),
):
    """删除新闻摘要"""
    service = NewsService()
    deleted = await service.delete_digest(digest_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"success": True}


@news.post("/digests/{digest_id}/regenerate")
async def regenerate_digest_markdown(
    digest_id: str,
    current_user: User = Depends(get_required_user),
):
    """根据编辑后的 items 重新生成 Markdown"""
    service = NewsService()
    markdown = await service.regenerate_markdown(digest_id)
    if markdown is None:
        raise HTTPException(status_code=404, detail="Digest not found or no items")
    return {"success": True, "data": {"raw_markdown": markdown}}


@news.post("/digests/{digest_id}/webhook/retry")
async def retry_webhook(
    digest_id: str,
    current_user: User = Depends(get_required_user),
):
    """重试 Webhook 投递"""
    service = NewsService()
    result = await service.deliver_webhook(digest_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Digest not found")
    return {"success": True, "data": result}


# ── Schedule endpoints ─────────────────────────────────────────


@news.get("/schedules")
async def list_schedules(
    current_user: User = Depends(get_required_user),
):
    """查询当前用户的定时调度列表"""
    repo = NewsScheduleRepository()
    records = await repo.list_by_user(created_by=current_user.uid)
    return {"success": True, "data": [r.to_dict() for r in records]}


@news.post("/schedules")
async def create_schedule(
    payload: CreateSchedulePayload,
    current_user: User = Depends(get_required_user),
):
    """创建定时调度"""
    repo = NewsScheduleRepository()
    record = await repo.create({
        **payload.model_dump(),
        "created_by": current_user.uid,
    })
    return {"success": True, "data": record.to_dict()}


@news.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    payload: UpdateSchedulePayload,
    current_user: User = Depends(get_required_user),
):
    """更新定时调度"""
    repo = NewsScheduleRepository()
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    record = await repo.update(schedule_id, updates)
    if record is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"success": True, "data": record.to_dict()}
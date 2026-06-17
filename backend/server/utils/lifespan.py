import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from xiaoyu.services.task_service import tasker
from xiaoyu.agents.mcp.service import ensure_builtin_mcp_servers_in_db
from xiaoyu.models.providers.service import ensure_builtin_model_providers_in_db
from xiaoyu.services.run_queue_service import close_queue_clients, get_redis_client
from xiaoyu.storage.postgres.manager import pg_manager
from xiaoyu.knowledge import knowledge_base
from xiaoyu.utils import logger
from xiaoyu.utils.datetime_utils import utc_now_naive
from xiaoyu.agents.backends.sandbox import init_sandbox_provider, shutdown_sandbox_provider
from xiaoyu import get_version

_news_scheduler_task: asyncio.Task | None = None


async def _news_scheduler_loop():
    """Background coroutine: trigger Horizon runs at scheduled times."""
    from xiaoyu.repositories.news_repository import NewsScheduleRepository
    from xiaoyu.services.news_service import NewsService
    from xiaoyu.services.run_queue_service import get_arq_pool

    while True:
        try:
            repo = NewsScheduleRepository()
            schedules = await repo.list_enabled()
            now = utc_now_naive()
            now_hhmm = now.strftime("%H:%M")

            for schedule in schedules:
                if schedule.trigger_time != now_hhmm:
                    continue
                if schedule.last_run_status == "running":
                    continue

                service = NewsService()
                logger.info(f"News scheduler: triggering schedule {schedule.id} ({schedule.name})")
                result = await service.trigger_run_from_schedule(schedule.to_dict())
                if result:
                    digest_id = result["id"]
                    try:
                        pool = await get_arq_pool()
                        await pool.enqueue_job("process_horizon_run", digest_id, _job_id=f"news:{digest_id}")
                    except Exception as e:
                        logger.error(f"Failed to enqueue news job {digest_id}: {e}")

            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"News scheduler error: {e}")
            await asyncio.sleep(120)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan事件管理器"""
    # 初始化数据库连接
    try:
        pg_manager.initialize()
        await pg_manager.create_tables()
        await pg_manager.ensure_business_schema()
        await pg_manager.ensure_knowledge_schema()
    except Exception as e:
        logger.error(f"Failed to initialize database during startup: {e}")

    # 确保内置 MCP 服务器定义存在于数据库
    try:
        await ensure_builtin_mcp_servers_in_db()
    except Exception as e:
        logger.error(f"Failed to ensure builtin MCP servers during startup: {e}")

    try:
        from xiaoyu.agents.skills.service import init_builtin_skills

        async with pg_manager.get_async_session_context() as session:
            await init_builtin_skills(session)
    except Exception as e:
        logger.error(f"Failed to initialize builtin skills during startup: {e}")

    try:
        from xiaoyu.repositories.agent_repository import AgentRepository

        async with pg_manager.get_async_session_context() as session:
            repository = AgentRepository(session)
            await repository.ensure_default_agent()
            await repository.ensure_general_purpose_subagent()
            await repository.ensure_web_search_subagent()
            await repository.ensure_deep_research_agents()
    except Exception as e:
        logger.error(f"Failed to ensure default agent during startup: {e}")

    # 初始化内置模型供应商配置
    try:
        async with pg_manager.get_async_session_context() as session:
            await ensure_builtin_model_providers_in_db(session)
    except Exception as e:
        logger.error(f"Failed to ensure builtin model providers during startup: {e}")

    # 初始化模型缓存（v2 模型选择使用）
    try:
        from xiaoyu.models.providers.cache import model_cache
        from xiaoyu.models.providers.service import get_all_model_providers

        async with pg_manager.get_async_session_context() as session:
            providers = await get_all_model_providers(session)
            model_cache.rebuild(providers)
    except Exception as e:
        logger.error(f"Failed to initialize model cache during startup: {e}")

    # 初始化知识库管理器
    if os.environ.get("LITE_MODE", "").lower() in ("true", "1"):
        logger.info("LITE_MODE enabled, skipping knowledge base initialization")
    else:
        try:
            await knowledge_base.initialize()
        except Exception as e:
            logger.error(f"Failed to initialize knowledge base manager: {e}")

    # 预热 Redis（run 队列）
    try:
        redis = await get_redis_client()
        await redis.ping()
    except Exception as e:
        logger.warning(f"Run queue redis unavailable on startup: {e}")

    try:
        init_sandbox_provider()
    except Exception as e:
        logger.error(f"Failed to initialize sandbox provider during startup: {e}")

    # =========================================================
    # 2. 核心修复：在这里执行一次 setup()，建完表就拉倒
    # =========================================================
    checkpointer = AsyncPostgresSaver(pg_manager.langgraph_pool)
    await checkpointer.setup()
    print("LangGraph Checkpoint tables verified/created!")

    await tasker.start()
    _news_scheduler_task = asyncio.create_task(_news_scheduler_loop())
    logger.info(f"""

░██     ░██                       ░██
 ░██   ░██
  ░██ ░██   ░██    ░██ ░██    ░██ ░██
   ░████    ░██    ░██  ░██  ░██  ░██
    ░██     ░██    ░██   ░█████   ░██
    ░██     ░██   ░███  ░██  ░██  ░██
    ░██      ░█████░██ ░██    ░██ ░██  v{get_version()}

    """)
    logger.info("Xiaoyu backend startup complete")
    yield
    await tasker.shutdown()
    if _news_scheduler_task:
        _news_scheduler_task.cancel()
    shutdown_sandbox_provider()
    await close_queue_clients()
    await pg_manager.close()

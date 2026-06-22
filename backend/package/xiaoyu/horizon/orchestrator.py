"""Main orchestrator coordinating the entire workflow.

Adapted from Horizon (https://github.com/Thysrael/Horizon) for Xiaoyu integration.
Key changes: removed StorageManager/EmailManager/GitHubPages dependencies,
added ai_client_factory injection for XiaoyuAIClient support.
"""

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Dict, Optional
from urllib.parse import urlparse
import httpx

from xiaoyu.horizon.models import Config, ContentItem
from xiaoyu.horizon.services.webhook import WebhookNotifier
from xiaoyu.horizon.scrapers.github import GitHubScraper
from xiaoyu.horizon.scrapers.hackernews import HackerNewsScraper
from xiaoyu.horizon.scrapers.rss import RSSScraper
from xiaoyu.horizon.scrapers.reddit import RedditScraper
from xiaoyu.horizon.scrapers.telegram import TelegramScraper
from xiaoyu.horizon.scrapers.twitter import TwitterScraper
from xiaoyu.horizon.scrapers.twitter_playwright import TwitterPlaywrightScraper
from xiaoyu.horizon.scrapers.openbb import OpenBBScraper
from xiaoyu.horizon.scrapers.ossinsight import OSSInsightScraper
from xiaoyu.horizon.ai.client import AIClient, create_ai_client
from xiaoyu.horizon.ai.analyzer import ContentAnalyzer
from xiaoyu.horizon.ai.summarizer import DailySummarizer
from xiaoyu.horizon.ai.enricher import ContentEnricher
from xiaoyu.horizon.ai.tokens import get_usage_snapshot
from xiaoyu.utils import logger


@dataclass
class BalancedDigestResult:
    """Items and selection statistics from balanced digest filtering."""

    items: List[ContentItem]
    enabled: bool = False
    group_counts: Dict[str, int] = field(default_factory=dict)
    group_limits: Dict[str, Optional[int]] = field(default_factory=dict)
    duplicate_categories: List[str] = field(default_factory=list)


class HorizonOrchestrator:
    """Orchestrates the complete workflow for content aggregation and analysis.

    Adapted for Xiaoyu: accepts an optional ai_client_factory to inject
    XiaoyuAIClient instead of using Horizon's built-in AI providers.
    """

    def __init__(
        self,
        config: Config,
        ai_client_factory: Optional[Callable[..., AIClient]] = None,
        webhook_notifier: Optional[WebhookNotifier] = None,
    ):
        """Initialize orchestrator.

        Args:
            config: Application configuration
            ai_client_factory: Optional factory function that creates AIClient instances.
                When provided, this factory is used instead of create_ai_client(config.ai).
                Signature: ai_client_factory(json_mode: bool = False) -> AIClient
            webhook_notifier: Optional webhook notifier for delivery
        """
        self.config = config
        self._ai_client_factory = ai_client_factory
        self.webhook_notifier = webhook_notifier

    def _get_ai_client(self, json_mode: bool = False) -> AIClient:
        """Get an AI client, using the injected factory if available."""
        if self._ai_client_factory:
            return self._ai_client_factory(json_mode=json_mode)
        return create_ai_client(self.config.ai)

    async def run(self, force_hours: int = None) -> dict:
        """Execute the complete workflow.

        Adapted for Xiaoyu: returns a result dict instead of saving files.

        Args:
            force_hours: Optional override for time window in hours

        Returns:
            dict with keys: 'summaries' (dict of lang->markdown),
                            'important_items' (list of ContentItem),
                            'all_items_count' (int),
                            'date' (str)
        """
        logger.info("🌅 Horizon - Starting aggregation...")

        try:
            # 1. Determine time window
            since = self._determine_time_window(force_hours)
            logger.info(f"📅 Fetching content since: {since.strftime('%Y-%m-%d %H:%M:%S')}")

            # 2. Fetch content from all sources
            all_items = await self.fetch_all_sources(since)
            logger.info(f"📥 Fetched {len(all_items)} items from all sources")

            if not all_items:
                logger.info("No new content found. Exiting.")
                return {
                    "summaries": {},
                    "important_items": [],
                    "all_items_count": 0,
                    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }

            # 3. Merge cross-source duplicates (same URL from different sources)
            merged_items = self.merge_cross_source_duplicates(all_items)
            if len(merged_items) < len(all_items):
                logger.info(f"🔗 Merged {len(all_items) - len(merged_items)} cross-source duplicates "
                    f"→ {len(merged_items)} unique items\n"
                )

            # 4. Analyze with AI
            analyzed_items = await self._analyze_content(merged_items)
            logger.info(f"🤖 Analyzed {len(analyzed_items)} items with AI")

            # 5. Filter by score threshold
            threshold = self.config.filtering.ai_score_threshold
            important_items = [
                item for item in analyzed_items
                if item.ai_score and item.ai_score >= threshold
            ]
            important_items.sort(key=lambda x: x.ai_score or 0, reverse=True)

            logger.info(f"⭐️ {len(important_items)} items scored ≥ {threshold}\n"
            )

            # 5.5 Semantic deduplication: drop items covering the same topic
            deduped_items = await self.merge_topic_duplicates(important_items)
            if len(deduped_items) < len(important_items):
                logger.info(f"🧹 Removed {len(important_items) - len(deduped_items)} topic duplicates "
                    f"→ {len(deduped_items)} unique items\n"
                )
            important_items = deduped_items

            # 5.6 Optional second-stage Twitter reply expansion + targeted re-analysis
            await self._expand_twitter_discussion(important_items)

            # 5.7 Apply per-category and global digest limits before enrichment
            balanced_result = self.apply_balanced_digest(important_items)
            important_items = balanced_result.items

            # Show per-sub-source selection breakdown
            selected_counts: Dict[str, int] = defaultdict(int)
            for item in important_items:
                key = f"{item.source_type.value}/{self._sub_source_label(item)}"
                selected_counts[key] += 1
            for source_key, count in sorted(selected_counts.items()):
                logger.info(f"      • {source_key}: {count}")
            
            # 6. Search related stories + enrich with background knowledge (2nd AI pass)
            await self._enrich_important_items(important_items)

            # 7. Generate daily summaries for each configured language
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            summaries = {}
            for lang in self.config.ai.languages:
                summarizer = DailySummarizer()
                summary = await summarizer.generate_summary(important_items, today, len(all_items), language=lang)
                summaries[lang] = summary

                # Send webhook notification if configured (Xiaoyu-managed)
                if self.webhook_notifier:
                    try:
                        await self.webhook_notifier.send_daily_summary(
                            summary=summary,
                            important_items=important_items,
                            all_items_count=len(all_items),
                            date=today,
                            lang=lang,
                            summarizer=summarizer,
                        )
                    except Exception as e:
                        logger.warning(f"Webhook delivery failed (pipeline continues): {e}")

            logger.info("✅ Horizon completed successfully!")
            usage = get_usage_snapshot()
            if usage.total_tokens > 0:
                logger.info(f"\n🧮 Token usage this run: "
                    f"{usage.total_tokens} tokens "
                    f"(input: {usage.total_input_tokens}, output: {usage.total_output_tokens})"
                )
                for provider, u in sorted(usage.per_provider.items()):
                    if u.total <= 0:
                        continue
                    logger.info(f"   • {provider}: {u.total} tokens "
                        f"(in: {u.input_tokens}, out: {u.output_tokens})"
                    )

            return {
                "summaries": summaries,
                "important_items": important_items,
                "all_items_count": len(all_items),
                "date": today,
            }

        except Exception as e:
            logger.info(f"❌ Error: {e}")

            # Send webhook failure notification if configured
            if self.webhook_notifier:
                try:
                    await self.webhook_notifier.send_failure(
                        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        error_message=str(e),
                    )
                except Exception:
                    logger.exception("Webhook failure notification failed (original error follows)")

            raise

    def _determine_time_window(self, force_hours: int = None) -> datetime:
        if force_hours:
            since = datetime.now(timezone.utc) - timedelta(hours=force_hours)
        else:
            hours = self.config.filtering.time_window_hours
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return since

    async def fetch_all_sources(self, since: datetime) -> List[ContentItem]:
        """Fetch content from all configured sources.

        This is a stable stage entry point for integrations such as MCP.

        Args:
            since: Fetch items published after this time

        Returns:
            List[ContentItem]: All fetched items
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []

            # GitHub sources
            if self.config.sources.github:
                github_scraper = GitHubScraper(self.config.sources.github, client)
                tasks.append(self._fetch_with_progress("GitHub", github_scraper, since))

            # Hacker News
            if self.config.sources.hackernews.enabled:
                hn_scraper = HackerNewsScraper(self.config.sources.hackernews, client)
                tasks.append(self._fetch_with_progress("Hacker News", hn_scraper, since))

            # RSS feeds
            if self.config.sources.rss:
                rss_scraper = RSSScraper(self.config.sources.rss, client)
                tasks.append(self._fetch_with_progress("RSS Feeds", rss_scraper, since))

            # Reddit
            if self.config.sources.reddit.enabled:
                reddit_scraper = RedditScraper(self.config.sources.reddit, client)
                tasks.append(self._fetch_with_progress("Reddit", reddit_scraper, since))

            # Telegram
            if self.config.sources.telegram.enabled:
                telegram_scraper = TelegramScraper(self.config.sources.telegram, client)
                tasks.append(self._fetch_with_progress("Telegram", telegram_scraper, since))

            # Twitter (Apify or Playwright mode)
            if self.config.sources.twitter and self.config.sources.twitter.enabled:
                tw_cfg = self.config.sources.twitter
                if tw_cfg.mode == "playwright":
                    twitter_scraper = TwitterPlaywrightScraper(tw_cfg)
                else:
                    twitter_scraper = TwitterScraper(tw_cfg, client)
                tasks.append(self._fetch_with_progress("Twitter", twitter_scraper, since))

            # OpenBB (financial news / filings via the OpenBB Platform SDK)
            if self.config.sources.openbb and self.config.sources.openbb.enabled:
                openbb_scraper = OpenBBScraper(self.config.sources.openbb, client)
                tasks.append(self._fetch_with_progress("OpenBB", openbb_scraper, since))

            # OSS Insight trending repos
            if self.config.sources.ossinsight and self.config.sources.ossinsight.enabled:
                oss_scraper = OSSInsightScraper(self.config.sources.ossinsight, client)
                tasks.append(self._fetch_with_progress("OSS Insight", oss_scraper, since))

            # Fetch all concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Flatten results
            all_items = []
            for result in results:
                if isinstance(result, Exception):
                    logger.info(f"Error fetching source: {result}")
                elif isinstance(result, list):
                    all_items.extend(result)

            return all_items

    async def _fetch_with_progress(self, name: str, scraper, since: datetime) -> List[ContentItem]:
        """Fetch from a scraper with progress indication.

        Args:
            name: Source name for display
            scraper: Scraper instance
            since: Fetch items after this time

        Returns:
            List[ContentItem]: Fetched items
        """
        logger.info(f"🔍 Fetching from {name}...")
        items = await scraper.fetch(since)
        logger.info(f"   Found {len(items)} items from {name}")

        # Show per-sub-source breakdown when there are multiple sub-sources
        sub_counts: Dict[str, int] = defaultdict(int)
        for item in items:
            sub_counts[self._sub_source_label(item)] += 1
        if len(sub_counts) > 1:
            for sub, count in sorted(sub_counts.items()):
                logger.info(f"      • {sub}: {count}")

        return items

    @staticmethod
    def _sub_source_label(item: ContentItem) -> str:
        """Return a human-readable sub-source label for an item."""
        meta = item.metadata
        if meta.get("subreddit"):
            return f"r/{meta['subreddit']}"
        if meta.get("feed_name"):
            return meta["feed_name"]
        if meta.get("channel"):
            return f"@{meta['channel']}"
        if meta.get("period") and meta.get("repo"):
            return f"ossinsight:{meta.get('primary_language', 'all')}"
        if meta.get("repo"):
            return meta["repo"]
        if meta.get("watchlist"):
            return meta["watchlist"]
        return item.author or "unknown"

    def merge_cross_source_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Merge items that point to the same URL from different sources.

        This is a stable stage helper for integrations such as MCP.

        Keeps the item with the richest content and combines metadata.

        Args:
            items: Items to deduplicate

        Returns:
            List[ContentItem]: Deduplicated items
        """
        def normalize_url(url: str) -> str:
            parsed = urlparse(str(url))
            # Strip www prefix, trailing slashes, and fragments
            host = parsed.hostname or ""
            if host.startswith("www."):
                host = host[4:]
            path = parsed.path.rstrip("/")
            return f"{host}{path}"

        # Group by normalized URL
        url_groups: Dict[str, List[ContentItem]] = {}
        for item in items:
            key = normalize_url(str(item.url))
            url_groups.setdefault(key, []).append(item)

        merged = []
        for key, group in url_groups.items():
            if len(group) == 1:
                merged.append(group[0])
                continue

            # Pick the item with the richest content as primary
            primary = max(group, key=lambda x: len(x.content or ""))

            # Merge metadata and source info from other items
            all_sources = set()
            for item in group:
                all_sources.add(item.source_type.value)
                # Merge metadata (engagement, discussion, etc.)
                for mk, mv in item.metadata.items():
                    if mk not in primary.metadata or not primary.metadata[mk]:
                        primary.metadata[mk] = mv

                # Append content (e.g., comments from another source)
                if item is not primary and item.content:
                    if primary.content and item.content not in primary.content:
                        primary.content = (primary.content or "") + f"\n\n--- From {item.source_type.value} ---\n" + item.content

            primary.metadata["merged_sources"] = list(all_sources)
            merged.append(primary)

        return merged

    async def merge_topic_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Merge items covering the same topic using AI semantic deduplication.

        This is a stable stage helper for integrations such as MCP.

        Sends all item titles, tags, and summaries to AI in a single call.
        Items must already be sorted by ai_score descending so that the first
        item in each duplicate group is always the highest-scored one.
        Content (comments) from duplicate items is merged into the primary.

        Falls back to returning items unchanged if the AI call fails.
        """
        if len(items) <= 1:
            return items

        from xiaoyu.horizon.ai.prompts import TOPIC_DEDUP_SYSTEM, TOPIC_DEDUP_USER
        from xiaoyu.horizon.ai.utils import parse_json_response

        # Build the item list for the prompt
        lines = []
        for i, item in enumerate(items):
            tags = ", ".join(item.ai_tags) if item.ai_tags else "—"
            summary = item.ai_summary or "—"
            lines.append(f"[{i}] {item.title}\n    Tags: {tags}\n    Summary: {summary}")
        items_text = "\n\n".join(lines)

        try:
            ai_client = self._get_ai_client(json_mode=True)
            response = await ai_client.complete(
                system=TOPIC_DEDUP_SYSTEM,
                user=TOPIC_DEDUP_USER.format(items=items_text),
            )
            result = parse_json_response(response)
            if result is None:
                logger.info("  dedup: could not parse AI response, skipping")
                return items

            duplicate_groups = result.get("duplicates", [])
        except Exception as e:
            logger.info(f"  dedup: AI call failed ({e}), skipping")
            return items

        if not duplicate_groups:
            return items

        # Build a set of indices to drop (all non-primary duplicates)
        drop_indices: set[int] = set()
        for group in duplicate_groups:
            if not isinstance(group, list) or len(group) < 2:
                continue
            primary_idx = group[0]
            if primary_idx < 0 or primary_idx >= len(items):
                continue
            primary = items[primary_idx]
            for dup_idx in group[1:]:
                if not isinstance(dup_idx, int) or dup_idx < 0 or dup_idx >= len(items):
                    continue
                if dup_idx == primary_idx:
                    continue
                dup = items[dup_idx]
                # Merge comments/content from the duplicate into the primary
                if dup.content:
                    if not primary.content or dup.content not in primary.content:
                        label = dup.source_type.value
                        primary.content = (primary.content or "") + f"\n\n--- From {label} ---\n{dup.content}"
                logger.info(f"   dedup: keep [{primary_idx}] {primary.title}\n"
                    f"          drop [{dup_idx}] {dup.title}")
                drop_indices.add(dup_idx)

        return [item for i, item in enumerate(items) if i not in drop_indices]

    def apply_balanced_digest(
        self,
        items: List[ContentItem],
        *,
        log: bool = True,
    ) -> BalancedDigestResult:
        """Apply configured category quotas and the final item cap.

        Categories are read from ``item.metadata["category"]``. If a category
        appears in more than one configured group, the first group in config
        order wins.
        """
        filtering = self.config.filtering
        groups = filtering.category_groups
        max_items = filtering.max_items

        if not groups and max_items is None:
            return BalancedDigestResult(items=items)

        sorted_items = sorted(
            items,
            key=lambda item: item.ai_score or 0,
            reverse=True,
        )

        category_to_group: Dict[str, str] = {}
        duplicate_categories: List[str] = []
        for group_key, group in groups.items():
            for category in group.categories:
                if category in category_to_group:
                    if category_to_group[category] != group_key:
                        duplicate_categories.append(category)
                    continue
                category_to_group[category] = group_key

        if log:
            for category in sorted(set(duplicate_categories)):
                first_group = category_to_group[category]
                logger.info(f"Warning: category '{category}' is configured in multiple "
                    f"groups; using '{first_group}'.")

        selected: List[tuple[ContentItem, str]] = []
        group_counts: Dict[str, int] = defaultdict(int)
        default_group = filtering.default_group

        for item in sorted_items:
            category = item.metadata.get("category")
            group_key = (
                category_to_group.get(category, default_group)
                if isinstance(category, str)
                else default_group
            )

            if group_key in groups:
                limit = groups[group_key].limit
            else:
                limit = filtering.default_group_limit

            if limit is not None and group_counts[group_key] >= limit:
                continue

            selected.append((item, group_key))
            group_counts[group_key] += 1

        if max_items is not None:
            selected = selected[:max_items]

        final_counts: Dict[str, int] = defaultdict(int)
        for _, group_key in selected:
            final_counts[group_key] += 1

        group_limits: Dict[str, Optional[int]] = {
            group_key: group.limit for group_key, group in groups.items()
        }
        group_limits.setdefault(default_group, filtering.default_group_limit)

        if log:
            logger.info(f"⚖️ Balanced digest selected {len(selected)}/{len(items)} items"
            )
            for group_key, group in groups.items():
                label = group.name or group_key
                logger.info(f"      • {label}: {final_counts.get(group_key, 0)}/{group.limit}"
                )
            if (
                final_counts.get(default_group, 0)
                or filtering.default_group_limit is not None
            ):
                limit_label = (
                    str(filtering.default_group_limit)
                    if filtering.default_group_limit is not None
                    else "unlimited"
                )
                logger.info(f"      • {default_group}: "
                    f"{final_counts.get(default_group, 0)}/{limit_label}"
                )
            
        return BalancedDigestResult(
            items=[item for item, _ in selected],
            enabled=True,
            group_counts=dict(final_counts),
            group_limits=group_limits,
            duplicate_categories=sorted(set(duplicate_categories)),
        )

    async def _expand_twitter_discussion(self, items: List[ContentItem]) -> None:
        """Second-stage: fetch reply text for important Twitter items and re-analyze.

        Only runs when sources.twitter.fetch_reply_text is True.
        Bounded by max_tweets_to_expand to control cost.
        """
        tw_cfg = self.config.sources.twitter
        if not tw_cfg or not tw_cfg.enabled or not tw_cfg.fetch_reply_text:
            return

        from xiaoyu.horizon.models import SourceType

        twitter_items = [
            item for item in items
            if item.source_type == SourceType.TWITTER
        ][:tw_cfg.max_tweets_to_expand]

        if not twitter_items:
            return

        logger.info(f"💬 Fetching reply text for {len(twitter_items)} Twitter items..."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            if tw_cfg.mode == "playwright":
                logger.info("   Reply expansion not yet supported in Playwright mode.")
                return
            scraper = TwitterScraper(tw_cfg, client)
            expanded = []
            for item in twitter_items:
                try:
                    reply_lines = await scraper.fetch_replies_for_item(item)
                    if TwitterScraper.append_discussion_content(item, reply_lines):
                        expanded.append(item)
                        logger.info(f"   💬 {len(reply_lines)} replies added to: {item.title[:60]}"
                        )
                except Exception as exc:
                    logger.info(f"   ⚠️  Reply fetch failed for {item.id}: {exc}")

        if not expanded:
            return

        logger.info(f"   Re-analyzing {len(expanded)} Twitter items with reply context...\n"
        )
        ai_client = self._get_ai_client(json_mode=True)
        analyzer = ContentAnalyzer(ai_client)
        await analyzer.analyze_batch(expanded)

    async def _enrich_important_items(self, items: List[ContentItem]) -> None:
        """Enrich items with background knowledge (2nd AI pass).

        For each item that passed the score threshold, call AI to generate
        background knowledge based on the item's actual content.

        Args:
            items: Important items to enrich (modified in-place)
        """
        if not items:
            return

        logger.info("📚 Enriching with background knowledge...")
        ai_client = self._get_ai_client(json_mode=True)
        enricher = ContentEnricher(ai_client)
        await enricher.enrich_batch(items)
        logger.info(f"   Enriched {len(items)} items")

    async def _analyze_content(self, items: List[ContentItem]) -> List[ContentItem]:
        """Analyze content items with AI.

        Args:
            items: Items to analyze

        Returns:
            List[ContentItem]: Analyzed items
        """
        logger.info("🤖 Analyzing content with AI...")

        ai_client = self._get_ai_client(json_mode=True)
        analyzer = ContentAnalyzer(ai_client)

        return await analyzer.analyze_batch(items)

    async def _generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary.

        Args:
            items: Important items to include (already enriched with background/related)
            date: Date string
            total_fetched: Total items fetched
            language: Output language ("en" or "zh")

        Returns:
            str: Markdown summary
        """
        logger.info("📝 Generating daily summary...")

        summarizer = DailySummarizer()

        return await summarizer.generate_summary(items, date, total_fetched, language=language)

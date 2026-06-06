"""core/research.py — AI 联网检索并自动加为来源

流程：用户给主题/需求 → LLM 生成多个搜索查询 → Bing 搜索 →
抓取网页正文 → 自动入库为来源。
"""
import logging
from typing import Callable, Optional

from core.ingest import ingest_text
from core.llm import llm
from core.parsers import parse_url
from core.websearch import search

log = logging.getLogger(__name__)

_MIN_SOURCE_TEXT = 200


async def _gen_queries(topic: str, n: int = 3) -> list[str]:
    """让 LLM 把用户需求拆成若干精准搜索查询词。"""
    prompt = (
        f"用户想研究以下主题：{topic}\n"
        f"请生成 {n} 个用于搜索引擎的精准中文查询词，覆盖不同角度，"
        "每个查询词简洁有效。\n"
        '返回 JSON：{"queries":["查询1","查询2","查询3"]}'
    )
    try:
        data = await llm.chat_json(
            prompt, system="你是检索策略助手，仅返回 JSON。", temperature=0.3,
        )
        qs = [str(q).strip() for q in (data.get("queries") or []) if str(q).strip()]
        return qs[:n] or [topic]
    except Exception:
        log.warning("查询词生成失败，回退到原始主题", exc_info=True)
        return [topic]


async def research_and_ingest(
    vault_uuid: str, topic: str, max_sources: int = 5,
    progress: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """AI 联网检索并入库。返回已添加来源 [{title, url, chunks}]。"""
    def _notify(msg: str) -> None:
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    _notify("正在分析需求，生成搜索策略...")
    queries = await _gen_queries(topic)

    seen_urls: set[str] = set()
    added: list[dict] = []

    for q in queries:
        if len(added) >= max_sources:
            break
        _notify(f"搜索：{q}")
        hits = search(q, max_results=5)
        for hit in hits:
            if len(added) >= max_sources:
                break
            u = hit["url"]
            if u in seen_urls:
                continue
            seen_urls.add(u)
            title = hit.get("title") or u
            _notify(f"抓取：{title[:40]}")
            try:
                parsed = parse_url(u)
            except Exception:
                continue
            text = (parsed.get("text") or "").strip()
            if len(text) < _MIN_SOURCE_TEXT:
                continue
            try:
                res = await ingest_text(
                    vault_uuid, title, text,
                    source_type="url", source_url=u,
                )
            except Exception:
                log.warning("入库失败: %s", u, exc_info=True)
                continue
            if res.get("status") == "ok":
                added.append({"title": title, "url": u,
                              "chunks": res.get("chunks", 0)})

    _notify(f"完成，新增 {len(added)} 个来源")
    return added

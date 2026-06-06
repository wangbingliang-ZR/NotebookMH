"""core/research.py — AI 联网检索候选来源（NotebookLM Discover 风格）

流程：
1. search_candidates(topic) → 搜索网页，返回候选列表（不入库）
2. UI 展示候选：标题 + 相关描述 + 链接，用户勾选
3. ingest_selected(vault_uuid, candidates) → 只导入用户选中的
"""
import logging
import re
from typing import Optional

from core.ingest import ingest_text
from core.llm import llm
from core.parsers import parse_url
from core.websearch import search

log = logging.getLogger(__name__)

_MIN_SOURCE_TEXT = 300   # 正文至少 300 字
_MIN_CHINESE_RATIO = 0.3  # 中文字符占比至少 30%


def _extract_keywords(topic: str) -> list[str]:
    """从主题提取核心关键词。"""
    raw = topic.strip()
    keywords = {raw}
    for length in range(2, min(5, len(raw) + 1)):
        for i in range(len(raw) - length + 1):
            w = raw[i:i + length]
            if any('\u4e00' <= c <= '\u9fff' for c in w):
                keywords.add(w)
    return list(keywords)


def _is_relevant(hit: dict, keywords: list[str]) -> bool:
    """标题+摘要是否包含核心关键词。"""
    text = f"{hit.get('title', '')} {hit.get('snippet', '')}".lower()
    return any(kw.lower() in text for kw in keywords)


def _content_quality(text: str) -> bool:
    """正文质量检查。"""
    if len(text) < _MIN_SOURCE_TEXT:
        return False
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(text.strip())
    if total_chars == 0:
        return False
    if chinese_chars / total_chars < _MIN_CHINESE_RATIO:
        return False
    sentences = re.split(r'[。！？.!?]', text)
    if len([s for s in sentences if len(s.strip()) > 10]) < 5:
        return False
    return True


async def _gen_queries(topic: str, n: int = 3) -> list[str]:
    """LLM 拆分需求为精准搜索查询词。"""
    prompt = (
        f"用户想研究：{topic}\n"
        f"请生成 {n} 个具体、精准的搜索引擎查询词，要求包含限定词，"
        "避免过于宽泛，能导向高质量中文资料。\n"
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


async def search_candidates(topic: str, max_candidates: int = 8) -> list[dict]:
    """搜索并抓取候选网页，返回 [{title, url, snippet, preview, text, ok}]。"""
    queries = await _gen_queries(topic)
    keywords = _extract_keywords(topic)

    seen_urls: set[str] = set()
    candidates: list[dict] = []
    _rejected = 0

    for q in queries:
        if len(candidates) >= max_candidates:
            break
        hits = search(q, max_results=10)
        hits = [h for h in hits if _is_relevant(h, keywords)]
        for hit in hits:
            if len(candidates) >= max_candidates:
                break
            u = hit["url"]
            if u in seen_urls:
                continue
            seen_urls.add(u)
            title = hit.get("title") or u
            try:
                parsed = parse_url(u)
            except Exception:
                continue
            text = (parsed.get("text") or "").strip()
            if not _content_quality(text):
                _rejected += 1
                continue
            preview = text[:200].replace("\n", " ")
            candidates.append({
                "title": title,
                "url": u,
                "snippet": hit.get("snippet", ""),
                "preview": preview,
                "text": text,
                "ok": True,
            })

    log.info("搜索完成: %d 候选, %d 被过滤", len(candidates), _rejected)
    return candidates


async def ingest_selected(vault_uuid: str, candidates: list[dict]) -> list[dict]:
    """导入用户选中的候选。返回成功入库的 [{title, url, chunks}]。"""
    added: list[dict] = []
    for c in candidates:
        try:
            res = await ingest_text(
                vault_uuid, c["title"], c["text"],
                source_type="url", source_url=c["url"],
            )
        except Exception:
            log.warning("入库失败: %s", c["url"], exc_info=True)
            continue
        if res.get("status") == "ok":
            added.append({
                "title": c["title"], "url": c["url"],
                "chunks": res.get("chunks", 0),
            })
    return added

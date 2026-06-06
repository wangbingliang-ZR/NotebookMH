"""core/research.py — AI 联网检索并自动加为来源

流程：用户给主题/需求 → LLM 生成多个搜索查询 → Bing 搜索 →
相关性过滤 → 抓取网页正文 → 质量质检 → 自动入库为来源。
"""
import logging
import re
from typing import Callable, Optional

from core.ingest import ingest_text
from core.llm import llm
from core.parsers import parse_url
from core.websearch import search

log = logging.getLogger(__name__)

_MIN_SOURCE_TEXT = 300   # 正文至少 300 字
_MIN_CHINESE_RATIO = 0.3  # 中文字符占比至少 30%


def _extract_keywords(topic: str) -> list[str]:
    """从主题提取核心关键词（简单分词，去停用词）。"""
    # 简单策略：取 2 字以上的词作为关键词
    raw = topic.strip()
    # 先尝试按常见粒度拆分
    keywords = set()
    # 加入完整主题
    keywords.add(raw)
    # 2-4 字滑动窗口
    for length in range(2, min(5, len(raw) + 1)):
        for i in range(len(raw) - length + 1):
            w = raw[i:i + length]
            if any('\u4e00' <= c <= '\u9fff' for c in w):
                keywords.add(w)
    return list(keywords)


def _is_relevant(hit: dict, keywords: list[str]) -> bool:
    """检查搜索结果标题+摘要是否包含至少一个核心关键词。"""
    text = f"{hit.get('title', '')} {hit.get('snippet', '')}".lower()
    return any(kw.lower() in text for kw in keywords)


def _content_quality(text: str) -> bool:
    """检查网页正文质量：中文字符占比、句子数量。"""
    if len(text) < _MIN_SOURCE_TEXT:
        return False
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    total_chars = len(text.strip())
    if total_chars == 0:
        return False
    if chinese_chars / total_chars < _MIN_CHINESE_RATIO:
        return False
    # 至少要有几句像样的内容
    sentences = re.split(r'[。！？.!?]', text)
    if len([s for s in sentences if len(s.strip()) > 10]) < 5:
        return False
    return True


async def _gen_queries(topic: str, n: int = 3) -> list[str]:
    """让 LLM 把用户需求拆成若干精准搜索查询词。"""
    prompt = (
        f"用户想研究：{topic}\n"
        f"请生成 {n} 个具体、精准的搜索引擎查询词，要求：\n"
        "1. 查询词要包含具体限定词（如年份、地点、考试类型等），避免过于宽泛\n"
        "2. 每个查询词应能导向高质量的中文资料网页\n"
        "3. 优先使用带引号的精确短语或包含关键术语的组合\n"
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
    keywords = _extract_keywords(topic)

    seen_urls: set[str] = set()
    added: list[dict] = []
    rejected = 0  # 统计被过滤掉的

    for q in queries:
        if len(added) >= max_sources:
            break
        _notify(f"搜索：{q}")
        hits = search(q, max_results=8)
        # 先按相关性过滤搜索结果
        hits = [h for h in hits if _is_relevant(h, keywords)]
        if not hits:
            continue

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
            if not _content_quality(text):
                rejected += 1
                log.debug("网页质量未通过: %s (长度=%s)", u, len(text))
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

    _notify(f"完成，新增 {len(added)} 个来源" +
            (f"（过滤掉 {rejected} 个低质量网页）" if rejected else ""))
    return added

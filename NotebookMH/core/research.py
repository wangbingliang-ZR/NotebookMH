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

_MIN_SOURCE_TEXT = 300
_MIN_CHINESE_RATIO = 0.3


def _extract_key_terms(topic: str) -> list[str]:
    """提取有意义的独立关键词（过滤停用词、单字）。"""
    raw = topic.strip()
    # 常见停用词
    stops = {"的", "了", "在", "是", "和", "与", "或", "及", "等", "年",
             "月", "日", "中", "上", "下", "新", "一个", "最新"}
    terms: set[str] = set()
    # 加入完整主题本身
    terms.add(raw)
    # 按空格拆分
    for part in raw.split():
        if len(part) >= 2 and part not in stops:
            terms.add(part)
    # 2-6 字滑动窗口提取中文词组
    for length in range(2, min(7, len(raw) + 1)):
        for i in range(len(raw) - length + 1):
            w = raw[i:i + length]
            if any('\u4e00' <= c <= '\u9fff' for c in w) and w not in stops:
                terms.add(w)
    # 过滤太短的纯英文/数字和过长的无意义串
    return [t for t in terms if len(t) >= 2 and len(t) <= 20]


def _is_relevant(hit: dict, key_terms: list[str], min_match: int = 2) -> bool:
    """
    搜索结果必须匹配至少 min_match 个关键概念。
    对"河北省中考生物2026考试大纲"：
    关键词 = [河北, 中考, 生物, 考试大纲, 2026]
    一个旅游新闻只匹配"河北" → 不够 → 过滤掉。
    """
    text = f"{hit.get('title', '')} {hit.get('snippet', '')}".lower()
    matched = 0
    for term in key_terms:
        if term.lower() in text:
            matched += 1
            # 完整主题匹配算 2 分
            if term == key_terms[0] and len(term) > 6:
                matched += 1
    return matched >= min_match


def _page_contains_terms(text: str, key_terms: list[str], min_match: int = 2) -> bool:
    """网页正文是否包含足够多的关键术语。"""
    lower = text.lower()
    matched = sum(1 for t in key_terms if t.lower() in lower)
    return matched >= min_match


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
        f"请生成 {n} 个用于搜索引擎的查询词，要求：\n"
        "1. 每个查询词必须包含主题中的核心概念（如地点、学科、考试类型等），不能只包含宽泛词\n"
        "2. 查询词应组合多个关键词，以提高搜索结果相关性\n"
        "3. 避免拆分核心短语（如'考试大纲'不应拆成'考试'和'大纲'单独查询）\n"
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
    key_terms = _extract_key_terms(topic)
    # 至少需要匹配 ceil(术语数 * 0.6) 个
    min_match = max(2, (len(key_terms) + 1) // 2)

    seen_urls: set[str] = set()
    candidates: list[dict] = []
    _rejected = 0

    for q in queries:
        if len(candidates) >= max_candidates:
            break
        hits = search(q, max_results=10)
        # 第一层过滤：标题/摘要必须匹配多个关键词
        hits = [h for h in hits if _is_relevant(h, key_terms, min_match=min_match)]
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
            # 第二层过滤：正文也必须包含足够多的关键术语
            if not _page_contains_terms(text, key_terms, min_match=min_match):
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

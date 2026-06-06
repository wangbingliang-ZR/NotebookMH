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

_MIN_SOURCE_TEXT = 150
_MIN_CHINESE_RATIO = 0.2


async def _llm_select_relevant(topic: str, hits: list[dict]) -> list[dict]:
    """
    核心：让 DeepSeek 语义判断哪些搜索结果与用户需求相关。
    不再用关键词字符串匹配，改由 AI 理解语义。

    输入 hits: [{title, url, snippet}, ...]
    返回: [{index, reason}, ...] —— index 指向 hits，reason 是“为什么相关”。
    """
    if not hits:
        return []

    # 把候选编号列给 LLM
    lines = []
    for i, h in enumerate(hits):
        title = (h.get("title") or "").strip()
        snippet = (h.get("snippet") or "").strip()[:120]
        lines.append(f"[{i}] 标题：{title}\n    摘要：{snippet}")
    listing = "\n".join(lines)

    prompt = (
        f"用户想研究的主题是：「{topic}」\n\n"
        f"以下是搜索引擎返回的候选网页（共 {len(hits)} 条）：\n"
        f"{listing}\n\n"
        "请你判断哪些网页与用户主题【真正语义相关】，可作为学习/研究资料。\n"
        "判断标准：\n"
        "- 内容主题与用户需求一致（即使用词不同，如“学业水平考试”等同于“中考”）\n"
        "- 排除无关的新闻、广告、旅游、导航页、纯列表页\n"
        "- 优先选择权威、信息密度高的资料（如官方文件、教育网站、专业文章）\n"
        "为每个选中的网页写一句简短说明，告诉用户它为什么相关。\n"
        '返回 JSON：{"selected":[{"index":0,"reason":"..."},{"index":3,"reason":"..."}]}\n'
        "如果没有任何相关结果，返回 {\"selected\":[]}。"
    )
    try:
        data = await llm.chat_json(
            prompt, system="你是资料筛选助手，擅长语义相关性判断，仅返回 JSON。",
            temperature=0.2,
        )
        sel = data.get("selected") or []
        out = []
        for item in sel:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            if isinstance(idx, int) and 0 <= idx < len(hits):
                out.append({"index": idx,
                            "reason": str(item.get("reason", "")).strip()})
        return out
    except Exception:
        log.warning("LLM 相关性筛选失败，回退为全部候选", exc_info=True)
        return [{"index": i, "reason": ""} for i in range(len(hits))]


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
    if len([s for s in sentences if len(s.strip()) > 8]) < 2:
        return False
    return True


async def _plan_research(topic: str) -> list[dict]:
    """
    把用户需求拆解成一套完整的【知识资料结构】，每个模块带搜索查询词。
    这是 Agent 自动补全的核心：像教研专家一样规划要收集哪些类别的资料。
    返回 [{"category","purpose","queries":[...]}, ...]
    """
    prompt = (
        f"用户的学习/研究需求是：「{topic}」\n\n"
        "请你作为资深教研/研究专家，把这个需求拆解成一套【完整的知识资料结构】，"
        "列出为满足该需求需要系统收集哪些类别的资料，形成一条完整的知识链。\n\n"
        "例如对于「某地某学科的考试备考」，通常需要：\n"
        "- 考试大纲/考试说明（明确考查范围、题型、分值）\n"
        "- 历年真题（最近 2-4 年，每年单独一个查询，含答案解析）\n"
        "- 最新考点/命题趋势分析\n"
        "- 配套教材/知识点梳理\n"
        "- 高质量模拟题/押题卷\n"
        "- 官方政策/考试通知\n\n"
        "请根据用户的【具体需求】灵活设计类别（不要照搬上面的例子），"
        "覆盖面要全，要有“最新”和“历年”的时间维度。\n"
        "为每个类别生成 1-3 个【精准、具体】的搜索查询词（含地点/学科/年份等限定词）。\n"
        '返回 JSON：{"modules":[{"category":"考试大纲","purpose":"明确考查范围",'
        '"queries":["2024河北中考生物考试大纲","河北中考生物考试说明"]},'
        '{"category":"2024年真题","purpose":"...","queries":["..."]}]}'
    )
    try:
        data = await llm.chat_json(
            prompt, system="你是教研规划专家，擅长把需求拆解成完整知识结构，仅返回 JSON。",
            temperature=0.4,
        )
        modules = []
        for m in (data.get("modules") or []):
            if not isinstance(m, dict):
                continue
            cat = str(m.get("category", "")).strip()
            queries = [str(q).strip() for q in (m.get("queries") or [])
                       if str(q).strip()]
            if cat and queries:
                modules.append({
                    "category": cat,
                    "purpose": str(m.get("purpose", "")).strip(),
                    "queries": queries[:3],
                })
        return modules or [{"category": "综合资料", "purpose": "",
                            "queries": [topic]}]
    except Exception:
        log.warning("知识结构规划失败，回退到简单查询", exc_info=True)
        return [{"category": "综合资料", "purpose": "", "queries": [topic]}]


async def _fetch_candidate(hit: dict, reason: str, category: str) -> Optional[dict]:
    """抓取单个网页全文并做质量检查，返回候选或 None。"""
    import asyncio
    u = hit["url"]
    title = hit.get("title") or u
    try:
        parsed = await asyncio.wait_for(
            asyncio.to_thread(parse_url, u), timeout=12,
        )
    except Exception:
        return None
    text = (parsed.get("text") or "").strip()
    if not _content_quality(text):
        return None
    return {
        "title": title,
        "url": u,
        "snippet": hit.get("snippet", ""),
        "reason": reason,
        "category": category,
        "preview": text[:200].replace("\n", " "),
        "text": text,
        "ok": True,
    }


async def plan_and_discover(topic: str, max_total: int = 30) -> list[dict]:
    """
    NotebookLM 风格的深度来源发现（Agent 自动规划知识结构）：
    1. LLM 规划知识结构（考纲/真题/考点/教材/模拟题/政策…）
    2. 每个模块的查询词分别联网搜索，全局去重、过滤微信
    3. 每个模块用 LLM 语义筛选相关结果
    4. 并行抓取选中网页全文
    返回扁平候选列表，每条带 category 标签。
    """
    import asyncio

    modules = await _plan_research(topic)
    log.info("规划出 %d 个知识模块: %s", len(modules),
             [m["category"] for m in modules])

    # ── 步骤 1+2：分模块搜索，全局去重 ──
    seen_urls: set[str] = set()
    for m in modules:
        m_hits: list[dict] = []
        for q in m["queries"]:
            try:
                hits = search(q, max_results=8)
            except Exception:
                continue
            for h in hits:
                u = h.get("url", "")
                if not u or u in seen_urls:
                    continue
                if "mp.weixin.qq.com" in u:
                    continue
                seen_urls.add(u)
                m_hits.append(h)
        m["hits"] = m_hits
        log.info("模块[%s] 搜到 %d 条", m["category"], len(m_hits))

    # ── 步骤 3：每模块 LLM 语义筛选 ──
    select_tasks = [
        _llm_select_relevant(f"{topic} - {m['category']}（{m['purpose']}）", m["hits"])
        for m in modules
    ]
    selections = await asyncio.gather(*select_tasks, return_exceptions=True)

    # ── 步骤 4：并行抓取选中网页 ──
    fetch_tasks = []
    for m, sel in zip(modules, selections):
        if isinstance(sel, Exception) or not sel:
            continue
        for s in sel:
            hit = m["hits"][s["index"]]
            fetch_tasks.append(
                _fetch_candidate(hit, s.get("reason", ""), m["category"])
            )

    results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
    candidates: list[dict] = []
    for r in results:
        if isinstance(r, dict) and r:
            candidates.append(r)
            if len(candidates) >= max_total:
                break

    log.info("深度发现完成: %d 个候选，覆盖 %d 个模块",
             len(candidates), len({c["category"] for c in candidates}))
    return candidates


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
    """
    NotebookLM 风格的来源发现：
    1. 多查询词搜索，汇总大量候选（仅标题+摘要，不抓全文）
    2. 把候选丢给 DeepSeek 做语义筛选，挑出相关的并写“为什么相关”
    3. 只对选中的网页抓取全文，做基础质量检查
    返回 [{title, url, snippet, reason, preview, text, ok}]。
    """
    queries = await _gen_queries(topic)

    # ── 步骤 1：广撒网，汇总去重，过滤微信 ──
    seen_urls: set[str] = set()
    all_hits: list[dict] = []
    for q in queries:
        hits = search(q, max_results=10)
        log.info("查询 [%s] 返回 %d 条", q, len(hits))
        for h in hits:
            u = h.get("url", "")
            if not u or u in seen_urls:
                continue
            # 跳过微信文章链接（反爬严重，服务器上几乎无法抓取）
            if "mp.weixin.qq.com" in u:
                continue
            seen_urls.add(u)
            all_hits.append(h)
    log.info("汇总去重后共 %d 条候选", len(all_hits))

    if not all_hits:
        return []

    # ── 步骤 2：DeepSeek 语义筛选 ──
    selected = await _llm_select_relevant(topic, all_hits)
    log.info("AI 语义筛选选中 %d 条", len(selected))

    # ── 步骤 3：仅对选中的抓全文 + 质量检查 ──
    candidates: list[dict] = []
    _rejected_quality = 0
    import asyncio
    for sel in selected:
        if len(candidates) >= max_candidates:
            break
        hit = all_hits[sel["index"]]
        u = hit["url"]
        title = hit.get("title") or u
        try:
            # 用 to_thread 避免阻塞，wait_for 防止超时
            parsed = await asyncio.wait_for(
                asyncio.to_thread(parse_url, u),
                timeout=12,
            )
        except asyncio.TimeoutError:
            log.debug("抓取超时: %s", u)
            continue
        except Exception:
            log.debug("抓取失败: %s", u)
            continue
        text = (parsed.get("text") or "").strip()
        if not _content_quality(text):
            _rejected_quality += 1
            continue
        preview = text[:200].replace("\n", " ")
        candidates.append({
            "title": title,
            "url": u,
            "snippet": hit.get("snippet", ""),
            "reason": sel.get("reason", ""),
            "preview": preview,
            "text": text,
            "ok": True,
        })

    log.info("发现完成: %d 个候选, 质量过滤掉 %d", len(candidates), _rejected_quality)
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

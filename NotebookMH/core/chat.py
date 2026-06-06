"""core/chat.py — 对话编排"""
import logging
from typing import AsyncIterator, Optional

from core.db import db_manager
from core.llm import llm
from core.rag import retrieve

log = logging.getLogger(__name__)

_SYSTEM_PROMPT_SOURCES = """你是 NotebookMH，一个基于用户上传资料回答问题的智能助手。

回答规则：
1. 仅基于"参考资料"作答，不引入外部知识。
2. 在引用资料处用 [1] [2] 等编号，与参考资料编号一致。
3. 若资料不足以回答，诚实说"根据当前资料无法回答"。
4. 用简体中文，简洁清晰，必要时分点列出。
5. 不要重复参考资料原文，要做总结和整合。"""

_SYSTEM_PROMPT_GENERAL = """你是 NotebookMH，一个智能学习助手。

当前笔记库暂无资料，你可以：
1. 基于自身知识直接回答用户问题。
2. 如果问题需要特定资料支持，可以建议用户上传相关文档或粘贴网页链接。
3. 用户如果在对话中粘贴了网址，你可以提示他们去左侧"浏览网页链接"功能添加来源。
4. 用简体中文，简洁清晰，必要时分点列出。"""


def _build_user_prompt(query: str, chunks: list[dict]) -> str:
    if not chunks:
        return query
    parts = ["参考资料："]
    for i, c in enumerate(chunks, 1):
        fname = c.get("file_name", "?")
        parts.append(f"[{i}] 来源：《{fname}》\n{c['chunk_text']}")
    parts.append(f"\n用户问题：{query}")
    return "\n\n".join(parts)


async def _classify_intent(query: str, has_candidates: bool) -> dict:
    """
    判断用户意图：search（联网找资料）/ import（导入上次候选）/ normal（普通问答）。
    返回 {"intent", "topic", "selection"}。
    """
    options = (
        '- "search"：用户想联网搜索资料、找来源、找资源（如"帮我搜河北中考生物真题"、'
        '"找一些光合作用的资料加进来"、"上网查一下…"）\n'
        '- "normal"：普通问答，基于已有资料回答\n'
    )
    if has_candidates:
        options += (
            '- "import"：用户想把上一次搜到的候选导入来源'
            '（如"导入第1、3个"、"全部导入"、"都加进来"、"第2个不要"）\n'
        )
    prompt = (
        f"判断下面这句用户消息的意图。\n用户消息：「{query}」\n\n"
        f"可选意图：\n{options}\n"
        "规则：\n"
        "- 如果是 search，提取用户想搜索的主题 topic（简洁的搜索主题）。\n"
        + ("- 如果是 import，提取 selection：字符串 \"all\" 表示全部，"
           "或编号数组如 [1,3,5]（用户提到的序号）。\n" if has_candidates else "")
        + '返回 JSON：{"intent":"search|import|normal","topic":"","selection":"all"}'
    )
    try:
        data = await llm.chat_json(
            prompt, system="你是意图识别助手，仅返回 JSON。", temperature=0.1,
        )
        intent = data.get("intent", "normal")
        if intent not in ("search", "import", "normal"):
            intent = "normal"
        if intent == "import" and not has_candidates:
            intent = "normal"
        return {
            "intent": intent,
            "topic": str(data.get("topic", "")).strip(),
            "selection": data.get("selection", "all"),
        }
    except Exception:
        log.warning("意图识别失败，按普通问答处理", exc_info=True)
        return {"intent": "normal", "topic": "", "selection": "all"}


async def _handle_search(query: str, topic: str) -> AsyncIterator[dict]:
    """
    对话内深度来源发现（Agent 自动规划知识结构）：
    规划知识链 → 分维度搜索 → 语义筛选 → 抓取 → 按结构列出供用户选择。
    """
    from core.research import plan_and_discover

    search_topic = topic or query
    yield {"type": "delta",
           "text": (f"🧠 正在为「{search_topic}」规划知识结构并联网搜集资料，"
                    "这一步会分多个维度（考纲/真题/考点/教材等）深度搜索，"
                    "需要 30 秒左右，请稍候…\n\n")}
    try:
        candidates = await plan_and_discover(search_topic)
    except Exception:
        log.warning("对话内深度搜索失败", exc_info=True)
        msg = "抱歉，搜集资料时出错了，请稍后再试。"
        yield {"type": "delta", "text": msg}
        yield {"type": "agent_done", "full_text": f"🔍 搜索「{search_topic}」\n\n{msg}"}
        return

    if not candidates:
        msg = ("没有搜集到合适的网络来源。中文教育类资料很多锁在公众号/题库里，"
               "通用搜索难以抓取。你可以把已有的资料链接用左侧「批量导入网页链接」加进来。")
        yield {"type": "delta", "text": msg}
        yield {"type": "agent_done", "full_text": f"🔍 搜索「{search_topic}」\n\n{msg}"}
        return

    # 按知识结构分组展示，全局编号供导入
    from collections import OrderedDict
    groups: "OrderedDict[str, list]" = OrderedDict()
    for i, c in enumerate(candidates, 1):
        c["_num"] = i
        groups.setdefault(c.get("category", "其他"), []).append(c)

    n_cat = len(groups)
    lines = [f"📚 我为「{search_topic}」规划了 **{n_cat}** 个资料维度，"
             f"共搜集到 **{len(candidates)}** 个可用来源：\n"]
    for cat, items in groups.items():
        lines.append(f"### {cat}")
        for c in items:
            lines.append(f"**{c['_num']}. {c['title']}**")
            if c.get("reason"):
                lines.append(f"   💡 {c['reason']}")
            lines.append(f"   🔗 {c['url']}")
        lines.append("")
    lines.append('回复「**全部导入**」一次性收录，或「**导入第 1、3、5 个**」选择性收录。')
    listing = "\n".join(lines)

    yield {"type": "delta", "text": listing}
    yield {"type": "search_results", "data": candidates}
    yield {"type": "agent_done", "full_text": f"🔍 搜索「{search_topic}」\n\n{listing}"}


def _parse_selection(selection, n: int) -> list[int]:
    """把 selection 解析为 0-based 索引列表。"""
    if isinstance(selection, str) and selection.strip().lower() == "all":
        return list(range(n))
    if isinstance(selection, list):
        out = []
        for x in selection:
            try:
                idx = int(x) - 1  # 用户用 1-based
            except (ValueError, TypeError):
                continue
            if 0 <= idx < n:
                out.append(idx)
        return out
    # 兜底：全部
    return list(range(n))


async def _handle_import(vault_uuid: str, selection,
                         candidates: list[dict]) -> AsyncIterator[dict]:
    """把用户选中的候选导入来源。"""
    from core.research import ingest_selected

    indices = _parse_selection(selection, len(candidates))
    if not indices:
        msg = "没识别出你要导入哪几个，请说「全部导入」或「导入第 1、3 个」。"
        yield {"type": "delta", "text": msg}
        yield {"type": "agent_done", "full_text": msg}
        return

    chosen = [candidates[i] for i in indices]
    yield {"type": "delta", "text": f"📥 正在导入 {len(chosen)} 个来源…\n\n"}
    try:
        added = await ingest_selected(vault_uuid, chosen)
    except Exception:
        log.warning("对话内导入失败", exc_info=True)
        msg = "导入过程出错了，请稍后再试。"
        yield {"type": "delta", "text": msg}
        yield {"type": "agent_done", "full_text": msg}
        return

    if added:
        lines = [f"✅ 已成功导入 **{len(added)}** 个来源：\n"]
        for a in added:
            lines.append(f"- 《{a['title']}》（{a.get('chunks', 0)} 片段）")
        msg = "\n".join(lines)
        yield {"type": "delta", "text": msg}
        yield {"type": "sources_added"}
        yield {"type": "agent_done", "full_text": msg}
    else:
        msg = "导入失败，可能这些网页无法抓取，换几个来源试试。"
        yield {"type": "delta", "text": msg}
        yield {"type": "agent_done", "full_text": msg}


async def answer(query: str, vault_uuid: str, user_id: str,
                 history: Optional[list] = None,
                 source_hashes: Optional[list[str]] = None,
                 pending_candidates: Optional[list[dict]] = None
                 ) -> AsyncIterator[dict]:
    # 0. 意图识别：是否要联网搜索 / 导入候选
    intent = await _classify_intent(query, bool(pending_candidates))

    if intent["intent"] == "search":
        full = ""
        async for ev in _handle_search(query, intent["topic"]):
            if ev["type"] == "agent_done":
                full = ev["full_text"]
            else:
                yield ev
        db_manager.save_chat_pair(vault_uuid, user_id, query, full, [])
        yield {"type": "done", "full_text": full}
        return

    if intent["intent"] == "import":
        full = ""
        async for ev in _handle_import(vault_uuid, intent["selection"],
                                       pending_candidates or []):
            if ev["type"] == "agent_done":
                full = ev["full_text"]
            else:
                yield ev
        db_manager.save_chat_pair(vault_uuid, user_id, query, full, [])
        yield {"type": "done", "full_text": full}
        return

    # 1. 检索
    chunks = await retrieve(query, vault_uuid, source_hashes=source_hashes)
    citations = [{
        "index": i + 1,
        "doc_hash": c["doc_hash"],
        "chunk_index": c["chunk_index"],
        "file_name": c.get("file_name", "?"),
        "preview": c["chunk_text"][:200],
        "full_text": c["chunk_text"],  # 完整原文供展开查看
    } for i, c in enumerate(chunks)]
    yield {"type": "citations", "data": citations}

    # 2. 流式调 LLM
    user_prompt = _build_user_prompt(query, chunks)
    system = _SYSTEM_PROMPT_SOURCES if chunks else _SYSTEM_PROMPT_GENERAL
    full_text = ""
    async for delta in llm.chat_stream(
        user_prompt, system=system, history=history, temperature=0.5,
    ):
        full_text += delta
        yield {"type": "delta", "text": delta}

    # 3. 持久化对话（原子保存，避免半条记录）
    db_manager.save_chat_pair(vault_uuid, user_id, query, full_text, citations)
    yield {"type": "done", "full_text": full_text}

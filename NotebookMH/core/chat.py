"""core/chat.py — 对话编排"""
from typing import AsyncIterator, Optional

from core.db import db_manager
from core.llm import llm
from core.rag import retrieve

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


async def answer(query: str, vault_uuid: str, user_id: str,
                 history: Optional[list] = None,
                 source_hashes: Optional[list[str]] = None
                 ) -> AsyncIterator[dict]:
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

"""core/studio.py — Studio 内容生成"""
import functools
import json
import logging
from typing import Optional

from core.db import db_manager
from core.llm import llm

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=16)
def _gather_context(vault_uuid: str, max_chars: int = 8000) -> str:
    """收集 vault 内所有文档的代表性文本作为上下文（带缓存）。"""
    docs = db_manager.list_documents(vault_uuid)
    if not docs:
        return ""
    # 限制每个文档取 3 个最具代表性的片段（前几个 chunks）
    chunks_per_doc = max(1, 8000 // max(1, len(docs)) // 300)
    parts: list[str] = []
    for d in docs[:20]:
        chunks = db_manager.get_chunks(vault_uuid, d.content_hash)
        text_parts = [c.chunk_text for c in chunks[:chunks_per_doc]]
        parts.append(f"《{d.file_name}》\n" + "\n".join(text_parts))
    text = "\n\n---\n\n".join(parts)
    return text[:max_chars]


def clear_context_cache():
    """文档增删后调用，清空 _gather_context 缓存。"""
    _gather_context.cache_clear()


async def _gen_text(vault_uuid: str, system: str, task: str,
                    temperature: float = 0.5) -> str:
    ctx = _gather_context(vault_uuid)
    if not ctx:
        return "（当前笔记库没有来源，请先上传资料）"
    prompt = f"{task}\n\n以下是来源资料：\n\n{ctx}"
    return await llm.chat(prompt, system=system, temperature=temperature)


async def _gen_json(vault_uuid: str, system: str, task: str) -> dict:
    ctx = _gather_context(vault_uuid)
    if not ctx:
        return {}
    prompt = f"{task}\n\n以下是来源资料：\n\n{ctx}\n\n请严格返回 JSON。"
    return await llm.chat_json(prompt, system=system, temperature=0.3)


async def generate_summary(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是文档总结助手，仅基于资料作答，用中文。",
        task="请用 300 字左右总结这份资料的核心内容，分 3-5 个要点。",
    )


async def generate_faq(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是 FAQ 生成助手，仅基于资料作答。",
        task="基于资料生成 6-8 个常见问题及答案，格式：\n**Q1: 问题**\nA: 答案\n\n**Q2: ...**\n",
    )


async def generate_study_guide(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是学习指导助手。",
        task=(
            "基于资料生成一份学习指南，包含：\n"
            "1. 核心概念清单（5-8 个，每个一句话解释）\n"
            "2. 学习路径建议（先学什么再学什么）\n"
            "3. 重点难点提示\n"
            "4. 自测问题 3-5 个"
        ),
    )


async def generate_briefing(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是简报撰写助手。",
        task="把这份资料浓缩成 200 字简报，适合三分钟阅读。包含：背景、要点、结论。",
    )


async def generate_timeline(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是时间线整理助手。",
        task=(
            "如果资料含时间信息，提取关键事件并按时间排序，输出 markdown 列表：\n"
            "- **时间**: 事件描述\n\n"
            "如果资料不含明显时间，提取关键步骤/阶段按逻辑顺序排序。"
        ),
    )


async def generate_mindmap(vault_uuid: str) -> str:
    """返回 Mermaid mindmap 源码字符串。"""
    raw = await _gen_text(
        vault_uuid,
        system=(
            "你是思维导图生成器，仅返回 Mermaid mindmap 源码，"
            "不要任何额外解释、不要 markdown 代码块标记。"
        ),
        task=(
            "把资料的核心结构转成 Mermaid mindmap。格式：\n"
            "mindmap\n  root((中心主题))\n    分支1\n      子节点\n    分支2\n"
            "层级不超过 3，节点数 12-20 个。"
        ),
        temperature=0.3,
    )
    # 清理代码块标记
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    if not text.lstrip().startswith("mindmap"):
        text = "mindmap\n  root((笔记内容))\n    " + text.replace("\n", "\n    ")
    return text


async def generate_flashcards(vault_uuid: str, count: int = 10) -> list[dict]:
    data = await _gen_json(
        vault_uuid,
        system="你是闪卡生成器，仅返回 JSON。",
        task=(
            f"基于资料生成 {count} 张学习闪卡。"
            "返回 JSON：{\"cards\": [{\"question\": \"...\", \"answer\": \"...\"}, ...]}"
        ),
    )
    cards = data.get("cards") or []
    return [c for c in cards if isinstance(c, dict)
            and c.get("question") and c.get("answer")][:count]


async def generate_quiz(vault_uuid: str, count: int = 5) -> list[dict]:
    data = await _gen_json(
        vault_uuid,
        system="你是测验题生成器，仅返回 JSON。",
        task=(
            f"基于资料生成 {count} 道单选题。每题 4 个选项，标注正确答案字母（A/B/C/D），"
            "并给出简要解析。返回 JSON：{\"items\": ["
            "{\"question\":\"...\", \"options\":[\"A. ...\",\"B. ...\",\"C. ...\",\"D. ...\"],"
            "\"correct\":\"A\", \"explanation\":\"...\"}]}"
        ),
    )
    items = data.get("items") or []
    valid: list[dict] = []
    for it in items[:count]:
        if (isinstance(it, dict) and it.get("question")
                and isinstance(it.get("options"), list) and len(it["options"]) >= 2
                and it.get("correct")):
            valid.append(it)
    return valid


async def generate_presentation(vault_uuid: str, slide_count: int = 8) -> dict:
    data = await _gen_json(
        vault_uuid,
        system="你是演示文稿生成器，仅返回 JSON。",
        task=(
            f"基于资料生成一份 {slide_count} 页的演示文稿大纲。"
            "返回 JSON：{\"slides\": ["
            "{\"title\":\"第1页标题\", \"bullets\":[\"要点1\",\"要点2\"], \"speaker_notes\":\"备注...\"},"
            "...]}"
            "每页不超过 5 个要点。"
        ),
    )
    slides = data.get("slides") or []
    valid: list[dict] = []
    for s in slides[:slide_count]:
        if isinstance(s, dict) and s.get("title") and isinstance(s.get("bullets"), list):
            valid.append(s)
    return {"slides": valid}

"""core/ingest.py — 解析+切片+入库"""
import asyncio
import hashlib
import logging
import re

from config import CHUNK_SIZE, CHUNK_OVERLAP, MIN_CONTENT_LENGTH
from core.db import db_manager
from core.parsers import parse_file, parse_url
from core.vector_store import vector_store

log = logging.getLogger(__name__)


def _hash_content(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _split_into_chunks(text: str) -> list[dict]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []
    chunks: list[str] = []
    buf = ""
    # 按段落自然边界切分，尽量保持语义完整
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for para in paragraphs:
        # 段落本身超长才硬切
        if len(para) > CHUNK_SIZE * 2:
            step = CHUNK_SIZE - CHUNK_OVERLAP
            for i in range(0, len(para), step):
                chunks.append(para[i:i + CHUNK_SIZE])
            if buf:
                chunks.append(buf)
                buf = ""
            continue
        # 段落可放入当前 buffer
        if len(buf) + len(para) + 2 <= CHUNK_SIZE:
            buf = (buf + "\n\n" + para) if buf else para
        else:
            if buf:
                chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return [
        {"chunk_index": i, "chunk_text": c, "source_page": 0,
         "header_hierarchy": "", "chunk_size": len(c)}
        for i, c in enumerate(chunks)
    ]


async def _generate_doc_meta(vault_uuid: str, content_hash: str, text: str) -> None:
    """为文档生成摘要和推荐问题（失败静默，不阻塞上传）。"""
    from core.llm import llm
    sample = text[:1500].strip()
    if len(sample) < 100:
        return
    prompt = (
        "请基于以下资料，生成一段 80 字以内的中文摘要，并列出 3 个推荐问题。\n"
        '返回 JSON：{"summary":"...","suggested_questions":["...","...","..."]}\n\n'
        f"资料：\n{sample}"
    )
    try:
        data = await llm.chat_json(
            prompt, system="你是文档分析助手，仅返回 JSON。", temperature=0.3
        )
        summary = str(data.get("summary", ""))[:200]
        questions = [str(q)[:100] for q in data.get("suggested_questions", [])[:3] if q]
        if summary or questions:
            db_manager.update_document_summary(
                vault_uuid, content_hash,
                summary=summary, suggested_questions=questions,
            )
    except Exception:
        log.debug("摘要生成失败 %s", content_hash[:8], exc_info=True)


async def ingest_file(vault_uuid: str, file_name: str, data: bytes) -> dict:
    content_hash = _hash_content(data)
    if db_manager.document_exists(vault_uuid, content_hash):
        return {"status": "duplicate", "doc_hash": content_hash,
                "chunks": 0, "msg": "文件已存在"}
    try:
        parsed = parse_file(file_name, data)
    except Exception as exc:
        return {"status": "error", "doc_hash": "", "chunks": 0,
                "msg": f"解析失败: {exc}"}
    if parsed.get("error"):
        return {"status": "error", "doc_hash": "", "chunks": 0,
                "msg": f"无法提取文本: {parsed['error']}"}
    stripped = parsed["text"].strip()
    if len(stripped) < MIN_CONTENT_LENGTH:
        return {"status": "error", "doc_hash": "", "chunks": 0,
                "msg": f"内容过短（{len(stripped)} 字），未入库"}
    chunks = _split_into_chunks(stripped)
    if not chunks:
        return {"status": "error", "doc_hash": "", "chunks": 0,
                "msg": "文件无可提取文本"}
    db_manager.register_document(
        vault_uuid=vault_uuid, file_name=file_name,
        content_hash=content_hash, doc_size=len(data),
        page_count=parsed["page_count"], source_type="file",
        source_url="", full_text=parsed["text"][:50000],
    )
    db_manager.register_chunks(vault_uuid, content_hash, chunks)
    vector_store.add(vault_uuid, content_hash, chunks)
    # 入库后清空 Studio 上下文缓存
    from core import studio
    studio.clear_context_cache()
    # 异步生成摘要已禁用，避免抢 DeepSeek 带宽
    # asyncio.create_task(_generate_doc_meta(vault_uuid, content_hash, stripped))
    return {"status": "ok", "doc_hash": content_hash,
            "chunks": len(chunks), "msg": f"成功摄入 {len(chunks)} 片段"}


async def ingest_text(vault_uuid: str, title: str, text: str,
                      source_type: str = "paste", source_url: str = "") -> dict:
    data = text.encode("utf-8")
    content_hash = _hash_content(data)
    if db_manager.document_exists(vault_uuid, content_hash):
        return {"status": "duplicate", "doc_hash": content_hash,
                "chunks": 0, "msg": "内容已存在"}
    stripped = text.strip()
    if len(stripped) < MIN_CONTENT_LENGTH:
        return {"status": "error", "doc_hash": "", "chunks": 0,
                "msg": f"内容过短（{len(stripped)} 字），未入库"}
    chunks = _split_into_chunks(stripped)
    if not chunks:
        return {"status": "error", "doc_hash": "", "chunks": 0, "msg": "文本为空"}
    db_manager.register_document(
        vault_uuid=vault_uuid, file_name=title, content_hash=content_hash,
        doc_size=len(data), page_count=0,
        source_type=source_type, source_url=source_url,
        full_text=text[:50000],
    )
    db_manager.register_chunks(vault_uuid, content_hash, chunks)
    vector_store.add(vault_uuid, content_hash, chunks)
    # 入库后清空 Studio 上下文缓存
    from core import studio
    studio.clear_context_cache()
    # 异步生成摘要已禁用，避免抢 DeepSeek 带宽
    # asyncio.create_task(_generate_doc_meta(vault_uuid, content_hash, stripped))
    return {"status": "ok", "doc_hash": content_hash,
            "chunks": len(chunks), "msg": f"成功摄入 {len(chunks)} 片段"}


async def ingest_url(vault_uuid: str, url: str) -> dict:
    parsed = parse_url(url)
    if not parsed["text"].strip():
        msg = parsed.get("error") or "URL 无可提取文本"
        return {"status": "error", "doc_hash": "", "chunks": 0, "msg": msg}
    return await ingest_text(vault_uuid, url, parsed["text"],
                             source_type="url", source_url=url)

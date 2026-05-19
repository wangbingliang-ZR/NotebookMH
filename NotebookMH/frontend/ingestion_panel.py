"""
frontend/ingestion_panel.py - 异步遥测终端交互

职责：
  - Streamlit sidebar 文件上传器
  - 全息遥测控制台 (st.empty + Markdown 流式渲染)
  - 调用 core.rag_pipeline.IngestionPipeline 并流式展示进度

严禁在 app.py 中写入具体 UI 逻辑，全部集中于此模块。
"""

import asyncio
import logging
from typing import Any, Optional

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from core.rag_pipeline import get_pipeline
from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)

_PIPELINE = get_pipeline()

# 极客指令词库 —— 给用户“系统在高速轰鸣”的压迫感
_GEEK_LINES = {
    "HASHING": "[⚙️  扫描物理指纹] 正在计算 SHA-256 记忆哈希...",
    "HASH_OK": "[✅ 哈希校验通过] 未发现缓存命中，启动全量解析。",
    "CACHED": "[⚡ 秒传命中] 该文件已在当前 Vault 中锚定，跳过全量管线。",
    "PARSING": "[📄 语义解剖] 提取文档层级元数据 (H1/H2/粗体)...",
    "PARSE_OK": "[📊 解析完成] 文档结构扫描完毕。",
    "CHUNKING": "[🔪 逻辑切块] 按语义边界进行段落级微外科切割...",
    "CHUNK_OK": "[🧩 切块完毕] 语义闭环 Chunk 已生成。",
    "EMPTY_TEXT": "[⚠️ 空文本] 未从文件中解析到可检索文字。若是扫描版 PDF，请先 OCR 或换可复制文本的 PDF/TXT。",
    "EMBEDDING": "[🧠 高维映射] 正在将语义 Chunk 投射到 384 维向量空间...",
    "EMBED_OK": "[🎯 向量锚定] 全部 Chunk 已完成神经嵌入。",
    "INDEXING": "[💾 记忆固化] 写入 BM25 稀疏索引与向量矩阵...",
    "INDEX_OK": "[💿 索引就绪] 记忆网络已完成冷启动。",
    "ONTOLOGY": "[🕸️ 拓扑抽取] 构建概念依赖图谱...",
    "ONTOLOGY_OK": "[🕸️ 图谱就绪] DAG 已固化至认知容器。",
    "ONTOLOGY_SKIP": "[⚠️ 拓扑跳过] 本体抽取失败（非关键）。",
    "DONE": "[🌐 锚定完毕] 知识已注入 NotebookMH 认知容器。",
}


def _render_geek_line(event: dict) -> str:
    """将原始事件字典转换为极客指令文本。"""
    status = event.get("status", "UNKNOWN")
    elapsed = event.get("elapsed_ms", 0)
    base = _GEEK_LINES.get(status, f"[?] {status}")

    extras = []
    if "chunks" in event:
        extras.append(f"chunks={event['chunks']}")
    if "pages" in event:
        extras.append(f"pages={event['pages']}")
    if "chars" in event:
        extras.append(f"chars={event['chars']}")
    if "vectors" in event:
        extras.append(f"vectors={event['vectors']}")
    if "hash" in event:
        extras.append(f"hash={event['hash']}")
    if "file_name" in event:
        extras.append(f"file={event['file_name']}")

    suffix = f" | {' | '.join(extras)}" if extras else ""
    return f"`[{elapsed:>5}ms]` {base}{suffix}"


# ---------------------------------------------------------------------------
# 公共渲染接口
# ---------------------------------------------------------------------------

def render() -> None:
    """
    在 Streamlit sidebar 渲染文件上传面板、全息遥测控制台与文档列表。
    """
    if st is None:
        return

    st.sidebar.markdown("---")
    st.sidebar.header("🚀 知识摄入管线")

    # ── 文件上传器 ────────────────────────────────────────
    uploaded = st.sidebar.file_uploader(
        "拖拽 PDF / Word / TXT 文件至此",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=False,
        key="nb_mh_uploader",
    )

    # ── 全息遥测控制台 ────────────────────────────────────
    console = st.sidebar.empty()
    console.markdown(
        "```\n[NotebookMH 遥测终端 v1.0]\n等待数据注入...\n```"
    )

    if uploaded is not None:
        # 读取文件
        file_bytes = uploaded.read()
        file_name = uploaded.name
        vault_uuid = binder.get_state("vault_uuid", "default_vault")

        # 按钮触发
        if st.sidebar.button("🧬 启动摄入管线", key="btn_ingest"):
            _run_ingestion(console, file_bytes, file_name, vault_uuid)

    # ── 已上传文档列表（始终显示）────────────────────────
    st.sidebar.markdown("---")
    st.sidebar.subheader("📄 已上传来源")
    _render_document_list()


def _render_document_list() -> None:
    """渲染当前 Vault 下的文档列表，支持删除。"""
    if st is None:
        return

    vault_uuid = binder.get_state("vault_uuid", "")
    if not vault_uuid:
        st.sidebar.caption("未选择笔记库")
        return

    docs = db_pool.list_documents(vault_uuid)
    if not docs:
        st.sidebar.caption("该笔记库暂无文档")
        return

    for doc in docs:
        col_name, col_del = st.sidebar.columns([4, 1])
        with col_name:
            size_kb = doc.doc_size / 1024 if doc.doc_size else 0
            st.caption(
                f"📎 **{doc.file_name}**  ({size_kb:.1f} KB · {doc.page_count or 0} 页)"
            )
        with col_del:
            del_key = f"btn_del_doc_{doc.content_hash}"
            if st.button("🗑️", key=del_key, help="删除此文档"):
                db_pool.delete_document(vault_uuid, doc.content_hash)
                st.sidebar.success(f"已删除 {doc.file_name}")
                st.rerun()


def _run_ingestion(
    console: Any,
    file_bytes: bytes,
    file_name: str,
    vault_uuid: str,
) -> None:
    """
    执行异步摄入，实时流式打印到控制台。
    由于 Streamlit 的线程模型限制，我们使用 st.empty 进行 DOM 覆写。
    """
    lines: list[str] = []
    lines.append("```")
    lines.append("[NotebookMH 遥测终端 v1.0]")
    lines.append(f">>> 目标文件: {file_name}")
    lines.append(f">>> 目标 Vault: {vault_uuid}")
    lines.append("-" * 40)
    console.markdown("\n".join(lines))

    async def _loop() -> None:
        async for event in _PIPELINE.ingest_document(
            file_bytes, file_name, vault_uuid
        ):
            geek = _render_geek_line(event)
            lines.append(geek)
            # 只保留最近 12 行，避免 DOM 膨胀
            trimmed = lines[:2] + lines[-12:] if len(lines) > 14 else lines
            trimmed.append("```")
            console.markdown("\n".join(trimmed))
            logger.debug("Ingestion event: %s", event)

    try:
        # Streamlit 的 asyncio 支持有限，使用 asyncio.run 执行
        asyncio.run(_loop())
    except Exception as e:
        logger.error("Ingestion failed: %s", e)
        lines.append(f"[💥 FATAL] 摄入管线崩溃: {e}")
        lines.append("```")
        console.markdown("\n".join(lines))

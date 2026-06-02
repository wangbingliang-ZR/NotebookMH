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
except ImportError: # pragma: no cover
  st = None # type: ignore[assignment]

from core.rag_pipeline import get_pipeline
from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)

_PIPELINE = get_pipeline()

# 极客指令词库 —— 给用户“系统在高速轰鸣”的压迫感
_GEEK_LINES = {
  "HASHING": "[ 扫描物理指纹] 正在计算 SHA-256 记忆哈希...",
  "HASH_OK": "[ 哈希校验通过] 未发现缓存命中，启动全量解析。",
  "CACHED": "[ 秒传命中] 该文件已在当前 Vault 中锚定，跳过全量管线。",
  "PARSING": "[ 语义解剖] 提取文档层级元数据 (H1/H2/粗体)...",
  "PARSE_OK": "[ 解析完成] 文档结构扫描完毕。",
  "CHUNKING": "[ 逻辑切块] 按语义边界进行段落级微外科切割...",
  "CHUNK_OK": "[ 切块完毕] 语义闭环 Chunk 已生成。",
  "EMPTY_TEXT": "[ 空文本] 未从文件中解析到可检索文字。若是扫描版 PDF，请先 OCR 或换可复制文本的 PDF/TXT。",
  "EMBEDDING": "[ 高维映射] 正在将语义 Chunk 投射到 384 维向量空间...",
  "EMBED_OK": "[ 向量锚定] 全部 Chunk 已完成神经嵌入。",
  "INDEXING": "[ 记忆固化] 写入 BM25 稀疏索引与向量矩阵...",
  "INDEX_OK": "[ 索引就绪] 记忆网络已完成冷启动。",
  "ONTOLOGY": "[ 拓扑抽取] 构建概念依赖图谱...",
  "ONTOLOGY_OK": "[ 图谱就绪] DAG 已固化至认知容器。",
  "ONTOLOGY_SKIP": "[ 拓扑跳过] 本体抽取失败（非关键）。",
  "DONE": "[ 锚定完毕] 知识已注入 NotebookMH 认知容器。",
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

  vault_uuid = binder.get_state("vault_uuid", "default_vault")

  MAX_SOURCES = 50
  doc_count = db_pool.count_documents(vault_uuid) if vault_uuid else 0
  st.caption(f"来源: {doc_count} / {MAX_SOURCES}")

  # 来源选择过滤
  with st.expander("选择来源进行对话", expanded=False):
    all_docs = db_pool.list_documents(vault_uuid) if vault_uuid else []
    selected = st.session_state.get("selected_sources", [])
    for doc in all_docs:
        checked = doc.content_hash in selected
        if st.checkbox(doc.file_name, value=checked, key=f"sel_src_{doc.content_hash}"):
            if doc.content_hash not in selected:
                selected.append(doc.content_hash)
        else:
            if doc.content_hash in selected:
                selected.remove(doc.content_hash)
    if selected:
        st.session_state["selected_sources"] = selected
        st.caption(f"已选择 {len(selected)} 个来源")
    else:
        st.session_state.pop("selected_sources", None)
        st.caption("已选择全部来源")

  if doc_count >= MAX_SOURCES:
    st.warning(f"已达到 {MAX_SOURCES} 个来源上限，请删除旧来源后再添加。")
    _render_document_list()
    return

  # ── 文件上传器（支持多文件批量上传，最多50+来源）────────
  uploaded_files = st.file_uploader(
    "拖拽 PDF / Word / TXT / MD / CSV / JSON / PPTX 文件至此（支持多文件）",
    type=["pdf", "docx", "txt", "md", "csv", "json", "pptx"],
    accept_multiple_files=True,
    key="nb_mh_uploader",
  )

  # ── 摄入进度 ────────────────────────────────────────────
  console = st.empty()

  if uploaded_files:
    n = len(uploaded_files)
    st.caption(f"已选择 {n} 个文件")

    if st.button(f"上传并解析 ({n} 个文件)", key="btn_ingest"):
      for i, uploaded in enumerate(uploaded_files):
        file_bytes = uploaded.read()
        file_name = uploaded.name
        st.caption(f"[{i+1}/{n}] 正在处理: {file_name}")
        _run_ingestion(console, file_bytes, file_name, vault_uuid)

  # ── 网页 URL 来源 ─────────────────────────────────────
  st.divider()
  st.markdown("**添加网页链接**")
  url_input = st.text_input("粘贴网页 URL", key="nb_mh_url_input", placeholder="https://example.com/article")
  if url_input and st.button("添加网页来源", key="btn_ingest_url"):
    _run_url_ingestion(console, url_input, vault_uuid)

  # ── 粘贴文本来源 ─────────────────────────────────────
  st.divider()
  st.markdown("**粘贴文本**")
  pasted = st.text_area("粘贴内容作为来源", key="nb_mh_paste", height=120, placeholder="粘贴文章或笔记...")
  paste_name = st.text_input("来源标题", key="nb_mh_paste_title", placeholder="给文本取个名字")
  if pasted and paste_name and st.button("添加文本来源", key="btn_paste"):
    _run_ingestion(console, pasted.encode("utf-8"), f"{paste_name}.txt", vault_uuid)

  # ── 合并与导出 ─────────────────────────────────────
  c1, c2 = st.columns(2)
  with c1:
      if st.button("合并所有来源为虚拟文档", key="btn_merge_sources"):
          docs = db_pool.list_documents(vault_uuid)
          if not docs:
              st.warning("没有可合并的来源。")
          else:
              with st.spinner("正在合并来源..."):
                  from core.llm_engine import get_llm_engine
                  llm = get_llm_engine()
                  summaries = [d.summary or d.file_name for d in docs]
                  combined = "\n\n".join(f"来源 {i+1}: {s}" for i, s in enumerate(summaries))
                  try:
                      merged = asyncio.run(llm.ask_simple(
                          f"请基于以下多个来源的摘要，生成一份综合摘要（300字以内）：\n\n{combined}",
                          system_prompt="你是文档摘要助手。只返回综合摘要文字。",
                      ))
                      import hashlib
                      content_hash = hashlib.md5(merged.encode("utf-8")).hexdigest()
                      db_pool.register_document(vault_uuid, "合并摘要.docx", content_hash, len(merged), 1)
                      db_pool.update_document_summary(vault_uuid, content_hash, merged, "")
                      st.success("虚拟文档已创建")
                      st.rerun()
                  except Exception as e:
                      st.error(f"合并失败: {e}")
  with c2:
      docs = db_pool.list_documents(vault_uuid)
      if docs:
          try:
              from fpdf import FPDF
              pdf = FPDF()
              pdf.set_auto_page_break(auto=True, margin=15)
              for d in docs:
                  pdf.add_page()
                  pdf.set_font("Arial", "B", 14)
                  safe_title = d.file_name.encode("latin-1", "replace").decode("latin-1")
                  pdf.cell(0, 10, safe_title, ln=True)
                  pdf.set_font("Arial", "", 12)
                  summary = (d.summary or "").encode("latin-1", "replace").decode("latin-1")
                  for para in summary.split("\n"):
                      pdf.multi_cell(0, 8, para)
              pdf_bytes = pdf.output(dest="S").encode("latin-1")
              st.download_button("导出合并 PDF", pdf_bytes, "merged_sources.pdf", "application/pdf")
          except Exception:
              pass
      else:
          st.button("导出合并 PDF", disabled=True)

  # ── 已上传文档列表 ────────────────────────────────────
  _render_document_list()


def _render_document_list() -> None:
  """渲染当前 Vault 下的文档列表，支持删除。"""
  if st is None:
    return

  vault_uuid = binder.get_state("vault_uuid", "")
  if not vault_uuid:
    st.caption("未选择笔记库")
    return

  docs = db_pool.list_documents(vault_uuid)
  if not docs:
    st.caption("暂无来源文件")
    return

  search = st.text_input("在来源中搜索", key="doc_search", placeholder="输入关键词...")
  term = search.lower() if search else ""
  if term:
      docs = [
          d for d in docs
          if term in d.file_name.lower()
          or (d.summary and term in d.summary.lower())
          or (d.key_topics and term in d.key_topics.lower())
      ]

  def _hl(text: str, t: str) -> str:
      if not t or not text:
          return text
      import re
      return re.sub(re.escape(t), lambda m: f'<mark style="background:#ffeb3b;">{m.group(0)}</mark>', text, flags=re.IGNORECASE)

  for doc in docs:
    size_kb = doc.doc_size / 1024 if doc.doc_size else 0
    label = f"{doc.file_name} ({size_kb:.1f}KB)"
    with st.expander(label, expanded=False):
      if hasattr(doc, "summary") and doc.summary:
        st.markdown(f"**摘要**: {_hl(doc.summary, term)}", unsafe_allow_html=True)
      if hasattr(doc, "key_topics") and doc.key_topics:
        st.markdown(f"**关键主题**: {_hl(doc.key_topics, term)}", unsafe_allow_html=True)

      c1, c2 = st.columns(2)
      with c1:
        if st.button("查看详情", key=f"btn_view_{doc.content_hash}"):
            st.session_state["selected_source_hash"] = doc.content_hash
            st.rerun()
      with c2:
        if st.button("重新生成摘要", key=f"btn_regen_summary_{doc.content_hash}"):
          with st.spinner("正在重新生成摘要..."):
              from core.llm_engine import get_llm_engine
              llm = get_llm_engine()
              chunks = db_pool.get_chunks_by_doc(vault_uuid, doc.content_hash)
              text = "\n".join([c[1] for c in chunks])
              sample = text[:3000] if len(text) > 3000 else text
              try:
                  summary = asyncio.run(llm.ask_simple(
                      f"请用中文为以下文档写一段100字以内的摘要：\n\n{sample}",
                      system_prompt="你是文档摘要助手。只返回摘要文字。",
                  ))
                  db_pool.update_document_summary(vault_uuid, doc.content_hash, summary, doc.key_topics or "")
                  st.success("摘要已更新")
                  st.rerun()
              except Exception as e:
                  st.error(f"生成失败: {e}")
      del_key = f"confirm_del_{doc.content_hash}"
      if st.session_state.get(del_key, False):
          st.warning(f"确认删除 {doc.file_name}？此操作不可撤销。")
          c1, c2 = st.columns(2)
          with c1:
              if st.button("确认", key=f"yes_del_{doc.content_hash}"):
                  db_pool.delete_document(vault_uuid, doc.content_hash)
                  st.session_state[del_key] = False
                  st.success(f"已删除 {doc.file_name}")
                  st.rerun()
          with c2:
              if st.button("取消", key=f"no_del_{doc.content_hash}"):
                  st.session_state[del_key] = False
                  st.rerun()
      else:
          if st.button("删除此来源", key=f"btn_del_doc_{doc.content_hash}"):
              st.session_state[del_key] = True
              st.rerun()


def _run_url_ingestion(console: Any, url: str, vault_uuid: str) -> None:
    """抓取网页并作为来源摄入。"""
    try:
        with st.spinner("抓取网页..."):
            import httpx
            resp = httpx.get(url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text

            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)
                title = soup.title.string if soup.title else url
            except ImportError:
                import re
                text = re.sub(r'<script.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<style.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r'<[^>]+>', '', text)
                text = re.sub(r'\n\s*\n+', '\n', text).strip()
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
                title = title_match.group(1).strip() if title_match else url

            doc_text = text[:8000]
        _run_ingestion(console, doc_text.encode("utf-8"), f"{title}.txt", vault_uuid)
        st.success(f"网页来源已添加: {title}")
    except Exception as e:
        st.error(f"网页抓取失败: {e}")


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
    lines.append(f"[ FATAL] 摄入管线崩溃: {e}")
    lines.append("```")
    console.markdown("\n".join(lines))

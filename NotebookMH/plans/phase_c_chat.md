# Phase C — 对话链路（Step 18-24）

> **执行前必读**: `ARCHITECTURE.md` 第 6 节（接口签名）
> **本阶段目标**: LLM + RAG + 流式对话 + 引用 + 多轮 + 筛选
> **Checkpoint**: Step 20 完成后做

---

## Step 18：实现 core/llm.py（DeepSeek 客户端）

**目标**: 3 方法 `chat` / `chat_stream` / `chat_json`，无 Key 时 Mock。

**操作**: `core/llm.py` 完全替换:

```python
"""core/llm.py — DeepSeek LLM 客户端"""
import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import httpx

from config import DEEPSEEK_API_KEY, AI_BASE_URL, AI_MODEL, USE_MOCK_LLM

log = logging.getLogger(__name__)
_TIMEOUT = 90.0


class LLMClient:
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

    def _build_messages(self, prompt: str, system: str, history: list) -> list:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for h in (history or [])[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": h["content"]})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    async def chat(self, prompt: str, system: str = "",
                   history: Optional[list] = None,
                   temperature: float = 0.7) -> str:
        if USE_MOCK_LLM:
            return f"[Mock 模式] 收到问题：{prompt[:80]}\n\n请在 .env 配置 DEEPSEEK_API_KEY 启用真实回答。"
        messages = self._build_messages(prompt, system, history or [])
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{AI_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={"model": AI_MODEL, "messages": messages,
                      "temperature": temperature},
            )
            if r.status_code >= 400:
                log.error("LLM failed: %s %s", r.status_code, r.text[:500])
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def chat_stream(self, prompt: str, system: str = "",
                          history: Optional[list] = None,
                          temperature: float = 0.7) -> AsyncIterator[str]:
        if USE_MOCK_LLM:
            mock = f"[Mock 流式] 收到：{prompt[:50]}。配置 API Key 后启用真实回答。"
            for ch in mock:
                yield ch
                await asyncio.sleep(0.015)
            return
        messages = self._build_messages(prompt, system, history or [])
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            async with c.stream(
                "POST", f"{AI_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={"model": AI_MODEL, "messages": messages,
                      "temperature": temperature, "stream": True},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def chat_json(self, prompt: str, system: str = "",
                        temperature: float = 0.3) -> dict:
        if USE_MOCK_LLM:
            return {"mock": True, "preview": prompt[:80]}
        messages = self._build_messages(prompt, system, [])
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{AI_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={"model": AI_MODEL, "messages": messages,
                      "temperature": temperature,
                      "response_format": {"type": "json_object"}},
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                log.warning("LLM 返回非 JSON: %s", raw[:200])
                return {"raw": raw}


llm = LLMClient()
```

**验收**:
```powershell
python -c "import asyncio; from core.llm import llm; print(asyncio.run(llm.chat('一句话介绍中国')))"
```
- 有 Key: 真实回答
- 无 Key: `[Mock 模式] 收到问题：...`

---

## Step 19：实现 core/rag.py（混合检索）

**目标**: BM25 + dense + RRF 融合。

**操作**: `core/rag.py` 完全替换:

```python
"""core/rag.py — 混合检索 (BM25 + dense + RRF)"""
import logging
from typing import Optional

import jieba
from rank_bm25 import BM25Okapi

from config import RAG_TOP_K, BM25_WEIGHT, DENSE_WEIGHT
from core.db import db_manager
from core.vector_store import vector_store

log = logging.getLogger(__name__)


def _tokenize(text: str) -> list[str]:
    return [t for t in jieba.lcut(text) if t.strip()]


def _bm25_search(query: str, vault_uuid: str,
                 source_hashes: Optional[list[str]], top_k: int) -> list[dict]:
    candidates: list[dict] = []
    docs = db_manager.list_documents(vault_uuid)
    for d in docs:
        if source_hashes and d.content_hash not in source_hashes:
            continue
        chunks = db_manager.get_chunks(vault_uuid, d.content_hash)
        for c in chunks:
            candidates.append({
                "doc_hash": d.content_hash,
                "chunk_index": c.chunk_index,
                "chunk_text": c.chunk_text,
                "file_name": d.file_name,
            })
    if not candidates:
        return []
    corpus = [_tokenize(c["chunk_text"]) for c in candidates]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))
    ranked = sorted(zip(scores, candidates), key=lambda x: -x[0])[:top_k * 2]
    return [{**c, "score": float(s)} for s, c in ranked if s > 0]


def _enrich_dense_results(dense: list[dict], vault_uuid: str) -> list[dict]:
    """给 dense 结果补 file_name（vector_store 默认不带）"""
    if not dense:
        return []
    hash_to_name = {d.content_hash: d.file_name
                    for d in db_manager.list_documents(vault_uuid)}
    for item in dense:
        item["file_name"] = hash_to_name.get(item.get("doc_hash"), "?")
    return dense


def _rrf_merge(dense: list[dict], sparse: list[dict],
               k: int = 60, top_k: int = 5) -> list[dict]:
    scores: dict = {}
    for rank, item in enumerate(dense):
        key = f"{item['doc_hash']}_{item['chunk_index']}"
        scores.setdefault(key, {"item": item, "score": 0.0})
        scores[key]["score"] += DENSE_WEIGHT / (k + rank + 1)
    for rank, item in enumerate(sparse):
        key = f"{item['doc_hash']}_{item['chunk_index']}"
        scores.setdefault(key, {"item": item, "score": 0.0})
        scores[key]["score"] += BM25_WEIGHT / (k + rank + 1)
    merged = sorted(scores.values(), key=lambda x: -x["score"])[:top_k]
    return [{**m["item"], "rrf_score": m["score"]} for m in merged]


async def retrieve(query: str, vault_uuid: str, top_k: int = RAG_TOP_K,
                   source_hashes: Optional[list[str]] = None) -> list[dict]:
    if not query.strip() or not vault_uuid:
        return []
    try:
        dense = vector_store.query(vault_uuid, query, top_k=top_k * 2,
                                   source_hashes=source_hashes)
        dense = _enrich_dense_results(dense, vault_uuid)
    except Exception as e:
        log.warning("dense retrieval failed: %s", e)
        dense = []
    try:
        sparse = _bm25_search(query, vault_uuid, source_hashes, top_k)
    except Exception as e:
        log.warning("bm25 retrieval failed: %s", e)
        sparse = []
    return _rrf_merge(dense, sparse, top_k=top_k)
```

**验收**:
```powershell
python -c "
import asyncio
from core.db import db_manager
from core.ingest import ingest_text
from core.rag import retrieve
u = db_manager.create_vault('rag_t','t')
asyncio.run(ingest_text(u,'t','光合作用是植物利用阳光合成有机物。\n\n叶绿体是光合作用的场所。\n\n光反应在类囊体进行。'))
r = asyncio.run(retrieve('叶绿体在哪', u, top_k=3))
print('hit:', len(r))
for x in r: print(' -', x['chunk_text'][:40], 'rrf:', x.get('rrf_score'))
db_manager.delete_vault(u)
"
```

**预期**: hit >= 1，含"叶绿体"的片段在前。

---

## Step 20：实现 core/chat.py（对话编排）

**目标**: retrieve → 构造引用 prompt → LLM 流式 → yield 事件。

**操作**: `core/chat.py` 完全替换:

```python
"""core/chat.py — 对话编排"""
from typing import AsyncIterator, Optional

from core.db import db_manager
from core.llm import llm
from core.rag import retrieve

_SYSTEM_PROMPT = """你是 NotebookMH，一个基于用户上传资料回答问题的智能助手。

回答规则：
1. 仅基于"参考资料"作答，不引入外部知识。
2. 在引用资料处用 [1] [2] 等编号，与参考资料编号一致。
3. 若资料不足以回答，诚实说"根据当前资料无法回答"。
4. 用简体中文，简洁清晰，必要时分点列出。
5. 不要重复参考资料原文，要做总结和整合。"""


def _build_user_prompt(query: str, chunks: list[dict]) -> str:
    if not chunks:
        return f"用户问题：{query}\n\n（当前没有相关参考资料）"
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
    } for i, c in enumerate(chunks)]
    yield {"type": "citations", "data": citations}

    # 2. 流式调 LLM
    user_prompt = _build_user_prompt(query, chunks)
    full_text = ""
    async for delta in llm.chat_stream(
        user_prompt, system=_SYSTEM_PROMPT, history=history, temperature=0.5,
    ):
        full_text += delta
        yield {"type": "delta", "text": delta}

    # 3. 持久化对话
    db_manager.save_chat(vault_uuid, user_id, "user", query, [])
    db_manager.save_chat(vault_uuid, user_id, "assistant", full_text, citations)
    yield {"type": "done", "full_text": full_text}
```

**验收**:
```powershell
python -c "
import asyncio
from core.db import db_manager
from core.ingest import ingest_text
from core.chat import answer

u = db_manager.create_vault('chat_t','t')
asyncio.run(ingest_text(u,'t','猫是哺乳动物，喜欢吃鱼。\n\n狗喜欢吃肉。'))
async def run():
    types_seen = []
    async for ev in answer('猫吃什么', u, 'u1', [], None):
        types_seen.append(ev['type'])
    print('事件:', types_seen)
asyncio.run(run())
db_manager.delete_vault(u)
"
```

**预期**: `事件: ['citations', 'delta', 'delta', ..., 'done']`

---

## Step 20 完成 → CHECKPOINT 4

按规则重读 + 写 Checkpoint 4。

---

## Step 21：实现 ui/chat_panel.py（对话 UI）

**目标**: 中间栏: 历史 + 流式 + 引用 + 清空。

**操作**: `ui/chat_panel.py` 完全替换:

```python
"""ui/chat_panel.py — 对话面板"""
import asyncio
import traceback

import streamlit as st

from core.chat import answer
from core.db import db_manager


def _history_for_llm(vault_uuid: str, user_id: str) -> list[dict]:
    rows = db_manager.load_chat(vault_uuid, user_id)
    return [{"role": r.role, "content": r.content,
             "citations": r.citations or []} for r in rows]


def _render_message(msg: dict) -> None:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        cites = msg.get("citations") or []
        if cites and msg["role"] == "assistant":
            with st.expander(f"引用 {len(cites)} 条"):
                for c in cites:
                    st.markdown(f"**[{c['index']}]** 《{c.get('file_name','?')}》")
                    st.caption(c.get("preview", ""))


def render() -> None:
    vault_uuid = st.session_state.get("vault_uuid", "")
    user_id = st.session_state.get("user_id", "anonymous")

    if not vault_uuid:
        st.info("👈 请先在左侧选择或新建笔记库")
        return

    st.markdown("### 对话")

    history = _history_for_llm(vault_uuid, user_id)
    for msg in history:
        _render_message(msg)

    if history:
        if st.button("清空对话", key="btn_clear_chat"):
            db_manager.clear_chat(vault_uuid, user_id)
            st.rerun()

    query = st.chat_input("提出你的问题...")
    if not query:
        return

    with st.chat_message("user"):
        st.markdown(query)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        cite_box = st.empty()
        sources = st.session_state.get("selected_sources") or None
        text_buf = ""
        citations: list[dict] = []

        async def _run():
            nonlocal text_buf, citations
            async for ev in answer(query, vault_uuid, user_id,
                                   history=history, source_hashes=sources):
                if ev["type"] == "citations":
                    citations = ev["data"]
                elif ev["type"] == "delta":
                    text_buf += ev["text"]
                    placeholder.markdown(text_buf + "▌")
                elif ev["type"] == "done":
                    placeholder.markdown(text_buf)

        try:
            asyncio.run(_run())
            if citations:
                with cite_box.expander(f"引用 {len(citations)} 条"):
                    for c in citations:
                        st.markdown(f"**[{c['index']}]** 《{c.get('file_name','?')}》")
                        st.caption(c.get("preview", ""))
        except Exception:
            st.error("对话失败:")
            st.code(traceback.format_exc())

    st.rerun()
```

更新 `app.py`:
```python
"""app.py — NotebookMH 入口"""
import nest_asyncio
import streamlit as st

import config
from ui import sidebar, chat_panel

nest_asyncio.apply()

st.set_page_config(
    page_title="NotebookMH", page_icon="📓",
    layout="wide", initial_sidebar_state="expanded",
)
st.markdown(
    '<meta name="google" content="notranslate">'
    '<style>body, .stApp, [class*="st-"] { translate: no !important; }</style>',
    unsafe_allow_html=True,
)

sidebar.render()

left, right = st.columns([5, 3], gap="large")
with left:
    chat_panel.render()
with right:
    st.markdown("### Studio")
    st.caption("（Phase D 实现）")
```

**禁止**:
- ❌ 在对话面板加"模式切换"
- ❌ 把 LLM 调用放到 main thread 阻塞

**验收**（手动）:
1. 启动 streamlit
2. 已建库且已上传 ≥1 个文件
3. 输入框输入 "这份资料讲了什么"
4. 看到字符流式出现
5. 看到底部"引用 N 条"展开有片段
6. 刷新页面 → 历史保留
7. 点"清空对话" → 历史清空

---

## Step 22：来源筛选联动对话

**目标**: sidebar 取消勾选的源不出现在引用中。

**操作**: 已在 Step 21 通过 `st.session_state["selected_sources"]` 联动。**仅做验证**。

**验收**:
1. 库中有 ≥2 个不同主题的来源（如 A 是数学，B 是历史）
2. 仅勾选 A，问 A 主题相关问题 → 引用只来自 A
3. 仅勾选 B → 引用只来自 B
4. 都不勾 → `selected_sources = []` → chat 用 `None`（不过滤）→ 全部参与

**若行为不符**:
- 检查 sidebar.py 中 `st.session_state["selected_sources"] = selected` 是否在循环外
- 检查 chat_panel.py 中 `st.session_state.get("selected_sources") or None`（空列表也要转 None）

---

## Step 23：流式输出验证 + 多轮上下文验证

**目标**: 确认流式真生效（不是一次性返回）、多轮上下文真传递。

**操作**: 仅做联调验证，无代码改动。

**验收 1（流式）**:
1. 配置真实 API Key
2. 问一个长回答的问题（如"详细介绍光合作用的两个阶段"）
3. 观察：文字应逐字/逐词出现，**不是**一次性全显示
4. 在 LLM 响应未结束时，placeholder 末尾应有"▌"闪烁光标

**验收 2（多轮）**:
1. 第 1 轮: "什么是光合作用"
2. 第 2 轮: "它的两个阶段分别是什么"（注意用"它"而非"光合作用"）
3. AI 应理解"它"指代上文的"光合作用"

**若失败**:
- 流式失败 → 检查 `chat_stream` 是否真的 async for 逐 chunk yield
- 多轮失败 → 检查 `_history_for_llm` 是否传入 chat.answer，answer 是否传入 llm._build_messages

---

## Step 24：阶段 C 集成验收

**目标**: 端到端跑通对话全链路。

**操作**（人工）:
1. 用户 alice，vault 已有数据
2. 多轮对话 ≥ 3 轮
3. 切换来源筛选验证
4. 清空对话验证

**DB 验证**:
```powershell
python -c "
from core.db import db_manager
vs = db_manager.list_vaults('alice')
v = vs[0]
msgs = db_manager.load_chat(v.vault_uuid, 'alice')
print(f'对话历史 {len(msgs)} 条')
for m in msgs[-4:]:
    print(f' {m.role}: {m.content[:50]}...')
    if m.citations:
        print(f'   引用 {len(m.citations)} 条')
"
```

**预期**: 历史记录条数与界面一致，assistant 消息含 citations。

**记录 PROGRESS.md**:
```
[Step 24] ✅ 阶段 C 集成
- 12 项进度: F6=✅ F7=✅
```

---

## 阶段 C 完成

阅读 `plans/phase_d_studio.md`。

# Phase A — 地基（Step 4-9）

> **执行前必读**: `ARCHITECTURE.md` 第 5、6 节（DB schema 和接口签名）
> **本阶段目标**: SQLite ORM + ChromaDB 包装 + Sidebar 用户/Vault/上传基本款
> **Checkpoint**: Step 5 完成后做第一次 Checkpoint

---

## Step 4：实现 core/db.py（SQLAlchemy ORM + DBManager）

**目标**: 实现 ARCHITECTURE 第 5 节定义的 8 张表 + 第 6 节定义的 DBManager 接口。

**操作**: 把 `core/db.py` 内容**完全替换**为下面的实现。

```python
"""core/db.py — SQLAlchemy ORM + DBManager 单例"""
import json
import uuid as _uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, JSON, Boolean,
    create_engine, event, select, delete as sql_delete,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DB_PATH

Base = declarative_base()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── ORM 定义 ──────────────────────────────────────────

class Vault(Base):
    __tablename__ = "vault_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), unique=True, index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    vault_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class Document(Base):
    __tablename__ = "document_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), index=True, nullable=False)
    file_name = Column(String(512), nullable=False)
    content_hash = Column(String(64), index=True, nullable=False)
    doc_size = Column(Integer, default=0)
    page_count = Column(Integer, default=0)
    source_type = Column(String(32), default="file")  # file/url/paste
    source_url = Column(String(1024), default="")
    summary = Column(Text, default="")
    key_topics = Column(JSON, default=list)
    suggested_questions = Column(JSON, default=list)
    full_text = Column(Text, default="")
    created_at = Column(DateTime, default=_utcnow)


class Chunk(Base):
    __tablename__ = "chunk_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), index=True, nullable=False)
    doc_hash = Column(String(64), index=True, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    source_page = Column(Integer, default=0)
    header_hierarchy = Column(String(512), default="")
    chunk_size = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)


class ChatMsg(Base):
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    role = Column(String(16), nullable=False)  # user/assistant
    content = Column(Text, nullable=False)
    citations = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)


class Note(Base):
    __tablename__ = "note_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), index=True, nullable=False)
    user_id = Column(String(64), index=True, nullable=False)
    title = Column(String(512), nullable=False)
    content = Column(Text, default="")
    pinned = Column(Boolean, default=False)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=_utcnow)


class Flashcard(Base):
    __tablename__ = "flashcard_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), index=True, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    mastery = Column(Integer, default=0)  # 0=未掌握 1=部分 2=已掌握
    review_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)


class QuizItem(Base):
    __tablename__ = "quiz_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), index=True, nullable=False)
    question = Column(Text, nullable=False)
    options = Column(JSON, default=list)
    correct = Column(String(8), nullable=False)  # 'A'/'B'/...
    explanation = Column(Text, default="")
    user_answer = Column(String(8), default="")
    is_correct = Column(Integer, default=-1)  # -1 未答, 0 错, 1 对
    created_at = Column(DateTime, default=_utcnow)


class WrongAnswer(Base):
    __tablename__ = "wrong_answer_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), index=True, nullable=False)
    question = Column(Text, nullable=False)
    user_answer = Column(Text, default="")
    correct_answer = Column(Text, default="")
    explanation = Column(Text, default="")
    mastered = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)


# ── DBManager ──────────────────────────────────────────

class DBManager:
    def __init__(self):
        url = f"sqlite:///{DB_PATH}"
        self.engine = create_engine(url, future=True,
                                    connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _set_wal(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)

    @contextmanager
    def session(self):
        s = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ── Vault ──
    def list_vaults(self, user_id: str) -> list:
        with self.session() as s:
            rows = s.execute(
                select(Vault).where(Vault.user_id == user_id)
                .order_by(Vault.created_at.desc())
            ).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    def create_vault(self, user_id: str, name: str) -> str:
        uuid = _uuid.uuid4().hex
        with self.session() as s:
            s.add(Vault(vault_uuid=uuid, user_id=user_id, vault_name=name))
        return uuid

    def delete_vault(self, vault_uuid: str) -> None:
        with self.session() as s:
            for cls in (Vault, Document, Chunk, ChatMsg, Note, Flashcard,
                        QuizItem, WrongAnswer):
                s.execute(sql_delete(cls).where(cls.vault_uuid == vault_uuid))

    # ── Document ──
    def list_documents(self, vault_uuid: str) -> list:
        with self.session() as s:
            rows = s.execute(
                select(Document).where(Document.vault_uuid == vault_uuid)
                .order_by(Document.created_at.desc())
            ).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    def get_document(self, vault_uuid: str, content_hash: str) -> Optional[Document]:
        with self.session() as s:
            r = s.execute(
                select(Document).where(
                    Document.vault_uuid == vault_uuid,
                    Document.content_hash == content_hash,
                )
            ).scalar_one_or_none()
            if r:
                s.expunge(r)
            return r

    def document_exists(self, vault_uuid: str, content_hash: str) -> bool:
        return self.get_document(vault_uuid, content_hash) is not None

    def register_document(self, *, vault_uuid: str, file_name: str,
                          content_hash: str, doc_size: int = 0,
                          page_count: int = 0, source_type: str = "file",
                          source_url: str = "", full_text: str = "") -> int:
        with self.session() as s:
            d = Document(
                vault_uuid=vault_uuid, file_name=file_name,
                content_hash=content_hash, doc_size=doc_size,
                page_count=page_count, source_type=source_type,
                source_url=source_url, full_text=full_text,
            )
            s.add(d)
            s.flush()
            return d.id

    def update_document_summary(self, vault_uuid: str, content_hash: str,
                                summary: str = "", key_topics: list = None,
                                suggested_questions: list = None) -> None:
        with self.session() as s:
            d = s.execute(
                select(Document).where(
                    Document.vault_uuid == vault_uuid,
                    Document.content_hash == content_hash,
                )
            ).scalar_one_or_none()
            if not d:
                return
            if summary:
                d.summary = summary
            if key_topics is not None:
                d.key_topics = key_topics
            if suggested_questions is not None:
                d.suggested_questions = suggested_questions

    def delete_document(self, vault_uuid: str, content_hash: str) -> None:
        with self.session() as s:
            s.execute(sql_delete(Document).where(
                Document.vault_uuid == vault_uuid,
                Document.content_hash == content_hash))
            s.execute(sql_delete(Chunk).where(
                Chunk.vault_uuid == vault_uuid,
                Chunk.doc_hash == content_hash))

    # ── Chunk ──
    def register_chunks(self, vault_uuid: str, doc_hash: str,
                        chunks: list) -> None:
        with self.session() as s:
            for c in chunks:
                s.add(Chunk(
                    vault_uuid=vault_uuid, doc_hash=doc_hash,
                    chunk_index=c["chunk_index"],
                    chunk_text=c["chunk_text"],
                    source_page=c.get("source_page", 0),
                    header_hierarchy=c.get("header_hierarchy", ""),
                    chunk_size=c.get("chunk_size", len(c["chunk_text"])),
                ))

    def get_chunks(self, vault_uuid: str, doc_hash: str) -> list:
        with self.session() as s:
            rows = s.execute(
                select(Chunk).where(
                    Chunk.vault_uuid == vault_uuid,
                    Chunk.doc_hash == doc_hash,
                ).order_by(Chunk.chunk_index)
            ).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    # ── Chat ──
    def save_chat(self, vault_uuid: str, user_id: str, role: str,
                  content: str, citations: list = None) -> None:
        with self.session() as s:
            s.add(ChatMsg(
                vault_uuid=vault_uuid, user_id=user_id,
                role=role, content=content, citations=citations or [],
            ))

    def load_chat(self, vault_uuid: str, user_id: str, limit: int = 50) -> list:
        with self.session() as s:
            rows = s.execute(
                select(ChatMsg).where(
                    ChatMsg.vault_uuid == vault_uuid,
                    ChatMsg.user_id == user_id,
                ).order_by(ChatMsg.created_at).limit(limit)
            ).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    def clear_chat(self, vault_uuid: str, user_id: str) -> None:
        with self.session() as s:
            s.execute(sql_delete(ChatMsg).where(
                ChatMsg.vault_uuid == vault_uuid,
                ChatMsg.user_id == user_id))

    # ── Note ──
    def list_notes(self, vault_uuid: str, user_id: str) -> list:
        with self.session() as s:
            rows = s.execute(
                select(Note).where(
                    Note.vault_uuid == vault_uuid,
                    Note.user_id == user_id,
                ).order_by(Note.pinned.desc(), Note.created_at.desc())
            ).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    def save_note(self, vault_uuid: str, user_id: str, title: str,
                  content: str, tags: list = None) -> int:
        with self.session() as s:
            n = Note(vault_uuid=vault_uuid, user_id=user_id,
                     title=title, content=content, tags=tags or [])
            s.add(n)
            s.flush()
            return n.id

    def delete_note(self, note_id: int) -> None:
        with self.session() as s:
            s.execute(sql_delete(Note).where(Note.id == note_id))

    def toggle_pin_note(self, note_id: int) -> None:
        with self.session() as s:
            n = s.execute(select(Note).where(Note.id == note_id)).scalar_one_or_none()
            if n:
                n.pinned = not n.pinned

    # ── Flashcard ──
    def save_flashcards(self, vault_uuid: str, cards: list) -> None:
        with self.session() as s:
            for c in cards:
                s.add(Flashcard(vault_uuid=vault_uuid,
                                question=c["question"], answer=c["answer"]))

    def list_flashcards(self, vault_uuid: str) -> list:
        with self.session() as s:
            rows = s.execute(
                select(Flashcard).where(Flashcard.vault_uuid == vault_uuid)
                .order_by(Flashcard.created_at.desc())
            ).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    def update_flashcard_mastery(self, card_id: int, mastery: int) -> None:
        with self.session() as s:
            c = s.execute(select(Flashcard).where(Flashcard.id == card_id)).scalar_one_or_none()
            if c:
                c.mastery = mastery
                c.review_count = (c.review_count or 0) + 1

    def delete_flashcard(self, card_id: int) -> None:
        with self.session() as s:
            s.execute(sql_delete(Flashcard).where(Flashcard.id == card_id))

    # ── Quiz ──
    def save_quiz_items(self, vault_uuid: str, items: list) -> list:
        ids = []
        with self.session() as s:
            for it in items:
                q = QuizItem(vault_uuid=vault_uuid,
                             question=it["question"],
                             options=it.get("options", []),
                             correct=it["correct"],
                             explanation=it.get("explanation", ""))
                s.add(q)
                s.flush()
                ids.append(q.id)
        return ids

    def list_quiz_items(self, vault_uuid: str, only_unanswered: bool = False) -> list:
        with self.session() as s:
            stmt = select(QuizItem).where(QuizItem.vault_uuid == vault_uuid)
            if only_unanswered:
                stmt = stmt.where(QuizItem.is_correct == -1)
            rows = s.execute(stmt.order_by(QuizItem.created_at.desc())).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    def answer_quiz(self, quiz_id: int, user_answer: str) -> bool:
        with self.session() as s:
            q = s.execute(select(QuizItem).where(QuizItem.id == quiz_id)).scalar_one_or_none()
            if not q:
                return False
            q.user_answer = user_answer
            ok = user_answer.strip().upper() == q.correct.strip().upper()
            q.is_correct = 1 if ok else 0
            if not ok:
                s.add(WrongAnswer(
                    vault_uuid=q.vault_uuid, question=q.question,
                    user_answer=user_answer, correct_answer=q.correct,
                    explanation=q.explanation,
                ))
            return ok

    # ── WrongAnswer ──
    def list_wrong_answers(self, vault_uuid: str, only_unmastered: bool = True) -> list:
        with self.session() as s:
            stmt = select(WrongAnswer).where(WrongAnswer.vault_uuid == vault_uuid)
            if only_unmastered:
                stmt = stmt.where(WrongAnswer.mastered == False)  # noqa
            rows = s.execute(stmt.order_by(WrongAnswer.created_at.desc())).scalars().all()
            for r in rows:
                s.expunge(r)
            return rows

    def mark_wrong_mastered(self, wrong_id: int) -> None:
        with self.session() as s:
            w = s.execute(select(WrongAnswer).where(WrongAnswer.id == wrong_id)).scalar_one_or_none()
            if w:
                w.mastered = True


# 模块级单例
db_manager = DBManager()
```

**禁止**:
- ❌ 引入 `user_stats`、`concept_mastery`、`interaction_logs`、`concept_dependencies` 等已删除的表
- ❌ 在 db.py 中调用 LLM 或 ChromaDB
- ❌ 在方法返回前不做 expunge（会导致 DetachedInstanceError）

**验收命令**:
```powershell
python -c "from core.db import db_manager; u = db_manager.create_vault('testuser', '测试库'); print('创建:', u); vs = db_manager.list_vaults('testuser'); print('列表:', [v.vault_name for v in vs]); db_manager.delete_vault(u); print('删除后:', len(db_manager.list_vaults('testuser')))"
```

**预期**:
```
创建: <32位 hex>
列表: ['测试库']
删除后: 0
```

---

## Step 5：实现 ui/sidebar.py（用户 + Vault）

**目标**: 侧边栏第一段: 用户名输入 + Vault 选择/新建/删除。

**操作**: 把 `ui/sidebar.py` 内容**完全替换**为:

```python
"""ui/sidebar.py — 侧边栏（用户 + Vault + 来源）"""
import streamlit as st
from core.db import db_manager


def _get_user_id() -> str:
    return st.session_state.get("user_id", "anonymous")


def _get_vault_uuid() -> str:
    return st.session_state.get("vault_uuid", "")


def render_user_section() -> None:
    st.markdown("### 用户")
    name = st.text_input(
        "用户名", value=_get_user_id(), key="ui_user_input",
        help="输入用户名以切换个人空间",
    )
    if name and name.strip() and name.strip() != _get_user_id():
        st.session_state["user_id"] = name.strip()
        st.session_state["vault_uuid"] = ""
        st.rerun()


def render_vault_section() -> None:
    st.markdown("### 笔记库")
    user_id = _get_user_id()
    vaults = db_manager.list_vaults(user_id)

    if not vaults:
        st.caption("还没有笔记库，请新建一个")
    else:
        options = {v.vault_uuid: v.vault_name for v in vaults}
        keys = list(options.keys())
        current = _get_vault_uuid()
        if current not in options:
            current = keys[0]
            st.session_state["vault_uuid"] = current

        selected = st.selectbox(
            "当前库", options=keys,
            format_func=lambda u: options[u],
            index=keys.index(current),
            key="ui_vault_select",
        )
        if selected != _get_vault_uuid():
            st.session_state["vault_uuid"] = selected
            st.rerun()

    with st.expander("新建笔记库"):
        new_name = st.text_input("名称", key="ui_new_vault_name", label_visibility="collapsed",
                                 placeholder="输入库名")
        if st.button("创建", key="ui_btn_create_vault", use_container_width=True):
            if new_name.strip():
                uuid = db_manager.create_vault(user_id, new_name.strip())
                st.session_state["vault_uuid"] = uuid
                st.rerun()
            else:
                st.warning("请输入名称")

    if vaults and _get_vault_uuid():
        with st.expander("删除当前库"):
            st.caption("删除后不可恢复")
            if st.button("确认删除", key="ui_btn_delete_vault",
                         use_container_width=True, type="secondary"):
                db_manager.delete_vault(_get_vault_uuid())
                st.session_state["vault_uuid"] = ""
                st.rerun()


def render() -> None:
    with st.sidebar:
        render_user_section()
        st.divider()
        render_vault_section()
```

更新 `app.py`:
```python
"""app.py — NotebookMH 入口"""
import streamlit as st
import config
from ui import sidebar

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

st.title("NotebookMH")
st.caption(
    f"用户: {st.session_state.get('user_id', '未登录')} | "
    f"当前库: {st.session_state.get('vault_uuid', '未选')[:8] or '未选'}"
)
```

**禁止**:
- ❌ 加任何"模式切换"按钮
- ❌ 在 button label 用 emoji

**验收**（手动浏览器）:
1. `streamlit run app.py --server.headless true`
2. 浏览器操作:
   a. 输入用户名 "alice" → 顶部应显示 `用户: alice`
   b. 展开"新建笔记库"，输入"测试库1"，点创建 → 下拉出现
   c. 再建"测试库2"，下拉切换，顶部 vault_uuid 应变化
   d. 删除当前库 → 库消失
3. 全程无 Traceback

---

## ⛳ Checkpoint 1（Step 5 完成后必做）

按 `BUILD_PLAN.md` 第 2 节"每 5 步锚点"执行：
1. 重读 `ARCHITECTURE.md`
2. 重读 PROGRESS.md 中 Step 0-5
3. 在 PROGRESS.md 写 Checkpoint 1

完成 Checkpoint 后才能进入 Step 6。

---

## Step 6：实现 core/vector_store.py（ChromaDB）

**目标**: ChromaDB 单例 + add/query/delete。

**操作**: `core/vector_store.py` 完全替换:

```python
"""core/vector_store.py — ChromaDB 向量存储"""
import logging
from typing import Optional

import chromadb
from chromadb.config import Settings

from config import CHROMA_DIR, EMBEDDING_MODEL

log = logging.getLogger(__name__)


class VectorStore:
    def __init__(self):
        self._client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._embedder = None  # 懒加载

    def _get_embedder(self):
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(EMBEDDING_MODEL)
        return self._embedder

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self._get_embedder().encode(texts, convert_to_numpy=True).tolist()

    def _collection_name(self, vault_uuid: str) -> str:
        return f"vault_{vault_uuid}"

    def _get_collection(self, vault_uuid: str):
        return self._client.get_or_create_collection(
            name=self._collection_name(vault_uuid),
            metadata={"hnsw:space": "cosine"},
        )

    def add(self, vault_uuid: str, doc_hash: str, chunks: list[dict]) -> None:
        if not chunks:
            return
        coll = self._get_collection(vault_uuid)
        texts = [c["chunk_text"] for c in chunks]
        embeddings = self._embed(texts)
        ids = [f"{doc_hash}_{c['chunk_index']}" for c in chunks]
        metadatas = [{
            "doc_hash": doc_hash,
            "chunk_index": int(c["chunk_index"]),
            "source_page": int(c.get("source_page", 0)),
            "header": str(c.get("header_hierarchy", "")),
        } for c in chunks]
        coll.upsert(ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)

    def query(self, vault_uuid: str, query_text: str, top_k: int = 5,
              source_hashes: Optional[list[str]] = None) -> list[dict]:
        coll = self._get_collection(vault_uuid)
        emb = self._embed([query_text])[0]
        where = None
        if source_hashes:
            where = {"doc_hash": {"$in": source_hashes}}
        try:
            res = coll.query(query_embeddings=[emb], n_results=top_k, where=where)
        except Exception as e:
            log.warning("Chroma query failed: %s", e)
            return []
        out = []
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for i, _id in enumerate(ids):
            out.append({
                "chunk_text": docs[i],
                "doc_hash": metas[i].get("doc_hash"),
                "chunk_index": metas[i].get("chunk_index"),
                "score": 1.0 - float(dists[i]) if i < len(dists) else 0.0,
            })
        return out

    def delete(self, vault_uuid: str, doc_hash: str) -> None:
        try:
            coll = self._get_collection(vault_uuid)
            coll.delete(where={"doc_hash": doc_hash})
        except Exception as e:
            log.warning("Chroma delete failed: %s", e)

    def delete_collection(self, vault_uuid: str) -> None:
        try:
            self._client.delete_collection(self._collection_name(vault_uuid))
        except Exception:
            pass


vector_store = VectorStore()
```

**验收**:
```powershell
python -c "from core.vector_store import vector_store; v='t1'; vector_store.add(v,'d1',[{'chunk_index':0,'chunk_text':'光合作用是植物利用阳光合成有机物','source_page':1,'header_hierarchy':''}]); r=vector_store.query(v,'什么是光合作用',top_k=1); print('结果:', r); vector_store.delete_collection(v); print('清理完成')"
```

**预期**: `结果:` 含 1 条 dict，`chunk_text` 包含"光合作用"。

⚠️ **首次运行需联网下载 ~480MB 的 sentence-transformer 模型**。若失败 → 在 PROGRESS.md 记 BLOCKED，告知用户配置 HuggingFace 镜像或代理。

---

## Step 7：实现 core/parsers.py（多格式解析）

**目标**: 7 种文件 + URL 统一解析为 `{"text": str, "page_count": int}`。

**操作**: `core/parsers.py` 完全替换:

```python
"""core/parsers.py — 文件/URL 解析"""
import csv, json, io


def parse_pdf(data: bytes) -> dict:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return {"text": "\n\n".join(pages), "page_count": len(pages)}


def parse_docx(data: bytes) -> dict:
    from docx import Document
    doc = Document(io.BytesIO(data))
    paras = [p.text for p in doc.paragraphs if p.text.strip()]
    return {"text": "\n".join(paras), "page_count": 0}


def parse_pptx(data: bytes) -> dict:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    slides = []
    for slide in prs.slides:
        texts = []
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text.strip():
                texts.append(shape.text)
        slides.append("\n".join(texts))
    return {"text": "\n\n".join(slides), "page_count": len(slides)}


def parse_txt(data: bytes) -> dict:
    for enc in ("utf-8", "gbk", "gb18030", "latin-1"):
        try:
            return {"text": data.decode(enc), "page_count": 0}
        except UnicodeDecodeError:
            continue
    return {"text": data.decode("utf-8", errors="ignore"), "page_count": 0}


def parse_md(data: bytes) -> dict:
    return parse_txt(data)


def parse_csv(data: bytes) -> dict:
    text = parse_txt(data)["text"]
    reader = csv.reader(io.StringIO(text))
    rows = ["\t".join(r) for r in reader]
    return {"text": "\n".join(rows), "page_count": 0}


def parse_json(data: bytes) -> dict:
    text = parse_txt(data)["text"]
    try:
        obj = json.loads(text)
        return {"text": json.dumps(obj, ensure_ascii=False, indent=2), "page_count": 0}
    except json.JSONDecodeError:
        return {"text": text, "page_count": 0}


def parse_url(url: str) -> dict:
    import httpx
    from bs4 import BeautifulSoup
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0"}) as client:
        r = client.get(url)
        r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return {"text": text, "page_count": 0}


_DISPATCH = {
    "pdf": parse_pdf, "docx": parse_docx, "pptx": parse_pptx,
    "txt": parse_txt, "md": parse_md, "csv": parse_csv, "json": parse_json,
}


def parse_file(file_name: str, data: bytes) -> dict:
    ext = file_name.rsplit(".", 1)[-1].lower()
    if ext not in _DISPATCH:
        raise ValueError(f"不支持的文件类型: {ext}")
    return _DISPATCH[ext](data)
```

如 `requirements.txt` 缺 `beautifulsoup4`，**追加一行**：`beautifulsoup4>=4.12.0`，然后 `pip install beautifulsoup4`。

**验收**:
```powershell
python -c "from core.parsers import parse_txt, parse_json, parse_csv; print('TXT:', parse_txt('你好'.encode('utf-8'))); print('JSON:', parse_json(b'{\"x\":1}')); print('CSV:', parse_csv(b'a,b\n1,2'))"
```

**预期**: 三行 dict 输出。

---

## Step 8：实现 core/ingest.py（chunk + 入库）

**目标**: 把 parse 结果 → chunk → SQLite + ChromaDB 双写。

**操作**: `core/ingest.py` 完全替换:

```python
"""core/ingest.py — 解析+切片+入库"""
import hashlib
import re

from config import CHUNK_SIZE, CHUNK_OVERLAP
from core.db import db_manager
from core.parsers import parse_file, parse_url
from core.vector_store import vector_store


def _hash_content(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _split_into_chunks(text: str) -> list[dict]:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    if not text:
        return []
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) + 2 <= CHUNK_SIZE:
            buf = (buf + "\n\n" + para) if buf else para
        else:
            if buf:
                chunks.append(buf)
            if len(para) <= CHUNK_SIZE:
                buf = para
            else:
                step = CHUNK_SIZE - CHUNK_OVERLAP
                for i in range(0, len(para), step):
                    chunks.append(para[i:i + CHUNK_SIZE])
                buf = ""
    if buf:
        chunks.append(buf)
    return [
        {"chunk_index": i, "chunk_text": c, "source_page": 0,
         "header_hierarchy": "", "chunk_size": len(c)}
        for i, c in enumerate(chunks)
    ]


async def ingest_file(vault_uuid: str, file_name: str, data: bytes) -> dict:
    content_hash = _hash_content(data)
    if db_manager.document_exists(vault_uuid, content_hash):
        return {"status": "duplicate", "doc_hash": content_hash,
                "chunks": 0, "msg": "文件已存在"}
    parsed = parse_file(file_name, data)
    chunks = _split_into_chunks(parsed["text"])
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
    return {"status": "ok", "doc_hash": content_hash,
            "chunks": len(chunks), "msg": f"成功摄入 {len(chunks)} 片段"}


async def ingest_text(vault_uuid: str, title: str, text: str,
                      source_type: str = "paste", source_url: str = "") -> dict:
    data = text.encode("utf-8")
    content_hash = _hash_content(data)
    if db_manager.document_exists(vault_uuid, content_hash):
        return {"status": "duplicate", "doc_hash": content_hash,
                "chunks": 0, "msg": "内容已存在"}
    chunks = _split_into_chunks(text)
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
    return {"status": "ok", "doc_hash": content_hash,
            "chunks": len(chunks), "msg": f"成功摄入 {len(chunks)} 片段"}


async def ingest_url(vault_uuid: str, url: str) -> dict:
    parsed = parse_url(url)
    if not parsed["text"].strip():
        return {"status": "error", "doc_hash": "", "chunks": 0, "msg": "URL 无可提取文本"}
    return await ingest_text(vault_uuid, url, parsed["text"],
                             source_type="url", source_url=url)
```

**验收**:
```powershell
python -c "import asyncio; from core.db import db_manager; from core.ingest import ingest_text; u=db_manager.create_vault('test_ingest','t'); r=asyncio.run(ingest_text(u,'测试','光合作用是植物利用叶绿体捕获光能合成有机物的过程。\n\n它是生物圈能量循环的基础。')); print('结果:', r); print('文档数:', len(db_manager.list_documents(u))); db_manager.delete_vault(u)"
```

**预期**: `status='ok'`, `chunks>=1`, `文档数: 1`。

---

## Step 9：阶段 A 集成验收（上传 UI）

**目标**: 联调 sidebar + ingest，UI 能驱动上传。

**操作**: 在 `ui/sidebar.py` 末尾追加 `render_upload_section` 并在 `render()` 中调用。

```python
def render_upload_section() -> None:
    import asyncio, traceback
    from core.db import db_manager
    from core.ingest import ingest_file

    vault_uuid = _get_vault_uuid()
    st.markdown("### 来源")
    if not vault_uuid:
        st.caption("请先选择或新建笔记库")
        return
    docs = db_manager.list_documents(vault_uuid)
    st.caption(f"已上传 {len(docs)} / 50")
    for d in docs[:20]:
        st.markdown(f"📄 {d.file_name}")

    uploaded = st.file_uploader(
        "上传文件",
        type=["pdf", "docx", "pptx", "txt", "md", "csv", "json"],
        accept_multiple_files=True,
        key="ui_uploader",
    )
    if uploaded:
        for f in uploaded:
            with st.spinner(f"摄入 {f.name}..."):
                try:
                    data = f.read()
                    if len(data) > 500 * 1024 * 1024:
                        st.error(f"{f.name} 超过 500MB 上限")
                        continue
                    r = asyncio.run(ingest_file(vault_uuid, f.name, data))
                    if r["status"] == "ok":
                        st.success(f"{f.name}: {r['msg']}")
                    elif r["status"] == "duplicate":
                        st.info(f"{f.name}: 已存在")
                    else:
                        st.error(f"{f.name}: {r['msg']}")
                except Exception:
                    st.error(f"{f.name} 失败:")
                    st.code(traceback.format_exc())
        st.rerun()
```

更新 `render()`:
```python
def render() -> None:
    with st.sidebar:
        render_user_section()
        st.divider()
        render_vault_section()
        st.divider()
        render_upload_section()
```

更新 `app.py` 顶部加 `nest_asyncio`:
```python
import nest_asyncio
nest_asyncio.apply()
```
放在 `import streamlit as st` 之后。

**验收**（端到端）:
1. 启动 streamlit
2. 浏览器:
   a. 用户名 `alice`
   b. 新建库 `测试库`
   c. 上传一个真实 TXT 文件（几行中文）
   d. 看到绿色 `成功摄入 N 片段`
   e. 来源列表显示文件名
3. SQL 验证:
   ```powershell
   python -c "from core.db import db_manager; vs=db_manager.list_vaults('alice'); [print(v.vault_name, len(db_manager.list_documents(v.vault_uuid))) for v in vs]"
   ```
4. Chroma 验证:
   ```powershell
   python -c "from core.vector_store import vector_store; from core.db import db_manager; vs=db_manager.list_vaults('alice'); r=vector_store.query(vs[0].vault_uuid, '随便', top_k=2); print('chroma 命中:', len(r))"
   ```

**记录 + Checkpoint 阶段 A**: 在 PROGRESS.md 写阶段 A 完成清单 + 12 项功能进度 (F1/F2/F4 = ✅，F3 = 部分)。

---

## 阶段 A 完成

完成 Step 9 后:
1. 更新 PROGRESS.md "当前 Step" = Step 10
2. 阅读 `plans/phase_b_ingest.md`

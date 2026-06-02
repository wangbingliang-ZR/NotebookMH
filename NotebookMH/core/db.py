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
        # 同步清理向量库（避免幽灵 chunk）
        try:
            from core.vector_store import vector_store
            vector_store.delete_collection(vault_uuid)
        except Exception:
            pass  # 向量库可能从未创建

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

    def save_chat_pair(self, vault_uuid: str, user_id: str,
                       query: str, answer: str, citations: list = None) -> None:
        """原子保存 user + assistant 两条消息，避免半条记录。"""
        with self.session() as s:
            s.add(ChatMsg(
                vault_uuid=vault_uuid, user_id=user_id,
                role="user", content=query, citations=[],
            ))
            s.add(ChatMsg(
                vault_uuid=vault_uuid, user_id=user_id,
                role="assistant", content=answer, citations=citations or [],
            ))

    def load_chat(self, vault_uuid: str, user_id: str, limit: int = 50) -> list:
        with self.session() as s:
            rows = s.execute(
                select(ChatMsg).where(
                    ChatMsg.vault_uuid == vault_uuid,
                    ChatMsg.user_id == user_id,
                ).order_by(ChatMsg.id).limit(limit)  # 按 id 确保严格顺序
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

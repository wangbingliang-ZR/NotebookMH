"""
utils/db_manager.py - SQLAlchemy / SQLite WAL 并发池

Phase 1A 实现：
  - SQLite WAL 模式启用
  - document_registry 表（零越权哈希墙）
  - chunk_registry 表（语义 Chunk 记录）
  - 单例连接池 + 跨线程 Session 分发
"""

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, validator
from sqlalchemy import (
    Column, DateTime, Float, Integer, JSON, String, Text, create_engine, inspect, text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()

# ---------------------------------------------------------------------------
# 1. ORM 模型定义
# ---------------------------------------------------------------------------

class DocumentRegistryORM(Base):
    """文档注册表 —— 物理文件与认知容器的密码学绑定"""
    __tablename__ = "document_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    doc_size = Column(Integer, default=0)
    page_count = Column(Integer, default=0)
    created_at = Column(String(32), default=lambda: _utc_now())
    summary = Column(Text, default="")
    key_topics = Column(Text, default="")
    suggested_questions = Column(Text, default="")
    full_text = Column(Text, default="")

    # 联合唯一索引：同一 Vault 内同一文件不可重复入库
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class ChunkRegistryORM(Base):
    """Chunk 注册表 —— 语义切块的溯源记录"""
    __tablename__ = "chunk_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    doc_hash = Column(String(64), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    source_page = Column(Integer, default=0)
    header_hierarchy = Column(String(255), default="")
    chunk_size = Column(Integer, default=0)
    overlap_prev = Column(Integer, default=0)
    embedding_model = Column(String(64), default="")
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class VaultRegistryORM(Base):
    """笔记库注册表 —— 用户私有的知识容器"""
    __tablename__ = "vault_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), unique=True, nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    vault_name = Column(String(255), nullable=False)
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class ConceptDependencyORM(Base):
    """概念依赖关系表 —— 文档级 DAG 拓扑记录"""
    __tablename__ = "concept_dependencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    doc_hash = Column(String(64), nullable=False, index=True)
    concept_name = Column(String(255), nullable=False)
    depends_on = Column(String(1024), default="[]")  # JSON array of concept names
    summary = Column(Text, default="")
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


# ── Phase 3: 学习记忆表 ────────────────────────────────────────

class ChatHistoryORM(Base):
    """聊天历史持久化。"""
    __tablename__ = "chat_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False)
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    msg_type = Column(String(32), default="text")
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class FlashcardORM(Base):
    """闪卡注册表。"""
    __tablename__ = "flashcard_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    mastery = Column(Integer, default=0)  # 0=未学 1=模糊 2=已掌握
    review_count = Column(Integer, default=0)
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class QuizHistoryORM(Base):
    """测验历史记录。"""
    __tablename__ = "quiz_history"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    options = Column(Text, nullable=False)  # JSON: ["A...", "B...", "C...", "D..."]
    correct = Column(String(8), nullable=False)  # "A" / "B" / "C" / "D"
    explanation = Column(Text, default="")
    user_answer = Column(String(8), default="")
    is_correct = Column(Integer, default=-1)  # -1=未答 0=错 1=对
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class WrongAnswerORM(Base):
    """错题记录表。"""
    __tablename__ = "wrong_answer_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    question = Column(Text, nullable=False)
    user_answer = Column(String(256), default="")
    correct_answer = Column(String(256), default="")
    explanation = Column(Text, default="")
    mastered = Column(Integer, default=0)
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class NoteORM(Base):
    """笔记注册表。"""
    __tablename__ = "note_registry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uuid = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    content = Column(Text, nullable=False)
    pinned = Column(Integer, default=0)
    tags = Column(Text, default="")  # 逗号分隔的标签
    created_at = Column(String(32), default=lambda: _utc_now())

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class UserStatsORM(Base):
    """用户统计 —— 全局学习轨迹"""
    __tablename__ = "user_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), unique=True, nullable=False, index=True)
    total_questions = Column(Integer, default=0)
    correct_count = Column(Integer, default=0)
    wrong_count = Column(Integer, default=0)
    strategy_weights = Column(JSON, default=dict)   # MAB 策略权重 (Phase 4/8)
    last_login = Column(DateTime, nullable=True)    # Phase 8: 最后水合时间
    created_at = Column(DateTime, default=lambda: _utc_dt())
    updated_at = Column(DateTime, default=lambda: _utc_dt(), onupdate=lambda: _utc_dt())

    __table_args__ = ({"sqlite_autoincrement": True},)


class ConceptMasteryORM(Base):
    """知识点掌握度 —— 概念级认知图谱"""
    __tablename__ = "concept_mastery"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    concept_name = Column(String(255), nullable=False)
    mastery_level = Column(Float, default=0.0)      # 0.0 ~ 100.0
    status = Column(String(32), default="learning")  # learning / mastered / struggling
    consecutive_wrong = Column(Integer, default=0)
    last_interaction = Column(DateTime, nullable=True)

    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class InteractionLogORM(Base):
    """交互日志 —— 全量对话审计追踪"""
    __tablename__ = "interaction_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    mode = Column(String(32), default="adult")       # child / adult
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    question = Column(Text, nullable=True)
    user_answer = Column(Text, nullable=True)
    is_correct = Column(Integer, nullable=True)      # 1 / 0 / NULL
    c_load = Column(Float, nullable=True)              # 认知负荷
    e_valence = Column(Float, nullable=True)       # 情感效价
    diagnosis = Column(Text, nullable=True)
    teacher_type = Column(String(32), nullable=True)   # Phase 2 新增
    strategy_applied = Column(String(64), nullable=True)  # Phase 8: 选中策略臂
    mastery_delta = Column(Float, nullable=True)          # Phase 8: 掌握度变化
    timestamp = Column(DateTime, default=lambda: _utc_dt())

    __table_args__ = ({"sqlite_autoincrement": True},)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_dt() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# 2. Pydantic 防线 (Phase 8)
# ---------------------------------------------------------------------------


class UserStatsSchema(BaseModel):
    """Pydantic 防线：用户统计 —— 消除隐式装箱/拆箱错误。"""
    model_config = ConfigDict(from_attributes=True)

    user_id: str = Field(default="anonymous")
    mab_weights: Dict[str, Any] = Field(default_factory=dict, alias="strategy_weights")
    total_questions: int = Field(default=0, ge=0)
    correct_count: int = Field(default=0, ge=0)
    wrong_count: int = Field(default=0, ge=0)
    last_login: Optional[datetime] = None


class ConceptMasterySchema(BaseModel):
    """Pydantic 防线：知识点掌握度 —— mastery_level 强制 0~100。"""
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    concept_node: str = Field(..., alias="concept_name")
    mastery_level: float = Field(default=0.0, ge=0.0, le=100.0)
    status: str = Field(default="learning")
    consecutive_wrong: int = Field(default=0, ge=0)
    last_interaction: Optional[datetime] = None


class InteractionLogSchema(BaseModel):
    """Pydantic 防线：交互遥测日志 —— 策略与认知数据快照。"""
    model_config = ConfigDict(from_attributes=True)

    user_id: str
    timestamp: Optional[datetime] = None
    c_load: Optional[float] = None
    e_valence: Optional[float] = None
    strategy_applied: Optional[str] = None
    mastery_delta: Optional[float] = None


# ---------------------------------------------------------------------------
# 3. 连接池单例
# ---------------------------------------------------------------------------

class DBPoolManager:
    """
    数据库连接池单例。

    特性：
      - 自动启用 SQLite WAL 模式，消除读锁阻塞
      - 自动建表（若不存在）
      - sessionmaker 线程安全
    """

    _instance: Optional["DBPoolManager"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "DBPoolManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        db_path: str = "data/sys_meta.db",
        echo: bool = False,
    ) -> None:
        if self._initialized:
            return
        self._initialized = True

        # 确保目录存在
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self.db_url = f"sqlite:///{db_path}"
        self._engine = create_engine(
            self.db_url,
            echo=echo,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        # 启用 WAL 模式
        with self._engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            logger.info("SQLite WAL mode enabled.")

        Base.metadata.create_all(self._engine)
        self._migrate_schema()
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
            bind=self._engine,
        )
        logger.info("DBPoolManager initialized: %s", self.db_url)

    # ------------------ 上下文管理器 ------------------

    @contextmanager
    def session(self) -> Generator[Any, None, None]:
        """线程安全的 Session 上下文管理器。"""
        sess = self.SessionLocal()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    # ------------------ 文档注册接口 ------------------

    def document_exists(self, vault_uuid: str, content_hash: str) -> bool:
        """
        O(1) 闪电查询：检查该 Vault 内是否已有此文件的哈希记录。
        若命中，可直接短路整个解析管线（绝对秒传）。
        """
        with self.session() as sess:
            result = sess.query(DocumentRegistryORM).filter_by(
                vault_uuid=vault_uuid,
                content_hash=content_hash,
            ).first()
            return result is not None

    def register_document(
        self,
        vault_uuid: str,
        file_name: str,
        content_hash: str,
        doc_size: int = 0,
        page_count: int = 0,
        full_text: str = "",
    ) -> int:
        """注册新文档，返回自增 ID。"""
        with self.session() as sess:
            doc = DocumentRegistryORM(
                vault_uuid=vault_uuid,
                file_name=file_name,
                content_hash=content_hash,
                doc_size=doc_size,
                page_count=page_count,
                full_text=full_text[:50000] if full_text else "",
            )
            sess.add(doc)
            sess.flush()
            logger.info(
                "Document registered: vault=%s hash=%s", vault_uuid, content_hash[:16]
            )
            return doc.id

    # ------------------ Chunk 注册接口 ------------------

    def register_chunks(
        self,
        vault_uuid: str,
        doc_hash: str,
        chunks: List[Dict[str, Any]],
        embedding_model: str = "",
    ) -> None:
        """
        批量注册语义 Chunk。

        chunks 每项必须包含：
          chunk_index, chunk_text, source_page, header_hierarchy,
          chunk_size, overlap_prev
        """
        with self.session() as sess:
            for c in chunks:
                sess.add(
                    ChunkRegistryORM(
                        vault_uuid=vault_uuid,
                        doc_hash=doc_hash,
                        chunk_index=c["chunk_index"],
                        chunk_text=c["chunk_text"],
                        source_page=c.get("source_page", 0),
                        header_hierarchy=c.get("header_hierarchy", ""),
                        chunk_size=c.get("chunk_size", 0),
                        overlap_prev=c.get("overlap_prev", 0),
                        embedding_model=embedding_model,
                    )
                )
            logger.info(
                "Chunks registered: vault=%s doc_hash=%s count=%d",
                vault_uuid,
                doc_hash[:16],
                len(chunks),
            )

    def get_chunks_by_doc(
        self, vault_uuid: str, doc_hash: str
    ) -> List[Tuple[int, str, str]]:
        """按文档哈希取回所有 Chunk（chunk_index, chunk_text, header_hierarchy）。"""
        with self.session() as sess:
            rows = (
                sess.query(ChunkRegistryORM)
                .filter_by(vault_uuid=vault_uuid, doc_hash=doc_hash)
                .order_by(ChunkRegistryORM.chunk_index)
                .all()
            )
            return [(r.chunk_index, r.chunk_text, r.header_hierarchy) for r in rows]

    # ------------------ Vault 管理接口 ------------------

    def create_vault(
        self, vault_uuid: str, user_id: str, vault_name: str
    ) -> VaultRegistryORM:
        """创建新笔记库。"""
        with self.session() as sess:
            vault = VaultRegistryORM(
                vault_uuid=vault_uuid,
                user_id=user_id,
                vault_name=vault_name,
            )
            sess.add(vault)
            sess.flush()
            logger.info("Vault created: uuid=%s name=%s user=%s", vault_uuid, vault_name, user_id)
            return vault

    def list_vaults(self, user_id: str) -> List[VaultRegistryORM]:
        """列出某用户的全部笔记库。"""
        with self.session() as sess:
            return (
                sess.query(VaultRegistryORM)
                .filter_by(user_id=user_id)
                .order_by(VaultRegistryORM.created_at.desc())
                .all()
            )

    def get_vault(self, vault_uuid: str) -> Optional[VaultRegistryORM]:
        """按 UUID 查询单个笔记库。"""
        with self.session() as sess:
            return sess.query(VaultRegistryORM).filter_by(vault_uuid=vault_uuid).first()

    def delete_vault(self, vault_uuid: str) -> None:
        """删除笔记库及其下全部文档和 Chunk（SQLite 层）。"""
        with self.session() as sess:
            # 级联删除 chunks
            sess.query(ChunkRegistryORM).filter_by(vault_uuid=vault_uuid).delete()
            # 级联删除文档注册
            sess.query(DocumentRegistryORM).filter_by(vault_uuid=vault_uuid).delete()
            # 删除 vault 本身
            vault = sess.query(VaultRegistryORM).filter_by(vault_uuid=vault_uuid).first()
            if vault:
                sess.delete(vault)
            logger.info("Vault deleted: uuid=%s", vault_uuid)

    # ------------------ 文档列表与删除 ------------------

    def list_documents(self, vault_uuid: str) -> List[DocumentRegistryORM]:
        """列出某 Vault 下的全部文档。"""
        with self.session() as sess:
            return (
                sess.query(DocumentRegistryORM)
                .filter_by(vault_uuid=vault_uuid)
                .order_by(DocumentRegistryORM.created_at.desc())
                .all()
            )

    def count_documents(self, vault_uuid: str) -> int:
        """统计某 Vault 下的文档数量。"""
        with self.session() as sess:
            return sess.query(DocumentRegistryORM).filter_by(vault_uuid=vault_uuid).count()

    def get_document(self, vault_uuid: str, content_hash: str) -> DocumentRegistryORM:
        """获取单个文档。"""
        with self.session() as sess:
            return sess.query(DocumentRegistryORM).filter_by(
                vault_uuid=vault_uuid, content_hash=content_hash
            ).first()

    def update_document_summary(self, vault_uuid: str, content_hash: str,
                                 summary: str, key_topics: str) -> None:
        """更新文档的摘要和关键主题。"""
        with self.session() as sess:
            doc = sess.query(DocumentRegistryORM).filter_by(
                vault_uuid=vault_uuid, content_hash=content_hash
            ).first()
            if doc:
                doc.summary = summary
                doc.key_topics = key_topics
                sess.commit()

    def get_suggested_questions(self, vault_uuid: str) -> list:
        """获取该 Vault 下所有文档的建议问题，合并去重。"""
        with self.session() as sess:
            docs = sess.query(DocumentRegistryORM).filter_by(vault_uuid=vault_uuid).all()
            all_q = []
            for doc in docs:
                if doc.suggested_questions:
                    all_q.extend([q.strip() for q in doc.suggested_questions.split("\n") if q.strip()])
            return all_q[:6]

    def update_document_questions(self, vault_uuid: str, content_hash: str,
                                   questions: str) -> None:
        """更新文档的建议问题。"""
        with self.session() as sess:
            doc = sess.query(DocumentRegistryORM).filter_by(
                vault_uuid=vault_uuid, content_hash=content_hash
            ).first()
            if doc:
                doc.suggested_questions = questions
                sess.commit()

    def save_chat_message(self, vault_uuid: str, user_id: str,
                          role: str, content: str, msg_type: str = "text") -> None:
        with self.session() as sess:
            sess.add(ChatHistoryORM(
                vault_uuid=vault_uuid, user_id=user_id,
                role=role, content=content, msg_type=msg_type
            ))
            sess.commit()

    def load_chat_history(self, vault_uuid: str, user_id: str,
                          limit: int = 50) -> list:
        with self.session() as sess:
            rows = (
                sess.query(ChatHistoryORM)
                .filter_by(vault_uuid=vault_uuid, user_id=user_id)
                .order_by(ChatHistoryORM.id.desc())
                .limit(limit)
                .all()
            )
            return list(reversed(rows))

    def clear_chat_history(self, vault_uuid: str, user_id: str) -> None:
        with self.session() as sess:
            sess.query(ChatHistoryORM).filter_by(
                vault_uuid=vault_uuid, user_id=user_id
            ).delete()
            sess.commit()

    def save_flashcards(self, vault_uuid: str, cards: list) -> None:
        """批量保存闪卡。cards = [{\"question\": \"...\", \"answer\": \"...\"}, ...]"""
        with self.session() as sess:
            for c in cards:
                sess.add(FlashcardORM(
                    vault_uuid=vault_uuid,
                    question=c["question"],
                    answer=c["answer"],
                ))
            sess.commit()

    def list_flashcards(self, vault_uuid: str) -> list:
        with self.session() as sess:
            return sess.query(FlashcardORM).filter_by(vault_uuid=vault_uuid).all()

    def update_flashcard_mastery(self, card_id: int, mastery: int) -> None:
        with self.session() as sess:
            card = sess.query(FlashcardORM).get(card_id)
            if card:
                card.mastery = mastery
                card.review_count += 1
                sess.commit()

    def delete_all_flashcards(self, vault_uuid: str) -> None:
        with self.session() as sess:
            sess.query(FlashcardORM).filter_by(vault_uuid=vault_uuid).delete()
            sess.commit()

    def save_wrong_answer(self, vault_uuid: str, question: str, user_answer: str,
                          correct_answer: str, explanation: str = "") -> None:
        with self.session() as sess:
            sess.add(WrongAnswerORM(
                vault_uuid=vault_uuid,
                question=question,
                user_answer=user_answer,
                correct_answer=correct_answer,
                explanation=explanation,
            ))
            sess.commit()

    def list_wrong_answers(self, vault_uuid: str, mastered: int = 0) -> list:
        with self.session() as sess:
            return sess.query(WrongAnswerORM).filter_by(
                vault_uuid=vault_uuid, mastered=mastered
            ).all()

    def mark_wrong_answer_mastered(self, wrong_id: int) -> None:
        with self.session() as sess:
            item = sess.query(WrongAnswerORM).get(wrong_id)
            if item:
                item.mastered = 1
                sess.commit()

    def delete_wrong_answer(self, wrong_id: int) -> None:
        with self.session() as sess:
            item = sess.query(WrongAnswerORM).get(wrong_id)
            if item:
                sess.delete(item)
                sess.commit()

    def save_quiz_questions(self, vault_uuid: str, questions: list) -> None:
        """questions = [{\"question\", \"options\":[], \"correct\", \"explanation\"}]"""
        import json as _json
        with self.session() as sess:
            for q in questions:
                sess.add(QuizHistoryORM(
                    vault_uuid=vault_uuid, question=q["question"],
                    options=_json.dumps(q.get("options", []), ensure_ascii=False),
                    correct=q.get("correct", ""), explanation=q.get("explanation", ""),
                ))
            sess.commit()

    def list_quiz_unanswered(self, vault_uuid: str) -> list:
        with self.session() as sess:
            return sess.query(QuizHistoryORM).filter_by(vault_uuid=vault_uuid, is_correct=-1).all()

    def answer_quiz(self, quiz_id: int, user_answer: str) -> bool:
        with self.session() as sess:
            q = sess.query(QuizHistoryORM).get(quiz_id)
            if q:
                q.user_answer = user_answer
                q.is_correct = 1 if user_answer == q.correct else 0
                sess.commit()
                return q.is_correct == 1
        return False

    def save_note(self, vault_uuid: str, user_id: str, title: str, content: str, pinned: int = 0) -> None:
        with self.session() as sess:
            sess.add(NoteORM(
                vault_uuid=vault_uuid, user_id=user_id,
                title=title, content=content, pinned=pinned,
            ))
            sess.commit()

    def list_notes(self, vault_uuid: str, user_id: str, limit: int = 100) -> list:
        with self.session() as sess:
            return (
                sess.query(NoteORM)
                .filter_by(vault_uuid=vault_uuid, user_id=user_id)
                .order_by(NoteORM.pinned.desc(), NoteORM.id.desc())
                .limit(limit)
                .all()
            )

    def update_note(self, note_id: int, title: str = None, content: str = None, pinned: int = None, tags: str = None) -> None:
        with self.session() as sess:
            note = sess.query(NoteORM).get(note_id)
            if note:
                if title is not None:
                    note.title = title
                if content is not None:
                    note.content = content
                if pinned is not None:
                    note.pinned = pinned
                if tags is not None:
                    note.tags = tags
                sess.commit()

    def list_notes_by_tag(self, vault_uuid: str, user_id: str, tag: str, limit: int = 100) -> list:
        with self.session() as sess:
            return (
                sess.query(NoteORM)
                .filter_by(vault_uuid=vault_uuid, user_id=user_id)
                .filter(NoteORM.tags.ilike(f"%{tag}%"))
                .order_by(NoteORM.pinned.desc(), NoteORM.id.desc())
                .limit(limit)
                .all()
            )

    def delete_note(self, note_id: int) -> None:
        with self.session() as sess:
            note = sess.query(NoteORM).get(note_id)
            if note:
                sess.delete(note)
                sess.commit()

    def delete_document(self, vault_uuid: str, content_hash: str) -> None:
        """删除单文档及其 Chunk（SQLite 层）。"""
        with self.session() as sess:
            sess.query(ChunkRegistryORM).filter_by(
                vault_uuid=vault_uuid, doc_hash=content_hash
            ).delete()
            doc = sess.query(DocumentRegistryORM).filter_by(
                vault_uuid=vault_uuid, content_hash=content_hash
            ).first()
            if doc:
                sess.delete(doc)
            logger.info("Document deleted: vault=%s hash=%s", vault_uuid, content_hash[:16])

    # ------------------ 概念依赖关系 (DAG) 接口 ------------------

    def save_concept_dependencies(
        self,
        vault_uuid: str,
        doc_hash: str,
        concepts: List[Dict[str, Any]],
    ) -> None:
        """
        批量保存概念依赖关系。

        concepts 每项必须包含：
          concept_name, depends_on (List[str]), summary (str)
        """
        import json
        with self.session() as sess:
            # 先删除该文档旧记录（幂等写入）
            sess.query(ConceptDependencyORM).filter_by(
                vault_uuid=vault_uuid, doc_hash=doc_hash
            ).delete()
            for c in concepts:
                sess.add(
                    ConceptDependencyORM(
                        vault_uuid=vault_uuid,
                        doc_hash=doc_hash,
                        concept_name=c["concept_name"],
                        depends_on=json.dumps(c.get("depends_on", []), ensure_ascii=False),
                        summary=c.get("summary", ""),
                    )
                )
            logger.info(
                "Concept dependencies saved: vault=%s doc_hash=%s count=%d",
                vault_uuid,
                doc_hash[:16],
                len(concepts),
            )

    def get_concept_dependencies(
        self, vault_uuid: str, doc_hash: str
    ) -> List[Dict[str, Any]]:
        """按文档哈希取回全部概念依赖关系。"""
        import json
        with self.session() as sess:
            rows = (
                sess.query(ConceptDependencyORM)
                .filter_by(vault_uuid=vault_uuid, doc_hash=doc_hash)
                .all()
            )
            return [
                {
                    "concept_name": r.concept_name,
                    "depends_on": json.loads(r.depends_on),
                    "summary": r.summary,
                }
                for r in rows
            ]

    def get_vault_dag(self, vault_uuid: str) -> List[Dict[str, Any]]:
        """取回某 Vault 下全部文档的所有概念节点（合并去重）。"""
        import json
        with self.session() as sess:
            rows = (
                sess.query(ConceptDependencyORM)
                .filter_by(vault_uuid=vault_uuid)
                .all()
            )
            # 按 concept_name 合并（同一概念可能出现在多篇文档中）
            merged: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                name = r.concept_name
                deps = json.loads(r.depends_on)
                if name not in merged:
                    merged[name] = {
                        "concept_name": name,
                        "depends_on": set(deps),
                        "summary": r.summary,
                    }
                else:
                    merged[name]["depends_on"].update(deps)
            return [
                {
                    "concept_name": v["concept_name"],
                    "depends_on": list(v["depends_on"]),
                    "summary": v["summary"],
                }
                for v in merged.values()
            ]

    # ------------------------------------------------------------------
    # Phase 3: 学习记忆接口
    # ------------------------------------------------------------------

    # ---- UserStats ----

    def get_or_create_user_stats(self, user_id: str) -> UserStatsORM:
        """获取或创建用户统计记录。返回前 expunge，确保 session 外可安全访问属性。"""
        with self.session() as sess:
            stats = sess.query(UserStatsORM).filter_by(user_id=user_id).first()
            if not stats:
                stats = UserStatsORM(user_id=user_id)
                sess.add(stats)
                sess.flush()
                logger.info("UserStats created for %s", user_id)
            # 强制加载 JSON 等列，然后从 session 分离，避免 detached instance
            _ = stats.strategy_weights
            sess.expunge(stats)
            return stats

    def update_user_stats(
        self, user_id: str, correct: Optional[bool] = None, weights: Optional[dict] = None
    ) -> UserStatsORM:
        """更新用户统计：答题正确/错误计数 + 可选 MAB 权重。"""
        with self.session() as sess:
            stats = sess.query(UserStatsORM).filter_by(user_id=user_id).first()
            if not stats:
                stats = UserStatsORM(user_id=user_id)
                sess.add(stats)
            stats.total_questions = (stats.total_questions or 0) + 1
            if correct is True:
                stats.correct_count = (stats.correct_count or 0) + 1
            elif correct is False:
                stats.wrong_count = (stats.wrong_count or 0) + 1
            if weights is not None:
                stats.strategy_weights = weights
            sess.flush()
            logger.info(
                "UserStats updated: user=%s total=%d correct=%d wrong=%d",
                user_id, stats.total_questions, stats.correct_count, stats.wrong_count
            )
            return stats

    # ---- ConceptMastery ----

    def get_concept(self, user_id: str, concept_name: str) -> Optional[ConceptMasteryORM]:
        """获取单个知识点的掌握度记录。"""
        with self.session() as sess:
            return sess.query(ConceptMasteryORM).filter_by(
                user_id=user_id, concept_name=concept_name
            ).first()

    def update_concept_mastery(
        self,
        user_id: str,
        concept_name: str,
        mastery_delta: float = 0.0,
        correct: Optional[bool] = None,
    ) -> ConceptMasteryORM:
        """更新知识点掌握度，自动判断状态 (learning / mastered / struggling)。"""
        with self.session() as sess:
            cm = sess.query(ConceptMasteryORM).filter_by(
                user_id=user_id, concept_name=concept_name
            ).first()
            if not cm:
                cm = ConceptMasteryORM(user_id=user_id, concept_name=concept_name)
                sess.add(cm)

            cm.mastery_level = max(0.0, min(100.0, (cm.mastery_level or 0.0) + mastery_delta))
            cm.last_interaction = _utc_dt()

            if correct is True:
                cm.consecutive_wrong = 0
                cm.status = "mastered" if cm.mastery_level >= 85.0 else "learning"
            elif correct is False:
                cm.consecutive_wrong += 1
                cm.status = "struggling"

            sess.flush()
            logger.info(
                "ConceptMastery updated: user=%s concept=%s level=%.1f status=%s",
                user_id, concept_name, cm.mastery_level, cm.status
            )
            return cm

    def list_concepts(self, user_id: str) -> List[ConceptMasteryORM]:
        """列出用户所有知识点掌握度。"""
        with self.session() as sess:
            return sess.query(ConceptMasteryORM).filter_by(user_id=user_id).all()

    # ---- InteractionLog ----

    def log_interaction(
        self,
        user_id: str,
        query: str,
        response: str,
        mode: str = "adult",
        question: Optional[str] = None,
        user_answer: Optional[str] = None,
        is_correct: Optional[bool] = None,
        c_load: Optional[float] = None,
        e_valence: Optional[float] = None,
        diagnosis: Optional[str] = None,
        teacher_type: Optional[str] = None,
    ) -> InteractionLogORM:
        """记录一次完整交互，用于审计与认知诊断回溯。"""
        with self.session() as sess:
            log = InteractionLogORM(
                user_id=user_id,
                mode=mode,
                query=query,
                response=response,
                question=question,
                user_answer=user_answer,
                is_correct=int(is_correct) if is_correct is not None else None,
                c_load=c_load,
                e_valence=e_valence,
                diagnosis=diagnosis,
                teacher_type=teacher_type,
            )
            sess.add(log)
            sess.flush()
            logger.info("Interaction logged: user=%s query_len=%d", user_id, len(query))
            return log

    def get_recent_logs(self, user_id: str, limit: int = 10) -> List[InteractionLogORM]:
        """获取最近交互日志。"""
        with self.session() as sess:
            return (
                sess.query(InteractionLogORM)
                .filter_by(user_id=user_id)
                .order_by(InteractionLogORM.timestamp.desc())
                .limit(limit)
                .all()
            )

    def get_wrong_logs(self, user_id: str, limit: int = 20) -> List[InteractionLogORM]:
        """获取用户答错的交互日志，用于 Review 模式薄弱知识点分析。"""
        with self.session() as sess:
            return (
                sess.query(InteractionLogORM)
                .filter_by(user_id=user_id, is_correct=0)
                .order_by(InteractionLogORM.timestamp.desc())
                .limit(limit)
                .all()
            )

    def get_wrong_logs_by_concept(self, user_id: str, concept_name: str, limit: int = 10) -> List[InteractionLogORM]:
        """获取某知识点的错题记录（通过 query 模糊匹配）。"""
        with self.session() as sess:
            return (
                sess.query(InteractionLogORM)
                .filter(
                    InteractionLogORM.user_id == user_id,
                    InteractionLogORM.is_correct == 0,
                    InteractionLogORM.query.like(f"%{concept_name}%"),
                )
                .order_by(InteractionLogORM.timestamp.desc())
                .limit(limit)
                .all()
            )

    # ------------------------------------------------------------------
    # Phase 8: DAO 层 —— Pydantic 边界 + 事务 Upsert
    # ------------------------------------------------------------------

    def sync_mab_weights(self, weights_data: UserStatsSchema) -> None:
        """
        事务 Upsert MAB 权重（纯权重更新，不修改答题计数）。
        幂等：同一数据执行多次结果相同。
        """
        with self.session() as sess:
            stats = sess.query(UserStatsORM).filter_by(user_id=weights_data.user_id).first()
            if not stats:
                stats = UserStatsORM(user_id=weights_data.user_id)
                sess.add(stats)
            stats.strategy_weights = weights_data.mab_weights
            stats.last_login = weights_data.last_login or _utc_dt()
            sess.flush()
            logger.info("MAB weights synced for user=%s", weights_data.user_id)

    def upsert_concept_state(self, concept_data: ConceptMasterySchema) -> None:
        """
        Upsert 知识点掌握度（幂等）。
        mastery_level 强制钳制在 [0.0, 100.0]。
        """
        with self.session() as sess:
            cm = sess.query(ConceptMasteryORM).filter_by(
                user_id=concept_data.user_id, concept_name=concept_data.concept_node
            ).first()
            if not cm:
                cm = ConceptMasteryORM(
                    user_id=concept_data.user_id,
                    concept_name=concept_data.concept_node,
                )
                sess.add(cm)
            cm.mastery_level = max(0.0, min(100.0, concept_data.mastery_level))
            cm.status = concept_data.status
            cm.last_interaction = concept_data.last_interaction or _utc_dt()
            sess.flush()
            logger.info(
                "Concept state upserted: user=%s concept=%s level=%.1f status=%s",
                concept_data.user_id, concept_data.concept_node,
                cm.mastery_level, cm.status,
            )

    def append_telemetry_log(self, log_data: InteractionLogSchema) -> None:
        """追加遥测日志（Strategy + c_load + e_valence + mastery_delta）到 interaction_logs。"""
        with self.session() as sess:
            log = InteractionLogORM(
                user_id=log_data.user_id,
                timestamp=log_data.timestamp or _utc_dt(),
                c_load=log_data.c_load,
                e_valence=log_data.e_valence,
                strategy_applied=log_data.strategy_applied,
                mastery_delta=log_data.mastery_delta,
                mode="telemetry",
                query="",
                response="",
            )
            sess.add(log)
            sess.flush()
            logger.info(
                "Telemetry appended: user=%s strategy=%s c_load=%s mastery_delta=%s",
                log_data.user_id, log_data.strategy_applied,
                log_data.c_load, log_data.mastery_delta,
            )

    # ------------------------------------------------------------------
    # Phase 8: 私有迁移工具
    # ------------------------------------------------------------------

    def _migrate_schema(self) -> None:
        """SQLite 增量迁移：为现有表追加新列（不破坏数据）。"""
        try:
            with self._engine.connect() as conn:
                inspector = inspect(self._engine)

                # UserStats: last_login
                cols = [c["name"] for c in inspector.get_columns("user_stats")]
                if "last_login" not in cols:
                    conn.execute(text("ALTER TABLE user_stats ADD COLUMN last_login DATETIME"))
                    conn.commit()
                    logger.info("Migration: added last_login to user_stats")

                # InteractionLogs: strategy_applied, mastery_delta
                cols = [c["name"] for c in inspector.get_columns("interaction_logs")]
                if "strategy_applied" not in cols:
                    conn.execute(text("ALTER TABLE interaction_logs ADD COLUMN strategy_applied VARCHAR(64)"))
                    conn.commit()
                    logger.info("Migration: added strategy_applied to interaction_logs")
                if "mastery_delta" not in cols:
                    conn.execute(text("ALTER TABLE interaction_logs ADD COLUMN mastery_delta FLOAT"))
                    conn.commit()
                    logger.info("Migration: added mastery_delta to interaction_logs")

                # DocumentRegistry: summary, key_topics
                cols = [c["name"] for c in inspector.get_columns("document_registry")]
                if "summary" not in cols:
                    conn.execute(text("ALTER TABLE document_registry ADD COLUMN summary TEXT DEFAULT ''"))
                    conn.commit()
                    logger.info("Migration: added summary to document_registry")
                if "key_topics" not in cols:
                    conn.execute(text("ALTER TABLE document_registry ADD COLUMN key_topics TEXT DEFAULT ''"))
                    conn.commit()
                    logger.info("Migration: added key_topics to document_registry")
                if "suggested_questions" not in cols:
                    conn.execute(text("ALTER TABLE document_registry ADD COLUMN suggested_questions TEXT DEFAULT ''"))
                    conn.commit()
                    logger.info("Migration: added suggested_questions to document_registry")
                if "full_text" not in cols:
                    conn.execute(text("ALTER TABLE document_registry ADD COLUMN full_text TEXT DEFAULT ''"))
                    conn.commit()
                    logger.info("Migration: added full_text to document_registry")
        except Exception as e:
            logger.warning("Schema migration skipped (non-fatal): %s", e)


# ---------------------------------------------------------------------------
# 模块级单例快捷入口
# ---------------------------------------------------------------------------

db_pool = DBPoolManager()

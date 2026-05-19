"""
database.py - SQLite + SQLAlchemy 数据持久层
启用 WAL 模式保障并发安全，使用 Pydantic 校验边界数据。
"""

import os
from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Text, ForeignKey, event, JSON
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session
from pydantic import BaseModel, Field, ConfigDict

# ---------------------------------------------------------------------------
# 1. 引擎与 WAL 模式
# ---------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "learning.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

ENGINE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(ENGINE_URL, connect_args={"check_same_thread": False})

# 启用 SQLite WAL 模式
@event.listens_for(engine, "connect")
def _enable_wal(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
    dbapi_conn.execute("PRAGMA synchronous=NORMAL")

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ---------------------------------------------------------------------------
# 2. SQLAlchemy ORM 模型
# ---------------------------------------------------------------------------

class UserStatsORM(Base):
    __tablename__ = "user_stats"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, unique=True, nullable=False, index=True)
    total_questions = Column(Integer, default=0)
    correct_count = Column(Integer, default=0)
    wrong_count = Column(Integer, default=0)
    strategy_weights = Column(JSON, default=dict)   # MAB 策略权重
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConceptMasteryORM(Base):
    __tablename__ = "concept_mastery"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    concept_name = Column(String, nullable=False)
    mastery_level = Column(Float, default=0.0)      # 0.0 ~ 100.0
    status = Column(String, default="learning")     # learning / mastered / struggling
    consecutive_wrong = Column(Integer, default=0)
    last_interaction = Column(DateTime, nullable=True)

    __table_args__ = (
        # 同一用户对同一知识点唯一
        # SQLAlchemy 2.0 写法，但为兼容旧版用 UniqueConstraint
    )


class InteractionLogORM(Base):
    __tablename__ = "interaction_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    mode = Column(String, default="adult")          # child / adult
    query = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    question = Column(Text, nullable=True)
    user_answer = Column(Text, nullable=True)
    is_correct = Column(Integer, nullable=True)       # 1 / 0 / NULL
    c_load = Column(Float, nullable=True)             # 认知负荷
    e_valence = Column(Float, nullable=True)          # 情感效价
    diagnosis = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


# ---------------------------------------------------------------------------
# 3. Pydantic 校验模型
# ---------------------------------------------------------------------------

class UserStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    total_questions: int = 0
    correct_count: int = 0
    wrong_count: int = 0
    strategy_weights: dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConceptMastery(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    concept_name: str
    mastery_level: float = Field(0.0, ge=0.0, le=100.0)
    status: str = "learning"
    consecutive_wrong: int = 0
    last_interaction: Optional[datetime] = None


class InteractionLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    mode: str = "adult"
    query: str
    response: str
    question: Optional[str] = None
    user_answer: Optional[str] = None
    is_correct: Optional[int] = None
    c_load: Optional[float] = None
    e_valence: Optional[float] = None
    diagnosis: Optional[str] = None
    timestamp: Optional[datetime] = None


# ---------------------------------------------------------------------------
# 4. 单例数据库管理器
# ---------------------------------------------------------------------------

class CognitiveDBManager:
    _instance: Optional["CognitiveDBManager"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        Base.metadata.create_all(bind=engine)

    def get_session(self) -> Session:
        return SessionLocal()

    # ------------------ UserStats ------------------
    def get_or_create_user_stats(self, user_id: str) -> UserStatsORM:
        with self.get_session() as db:
            stats = db.query(UserStatsORM).filter_by(user_id=user_id).first()
            if not stats:
                stats = UserStatsORM(user_id=user_id)
                db.add(stats)
                db.commit()
                db.refresh(stats)
            return stats

    def update_user_stats(self, user_id: str, correct: bool = None, weights: dict = None):
        with self.get_session() as db:
            stats = db.query(UserStatsORM).filter_by(user_id=user_id).first()
            if not stats:
                stats = UserStatsORM(user_id=user_id)
                db.add(stats)
            stats.total_questions += 1
            if correct is True:
                stats.correct_count += 1
            elif correct is False:
                stats.wrong_count += 1
            if weights is not None:
                stats.strategy_weights = weights
            db.commit()
            db.refresh(stats)
            return stats

    # ------------------ ConceptMastery ------------------
    def get_concept(self, user_id: str, concept_name: str) -> Optional[ConceptMasteryORM]:
        with self.get_session() as db:
            return db.query(ConceptMasteryORM).filter_by(
                user_id=user_id, concept_name=concept_name
            ).first()

    def update_concept_mastery(
        self,
        user_id: str,
        concept_name: str,
        mastery_delta: float = 0.0,
        correct: bool = None,
    ):
        with self.get_session() as db:
            cm = db.query(ConceptMasteryORM).filter_by(
                user_id=user_id, concept_name=concept_name
            ).first()
            if not cm:
                cm = ConceptMasteryORM(user_id=user_id, concept_name=concept_name)
                db.add(cm)

            cm.mastery_level = max(0.0, min(100.0, cm.mastery_level + mastery_delta))
            cm.last_interaction = datetime.utcnow()

            if correct is True:
                cm.consecutive_wrong = 0
                if cm.mastery_level >= 85.0:
                    cm.status = "mastered"
                else:
                    cm.status = "learning"
            elif correct is False:
                cm.consecutive_wrong += 1
                cm.status = "struggling"

            db.commit()
            db.refresh(cm)
            return cm

    def list_concepts(self, user_id: str) -> List[ConceptMasteryORM]:
        with self.get_session() as db:
            return db.query(ConceptMasteryORM).filter_by(user_id=user_id).all()

    # ------------------ InteractionLogs ------------------
    def log_interaction(
        self,
        user_id: str,
        query: str,
        response: str,
        mode: str = "adult",
        question: str = None,
        user_answer: str = None,
        is_correct: bool = None,
        c_load: float = None,
        e_valence: float = None,
        diagnosis: str = None,
    ) -> InteractionLogORM:
        with self.get_session() as db:
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
            )
            db.add(log)
            db.commit()
            db.refresh(log)
            return log

    def get_recent_logs(self, user_id: str, limit: int = 10) -> List[InteractionLogORM]:
        with self.get_session() as db:
            return (
                db.query(InteractionLogORM)
                .filter_by(user_id=user_id)
                .order_by(InteractionLogORM.timestamp.desc())
                .limit(limit)
                .all()
            )


# ---------------------------------------------------------------------------
# 5. 模块级便捷函数
# ---------------------------------------------------------------------------

db_manager = CognitiveDBManager()

def init_db():
    Base.metadata.create_all(bind=engine)

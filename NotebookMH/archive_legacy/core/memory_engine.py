"""
core/memory_engine.py - 认知记忆引擎 (Phase 3)

职责：
  - 在内存中维护活跃用户会话状态
  - 与 SQLite 认知数据库双向水合/脱水
  - 情绪自动推断、静默检测、答案匹配
  - 对话历史上下文截取

迁移自根目录 memory.py，去除根目录依赖，直接接入 NotebookMH 架构：
  - db_pool (utils/db_manager) 进行持久化
  - binder (utils/state_manager) 进行前端状态同步
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)

SILENCE_THRESHOLD = 30.0   # 秒，超过此时间视为思考空窗


# ---------------------------------------------------------------------------
# 1. 单会话状态
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    """单个用户的运行时认知态。"""
    user_id: str
    mode: str = "adult"          # child | adult
    teacher_type: str = "auto"   # socratic | strict | auto
    emotion_state: str = "专注"
    current_concept: Optional[str] = None
    current_question: Optional[str] = None
    current_answer: Optional[str] = None
    last_activity: float = field(default_factory=time.time)
    silence_triggered: bool = False
    consecutive_wrong: int = 0
    history: List[dict] = field(default_factory=list)

    def touch(self) -> None:
        self.last_activity = time.time()
        self.silence_triggered = False

    def record_exchange(self, role: str, content: str) -> None:
        self.history.append({
            "role": role,
            "content": content,
            "ts": datetime.now(timezone.utc).isoformat(),
        })
        if len(self.history) > 20:
            self.history = self.history[-20:]


# ---------------------------------------------------------------------------
# 2. 认知记忆引擎
# ---------------------------------------------------------------------------

class MemoryEngine:
    """
    认知记忆引擎 —— 管理活跃会话与数据库的双向同步。

    职责边界：
      - 内存态：SessionState（瞬时认知）
      - 持久态：SQLite user_stats / concept_mastery / interaction_logs
      - 前端态：GlobalState（teacher_type / emotion_state / user_mode）
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, SessionState] = {}

    def get_session(self, user_id: str) -> SessionState:
        """获取或创建会话，首次访问时从数据库水合。"""
        if user_id not in self._sessions:
            self._hydrate(user_id)
        return self._sessions[user_id]

    def _hydrate(self, user_id: str) -> None:
        """从 SQLite 加载用户学习进度到内存。"""
        db_pool.get_or_create_user_stats(user_id)
        state = SessionState(user_id=user_id)

        # 水合最近知识点
        concepts = db_pool.list_concepts(user_id)
        if concepts:
            latest = max(concepts, key=lambda c: c.last_interaction or datetime.min.replace(tzinfo=timezone.utc))
            state.current_concept = latest.concept_name
            state.consecutive_wrong = latest.consecutive_wrong

        # 水合前端人格态
        state.teacher_type = binder.get_state("teacher_type", "auto")
        state.emotion_state = binder.get_state("emotion_state", "专注")
        state.mode = binder.get_state("user_mode", "adult")

        self._sessions[user_id] = state
        logger.info("Session hydrated for user=%s concept=%s", user_id, state.current_concept)

    # ------------------------------------------------------------------
    # 状态同步
    # ------------------------------------------------------------------

    def set_mode(self, user_id: str, mode: str) -> None:
        sess = self.get_session(user_id)
        sess.mode = mode
        sess.touch()
        binder.update_state("user_mode", mode)

    def set_teacher_type(self, user_id: str, teacher_type: str) -> None:
        sess = self.get_session(user_id)
        sess.teacher_type = teacher_type
        sess.touch()
        binder.update_state("teacher_type", teacher_type)

    def set_emotion_state(self, user_id: str, emotion: str) -> None:
        sess = self.get_session(user_id)
        sess.emotion_state = emotion
        sess.touch()
        binder.update_state("emotion_state", emotion)

    def auto_infer_emotion(self, user_id: str) -> str:
        """根据会话状态推断用户情绪。"""
        sess = self.get_session(user_id)
        if sess.consecutive_wrong >= 2:
            return "挫败"
        if sess.consecutive_wrong == 1:
            return "困惑"
        if time.time() - sess.last_activity > SILENCE_THRESHOLD * 2:
            return "懒散"
        return "专注"

    # ------------------------------------------------------------------
    # 学习交互
    # ------------------------------------------------------------------

    def update_concept(self, user_id: str, concept_name: str) -> None:
        """切换当前知识点，重置连续错误计数。"""
        sess = self.get_session(user_id)
        sess.current_concept = concept_name
        sess.consecutive_wrong = 0
        sess.touch()

    def set_current_question(self, user_id: str, question: str, answer: str) -> None:
        sess = self.get_session(user_id)
        sess.current_question = question
        sess.current_answer = answer
        sess.silence_triggered = False
        sess.touch()

    def check_answer(self, user_id: str, user_answer: str) -> bool:
        """判断用户答案是否正确（宽松匹配），同步更新数据库。"""
        sess = self.get_session(user_id)
        if not sess.current_answer:
            return False

        correct = _fuzzy_match(user_answer, sess.current_answer)
        if correct:
            sess.consecutive_wrong = 0
        else:
            sess.consecutive_wrong += 1
        sess.touch()

        # 同步到数据库
        db_pool.update_user_stats(user_id, correct=correct)
        if sess.current_concept:
            delta = 10.0 if correct else -5.0
            db_pool.update_concept_mastery(
                user_id, sess.current_concept, mastery_delta=delta, correct=correct
            )

        # 自动推断并同步情绪
        inferred = self.auto_infer_emotion(user_id)
        self.set_emotion_state(user_id, inferred)

        logger.info(
            "Answer checked: user=%s correct=%s concept=%s emotion=%s",
            user_id, correct, sess.current_concept, inferred
        )
        return correct

    def is_silence(self, user_id: str) -> bool:
        """检测是否进入思考空窗（超过 SILENCE_THRESHOLD 秒未互动）。"""
        sess = self.get_session(user_id)
        if not sess.current_question:
            return False
        elapsed = time.time() - sess.last_activity
        return elapsed > SILENCE_THRESHOLD and not sess.silence_triggered

    def mark_silence_triggered(self, user_id: str) -> None:
        sess = self.get_session(user_id)
        sess.silence_triggered = True

    def get_history_context(self, user_id: str, max_turns: int = 5) -> str:
        """获取最近对话上下文，用于 prompt 增强。"""
        sess = self.get_session(user_id)
        recent = sess.history[-max_turns:]
        lines = [f"[{item['role']}] {item['content']}" for item in recent]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 日志审计
    # ------------------------------------------------------------------

    def log_exchange(
        self,
        user_id: str,
        query: str,
        response: str,
        question: Optional[str] = None,
        user_answer: Optional[str] = None,
        is_correct: Optional[bool] = None,
        c_load: Optional[float] = None,
        e_valence: Optional[float] = None,
        diagnosis: Optional[str] = None,
    ) -> None:
        """记录一次完整交互到 SQLite，同时更新内存历史。"""
        sess = self.get_session(user_id)
        sess.record_exchange("user", query)
        sess.record_exchange("assistant", response)

        db_pool.log_interaction(
            user_id=user_id,
            query=query,
            response=response,
            mode=sess.mode,
            question=question,
            user_answer=user_answer,
            is_correct=is_correct,
            c_load=c_load,
            e_valence=e_valence,
            diagnosis=diagnosis,
            teacher_type=sess.teacher_type,
        )


# ---------------------------------------------------------------------------
# 3. 简易答案匹配
# ---------------------------------------------------------------------------

def _fuzzy_match(user_ans: str, correct_ans: str) -> bool:
    """允许空格、标点和大小写差异的宽松匹配。"""
    def normalize(s: str) -> str:
        return "".join(c.lower() for c in s if c.isalnum())
    return normalize(user_ans) == normalize(correct_ans)


# ---------------------------------------------------------------------------
# 4. 模块级单例
# ---------------------------------------------------------------------------

_memory_singleton: Optional[MemoryEngine] = None


def get_memory_engine() -> MemoryEngine:
    """获取全局唯一的 MemoryEngine 实例。"""
    global _memory_singleton
    if _memory_singleton is None:
        _memory_singleton = MemoryEngine()
    return _memory_singleton

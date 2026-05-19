"""
memory.py - 用户会话状态与学习进度管理
在内存中维护活跃会话，并与数据库同步。
"""

import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from database import db_manager, ConceptMasteryORM
from prompt import UserMode
from teacher_profiles import TeacherType


# ---------------------------------------------------------------------------
# 1. 单会话状态
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    user_id: str
    mode: UserMode = UserMode.ADULT
    teacher_type: TeacherType = TeacherType.AUTO   # 当前教师角色
    emotion_state: str = ""                          # 用户情绪状态（如沮丧、懒散）
    current_concept: Optional[str] = None          # 当前正在讲解的知识点
    current_question: Optional[str] = None       # 当前待回答的题目
    current_answer: Optional[str] = None           # 当前题目的标准答案
    last_activity: float = field(default_factory=time.time)
    silence_triggered: bool = False                # 是否已触发主动提示
    consecutive_wrong: int = 0                     # 当前知识点连续答错次数
    history: List[dict] = field(default_factory=list)  # 最近对话记录

    def touch(self):
        self.last_activity = time.time()
        self.silence_triggered = False

    def record_exchange(self, role: str, content: str):
        self.history.append({
            "role": role,
            "content": content,
            "ts": datetime.utcnow().isoformat(),
        })
        if len(self.history) > 20:
            self.history = self.history[-20:]


# ---------------------------------------------------------------------------
# 2. 全局会话管理器
# ---------------------------------------------------------------------------

SILENCE_THRESHOLD = 30.0   # 秒，超过此时间视为思考空窗

class StateManager:
    """管理所有活跃用户的会话状态（内存 + 数据库水合）"""

    def __init__(self):
        self._sessions: Dict[str, SessionState] = {}

    def get_session(self, user_id: str) -> SessionState:
        if user_id not in self._sessions:
            self._hydrate(user_id)
        return self._sessions[user_id]

    def _hydrate(self, user_id: str):
        """从数据库加载用户学习进度到内存"""
        db_stats = db_manager.get_or_create_user_stats(user_id)
        state = SessionState(user_id=user_id)

        # 加载最近的知识点进度
        concepts: List[ConceptMasteryORM] = db_manager.list_concepts(user_id)
        if concepts:
            # 取最近互动过的知识点作为当前上下文
            latest = max(concepts, key=lambda c: c.last_interaction or datetime.min)
            state.current_concept = latest.concept_name
            state.consecutive_wrong = latest.consecutive_wrong

        self._sessions[user_id] = state

    def set_mode(self, user_id: str, mode: UserMode):
        sess = self.get_session(user_id)
        sess.mode = mode
        sess.touch()

    def set_teacher_type(self, user_id: str, teacher_type: TeacherType):
        sess = self.get_session(user_id)
        sess.teacher_type = teacher_type
        sess.touch()

    def set_emotion_state(self, user_id: str, emotion: str):
        sess = self.get_session(user_id)
        sess.emotion_state = emotion
        sess.touch()

    def auto_infer_emotion(self, user_id: str) -> str:
        """根据会话状态推断用户情绪"""
        sess = self.get_session(user_id)
        if sess.consecutive_wrong >= 2:
            return "挫败"
        if sess.consecutive_wrong == 1:
            return "困惑"
        # 无活跃互动 → 懒散（简化规则，可扩展）
        if time.time() - sess.last_activity > SILENCE_THRESHOLD * 2:
            return "懒散"
        return "专注"

    def update_concept(self, user_id: str, concept_name: str):
        sess = self.get_session(user_id)
        sess.current_concept = concept_name
        sess.consecutive_wrong = 0
        sess.touch()

    def set_current_question(self, user_id: str, question: str, answer: str):
        sess = self.get_session(user_id)
        sess.current_question = question
        sess.current_answer = answer
        sess.silence_triggered = False
        sess.touch()

    def check_answer(self, user_id: str, user_answer: str) -> bool:
        """简单判断对错（可扩展为更智能的语义匹配）"""
        sess = self.get_session(user_id)
        if not sess.current_answer:
            return False
        correct = _fuzzy_match(user_answer, sess.current_answer)
        if correct:
            sess.consecutive_wrong = 0
        else:
            sess.consecutive_wrong += 1
        sess.touch()
        return correct

    def is_silence(self, user_id: str) -> bool:
        """检测是否进入思考空窗"""
        sess = self.get_session(user_id)
        if not sess.current_question:
            return False
        elapsed = time.time() - sess.last_activity
        return elapsed > SILENCE_THRESHOLD and not sess.silence_triggered

    def mark_silence_triggered(self, user_id: str):
        sess = self.get_session(user_id)
        sess.silence_triggered = True

    def get_history_context(self, user_id: str, max_turns: int = 5) -> str:
        """获取最近对话上下文，用于 prompt 增强"""
        sess = self.get_session(user_id)
        recent = sess.history[-max_turns:]
        lines = []
        for item in recent:
            lines.append(f"[{item['role']}] {item['content']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 3. 简易答案匹配
# ---------------------------------------------------------------------------

def _fuzzy_match(user_ans: str, correct_ans: str) -> bool:
    """允许空格、标点和大小写差异的宽松匹配"""
    def normalize(s: str) -> str:
        return "".join(c.lower() for c in s if c.isalnum() or c.isdigit())
    return normalize(user_ans) == normalize(correct_ans)


# ---------------------------------------------------------------------------
# 4. 单例
# ---------------------------------------------------------------------------
state_manager = StateManager()

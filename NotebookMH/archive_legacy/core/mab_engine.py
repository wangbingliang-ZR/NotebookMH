"""
core/mab_engine.py - 多臂老虎机策略引擎 (Phase 2B Optimized)

职责：
  - 在线学习最优教学策略、难度、题型组合
  - Epsilon-Greedy + UCB 混合策略
  - 回报计算：答题正确率 × (1 - c_load) × 情绪正向系数

臂定义（Arms）：
  - strategy: socratic / strict
  - difficulty: easy / medium / hard
  - question_type: calculation / concept / application

零外部依赖，纯 Python 实现，可直接序列化到 SQLite JSON 字段。
"""

import logging
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. 臂定义
# ---------------------------------------------------------------------------

ARMS_STRATEGY = ["socratic", "strict"]
ARMS_DIFFICULTY = ["easy", "medium", "hard"]
ARMS_TYPE = ["calculation", "concept", "application"]

DEFAULT_EPSILON = 0.15   # 15% 探索率
DEFAULT_ALPHA = 1.0      # UCB 探索系数


# ---------------------------------------------------------------------------
# 2. 臂的回报追踪
# ---------------------------------------------------------------------------

@dataclass
class ArmStats:
    """单个臂的统计量。"""
    pulls: int = 0
    total_reward: float = 0.0

    @property
    def avg_reward(self) -> float:
        if self.pulls == 0:
            return 1.0  # 乐观初始化：未尝试过的臂给高初始值
        return self.total_reward / self.pulls

    def update(self, reward: float) -> None:
        self.pulls += 1
        self.total_reward += reward


# ---------------------------------------------------------------------------
# 3. MAB 策略引擎
# ---------------------------------------------------------------------------

class MABEngine:
    """
    多臂老虎机策略引擎。

    三路独立 MAB：
      - strategy_bandit: 选择教学策略
      - difficulty_bandit: 选择难度
      - type_bandit: 选择题型

    回报计算：
      reward = is_correct * (1 - c_load) * (0.5 + 0.5 * e_valence)
      其中：is_correct ∈ {0, 1}, c_load ∈ [0, 1], e_valence ∈ [-1, 1]
    """

    def __init__(
        self,
        epsilon: float = DEFAULT_EPSILON,
        alpha: float = DEFAULT_ALPHA,
        weights: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self.epsilon = epsilon
        self.alpha = alpha

        # 从外部 weights 恢复或新建
        if weights:
            self._strategy = self._deserialize(weights.get("strategy", {}))
            self._difficulty = self._deserialize(weights.get("difficulty", {}))
            self._qtype = self._deserialize(weights.get("type", {}))
        else:
            self._strategy = {a: ArmStats() for a in ARMS_STRATEGY}
            self._difficulty = {a: ArmStats() for a in ARMS_DIFFICULTY}
            self._qtype = {a: ArmStats() for a in ARMS_TYPE}

    # ------------------------------------------------------------------
    # 选择
    # ------------------------------------------------------------------

    def select_strategy(self) -> str:
        return self._select(self._strategy)

    def select_difficulty(self) -> str:
        return self._select(self._difficulty)

    def select_question_type(self) -> str:
        return self._select(self._qtype)

    def select_all(self) -> Dict[str, str]:
        """同时选择三路最优组合。"""
        return {
            "strategy": self.select_strategy(),
            "difficulty": self.select_difficulty(),
            "type": self.select_question_type(),
        }

    def _select(self, bandit: Dict[str, ArmStats]) -> str:
        """Epsilon-Greedy + UCB 混合选择。"""
        arms = list(bandit.keys())

        # Epsilon 探索
        if random.random() < self.epsilon:
            chosen = random.choice(arms)
            logger.debug("MAB explore: %s", chosen)
            return chosen

        # UCB 利用
        total_pulls = sum(a.pulls for a in bandit.values())
        best_arm = None
        best_score = -float("inf")

        for arm_name, stats in bandit.items():
            if stats.pulls == 0:
                # 未尝试过的臂优先
                score = float("inf")
            else:
                # UCB1 公式: avg_reward + alpha * sqrt(2 * ln(total) / pulls)
                exploration = self.alpha * math.sqrt(
                    2 * math.log(max(1, total_pulls)) / stats.pulls
                )
                score = stats.avg_reward + exploration

            if score > best_score:
                best_score = score
                best_arm = arm_name

        logger.debug("MAB exploit: %s (score=%.3f)", best_arm, best_score)
        return best_arm  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    def update(
        self,
        strategy: str,
        difficulty: str,
        qtype: str,
        is_correct: bool,
        c_load: Optional[float] = None,
        e_valence: Optional[float] = None,
    ) -> None:
        """根据一次交互结果更新三路 MAB。"""
        reward = self._compute_reward(is_correct, c_load, e_valence)

        self._strategy.get(strategy, ArmStats()).update(reward)
        self._difficulty.get(difficulty, ArmStats()).update(reward)
        self._qtype.get(qtype, ArmStats()).update(reward)

        logger.info(
            "MAB updated: strategy=%s difficulty=%s type=%s reward=%.3f",
            strategy, difficulty, qtype, reward,
        )

    @staticmethod
    def _compute_reward(
        is_correct: bool,
        c_load: Optional[float] = None,
        e_valence: Optional[float] = None,
    ) -> float:
        """计算单次交互的回报。"""
        correct = 1.0 if is_correct else 0.0
        load_penalty = max(0.0, 1.0 - (c_load or 0.5))
        emotion_boost = 0.5 + 0.5 * max(-1.0, min(1.0, e_valence or 0.0))
        return correct * load_penalty * emotion_boost

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def serialize(self) -> Dict[str, Dict[str, Any]]:
        """序列化为可存入 SQLite JSON 的字典。"""
        return {
            "strategy": self._serialize(self._strategy),
            "difficulty": self._serialize(self._difficulty),
            "type": self._serialize(self._qtype),
        }

    @staticmethod
    def _serialize(bandit: Dict[str, ArmStats]) -> Dict[str, Dict[str, float]]:
        return {
            name: {"pulls": s.pulls, "total_reward": s.total_reward}
            for name, s in bandit.items()
        }

    @staticmethod
    def _deserialize(raw: Dict[str, Dict[str, float]]) -> Dict[str, ArmStats]:
        result: Dict[str, ArmStats] = {}
        for name, data in raw.items():
            arm = ArmStats()
            arm.pulls = int(data.get("pulls", 0))
            arm.total_reward = float(data.get("total_reward", 0.0))
            result[name] = arm
        return result

    # ------------------------------------------------------------------
    # 报告
    # ------------------------------------------------------------------

    def report(self) -> Dict[str, Any]:
        """生成人类可读的 MAB 状态报告。"""
        return {
            "strategy": {name: {"pulls": s.pulls, "avg_reward": round(s.avg_reward, 3)}
                        for name, s in self._strategy.items()},
            "difficulty": {name: {"pulls": s.pulls, "avg_reward": round(s.avg_reward, 3)}
                          for name, s in self._difficulty.items()},
            "type": {name: {"pulls": s.pulls, "avg_reward": round(s.avg_reward, 3)}
                    for name, s in self._qtype.items()},
        }


# ---------------------------------------------------------------------------
# 4. 模块级单例
# ---------------------------------------------------------------------------

_mab_singleton: Optional[MABEngine] = None


def get_mab_engine(weights: Optional[Dict[str, Dict[str, Any]]] = None) -> MABEngine:
    """获取全局唯一的 MABEngine 实例。"""
    global _mab_singleton
    if _mab_singleton is None:
        _mab_singleton = MABEngine(weights=weights)
    elif weights is not None:
        # 支持热更新权重
        _mab_singleton = MABEngine(weights=weights)
    return _mab_singleton

"""
utils/evolutionary_strategy.py — 进化策略路由引擎 (Phase 6A)

职责：
  - UCB1 动态策略选择（Upper Confidence Bound Routing）
  - 认知收益奖励函数（Cognitive Reward Function）
  - 时间衰减（Time Decay）
  - 四象限安全过滤（Quadrant-to-Arm Mapping）

约束：
  - 纯数学函数，零 Streamlit 依赖
  - 便于单元测试
"""

import logging
import math
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────
# 1. 策略臂基因枚举
# ──────────────────────────────────────────────────────────────────────────


class StrategyArm(str, Enum):
    """四象限策略基因库 —— 每轮对话必须从中选一条臂拉动。"""

    SOCRATIC_PRESSURE = "Socratic_Pressure"
    FIRST_PRINCIPLES = "First_Principles"
    CONCRETE_ANALOGY = "Concrete_Analogy"
    PRAGMATIC_EXECUTION = "Pragmatic_Execution"


# ──────────────────────────────────────────────────────────────────────────
# 2. Pydantic 数据结构
# ──────────────────────────────────────────────────────────────────────────


class StrategyArmStats(BaseModel):
    """单条臂的实战数据：拉动次数 + 累积奖励。"""

    pulls: int = Field(default=0, ge=0)
    reward: float = Field(default=0.0)

    @field_validator("pulls", mode="before")
    @classmethod
    def _non_negative(cls, v: int) -> int:
        return max(int(v), 0)

    def pull(self, reward: float) -> "StrategyArmStats":
        """执行一次拉动，更新 stats。"""
        return StrategyArmStats(pulls=self.pulls + 1, reward=self.reward + reward)


class StrategyGenome(BaseModel):
    """用户认知策略基因库：维护四条臂的完整 stats。"""

    arms: Dict[StrategyArm, StrategyArmStats] = Field(default_factory=dict)

    def __init__(self, **data):
        super().__init__(**data)
        # 确保四条臂始终存在
        for arm in StrategyArm:
            if arm not in self.arms:
                self.arms[arm] = StrategyArmStats()

    def total_pulls(self) -> int:
        return sum(s.pulls for s in self.arms.values())

    def best_arm(self) -> StrategyArm:
        """返回当前经验收益最高的臂（用于展示，不用于选择）。"""
        best = max(
            self.arms.items(),
            key=lambda kv: (kv[1].reward / kv[1].pulls) if kv[1].pulls > 0 else 0.0,
        )
        return best[0]


# ──────────────────────────────────────────────────────────────────────────
# 3. 四象限安全过滤表
# ──────────────────────────────────────────────────────────────────────────

# 四象限 → 允许拉动的臂（安全约束）
ALLOWED_ARMS_BY_QUADRANT: Dict[str, List[StrategyArm]] = {
    "collapse": [StrategyArm.CONCRETE_ANALOGY, StrategyArm.FIRST_PRINCIPLES],
    "provocation": [StrategyArm.PRAGMATIC_EXECUTION, StrategyArm.SOCRATIC_PRESSURE],
    "socratic_pressure": [StrategyArm.SOCRATIC_PRESSURE, StrategyArm.PRAGMATIC_EXECUTION],
    "baseline": [
        StrategyArm.SOCRATIC_PRESSURE,
        StrategyArm.FIRST_PRINCIPLES,
        StrategyArm.CONCRETE_ANALOGY,
        StrategyArm.PRAGMATIC_EXECUTION,
    ],
}


# ──────────────────────────────────────────────────────────────────────────
# 4. UCB1 纯函数
# ──────────────────────────────────────────────────────────────────────────


def ucb1_score(
    reward: float,
    pulls: int,
    total_pulls: int,
    exploration_c: float = 1.5,
) -> float:
    """
    UCB1 置信上界分数。

    公式:  Score = (reward / pulls) + C * sqrt(ln(total_pulls) / pulls)

    边界:
      - pulls == 0   → 返回 +inf（强制探索未使用过的臂）
      - total_pulls == 0 → 返回 +inf（所有臂均未使用）

    Args:
        reward: 该臂的累积奖励。
        pulls: 该臂被拉动次数。
        total_pulls: 所有臂的总拉动次数。
        exploration_c: 探索系数 C，默认 1.5。

    Returns:
        float: UCB1 Score。
    """
    if pulls <= 0 or total_pulls <= 0:
        return float("inf")

    exploitation = reward / pulls
    exploration = exploration_c * math.sqrt(math.log(total_pulls) / pulls)
    return exploitation + exploration


def select_arm_ucb1(
    genome: StrategyGenome,
    quadrant: str = "baseline",
    exploration_c: float = 1.5,
) -> StrategyArm:
    """
    在允许的安全臂集合中，用 UCB1 选择最优策略臂。

    步骤:
      1. 根据 quadrant 过滤允许的臂
      2. 计算每个允许臂的 UCB1 Score
      3. 取最大 Score 的臂

    Args:
        genome: 用户的策略基因库。
        quadrant: 当前四象限分类。
        exploration_c: UCB1 探索系数。

    Returns:
        StrategyArm: 被选中的策略臂。
    """
    allowed = ALLOWED_ARMS_BY_QUADRANT.get(quadrant, list(StrategyArm))
    total = genome.total_pulls()

    scores: Dict[StrategyArm, float] = {}
    for arm in allowed:
        stats = genome.arms[arm]
        score = ucb1_score(
            reward=stats.reward,
            pulls=stats.pulls,
            total_pulls=total,
            exploration_c=exploration_c,
        )
        scores[arm] = score
        logger.debug("UCB1 score: arm=%s pulls=%d reward=%.2f score=%.3f", arm, stats.pulls, stats.reward, score)

    best = max(scores.items(), key=lambda kv: kv[1])
    logger.info("UCB1 selected: arm=%s score=%.3f (quadrant=%s)", best[0], best[1], quadrant)
    return best[0]


# ──────────────────────────────────────────────────────────────────────────
# 5. 认知收益奖励计算器 (NeuralRewardCalculator)
# ──────────────────────────────────────────────────────────────────────────


class RewardBreakdown(BaseModel):
    """奖励计算的完整拆解，供可解释审计使用。

    Attributes:
        mastery_term: α × Mastery_Delta。
        valence_term: β × tanh(k × ΔE_valence)。
        overload_penalty: 认知负荷过载惩罚项。
        base_reward: 截断前的原始奖励值。
        final_reward: [-100, 100] 截断后的最终奖励值。
        selected_arm: 当前策略臂名，用于日志追踪。
    """

    mastery_term: float
    valence_term: float
    overload_penalty: float
    base_reward: float
    final_reward: float
    selected_arm: str = "N/A"


class NeuralRewardCalculator:
    """无状态认知奖励计算器（静态方法类）。

    核心算法约束:
      - 情绪效价非线性断崖: tanh(k × ΔE)，k = 2.5。
      - 过载硬阈值 + clamp。
      - 最终截断: [-100, 100] 防止 UCB1 污染。
      - 艾宾浩斯衰减: mastery × 0.98^(Δt/24)。
      - 严格 O(1)，无遍历。
    """

    # 硬编码陡峭系数
    _VALENCE_STEEPNESS: float = 2.5
    # 截断边界
    _REWARD_CLAMP: tuple = (-100.0, 100.0)
    _CLAMP_DELTA_E: tuple = (-10.0, 10.0)
    _CLAMP_C_LOAD: tuple = (0.0, 1.0)
    _CLAMP_MASTERY: tuple = (0.0, 100.0)
    _MAX_HOURS: float = 87600.0  # ~10年

    # ------------------------------------------------------------------
    # 边界工具
    # ------------------------------------------------------------------

    @staticmethod
    def clamp(value: float, lower: float, upper: float) -> float:
        """钳制浮点数到闭区间 [lower, upper]。"""
        return max(lower, min(upper, value))

    # ------------------------------------------------------------------
    # 情绪效价非线性项 (Tanh Cliff)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_valence_reward(delta_e_valence: float, beta: float = 0.8) -> float:
        """
        情绪效价的非线性奖励项。

        公式:
            R_val = β × tanh(k × clamp(ΔE_valence, -10, 10))

        其中 k = 2.5，使得细微波动被平滑，负向情绪超过阈值时断崖式下跌。

        Args:
            delta_e_valence: 情绪效价变化量。
            beta: 情绪权重系数。

        Returns:
            float: 非线性情绪奖励项，范围 [-β, +β]。
        """
        safe = NeuralRewardCalculator.clamp(
            delta_e_valence, *NeuralRewardCalculator._CLAMP_DELTA_E
        )
        return beta * math.tanh(NeuralRewardCalculator._VALENCE_STEEPNESS * safe)

    # ------------------------------------------------------------------
    # 主计算
    # ------------------------------------------------------------------

    @staticmethod
    def calculate(
        mastery_delta: float,
        delta_e_valence: float,
        c_load: float,
        selected_arm: str = "N/A",
        alpha: float = 1.2,
        beta: float = 0.8,
        gamma: float = 1.0,
        overload_threshold: float = 0.85,
    ) -> RewardBreakdown:
        """
        计算认知奖励的完整拆解。

        公式:
            mastery_term = α × Mastery_Delta
            valence_term = β × tanh(k × clamp(ΔE_valence))
            penalty      = γ × c_load   (if c_load >= overload_threshold)
            base_reward  = mastery_term + valence_term - penalty
            final_reward = clamp(base_reward, -100, 100)

        Args:
            mastery_delta: 知识点掌握度变化量。
            delta_e_valence: 情绪效价变化量。
            c_load: 当前认知负荷 [0.0, 1.0]。
            selected_arm: 策略臂名（用于日志追踪）。
            alpha, beta, gamma: 三项权重。
            overload_threshold: 过载判定阈值。

        Returns:
            RewardBreakdown: 包含各分项和最终奖励的结构化结果。
        """
        # Mastery 项
        mastery_term = alpha * mastery_delta

        # 情绪效价非线性项 (Tanh Cliff)
        valence_term = NeuralRewardCalculator.compute_valence_reward(delta_e_valence, beta)

        # 认知负荷过载惩罚
        safe_c_load = NeuralRewardCalculator.clamp(c_load, *NeuralRewardCalculator._CLAMP_C_LOAD)
        penalty = gamma * safe_c_load if safe_c_load >= overload_threshold else 0.0

        # 原始奖励
        base_reward = mastery_term + valence_term - penalty

        # 最终截断（防止 UCB1 污染）
        final_reward = NeuralRewardCalculator.clamp(base_reward, *NeuralRewardCalculator._REWARD_CLAMP)

        # 极客级结构化日志
        logger.info(
            "[NEURAL_CALC] ΔMastery: %+.2f | ΔValence(Tanh): %+.2f | Base_Reward: %.2f | "
            "Final_Weight_Update: %s -> %.2f",
            mastery_term, valence_term, base_reward, selected_arm, final_reward,
        )

        return RewardBreakdown(
            mastery_term=mastery_term,
            valence_term=valence_term,
            overload_penalty=penalty,
            base_reward=base_reward,
            final_reward=final_reward,
            selected_arm=selected_arm,
        )

    # ------------------------------------------------------------------
    # 艾宾浩斯连续衰减 (O(1))
    # ------------------------------------------------------------------

    @staticmethod
    def apply_time_decay(
        mastery_level: float,
        last_timestamp: Optional[datetime],
        now: Optional[datetime] = None,
    ) -> float:
        """
        连续艾宾浩斯遗忘衰减。

        公式:
            Δt(hours) = max((now - last_timestamp).total_seconds() / 3600, 0)
            Δt = min(Δt, 87600)   # 十年上限保护
            Mastery_current = Mastery_db × 0.98^(Δt / 24.0)

        边界:
            - Δt < 0 → 强制归零（时钟偏移保护）
            - 结果 clamp 到 [0, 100]

        复杂度: O(1)。

        Args:
            mastery_level: 数据库中的原始掌握度。
            last_timestamp: 上次交互时间。
            now: 当前时间（默认 utcnow）。

        Returns:
            float: 衰减后的当前掌握度。
        """
        if not last_timestamp:
            return NeuralRewardCalculator.clamp(mastery_level, *NeuralRewardCalculator._CLAMP_MASTERY)

        if now is None:
            now = datetime.now(timezone.utc)

        delta_seconds = (now - last_timestamp).total_seconds()
        hours = max(delta_seconds / 3600.0, 0.0)
        hours = min(hours, NeuralRewardCalculator._MAX_HOURS)

        decayed = mastery_level * (0.98 ** (hours / 24.0))
        return NeuralRewardCalculator.clamp(decayed, *NeuralRewardCalculator._CLAMP_MASTERY)


# ──────────────────────────────────────────────────────────────────────────
# 5b. 兼容包装器 (backward-compatible)
# ──────────────────────────────────────────────────────────────────────────


def compute_cognitive_reward(
    mastery_delta: float,
    delta_e_valence: float,
    c_load: float,
    selected_arm: str = "N/A",
    alpha: float = 1.2,
    beta: float = 0.8,
    gamma: float = 1.0,
    overload_threshold: float = 0.85,
) -> float:
    """
    兼容包装器：返回最终奖励值（float）。

    内部委托 NeuralRewardCalculator.calculate()，保证所有新算法
    （Tanh 非线性、截断保护、结构化日志）自动生效。
    """
    return NeuralRewardCalculator.calculate(
        mastery_delta=mastery_delta,
        delta_e_valence=delta_e_valence,
        c_load=c_load,
        selected_arm=selected_arm,
        alpha=alpha,
        beta=beta,
        gamma=gamma,
        overload_threshold=overload_threshold,
    ).final_reward


# ──────────────────────────────────────────────────────────────────────────
# 6. 时间衰减 (Time Decay)
# ──────────────────────────────────────────────────────────────────────────


def apply_time_decay(
    genome: StrategyGenome,
    decay: float = 0.95,
) -> StrategyGenome:
    """
    对所有臂的累积 reward 乘以衰减系数。
    pulls 不变（它是计数，不是时间敏感值）。

    衰减后，低频 / 过时臂的 exploitation 项自然降低，
    系统会重新探索新策略。

    Args:
        genome: 策略基因库。
        decay: 衰减系数，默认 0.95。

    Returns:
        StrategyGenome: 衰减后的新基因库。
    """
    new_arms: Dict[StrategyArm, StrategyArmStats] = {}
    for arm, stats in genome.arms.items():
        new_reward = stats.reward * decay
        new_arms[arm] = StrategyArmStats(pulls=stats.pulls, reward=new_reward)
        logger.debug("Decay: arm=%s old_reward=%.2f new_reward=%.2f", arm, stats.reward, new_reward)
    return StrategyGenome(arms=new_arms)


# ──────────────────────────────────────────────────────────────────────────
# 7. 序列化 / 反序列化辅助（用于 DB 存储）
# ──────────────────────────────────────────────────────────────────────────


def genome_to_dict(genome: StrategyGenome) -> dict:
    """将 StrategyGenome 序列化为扁平字典，便于存入 JSON 字段。"""
    return {
        arm.value: {"pulls": stats.pulls, "reward": stats.reward}
        for arm, stats in genome.arms.items()
    }


def genome_from_dict(raw: dict) -> StrategyGenome:
    """从扁平字典重建 StrategyGenome。"""
    arms: Dict[StrategyArm, StrategyArmStats] = {}
    for key, val in raw.items():
        try:
            arm = StrategyArm(key)
            arms[arm] = StrategyArmStats(
                pulls=int(val.get("pulls", 0)),
                reward=float(val.get("reward", 0.0)),
            )
        except (ValueError, TypeError):
            logger.warning("Ignore unknown arm key in genome dict: %s", key)
    return StrategyGenome(arms=arms)

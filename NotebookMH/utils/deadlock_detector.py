"""
utils/deadlock_detector.py - 认知死锁检测器 (Phase 5B Guardian)

职责：
  - 轻量级文本相似度计算（difflib.SequenceMatcher + Jaccard）
  - 复合死锁判定：重复输入 × 高认知负荷 × 学习/测验模式
  - 零 Streamlit 依赖，纯工具函数

约束：
  - 不引入任何 NLP 模型
  - 不 import streamlit
"""

import difflib
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# 默认阈值常量
DEFAULT_SIMILARITY_THRESHOLD = 0.75
DEFAULT_C_LOAD_THRESHOLD = 0.80
DEADLOCK_INPUT_WINDOW = 3


# ---------------------------------------------------------------------------
# 1. 文本相似度
# ---------------------------------------------------------------------------

def sequence_similarity(a: str, b: str) -> float:
    """
    基于 difflib.SequenceMatcher 的字符级相似度。
    返回值 0.0 ~ 1.0。
    """
    if not a.strip() or not b.strip():
        return 0.0
    return difflib.SequenceMatcher(None, a.strip(), b.strip()).ratio()


def jaccard_similarity(a: str, b: str) -> float:
    """
    基于集合词频的 Jaccard 相似度。
    将文本分词后计算交集/并集。
    """
    if not a.strip() or not b.strip():
        return 0.0
    # 简单分词：按空格和标点拆分，取长度>=2的词
    def _tokenize(s: str) -> set:
        import re
        tokens = re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]{2,}", s.lower())
        return set(tokens)

    set_a = _tokenize(a)
    set_b = _tokenize(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def blended_similarity(a: str, b: str) -> float:
    """
    混合相似度：SequenceMatcher(0.6) + Jaccard(0.4)。
    兼顾字符级连续性和语义重叠。
    """
    seq_sim = sequence_similarity(a, b)
    jac_sim = jaccard_similarity(a, b)
    return seq_sim * 0.6 + jac_sim * 0.4


# ---------------------------------------------------------------------------
# 2. 重复输入检测
# ---------------------------------------------------------------------------

def recent_inputs_are_repetitive(
    inputs: List[str],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> bool:
    """
    判断最近 N 次输入是否构成重复死锁。

    判定规则：
      - 必须至少 N 次输入
      - 所有两两组合的相似度均 >= threshold
      - 使用 min(pairwise) 而非 average，防止两个像样本拉高均值

    Args:
        inputs: 最近用户输入列表（已按时间排序，最新在最后）。
        threshold: 相似度阈值，默认 0.75。

    Returns:
        bool: True 表示构成重复死锁。
    """
    window = inputs[-DEADLOCK_INPUT_WINDOW:]
    if len(window) < DEADLOCK_INPUT_WINDOW:
        return False

    pairwise: List[float] = []
    for i in range(len(window)):
        for j in range(i + 1, len(window)):
            sim = blended_similarity(window[i], window[j])
            pairwise.append(sim)
            logger.debug("sim(%s, %s) = %.3f", window[i][:20], window[j][:20], sim)

    if not pairwise:
        return False

    min_sim = min(pairwise)
    logger.info(
        "Repetitive check: window=%d pairwise=%d min_sim=%.3f",
        len(window), len(pairwise), min_sim,
    )
    return min_sim >= threshold


# ---------------------------------------------------------------------------
# 3. 复合死锁判定
# ---------------------------------------------------------------------------

def should_trigger_deadlock(
    recent_inputs: List[str],
    c_load: float,
    mode: str,
    similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    c_load_threshold: float = DEFAULT_C_LOAD_THRESHOLD,
) -> bool:
    """
    复合死锁判定 —— 必须同时满足三条件：
      a) 最近 N 次输入两两相似度 >= threshold
      b) c_load >= c_load_threshold
      c) mode 为 'learning' 或 'quizzing'

    Args:
        recent_inputs: 最近用户输入列表。
        c_load: 当前认知负荷 (0.0~1.0)。
        mode: 当前认知模式字符串。
        similarity_threshold: 输入相似度阈值。
        c_load_threshold: 认知负荷阈值。

    Returns:
        bool: True 表示应触发死锁接管。
    """
    # 条件 a：重复输入
    repetitive = recent_inputs_are_repetitive(recent_inputs, similarity_threshold)
    if not repetitive:
        return False

    # 条件 b：高认知负荷
    if c_load < c_load_threshold:
        return False

    # 条件 c：学习/测验高压模式
    if mode not in ("learning", "quizzing"):
        return False

    logger.warning(
        "DEADLOCK TRIGGERED: c_load=%.2f mode=%s inputs=%s",
        c_load, mode, recent_inputs[-DEADLOCK_INPUT_WINDOW:],
    )
    return True


def should_trigger_deadlock_from_state(
    recent_inputs: List[str],
    neural_state: Optional[dict] = None,
    mode: str = "learning",
) -> bool:
    """
    从 st.session_state 风格的字典中读取 c_load，执行复合判定。

    Args:
        recent_inputs: 最近用户输入。
        neural_state: current_neural_state 字典（或 None）。
        mode: 当前模式。

    Returns:
        bool: 是否触发死锁。
    """
    c_load = 0.0
    if neural_state and isinstance(neural_state, dict):
        c_load = float(neural_state.get("c_load", 0.0))
    return should_trigger_deadlock(recent_inputs, c_load, mode)

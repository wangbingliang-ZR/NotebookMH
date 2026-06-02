"""
utils/state_hydration.py — 物理层与状态机的热水合协议 (Phase 8)

职责：
  - 在 Streamlit 初始化阶段，将硬盘认知数据水合到 session_state
  - 幂等：重复执行不产生副作用
  - Genesis：首次启动时初始化默认认知状态

约束：
  - 仅在 app.py 顶部调用，UI 渲染前完成
  - Streamlit 导入在函数内部（避免非 UI 运行时出错）
  - 所有 DB 读取经过 Pydantic Schema 校验
"""

import logging
import sys
from typing import Any, Dict

from utils.db_manager import ConceptMasterySchema, UserStatsSchema, db_pool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Genesis 默认配置
# ---------------------------------------------------------------------------

_DEFAULT_MAB_WEIGHTS: Dict[str, Any] = {
    "strategy": {"socratic": 1.0, "direct": 1.0},
    "difficulty": {"easy": 1.0, "medium": 1.0, "hard": 1.0},
    "type": {"concept": 1.0, "application": 1.0, "analysis": 1.0},
    "evolutionary_prompt_stats": {
        "Socratic_Pressure": {"pulls": 0, "reward": 0.0},
        "First_Principles": {"pulls": 0, "reward": 0.0},
        "Concrete_Analogy": {"pulls": 0, "reward": 0.0},
        "Pragmatic_Execution": {"pulls": 0, "reward": 0.0},
    },
}


# ---------------------------------------------------------------------------
# 热水合入口
# ---------------------------------------------------------------------------


def hydrate_state_from_disk(user_id: str = "anonymous") -> None:
    """
    在任何 UI 渲染前，将硬盘认知数据水合到 session_state。

    流程：
      1. 检查 hydrated flag，已水合则直接 return（幂等）
      2. 读取 UserStats → 若为空则 Genesis
      3. 读取 ConceptMastery → 水合概念图谱
      4. 写回 session_state 与 binder 命名空间
      5. stdout 打印冷峻启动日志
    """
    try:
        import streamlit as st
    except ImportError:
        return

    if st.session_state.get("hydrated"):
        return

    # ── 读取用户统计 ──────────────────────────────
    stats_orm = db_pool.get_or_create_user_stats(user_id)
    weights = stats_orm.strategy_weights or {}

    # Genesis：首次启动，写入默认权重
    if not weights:
        weights = _DEFAULT_MAB_WEIGHTS.copy()
        db_pool.sync_mab_weights(
            UserStatsSchema(user_id=user_id, mab_weights=weights)
        )
        sys.stdout.write(
            f"[DB_CORE] Genesis triggered for user={user_id}. Default weights seeded.\n"
        )
        from utils.ui_renderer import push_system_toast
        push_system_toast("[SYS_INIT] 认知数据库已建立。神经链路在线。", icon="🧬")

    # ── 水合到 session_state ─────────────────────
    st.session_state["user_id"] = user_id
    st.session_state["mab_weights"] = weights
    st.session_state["nb_mh_last_mastery_level"] = 50.0  # 默认值
    st.session_state["nb_mh_last_mastery_delta"] = 0.0

    # 同时写入 binder 命名空间，确保前端通过 binder.get_state("user_id") 能读取
    from utils.state_manager import binder
    binder.update_state("user_id", user_id)

    # ── 知识点图谱水合 ────────────────────────────
    concepts = db_pool.list_concepts(user_id)
    concept_map: Dict[str, Dict[str, Any]] = {}
    for c in concepts:
        # 经过 Pydantic 边界校验
        schema = ConceptMasterySchema.model_validate(c)
        concept_map[schema.concept_node] = {
            "mastery_level": schema.mastery_level,
            "status": schema.status,
            "consecutive_wrong": schema.consecutive_wrong,
        }
    st.session_state["concept_mastery"] = concept_map

    # ── 标记水合完成 ──────────────────────────────
    st.session_state["hydrated"] = True
    sys.stdout.write("[DB_CORE] Cognitive Vault Mounted. WAL Mode Active.\n")

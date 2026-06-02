"""
frontend/neural_panel.py - 神经中枢遥测面板 (Phase 6)

职责：
  - 展示 UnifiedNeuralCore 实时评估的 current_neural_state
  - 展示用户认知画像（mastery、正确率、连续错误）
  - 展示进化策略基因库（4 臂 pulls/reward/UCB1 score）
  - 提供 state_sink callback 将 NeuralEvaluation 写入 st.session_state
  - 与 visual_engine / cognitive_panel 联动

严禁在 app.py 中写入具体 UI 逻辑。
"""

import json
import logging
from typing import Any, Dict, Optional

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from core.llm_engine import NeuralEvaluation, get_neural_core
from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)

_SSK_NEURAL_STATE = "nb_mh_current_neural_state"


# ---------------------------------------------------------------------------
# 公共渲染接口
# ---------------------------------------------------------------------------

def render() -> None:
    """渲染神经中枢遥测面板。"""
    if st is None:
        return

    st.divider()
    st.subheader("🧠 神经中枢遥测 (Phase 6)")

    user_id = binder.get_state("user_id", "anonymous")

    # ── 四象限神经态仪表 ──────────────────────────────────
    neural_state: Optional[Dict[str, Any]] = st.session_state.get(_SSK_NEURAL_STATE)
    if neural_state:
        _render_neural_dashboard(neural_state)
    else:
        st.info("神经态尚未初始化。发起一次问答后自动评估。")

    # ── 进化策略基因库 ───────────────────────────────────
    st.divider()
    st.caption("🧬 进化策略基因库 (UCB1)")
    _render_evolutionary_genome(user_id, neural_state)

    # ── 用户认知画像速览 ──────────────────────────────────
    st.divider()
    st.caption("🧬 用户认知画像")
    _render_cognitive_profile(user_id)

    # ── 状态同步按钮 ─────────────────────────────────────
    if st.button("🔄 强制同步神经态 → Visual", key="btn_sync_neural"):
        _sync_to_visual()
        st.success("已同步")


def get_state_sink():
    """返回可用于 UnifiedNeuralCore.generate_response 的 state_sink 回调。"""
    def _sink(evaluation: NeuralEvaluation) -> None:
        if st is None:
            return
        st.session_state[_SSK_NEURAL_STATE] = evaluation.model_dump()
        # 同时同步到 binder（供 visual_engine 消费）
        binder.update_state("c_load", evaluation.c_load)
        binder.update_state("e_valence", evaluation.e_valence)
        binder.update_state("emotion_state", _valence_to_emotion(evaluation.e_valence))
        # Phase 7: 遥测事件注入
        from utils.telemetry_events import append_telemetry_event
        append_telemetry_event(
            f"c_load={evaluation.c_load:.2f} e_valence={evaluation.e_valence:+.2f} quadrant={evaluation.quadrant}",
            level="INFO",
        )
        logger.info(
            "Neural state synced: c_load=%.2f e_valence=%.2f quadrant=%s",
            evaluation.c_load, evaluation.e_valence, evaluation.quadrant,
        )
    return _sink


# ---------------------------------------------------------------------------
# 内部渲染
# ---------------------------------------------------------------------------

def _render_neural_dashboard(state: Dict[str, Any]) -> None:
    """渲染四象限神经态仪表。"""
    c_load = state.get("c_load", 0.5)
    e_valence = state.get("e_valence", 0.0)
    diagnosis = state.get("diagnosis", "neutral")
    quadrant = state.get("quadrant", "baseline")
    strategy = state.get("strategy", "base_learning")

    # 状态徽章
    emoji_map = {
        "collapse": "🚨",
        "provocation": "⚡",
        "socratic_pressure": "🔥",
        "baseline": "🟢",
    }
    badge = emoji_map.get(quadrant, "⚪")

    cols = st.columns(4)
    with cols[0]:
        st.metric(label=f"{badge} 象限", value=quadrant.upper())
    with cols[1]:
        st.metric(label="策略", value=strategy)
    with cols[2]:
        st.metric(label="认知负荷", value=f"{c_load:.2f}")
    with cols[3]:
        st.metric(label="情绪效价", value=f"{e_valence:+.2f}")

    st.caption(f"诊断: {diagnosis}")

    # 四象限位置图（简化：两个 progress bar）
    col_a, col_b = st.columns(2)
    with col_a:
        st.progress(min(c_load, 1.0), text=f"c_load 轴: {c_load:.2f}")
    with col_b:
        # e_valence -1~+1 映射到 0~1
        val_pos = (e_valence + 1.0) / 2.0
        st.progress(val_pos, text=f"e_valence 轴: {e_valence:+.2f}")


def _render_cognitive_profile(user_id: str) -> None:
    """渲染用户认知画像速览。"""
    stats = db_pool.get_or_create_user_stats(user_id)
    concepts = db_pool.list_concepts(user_id)

    total = stats.total_questions or 0
    correct = stats.correct_count or 0
    accuracy = (correct / total * 100) if total > 0 else 0.0

    # 查找最近知识点
    latest_concept = None
    if concepts:
        from datetime import datetime, timezone
        latest_concept = max(
            concepts,
            key=lambda c: c.last_interaction or datetime.min.replace(tzinfo=timezone.utc),
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(label="总题数", value=total)
    with col2:
        st.metric(label="正确率", value=f"{accuracy:.1f}%")
    with col3:
        cw = latest_concept.consecutive_wrong if latest_concept else 0
        st.metric(label="连续错误", value=cw)

    if latest_concept:
        st.caption(
            f"最近知识点: **{latest_concept.concept_name}**  掌握度: {latest_concept.mastery_level:.0f}/100"
        )


def _sync_to_visual() -> None:
    """将 current_neural_state 同步到 binder，供 visual_engine 读取。"""
    state = st.session_state.get(_SSK_NEURAL_STATE)
    if not state:
        return
    c_load = state.get("c_load", 0.5)
    e_valence = state.get("e_valence", 0.0)
    binder.update_state("c_load", c_load)
    binder.update_state("e_valence", e_valence)
    binder.update_state("emotion_state", _valence_to_emotion(e_valence))


def _render_evolutionary_genome(user_id: str, neural_state: Optional[Dict[str, Any]]) -> None:
    """渲染 4 臂进化遥测：pulls / reward / UCB1 score。"""
    if st is None:
        return

    # 从 DB 读取 genome
    genome_data: Optional[Dict[str, Any]] = None
    try:
        stats = db_pool.get_or_create_user_stats(user_id)
        raw_weights = stats.weights or "{}"
        weights = json.loads(raw_weights) if isinstance(raw_weights, str) else (raw_weights or {})
        genome_data = weights.get("evolutionary_prompt_stats")
    except Exception:
        pass

    if not genome_data:
        st.caption("策略基因库尚未初始化。完成一次测验后开始进化。")
        return

    # 当前选中的臂（来自 neural_state）
    current_arm = neural_state.get("strategy", "") if neural_state else ""

    # 导入 UCB1 计算
    try:
        from utils.evolutionary_strategy import ucb1_score
    except ImportError:
        ucb1_score = None  # type: ignore

    # 计算总 pulls
    total_pulls = sum(int(v.get("pulls", 0)) for v in genome_data.values())

    # 渲染每条臂
    for arm_name, data in genome_data.items():
        pulls = int(data.get("pulls", 0))
        reward = float(data.get("reward", 0.0))
        avg = reward / pulls if pulls > 0 else 0.0

        # UCB1 score
        score = 0.0
        if ucb1_score and pulls > 0 and total_pulls > 0:
            score = ucb1_score(reward, pulls, total_pulls, exploration_c=1.5)

        is_current = arm_name == current_arm
        header = f"{'👉 ' if is_current else ''}{arm_name}"
        if is_current:
            st.markdown(f"**{header}**")
        else:
            st.caption(header)

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(label="拉动", value=pulls)
        with col2:
            st.metric(label="累计收益", value=f"{reward:.1f}")
        with col3:
            if score:
                st.metric(label="UCB1 Score", value=f"{score:.2f}")
            else:
                st.metric(label="平均收益", value=f"{avg:.2f}")

        if is_current:
            st.progress(min(avg if avg > 0 else 0.3, 1.0), text=f"当前选中臂: {arm_name}")

    st.caption(f"总拉动次数: {total_pulls}")


def _valence_to_emotion(e_valence: float) -> str:
    """简单映射效价到情绪标签。"""
    if e_valence < -0.5:
        return "挫败"
    if e_valence < -0.2:
        return "困惑"
    if e_valence > 0.5:
        return "专注"
    return "专注"

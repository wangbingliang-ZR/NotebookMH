"""
frontend/guardian_monitor.py - GuardianMonitor 认知死锁接管 (Phase 5B)

职责：
  - 全息遥测侧边栏：实时展示神经态 c_load / e_valence
  - 死锁检测与接管：复合条件触发 → UI 强制阻断
  - 唯一恢复按钮：降维重构 → 输出极简类比 → 解除死锁

约束：
  - 允许 import streamlit（frontend 职责）
  - 死锁检测调用 utils.deadlock_detector
"""

import logging
from typing import Any, Dict, List, Optional

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from utils.deadlock_detector import should_trigger_deadlock_from_state
from utils.state_manager import binder

logger = logging.getLogger(__name__)

# Session state 键名常量
_SSK_RECENT_INPUTS = "nb_mh_guardian_recent_inputs"
_SSK_DEADLOCKED = "nb_mh_guardian_is_deadlocked"
_SSK_RECOVERY_MSG = "nb_mh_guardian_recovery_msg"
_SSK_COGNITIVE_MODE = "nb_mh_cognitive_state"  # 与 cognitive_panel 共用


# ---------------------------------------------------------------------------
# 公共 API：输入记录 + 死锁检测
# ---------------------------------------------------------------------------

def record_user_input(text: str) -> None:
    """记录一次用户输入，用于死锁检测窗口。"""
    if st is None:
        return
    if _SSK_RECENT_INPUTS not in st.session_state:
        st.session_state[_SSK_RECENT_INPUTS] = []
    st.session_state[_SSK_RECENT_INPUTS].append(text.strip())
    # 只保留最近 10 条
    if len(st.session_state[_SSK_RECENT_INPUTS]) > 10:
        st.session_state[_SSK_RECENT_INPUTS] = st.session_state[_SSK_RECENT_INPUTS][-10:]


def evaluate_deadlock() -> bool:
    """
    评估当前是否应触发死锁。
    若触发，设置 is_deadlocked = True 并返回 True。
    调用方应在返回 True 时立即 st.rerun()。
    """
    if st is None:
        return False

    # 已处于死锁状态则不重复触发
    if st.session_state.get(_SSK_DEADLOCKED, False):
        return False

    recent_inputs = st.session_state.get(_SSK_RECENT_INPUTS, [])
    neural_state = st.session_state.get("current_neural_state")
    mode = st.session_state.get(_SSK_COGNITIVE_MODE, "learning")

    triggered = should_trigger_deadlock_from_state(
        recent_inputs=recent_inputs,
        neural_state=neural_state,
        mode=mode,
    )

    if triggered:
        st.session_state[_SSK_DEADLOCKED] = True
        from utils.telemetry_events import log_deadlock
        log_deadlock(triggered=True, reason="重复输入 + 高认知负荷 → 强制接管")
        logger.warning("GuardianMonitor: deadlock triggered")
        return True
    return False


def is_deadlocked() -> bool:
    """查询当前是否处于死锁接管状态。"""
    if st is None:
        return False
    return st.session_state.get(_SSK_DEADLOCKED, False)


def clear_deadlock() -> None:
    """解除死锁状态，清空最近输入缓存。"""
    if st is None:
        return
    from utils.telemetry_events import log_deadlock
    log_deadlock(triggered=False, reason="用户接受降维重构 → 解除 lockdown")
    st.session_state[_SSK_DEADLOCKED] = False
    from utils.ui_renderer import push_system_toast
    push_system_toast("[SYS_OVERRIDE] 死锁解除。神经连接重构完毕。", icon="⚡")
    # 清空死锁输入缓存（保留更早的上下文）
    recent = st.session_state.get(_SSK_RECENT_INPUTS, [])
    if len(recent) >= 3:
        st.session_state[_SSK_RECENT_INPUTS] = recent[:-3]
    else:
        st.session_state[_SSK_RECENT_INPUTS] = []
    logger.info("GuardianMonitor: deadlock cleared")


# ---------------------------------------------------------------------------
# 公共 API：侧边栏遥测
# ---------------------------------------------------------------------------

def render_sidebar_telemetry() -> None:
    """在侧边栏渲染全息神经遥测。"""
    if st is None:
        return

    with st.sidebar:
        st.markdown("---")
        st.subheader("🛡️ Guardian 神经遥测")

        neural_state = st.session_state.get("current_neural_state", {})
        c_load = float(neural_state.get("c_load", 0.5)) if isinstance(neural_state, dict) else 0.5
        e_valence = float(neural_state.get("e_valence", 0.0)) if isinstance(neural_state, dict) else 0.0
        quadrant = (neural_state.get("quadrant", "baseline") if isinstance(neural_state, dict) else "baseline")

        # 认知负荷进度条
        st.markdown("**认知负荷 c_load**")
        st.progress(min(c_load, 1.0))
        if c_load > 0.8:
            st.error(f"⚠️ 负荷临界: {c_load:.2f}")
        elif c_load > 0.6:
            st.warning(f"负荷偏高: {c_load:.2f}")
        else:
            st.success(f"负荷稳定: {c_load:.2f}")

        # 情绪效价
        st.markdown("**情绪效价 e_valence**")
        val_pos = (e_valence + 1.0) / 2.0
        st.progress(val_pos)
        delta = f"{e_valence:+.2f}"
        st.metric(label="效价", value=delta)

        # 象限状态
        emoji_map = {
            "collapse": "🚨",
            "provocation": "⚡",
            "socratic_pressure": "🔥",
            "baseline": "🟢",
        }
        st.caption(f"当前象限: {emoji_map.get(quadrant, '⚪')} {quadrant.upper()}")

        # 死锁状态
        if is_deadlocked():
            st.error("🔒 认知死锁已激活")
        else:
            st.success("🔓 系统正常")

        st.markdown("---")


# ---------------------------------------------------------------------------
# 公共 API：死锁接管 UI
# ---------------------------------------------------------------------------

def render_deadlock_takeover() -> None:
    """
    渲染死锁接管 UI —— 当 is_deadlocked() 为 True 时调用。
    强制阻断常规交互，提供唯一恢复路径。
    """
    if st is None:
        return

    st.error("🔒 认知死锁检测")

    # 高压迫感容器
    st.markdown(
        """
        <div style="
            background: linear-gradient(135deg, #2d0a0a, #1a0505);
            border: 2px solid #ff4444;
            border-radius: 12px;
            padding: 24px;
            margin: 16px 0;
        ">
            <h3 style="color: #ff6b6b; margin-top: 0;">⚠️ 检测到认知死锁</h3>
            <p style="color: #ffcccc; font-size: 16px;">
                当前推理路径正在重复失败。<br>
                系统强制启动<b>"第一性原理"降维拆解</b>。<br>
                请暂停无效试错。
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 禁用常规输入
    st.chat_input("系统已接管 — 等待恢复", disabled=True)

    # 显示最近死锁输入（帮助用户自省）
    recent = st.session_state.get(_SSK_RECENT_INPUTS, [])
    if len(recent) >= 3:
        st.caption("最近重复输入:")
        for i, txt in enumerate(recent[-3:], 1):
            st.code(f"#{i}: {txt[:60]}", language="text")

    # 唯一恢复按钮
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 我接受降维重构", type="primary", key="btn_deadlock_recovery"):
        _handle_recovery()

    # 如有恢复消息，展示
    recovery_msg = st.session_state.get(_SSK_RECOVERY_MSG, "")
    if recovery_msg:
        st.info(f"💡 {recovery_msg}")


def _handle_recovery() -> None:
    """处理死锁恢复逻辑。"""
    if st is None:
        return

    # 设置恢复消息（极简类比，由 cognitive_panel 下一次渲染时展示）
    st.session_state[_SSK_RECOVERY_MSG] = (
        "我们先退回最小模型。想象你在学骑自行车："
        "不是先看理论手册，而是先感受平衡。"
        "现在，让我们用最基础的类比重新理解这个概念。"
    )

    # 解除死锁
    clear_deadlock()

    # 强制刷新
    st.rerun()


# ---------------------------------------------------------------------------
# 恢复消息消费（供 cognitive_panel 调用）
# ---------------------------------------------------------------------------

def consume_recovery_message() -> Optional[str]:
    """
    消费并清空恢复消息。
    cognitive_panel 应在每次渲染前调用，若有消息则插入 assistant 回复。
    """
    if st is None:
        return None
    msg = st.session_state.get(_SSK_RECOVERY_MSG, "")
    if msg:
        st.session_state[_SSK_RECOVERY_MSG] = ""
        return msg
    return None

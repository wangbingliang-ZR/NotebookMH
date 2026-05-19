"""
utils/telemetry_events.py — 遥测事件缓冲区 (Phase 7)

职责：
  - 为 HolographicConsole 提供 XAI Thought Stream 的数据源
  - 零 UI 逻辑，纯数据管道
  - 可安全在 core/ 和 frontend/ 调用

约束：
  - 不依赖 Streamlit（但支持如果可用）
  - 默认 session_state 作为 buffer，fallback 到内存 list
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SSK_TELEMETRY = "nb_mh_telemetry_events"


# ---------------------------------------------------------------------------
# 核心 API
# ---------------------------------------------------------------------------


def append_telemetry_event(message: str, level: str = "INFO") -> None:
    """
    追加一条遥测事件到 session_state buffer。

    Args:
        message: 事件文本（建议不含换行，单条控制在一行）。
        level: 级别字符串（INFO / WARN / ROUTE / DEADLOCK / MASTERY）。
    """
    try:
        import streamlit as st
        if _SSK_TELEMETRY not in st.session_state:
            st.session_state[_SSK_TELEMETRY] = []
        st.session_state[_SSK_TELEMETRY].append({
            "timestamp": _now_iso(),
            "message": message,
            "level": level,
        })
        # 自动截断最近 50 条
        if len(st.session_state[_SSK_TELEMETRY]) > 50:
            st.session_state[_SSK_TELEMETRY] = st.session_state[_SSK_TELEMETRY][-50:]
    except Exception:
        # Streamlit 不可用（如 backend 运行时），fallback 到 logger
        logger.info("[TELEMETRY %s] %s", level, message)


def get_telemetry_events(limit: int = 12) -> List[Dict[str, Any]]:
    """
    读取最近的遥测事件列表。

    Args:
        limit: 返回的最大条数。

    Returns:
        List[dict]: 每个元素含 timestamp / message / level。
    """
    try:
        import streamlit as st
        events = st.session_state.get(_SSK_TELEMETRY, [])
        return events[-limit:]
    except Exception:
        return []


def clear_telemetry_events() -> None:
    """清空事件缓冲区。"""
    try:
        import streamlit as st
        st.session_state[_SSK_TELEMETRY] = []
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 便捷封装（语义化级别）
# ---------------------------------------------------------------------------


def log_route(arm: str, quadrant: str, score: str = "") -> None:
    """记录策略路由事件。"""
    msg = f"动态路由: 选中 [{arm}] (quadrant={quadrant})"
    if score:
        msg += f" score={score}"
    append_telemetry_event(msg, level="ROUTE")


def log_deadlock(triggered: bool, reason: str) -> None:
    """记录死锁检测/触发事件。"""
    level = "DEADLOCK" if triggered else "WARN"
    prefix = "[COGNITIVE LOCKDOWN] " if triggered else "[DEADLOCK CHECK] "
    append_telemetry_event(f"{prefix}{reason}", level=level)


def log_reward(arm: str, reward: float, mastery_delta: float, delta_e: float) -> None:
    """记录 reward 更新事件。"""
    append_telemetry_event(
        f"反向传播: arm=[{arm}] ΔR={reward:+.2f} ΔM={mastery_delta:+.1f} ΔE={delta_e:+.2f}",
        level="INFO",
    )


def log_mastery(level: float, delta: float) -> None:
    """记录掌握度变化事件。"""
    append_telemetry_event(
        f"MASTERY STATE: {level:.0f}/100 (Δ{delta:+.1f})",
        level="MASTERY",
    )


def log_decay() -> None:
    """记录 Time Decay 执行事件。"""
    append_telemetry_event("执行全局 Time Decay: reward × 0.95", level="INFO")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """返回紧凑时间戳，格式 HH:MM:SS。"""
    return datetime.now(timezone.utc).strftime("%H:%M:%S")

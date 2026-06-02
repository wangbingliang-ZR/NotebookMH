"""
utils/ui_renderer.py — 全局终端皮肤与系统遥测注入器 (Phase 7 补完)

职责：
  - 全局 CSS 主题注入（Matrix Green SpaceX 终端）
  - 死锁时全页面红色脉冲遮罩
  - 系统级军事 toast 通知队列

约束：
  - 纯工具函数，不承载业务逻辑
  - CSS 字符串生成使用 lru_cache 等效缓存（零重复构建开销）
  - 使用现有 session state 命名空间，不创建新键冲突
"""

import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. 全局终端 CSS（lru_cache 等效 @st.cache_data 语义）
# ---------------------------------------------------------------------------

_TERMINAL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;700&display=swap');

:root, .stApp, [data-testid="stAppViewContainer"], [data-testid="stSidebar"] {
    --nbmh-bg-primary: #0E1117;
    --nbmh-text-primary: #00FF41;
    --nbmh-text-secondary: #A0AEC0;
    --nbmh-font-stack: 'Fira Code', monospace;
}

.stApp, [data-testid="stAppViewContainer"] {
    background-color: var(--nbmh-bg-primary) !important;
}

html, body, [class*="css"] {
    font-family: var(--nbmh-font-stack) !important;
}

/* 温和覆写 Streamlit 默认文字色为 Matrix Green（允许局部 !important 覆盖） */
.stApp [data-testid="stMarkdownContainer"] p,
.stApp [data-testid="stMarkdownContainer"] span,
.stApp [data-testid="stText"] {
    color: #00FF41 !important;
}

.stApp [data-testid="stCaption"] {
    color: #A0AEC0 !important;
}
"""


@lru_cache(maxsize=1)
def get_terminal_css() -> str:
    """返回全局终端 CSS 字符串。使用 lru_cache 确保零重复构建开销。"""
    return _TERMINAL_CSS


def inject_terminal_css() -> None:
    """在 Streamlit 上下文中注入全局终端 CSS。供 app.py 在 set_page_config 后调用。"""
    try:
        import streamlit as st
        st.html(f"<style>{get_terminal_css()}</style>")
        logger.debug("Terminal CSS injected.")
    except Exception:
        logger.debug("inject_terminal_css skipped (no Streamlit context)")


# ---------------------------------------------------------------------------
# 2. 死锁脉冲遮罩
# ---------------------------------------------------------------------------

_DEADLOCK_PULSE_CSS = """
@keyframes nbmh-pulse-red {
    0%   { box-shadow: inset 0 0 0px rgba(255,0,0,0); }
    50%  { box-shadow: inset 0 0 150px rgba(255,0,0,0.5); }
    100% { box-shadow: inset 0 0 0px rgba(255,0,0,0); }
}

.nbmh-deadlock-pulse .stApp,
.nbmh-deadlock-pulse [data-testid="stAppViewContainer"] {
    animation: nbmh-pulse-red 1.8s infinite ease-in-out;
}
"""


def inject_deadlock_pulse_mask() -> None:
    """
    若当前处于死锁态，向页面注入全屏红色脉冲 CSS。
    读取 nb_mh_guardian_is_deadlocked（与 GuardianMonitor 共用键）。
    """
    try:
        import streamlit as st
    except Exception:
        return

    is_deadlocked = st.session_state.get("nb_mh_guardian_is_deadlocked", False)
    if not is_deadlocked:
        return

    try:
        st.html(
            f'<div class="nbmh-deadlock-pulse"><style>{_DEADLOCK_PULSE_CSS}</style></div>'
        )
        logger.debug("Deadlock pulse mask injected.")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 3. 军事化系统 Toast 队列
# ---------------------------------------------------------------------------

_SSK_TOAST_QUEUE = "nb_mh_system_toast_queue"


def push_system_toast(message: str, icon: str = "⚡") -> None:
    """
    将一条军事 toast 推入 pending 队列。
    可在任意模块安全调用（包括无 Streamlit 环境的后台线程）。
    """
    try:
        import streamlit as st
        if _SSK_TOAST_QUEUE not in st.session_state:
            st.session_state[_SSK_TOAST_QUEUE] = []
        st.session_state[_SSK_TOAST_QUEUE].append({"message": message, "icon": icon})
    except Exception:
        # 无 Streamlit 上下文时，降级到日志
        logger.info("[SYS_TOAST] %s %s", icon, message)


def render_pending_system_toasts(max_n: int = 3) -> None:
    """
    消费并渲染 pending 的系统 toast 队列。
    每轮最多渲染 max_n 条，防止队列积压时 UI 轰炸。
    """
    try:
        import streamlit as st
    except Exception:
        return

    queue: List[Dict[str, str]] = st.session_state.get(_SSK_TOAST_QUEUE, [])
    if not queue:
        return

    # 安全截断消费
    to_render = queue[:max_n]
    st.session_state[_SSK_TOAST_QUEUE] = queue[max_n:]

    for item in to_render:
        try:
            st.toast(item["message"], icon=item["icon"])
        except Exception:
            pass

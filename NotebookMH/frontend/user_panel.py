"""
frontend/user_panel.py - 用户切换 / 轻量登录 (Vault Step 1)

职责：
  - 在 sidebar 顶部提供用户名输入框
  - 切换用户时自动清除 hydrated 标记，重新水合新用户数据
  - 零密码设计：仅通过用户名区分个人学习空间

约束：
  - 允许 import streamlit（frontend 职责）
  - 切换用户后调用 st.rerun() 刷新全页
"""

import logging
from typing import NoReturn

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from utils.state_hydration import hydrate_state_from_disk
from utils.state_manager import binder

logger = logging.getLogger(__name__)


def render() -> None:
    """在 sidebar 顶部渲染用户切换面板。"""
    if st is None:
        return

    st.sidebar.markdown("---")
    st.sidebar.subheader("👤 用户")

    # 读取当前用户（binder 命名空间已包含 user_id）
    current_user = binder.get_state("user_id", "anonymous")

    user_input = st.sidebar.text_input(
        "用户名",
        value=current_user,
        key="nb_mh_user_id_input",
        help="输入你的用户名以切换个人学习空间，数据按用户隔离",
    )

    # 用户变更检测
    if user_input != current_user:
        _switch_user(user_input)


def _switch_user(new_user_id: str) -> NoReturn:
    """
    切换用户：清除水合标记 → 更新 binder → 重新水合 → 强制刷新。
    调用后会通过 st.rerun() 终止当前脚本执行。
    """
    if st is None:
        return

    logger.info("User switch: %s -> %s", binder.get_state("user_id", "anonymous"), new_user_id)

    # 1. 清除水合标记，强制下一轮重新加载 DB 数据
    st.session_state["hydrated"] = False

    # 2. 更新 binder 命名空间中的用户标识
    binder.update_state("user_id", new_user_id)

    # 3. 立即重新水合新用户数据
    hydrate_state_from_disk(user_id=new_user_id)

    # 4. 触发 Streamlit 全页刷新
    st.rerun()

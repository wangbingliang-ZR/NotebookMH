"""
frontend/vault_panel.py - 笔记库 (Vault) 管理面板 (Vault Step 2)

职责：
  - 列出当前用户的所有笔记库
  - 创建新笔记库（自动生成 UUID）
  - 切换当前激活笔记库
  - 删除笔记库（连带文档与 Chunk）

约束：
  - 允许 import streamlit（frontend 职责）
  - 切换 vault 后更新 binder，确保 RAG 检索指向正确容器
  - 自动创建默认 "default_vault" 以保持向后兼容
"""

import logging
import uuid
from typing import NoReturn

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)


def render() -> None:
    """在 sidebar 渲染 Vault 管理面板（紧随用户面板之后）。"""
    if st is None:
        return

    st.markdown("### 笔记库")

    user_id = binder.get_state("user_id", "anonymous")
    vaults = db_pool.list_vaults(user_id)

    # 向后兼容：若用户没有任何 vault，自动创建 default_vault
    if not vaults:
        db_pool.create_vault(
            vault_uuid="default_vault",
            user_id=user_id,
            vault_name="默认笔记库",
        )
        vaults = db_pool.list_vaults(user_id)

    # 当前激活 vault（双写 session_state + binder，确保持久化）
    current_vault = st.session_state.get("vault_uuid") or binder.get_state("vault_uuid", "")
    if not current_vault and vaults:
        current_vault = vaults[0].vault_uuid
        st.session_state["vault_uuid"] = current_vault
        binder.update_state("vault_uuid", current_vault)

    # ── 1. Vault 选择器 ───────────────────────────────
    vault_options = {v.vault_uuid: v.vault_name for v in vaults}
    selected_uuid = st.selectbox(
        "当前笔记库",
        options=list(vault_options.keys()),
        format_func=lambda uuid: vault_options.get(uuid, uuid),
        index=list(vault_options.keys()).index(current_vault) if current_vault in vault_options else 0,
        key="nb_mh_vault_select",
    )

    # 显式切换按钮（比 selectbox on_change 更可靠）
    if st.button("切换到选中库", key="btn_switch_vault"):
        if selected_uuid != current_vault:
            st.session_state["vault_uuid"] = selected_uuid
            binder.update_state("vault_uuid", selected_uuid)
            st.success(f"已切换到：{vault_options.get(selected_uuid, selected_uuid)}")
            st.rerun()
        else:
            st.info("已经是当前库")

    # ── 2. 新建 Vault ─────────────────────────────────
    with st.expander("新建笔记库"):
        new_name = st.text_input("笔记库名称", key="nb_mh_new_vault_name")
        if st.button("创建", key="btn_create_vault"):
            if new_name.strip():
                new_uuid = str(uuid.uuid4())
                db_pool.create_vault(
                    vault_uuid=new_uuid,
                    user_id=user_id,
                    vault_name=new_name.strip(),
                )
                logger.info("User=%s created vault=%s name=%s", user_id, new_uuid, new_name)
                st.success(f"笔记库「{new_name}」已创建")
                # 自动切换到新库（双写 session_state + binder）
                st.session_state["vault_uuid"] = new_uuid
                binder.update_state("vault_uuid", new_uuid)
                st.rerun()
            else:
                st.warning("请输入笔记库名称")

    # ── 3. 删除 Vault ─────────────────────────────────
    with st.expander("删除笔记库"):
        st.caption("删除后无法恢复，文档与 Chunk 一并清除")
        # 独立读取，确保列表是最新的
        all_vaults = db_pool.list_vaults(user_id)
        del_options = {v.vault_uuid: v.vault_name for v in all_vaults}
        active_vault = st.session_state.get("vault_uuid") or binder.get_state("vault_uuid", "")
        del_target = st.selectbox(
            "选择要删除的笔记库",
            options=list(del_options.keys()),
            format_func=lambda uuid: del_options.get(uuid, uuid),
            key="nb_mh_del_vault_select",
        )
        if st.button("确认删除", key="btn_delete_vault"):
            if del_target == active_vault:
                st.error("不能删除当前正在使用的笔记库，请先切换到其他库")
            else:
                db_pool.delete_vault(del_target)
                st.success("笔记库已删除")
                st.rerun()

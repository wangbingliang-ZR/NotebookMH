"""
frontend/persona_panel.py - 教师人格态选择器

职责：
 - Streamlit sidebar 人格选择器（教师类型 + 用户模式 + 情绪状态）
 - 实时显示当前生效的人格标签
 - 将选择结果写入 GlobalState，供 core/qa_panel 和 llm_engine 读取

严禁在 app.py 中写入具体 UI 逻辑。
"""

import logging
from typing import Optional

try:
  import streamlit as st
except ImportError: # pragma: no cover
  st = None # type: ignore[assignment]

from core.persona_engine import PersonaEngine
from utils.state_manager import binder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 公共渲染接口
# ---------------------------------------------------------------------------

def render() -> None:
  """在 Streamlit sidebar 渲染人格选择面板。"""
  if st is None:
    return

  # 读取当前状态（无则使用默认值）
  current_teacher = binder.get_state("teacher_type", "auto")
  current_mode = binder.get_state("user_mode", "adult")
  current_emotion = binder.get_state("emotion_state", "专注")

  # ── 教师类型选择 ──────────────────────────────────────
  teacher_options = {
    "auto": " 自适应 (根据情绪自动切换)",
    "socratic": " 启发型 (苏格拉底式引导)",
    "strict": " 严师型 (直接犀利要求)",
  }
  teacher_sel = st.selectbox(
    "教师人格",
    options=list(teacher_options.keys()),
    format_func=lambda x: teacher_options[x],
    index=list(teacher_options.keys()).index(current_teacher),
    key="nb_mh_teacher_select",
  )
  if teacher_sel != current_teacher:
    binder.update_state("teacher_type", teacher_sel)
    logger.info("Teacher type switched to %s", teacher_sel)

  # ── 用户模式选择 ──────────────────────────────────────
  mode_options = {
    "adult": " 成人模式",
    "child": " 儿童模式",
  }
  mode_sel = st.selectbox(
    "受众模式",
    options=list(mode_options.keys()),
    format_func=lambda x: mode_options[x],
    index=list(mode_options.keys()).index(current_mode),
    key="nb_mh_mode_select",
  )
  if mode_sel != current_mode:
    binder.update_state("user_mode", mode_sel)
    logger.info("User mode switched to %s", mode_sel)

  # ── 情绪状态选择 ──────────────────────────────────────
  emotion_options = [
    "专注", "开心", "困惑", "沮丧", "挫败", "走神", "懒散", "疲倦"
  ]
  emotion_sel = st.selectbox(
    "当前情绪",
    options=emotion_options,
    index=emotion_options.index(current_emotion) if current_emotion in emotion_options else 0,
    key="nb_mh_emotion_select",
  )
  if emotion_sel != current_emotion:
    binder.update_state("emotion_state", emotion_sel)
    logger.info("Emotion state updated to %s", emotion_sel)

  # ── 当前生效标签展示 ──────────────────────────────────
  resolved_label = PersonaEngine.get_resolved_label(teacher_sel, emotion_sel, mode_sel)
  st.caption(f" 当前人格: {resolved_label}")

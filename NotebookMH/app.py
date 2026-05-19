"""
app.py - [奇点入口] NotebookMH 创世方舟

纯净的宏观路由，零业务逻辑。
职责边界：
  1. 页面级配置 (st.set_page_config)
  2. SessionStateBinder 初始化
  3. 顶级路由骨架 (占位符)
  4. asyncio 顶层运行循环 + 异常黑洞护盾

严禁在此文件写入任何具体的 UI 绘制逻辑（如 st.chat_input）。
"""

import asyncio
import logging
import os
import sys
from typing import NoReturn

# 修复 Streamlit 嵌套 event loop 问题（asyncio.run() 冲突）
import nest_asyncio
nest_asyncio.apply()

# 优先加载环境变量，确保后续模块能读取 API Key
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# 1. 页面级全局配置
# ---------------------------------------------------------------------------

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    print("[FATAL] streamlit not installed. Run: pip install -r requirements.txt")
    sys.exit(1)

st.set_page_config(
    layout="wide",
    initial_sidebar_state="expanded",
    page_title="NotebookMH - 多模态硅基共生体",
    page_icon="🧬",
)

# Phase 7 补完：全局终端皮肤注入（Matrix Green SpaceX 终端）
from utils.ui_renderer import inject_terminal_css
inject_terminal_css()

# ---------------------------------------------------------------------------
# 2. 日志与遥测
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("NotebookMH")

# ---------------------------------------------------------------------------
# 3. Session 绑定 (零业务逻辑，纯初始化)
# ---------------------------------------------------------------------------

from utils.state_manager import binder

# 确保 session state 水合完成
binder._init_state()
logger.info("SessionStateBinder hydrated. Snapshot: %s", binder.snapshot().model_dump())

# Phase 8: 物理层热水合 —— DB → session_state
from utils.state_hydration import hydrate_state_from_disk
hydrate_state_from_disk()

# ---------------------------------------------------------------------------
# 4. 全局异常黑洞护盾
# ---------------------------------------------------------------------------

_SYS_SHIELD_MSG = (
    "⚠️ 程序遇到异常，已自动保护未崩溃。"
    "请查看终端/PowerShell 窗口的日志获取详细报错信息。"
)


async def _route_main() -> None:
    """
    顶级异步路由骨架。
    当前为 Phase 0 占位符，后续各 Phase 的业务模块在此注册。
    """
    logger.info("Entering _route_main...")

    # Vault Step 1: 用户切换面板（sidebar 最顶部）
    from frontend.user_panel import render as render_user_panel
    render_user_panel()

    # Vault Step 2: 笔记库管理面板
    from frontend.vault_panel import render as render_vault_panel
    render_vault_panel()

    # Phase 7 补完：全屏死锁脉冲遮罩 + 系统军事 toast 消费
    from utils.ui_renderer import inject_deadlock_pulse_mask, render_pending_system_toasts
    inject_deadlock_pulse_mask()
    render_pending_system_toasts()

    # ── 未来各 Phase 业务挂载点 ────────────────────────────
    # Phase 1A: RAG Truth Sentinel Ingestion Pipeline  ✅ 已挂载
    # Phase 1B: RAG Retrieval QA                        ✅ 已挂载
    # Phase 2: Teacher Persona Integration              ✅ 已挂载
    # Phase 2B: Cognitive Control Engine                ✅ 已挂载
    # Phase 3: Learning Memory & DB Migration           ✅ 已挂载
    # Phase 4: 3D Fluidic Sandbox + ASMR                ✅ 已挂载
    # Phase 5: Unified Neural Core + Quadrant Strategy    ✅ 已挂载
    # ---------------------------------------------------------

    # Phase 7: 全息认知遥测控制台 (HolographicConsole) + 死锁接管
    from frontend.holographic_console import render_holographic_console
    from frontend.guardian_monitor import is_deadlocked, render_deadlock_takeover
    render_holographic_console()

    # ── 死锁接管屏障 ──────────────────────────────────────
    if is_deadlocked():
        render_deadlock_takeover()
        return

    # Phase 2: 侧边栏人格选择器
    from frontend.persona_panel import render as render_persona_panel
    render_persona_panel()

    # Phase 1A: 侧边栏摄入面板
    from frontend.ingestion_panel import render as render_ingestion_panel
    render_ingestion_panel()

    # Phase 4: 3D 流体认知沙箱
    from frontend.visual_sandbox import render as render_visual_sandbox
    render_visual_sandbox()

    # Phase 5: 神经中枢遥测（四象限策略 + 用户认知画像）
    from frontend.neural_panel import render as render_neural_panel
    render_neural_panel()

    # Phase 2B: 认知控制引擎（苏格拉底压制协议状态路由）
    from frontend.cognitive_panel import render as render_cognitive_panel
    render_cognitive_panel()

    # Phase 2: 主界面问答检索面板（传统 RAG 问答，保留为参考）
    from frontend.qa_panel import render as render_qa_panel
    render_qa_panel()

    # Phase 3: 学习进度遥测仪表盘
    from frontend.memory_panel import render as render_memory_panel
    render_memory_panel()

    st.title("NotebookMH 🧬 创世方舟 (Phase 5)")
    st.markdown(
        """
        > **当前阶段**: Phase 5 — 统一神经核心 × 四象限策略 × 认知态遥测 × Guardian 死锁接管  
        > **系统状态**: 🟢 运行中 (Mock / Live 自适应)  
        > **渲染等级**: `{}`  
        > **认知负荷**: `{:.2f}`  
        > **情绪效价**: `{:.2f}`
        """.format(
            binder.get_state("render_tier", "UNKNOWN"),
            binder.get_state("c_load", 0.0),
            binder.get_state("e_valence", 0.0),
        )
    )

    st.divider()
    st.subheader("📡 系统遥测")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="渲染等级", value=binder.get_state("render_tier", "UNKNOWN"))
    with col2:
        st.metric(label="认知负荷", value=f"{binder.get_state('c_load', 0.0):.2f}")
    with col3:
        st.metric(label="情绪效价", value=f"{binder.get_state('e_valence', 0.0):.2f}")
    with col4:
        persona = binder.get_state("teacher_type", "auto")
        st.metric(label="教师人格", value=persona)

    st.divider()
    st.info(
        "Phase 4 全栈闭环：上传 → 摄入 → 检索 → 人格注入 → 状态路由 → LLM 生成 → 记忆固化 → 3D 流体可视化。"
        "系统已具备认知态驱动的实时 ASMR 遥测与自适应教学策略。"
    )


async def main() -> None:
    """
    最外层入口。套用 try...except 捕获所有未知异常，
    严禁暴露 Traceback 污染前端 UI。
    """
    try:
        await _route_main()
    except Exception as e:
        logger.critical("SYS_SHIELD triggered: %s", e, exc_info=True)
        st.error(_SYS_SHIELD_MSG)
        # 不 re-raise，确保 Streamlit 进程不崩溃


# ---------------------------------------------------------------------------
# 5. asyncio 顶层运行循环
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Streamlit 本身已经是事件驱动，asyncio.run 用于包裹我们自己的异步逻辑。
    # 若 streamlit 在 watcher 模式下运行，此入口会被重复执行。
    asyncio.run(main())

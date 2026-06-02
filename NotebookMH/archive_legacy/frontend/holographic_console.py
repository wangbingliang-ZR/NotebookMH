"""
frontend/holographic_console.py — 全息认知遥测控制台 (Phase 7)

职责：
  - SpaceX 遥测级仪表盘：深色工业终端风格
  - XAI 战略透明化终端：Thought Stream 日志
  - 死锁 lockdown 侧边栏灰化
  - 认知相变 toast

约束：
  - 只读取 session_state，不写入业务逻辑
  - 使用 st.empty() 包裹日志区防闪烁
"""

import json
import logging
from typing import Any, Dict, List, Optional

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from utils.db_manager import db_pool
from utils.telemetry_events import get_telemetry_events
from utils.state_manager import binder

from core.holographic_sandbox import SimulationContext, get_simulation_registry
from core.language_engine import (
    EmbodiedContext,
    drain_signals,
    enter_emergency_repair,
    process_voice_command,
    resolve_tetris,
    submit_tetris_block,
)
from core.visual_engine import render_cognitive_landscape_from_vault

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置常量
# ---------------------------------------------------------------------------

# 相变仪式阈值（开放可调）
_PHASE_DELTA_THRESHOLD = 10.0   # mastery_delta 绝对值 ≥ 此值触发
_PHASE_LEVEL_THRESHOLD = 80.0   # 掌握度突破此值触发

_SSK_NEURAL_STATE = "nb_mh_current_neural_state"
_SSK_DEADLOCKED = "nb_mh_guardian_is_deadlocked"
_SSK_LAST_MASTERY = "nb_mh_last_mastery_level"
_SSK_LAST_MASTERY_DELTA = "nb_mh_last_mastery_delta"
_SSK_TRANSITION_DONE = "nb_mh_phase_transition_done"

# Thought Stream 容器 key（防闪烁）
_SSK_TERM_CONTAINER = "nb_mh_term_container"


# ---------------------------------------------------------------------------
# 公共渲染接口
# ---------------------------------------------------------------------------

def render_holographic_console() -> None:
    """渲染全息认知遥测控制台（侧边栏）。"""
    if st is None:
        return

    # ── 死锁 lockdown 警告 ──────────────────────────────
    is_deadlocked = st.session_state.get(_SSK_DEADLOCKED, False)
    if is_deadlocked:
        _render_lockdown_banner()
        _render_biofeedback(grayed=True)
        return

    # ── 正常遥测 ────────────────────────────────────────
    _render_biofeedback(grayed=False)
    _render_strategy_terminal(grayed=False)
    _render_thought_stream()


# ---------------------------------------------------------------------------
# 1. CSS 注入
# ---------------------------------------------------------------------------

def _inject_css() -> None:
    """注入 SpaceX 工业终端风格 CSS。"""
    st.html(
        """
        <style>
        /* 侧边栏整体深色背景 */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0a0a0f 0%, #111118 100%);
        }
        /* 遥测控制台容器 */
        .holo-container {
            font-family: 'Fira Code', 'Courier New', monospace;
            color: #00f2ff !important;
            background: rgba(10,10,20,0.6);
            border: 1px solid #00f2ff22;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 12px;
        }
        .holo-label {
            font-size: 11px;
            color: #7a8b99 !important;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 4px;
        }
        .holo-value {
            font-size: 18px;
            font-weight: 700;
            color: #00f2ff !important;
            text-shadow: 0 0 8px #00f2ff44;
        }
        .holo-value.warn { color: #ffaa00 !important; text-shadow: 0 0 8px #ffaa0044; }
        .holo-value.danger { color: #ff2d2d !important; text-shadow: 0 0 8px #ff2d2d44; }
        .holo-value.optimal { color: #00ff88 !important; text-shadow: 0 0 8px #00ff8844; }
        /* 进度条 */
        .holo-bar-bg {
            background: #1a1a2e;
            border-radius: 2px;
            height: 8px;
            width: 100%;
            overflow: hidden;
            margin-top: 4px;
        }
        .holo-bar-fill {
            height: 100%;
            border-radius: 2px;
            transition: width 0.3s ease;
        }
        .holo-bar-fill.optimal { background: #00ff88; }
        .holo-bar-fill.warn { background: #ffaa00; }
        .holo-bar-fill.danger { background: #ff2d2d; }
        /* 日志终端 */
        .holo-term {
            font-family: 'Fira Code', 'Courier New', monospace;
            font-size: 12px;
            color: #c0c8d0 !important;
            background: rgba(0,0,0,0.4);
            border-radius: 4px;
            padding: 8px;
            line-height: 1.5;
            max-height: 220px;
            overflow-y: auto;
        }
        .holo-term .ts { color: #7a8b99 !important; margin-right: 6px; }
        .holo-term .route { color: #00f2ff !important; }
        .holo-term .warn { color: #ffaa00 !important; }
        .holo-term .deadlock { color: #ff2d2d !important; font-weight: bold; }
        .holo-term .mastery { color: #00ff88 !important; }
        /* lockdown 遮罩 */
        .lockdown-overlay {
            opacity: 0.25;
            pointer-events: none;
            filter: grayscale(0.8);
        }
        /* lockdown 警告 */
        .lockdown-banner {
            background: linear-gradient(90deg, #2d0a0a, #1a0505);
            border: 1px solid #ff2d2d;
            border-radius: 4px;
            padding: 10px;
            margin-bottom: 12px;
            animation: pulse-red 2s infinite;
        }
        @keyframes pulse-red {
            0% { box-shadow: 0 0 0 0 rgba(255,45,45,0.4); }
            70% { box-shadow: 0 0 0 10px rgba(255,45,45,0); }
            100% { box-shadow: 0 0 0 0 rgba(255,45,45,0); }
        }
        </style>
        """,
    )


# ---------------------------------------------------------------------------
# 2. 死锁 Lockdown Banner
# ---------------------------------------------------------------------------

def _render_lockdown_banner() -> None:
    st.html(
        """
        <div class="lockdown-banner">
            <div style="font-size:14px; color:#ff6b6b; font-weight:bold; text-align:center;">
                ⚠️ 系统接管：认知过载
            </div>
            <div style="font-size:11px; color:#ffcccc; text-align:center; margin-top:4px;">
                检测到重复困惑模式，建议休息一下或调整学习方式
            </div>
        </div>
        """,
    )


def _render_sandbox_trigger() -> None:
    """死锁状态下显示【降维补课】按钮，点击后渲染 3D 概念沙盒。"""
    if st is None:
        return

    # 获取当前概念：优先从 session_state，其次从 concept_mastery 推断
    current_concept = st.session_state.get("current_concept", "")
    concept_map = st.session_state.get("concept_mastery", {})

    if not current_concept and concept_map:
        # 取最近一个掌握度 < 60 的概念，或随便一个
        struggling = [c for c, data in concept_map.items() if data.get("mastery_level", 100) < 60]
        current_concept = struggling[0] if struggling else next(iter(concept_map), "未知概念")

    if not current_concept:
        current_concept = "未知概念"

    # 获取掌握度
    mastery = concept_map.get(current_concept, {}).get("mastery_level", 0.0)
    c_load = binder.get_state("c_load", 0.8)
    e_valence = binder.get_state("e_valence", 0.0)

    # 按钮触发（懒加载）
    if st.button("🧬 启动降维补课", key="btn_sandbox", help="用 3D 可视化降维讲解当前概念"):
        _render_holographic_sandbox(current_concept, mastery, c_load, e_valence)


def _render_holographic_sandbox(
    concept_name: str,
    mastery_level: float,
    c_load: float,
    e_valence: float,
    embodied_signals: tuple = (),
) -> None:
    """构建 SimulationContext 并渲染 Plotly 沙盒。"""
    import plotly.graph_objects as go

    ctx = SimulationContext(
        concept_name=concept_name,
        mastery_level=mastery_level,
        c_load=c_load,
        e_valence=e_valence,
        source="current_concept",
        embodied_signals=embodied_signals,
    )

    registry = get_simulation_registry()
    try:
        fig = registry.render(ctx)
        st.plotly_chart(fig, use_container_width=True, theme="streamlit")
    except Exception as e:
        logger.error("Plotly render error: %s", e)
        st.info("[视觉生成失败，已切换文本讲解模式]")


def _render_embodied_language_panel() -> None:
    """具身英语物理指令面板：手动输入英文，驱动工业孪生信号。

    当 c_load>0.85 && e_valence<-0.7 && consecutive_errors>=3 时，
    自动切换为句法俄罗斯方块紧急修复模式。
    """
    if st is None:
        return

    # ── 状态探针 ──
    c_load = float(binder.get_state("c_load", 0.0))
    e_valence = float(binder.get_state("e_valence", 0.0))
    consecutive_errors = int(st.session_state.get("embodied_consecutive_errors", 0))

    # ── 紧急修复判断 ──
    is_emergency = (
        c_load > 0.85
        and e_valence < -0.7
        and consecutive_errors >= 3
    )

    if is_emergency:
        _render_syntactic_tetris_repair(c_load, e_valence)
        return

    # ── 正常指令面板 ──
    st.markdown("### 🗣️ Embodied English")
    st.caption("用英文控制虚拟设备，例如 `open the valve` / `inspect the coupling`")

    scenario_tag = st.selectbox(
        "Scenario",
        options=["pipeline", "mechanical", "abstract"],
        index=0,
        key="embodied_scenario_tag",
    )
    transcript = st.text_input(
        "Command",
        value="",
        placeholder="open the valve",
        key="embodied_command_text",
    )

    if st.button("EXECUTE PHYSICAL COMMAND", key="btn_embodied_execute"):
        user_id = str(binder.get_state("user_id", "anonymous"))
        context = EmbodiedContext(
            scenario_tag=scenario_tag,
            c_load=c_load,
            e_valence=e_valence,
            consecutive_errors=consecutive_errors,
            current_focus_mesh=st.session_state.get("embodied_focus_mesh", "engine_01"),
            user_id=user_id,
        )

        cmd = process_voice_command(transcript, context)
        signals = tuple(drain_signals())
        st.session_state["embodied_last_command"] = cmd.model_dump()
        st.session_state["embodied_last_signals"] = [s.model_dump() for s in signals]

        if cmd.syntax_valid:
            st.session_state["embodied_consecutive_errors"] = 0
            st.session_state["embodied_focus_mesh"] = cmd.target_mesh
            st.success(f"{cmd.target_mesh} → {cmd.physical_action}")
        else:
            st.session_state["embodied_consecutive_errors"] = consecutive_errors + 1
            st.session_state["embodied_tetris_sentence"] = transcript
            st.warning(cmd.diagnosis or "Syntax invalid")

        _render_holographic_sandbox(
            "工业管线",
            mastery_level=70.0,
            c_load=max(c_load, 0.35),
            e_valence=e_valence,
            embodied_signals=signals,
        )

        # 持久化：保存最近一次 signal 到主屏常驻显示
        if signals:
            st.session_state["embodied_persistent_signals"] = [s.model_dump() for s in signals]

    last_command = st.session_state.get("embodied_last_command")
    if last_command:
        with st.expander("Last command payload", expanded=False):
            st.json(last_command)


def _render_syntactic_tetris_repair(c_load: float, e_valence: float) -> None:
    """句法俄罗斯方块紧急修复模式 UI。"""
    st.error("⚠️ EMERGENCY REPAIR MODE — 句法俄罗斯方块")
    st.caption(
        "检测到认知过载 + 连续语法错误。请按正确顺序拼接句子积木，修复完成后系统将重新点火。"
    )

    # 获取或初始化修复句子
    sentence = st.session_state.get("embodied_tetris_sentence", "")
    if not sentence:
        sentence = "open the valve"
        st.session_state["embodied_tetris_sentence"] = sentence

    # ── 初始化 / 恢复 tetris 状态 ──
    tetris_dict = st.session_state.get("embodied_tetris_state")

    if tetris_dict is None:
        ctx = EmbodiedContext(
            c_load=c_load,
            e_valence=e_valence,
            consecutive_errors=3,
        )
        state = enter_emergency_repair(sentence, ctx)
        st.session_state["embodied_tetris_state"] = state.model_dump()
    else:
        from core.language_engine import SyntacticBlock, SyntacticTetrisState

        state = SyntacticTetrisState(**tetris_dict)

    # ── 显示当前句子 ──
    st.markdown(f"**修复目标句：** `{state.sentence}`")

    # ── 已提交序列可视化 ──
    st.write("**已提交序列：**")
    if state.submitted_order:
        cols = st.columns(max(len(state.submitted_order), 1))
        for i, bid in enumerate(state.submitted_order):
            block = next((b for b in state.available_blocks if b.block_id == bid), None)
            if block:
                with cols[i]:
                    st.markdown(
                        f"<div style='background:{block.color_hex};color:white;padding:6px 10px;border-radius:6px;text-align:center;font-weight:bold;'>{block.pos_tag}: {block.label}</div>",
                        unsafe_allow_html=True,
                    )
    else:
        st.caption("（尚未提交任何积木）")

    # ── 可用积木按钮 ──
    remaining = [
        b for b in state.available_blocks if b.block_id not in state.submitted_order
    ]
    if remaining:
        st.write("**可用积木：**")
        cols = st.columns(max(len(remaining), 1))
        for i, block in enumerate(remaining):
            with cols[i]:
                if st.button(
                    f"{block.pos_tag}: {block.label}",
                    key=f"tetris_block_{block.block_id}",
                    type="primary",
                ):
                    next_state = submit_tetris_block(block.block_id)
                    st.session_state["embodied_tetris_state"] = next_state.model_dump()
                    st.rerun()

    # ── 完成判断 ──
    if state.is_complete:
        if state.is_correct:
            st.success("✅ 句法修复成功 — 系统重新点火")
            sig = resolve_tetris()
            if sig:
                st.balloons()
                _render_holographic_sandbox(
                    "工业管线",
                    mastery_level=70.0,
                    c_load=max(c_load, 0.35),
                    e_valence=e_valence,
                    embodied_signals=(sig,),
                )
            # 清除紧急状态，恢复正常
            st.session_state["embodied_consecutive_errors"] = 0
            for key in ["embodied_tetris_state", "embodied_tetris_sentence"]:
                st.session_state.pop(key, None)
        else:
            st.error(f"❌ 顺序错误 (attempt #{state.attempt_count}) — 请按 S→V→O 顺序拼接")
            if st.button("🔄 重置积木", key="btn_tetris_reset"):
                for key in ["embodied_tetris_state", "embodied_tetris_sentence"]:
                    st.session_state.pop(key, None)
                st.rerun()


# ---------------------------------------------------------------------------
# 3. 生物反馈仪表盘 (Biofeedback Mirroring)
# ---------------------------------------------------------------------------

def _render_biofeedback(grayed: bool = False) -> None:
    wrapper = 'class="lockdown-overlay"' if grayed else ""
    state = st.session_state.get(_SSK_NEURAL_STATE) or {}

    c_load = float(state.get("c_load", 0.5))
    e_valence = float(state.get("e_valence", 0.0))

    # c_load 等级
    if c_load >= 0.8:
        c_class = "danger"
        c_alert = "<div style='font-size:10px;color:#ff2d2d;margin-top:4px;'>[警告：负荷过高]</div>"
    elif c_load >= 0.6:
        c_class = "warn"
        c_alert = ""
    else:
        c_class = "optimal"
        c_alert = ""

    # e_valence 终端文本
    if e_valence >= 0.4:
        e_text = f"状态：良好 ({e_valence:+.2f})"
        e_class = "optimal"
    elif e_valence >= -0.3:
        e_text = f"状态：平稳 ({e_valence:+.2f})"
        e_class = "warn"
    else:
        e_text = f"状态：下滑 ({e_valence:+.2f})"
        e_class = "danger"

    st.html(
        f"""
        <div {wrapper}>
            <div class="holo-container">
                <div class="holo-label">脑力负荷</div>
                <div class="holo-value {c_class}">{c_load:.2f}</div>
                <div class="holo-bar-bg">
                    <div class="holo-bar-fill {c_class}" style="width:{min(c_load,1.0)*100:.1f}%;"></div>
                </div>
                {c_alert}
            </div>
            <div class="holo-container">
                <div class="holo-label">情绪状态</div>
                <div class="holo-value {e_class}">{e_text}</div>
            </div>
        </div>
        """
    )


# ---------------------------------------------------------------------------
# 4. 策略终端 (Strategy Terminal)
# ---------------------------------------------------------------------------

def _render_strategy_terminal(grayed: bool = False) -> None:
    wrapper = 'class="lockdown-overlay"' if grayed else ""
    state = st.session_state.get(_SSK_NEURAL_STATE) or {}
    quadrant = state.get("quadrant", "baseline")
    strategy = state.get("strategy", "N/A")

    # 读取 4 臂 stats
    user_id = binder.get_state("user_id", "anonymous")
    genome_data = _load_genome(user_id)

    arm_lines: List[str] = []
    if genome_data:
        for arm_name, data in genome_data.items():
            pulls = int(data.get("pulls", 0))
            reward = float(data.get("reward", 0.0))
            avg = reward / pulls if pulls > 0 else 0.0
            is_current = arm_name == strategy
            marker = "=>" if is_current else "  "
            arm_lines.append(
                f"{marker} [{arm_name}] pulls={pulls} reward={reward:.1f} avg={avg:.2f}"
            )
    else:
        arm_lines.append("[CALIBRATING SENSORS...]")

    arms_text = "\n".join(arm_lines)

    st.html(
        f"""
        <div {wrapper}>
            <div class="holo-container">
                <div class="holo-label">当前策略模式</div>
                <div class="holo-value">{quadrant.upper()} / {strategy}</div>
            </div>
            <div class="holo-container">
                <div class="holo-label">策略效果记录</div>
                <pre style="color:#7a8b99;font-size:11px;margin:0;">{arms_text}</pre>
            </div>
        </div>
        """
    )


# ---------------------------------------------------------------------------
# 5. Thought Stream (XAI 日志终端)
# ---------------------------------------------------------------------------

def _render_thought_stream() -> None:
    """渲染 XAI 日志终端，使用 st.empty() 容器防闪烁。"""
    events = get_telemetry_events(limit=12)

    if not events:
        lines_html = '<span class="ts">--:--:--</span> [CALIBRATING SENSORS...]'
    else:
        lines_html = ""
        for ev in events:
            ts = ev.get("timestamp", "--:--:--")
            msg = ev.get("message", "")
            level = ev.get("level", "INFO")
            css_class = {
                "DEADLOCK": "deadlock",
                "MASTERY": "mastery",
                "ROUTE": "route",
                "WARN": "warn",
                "INFO": "",
            }.get(level, "")
            lines_html += f'<div><span class="ts">[{ts}]</span> <span class="{css_class}">{msg}</span></div>'

    # Phase 7: 使用 st.empty() 包裹日志区，防止全侧边栏重绘闪烁
    container = st.empty()
    with container.container():
        st.html(
            f"""
            <div class="holo-container">
                <div class="holo-label">系统运行日志</div>
                <div class="holo-term">
                    {lines_html}
                </div>
            </div>
            """
        )


# ---------------------------------------------------------------------------
# 6. 认知相变 Toast
# ---------------------------------------------------------------------------

def _render_phase_transition() -> None:
    """在主屏触发相变 toast。"""
    last_delta = st.session_state.get(_SSK_LAST_MASTERY_DELTA, 0.0)
    last_level = st.session_state.get(_SSK_LAST_MASTERY, 0.0)
    done = st.session_state.get(_SSK_TRANSITION_DONE, False)

    # 触发条件：掌握度跃升 ≥ 阈值 或 突破等级阈值
    triggered = False
    message = ""
    if abs(last_delta) >= _PHASE_DELTA_THRESHOLD and not done:
        triggered = True
        message = f"[NEURAL_UPDATE] 掌握度突破阈值。防线已推进。Δ{last_delta:+.0f}。"
    elif last_level >= _PHASE_LEVEL_THRESHOLD and not done and last_delta > 0:
        triggered = True
        message = f"[NEURAL_UPDATE] 掌握度突破阈值。防线已推进。当前 {last_level:.0f}/100。"

    if triggered:
        st.toast(message, icon="🛡️")
        st.session_state[_SSK_TRANSITION_DONE] = True
        # 追加遥测事件
        from utils.telemetry_events import append_telemetry_event
        append_telemetry_event(f"PHASE TRANSITION: mastery={last_level:.0f} Δ{last_delta:+.0f}", level="MASTERY")


def reset_phase_transition_flag() -> None:
    """由 cognitive_panel 在下一轮开始前调用，允许新相变触发。"""
    st.session_state[_SSK_TRANSITION_DONE] = False


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _render_cognitive_landscape_panel() -> None:
    """认知地形图独立面板：从当前 Vault + User 直接渲染 3D DAG。"""
    if st is None:
        return

    st.markdown("### 🗺️ 认知地形图")
    st.caption("基于当前笔记库概念依赖与掌握度生成的 3D 地形")

    vault_uuid = st.session_state.get("current_vault_uuid", "")
    if not vault_uuid:
        st.info("请先选择或创建一个笔记库，以查看认知地形图。")
        return

    user_id = str(binder.get_state("user_id", "anonymous"))
    current_concept = st.session_state.get("current_concept", "")

    if st.button("🌐 渲染认知地形", key="btn_cognitive_landscape"):
        try:
            fig = render_cognitive_landscape_from_vault(
                vault_uuid=vault_uuid,
                user_id=user_id,
                current_node_id=current_concept or None,
            )
            st.plotly_chart(fig, use_container_width=True, theme="streamlit")
            st.success(f"认知地形图已渲染 — Vault: {vault_uuid[:8]}...")
        except Exception as e:
            logger.error("Cognitive landscape render failed: %s", e)
            st.error(f"地形图渲染失败: {e}")


def _render_persistent_signal_badge() -> None:
    """常驻信号徽章：展示最近一次具身英语动作，常驻主屏不消失。"""
    if st is None:
        return

    sigs = st.session_state.get("embodied_persistent_signals")
    if not sigs:
        return

    st.markdown("---")
    st.markdown("### ⚡ 最近物理动作")

    for sig in sigs:
        action = sig.get("action", "unknown")
        mesh_id = sig.get("mesh_id", "")
        intensity = sig.get("intensity", 1.0)

        # 根据动作类型着色
        color = "#FFD700"
        emoji = "⚙️"
        if action == "failure_smoke":
            color = "#FF003C"
            emoji = "💨"
        elif action == "restart_ignition":
            color = "#00FF41"
            emoji = "🔥"
        elif action in {"open", "start", "vent", "pressurize"}:
            emoji = "🟢"
        elif action in {"close", "stop"}:
            emoji = "🔴"

        st.markdown(
            f"<div style='display:inline-flex;align-items:center;gap:6px;"
            f"background:{color}22;border-left:3px solid {color};"
            f"padding:4px 10px;border-radius:4px;font-size:13px;'>"
            f"<span>{emoji}</span>"
            f"<span style='color:{color};font-weight:bold;'>{mesh_id}</span>"
            f"<span style='color:#c0c8d0;'>→ {action}</span>"
            f"<span style='color:#7a8b99;'>(intensity {intensity:.1f})</span>"
            f"</div>",
            unsafe_allow_html=True,
        )


def _load_genome(user_id: str) -> Optional[Dict[str, Any]]:
    try:
        stats = db_pool.get_or_create_user_stats(user_id)
        raw = stats.weights or "{}"
        weights = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return weights.get("evolutionary_prompt_stats")
    except Exception:
        return None

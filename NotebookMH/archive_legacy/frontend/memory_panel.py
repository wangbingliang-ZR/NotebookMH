"""
frontend/memory_panel.py - 学习进度遥测仪表盘 (Phase 2B/3 Optimized)

职责：
  - Streamlit 主界面学习进度可视化
  - 用户统计指标 (总题数、正确率、错题数)
  - 知识点掌握度热力图/进度条
  - MAB 策略权重实时展示
  - 薄弱知识点错题热力图
  - 最近交互日志审计

严禁在 app.py 中写入具体 UI 逻辑。
"""

import logging
from typing import Any, Dict, List

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from core.mab_engine import get_mab_engine
from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 公共渲染接口
# ---------------------------------------------------------------------------

def render() -> None:
    """渲染学习进度遥测仪表盘。"""
    if st is None:
        return

    st.divider()
    st.subheader("📊 认知记忆遥测 (Phase 2B/3)")

    user_id = binder.get_state("user_id", "anonymous")

    # ── 用户统计卡片 ──────────────────────────────────────
    stats = db_pool.get_or_create_user_stats(user_id)
    total = stats.total_questions or 0
    correct = stats.correct_count or 0
    wrong = stats.wrong_count or 0
    accuracy = (correct / total * 100) if total > 0 else 0.0

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(label="总题数", value=total)
    with col2:
        st.metric(label="正确数", value=correct, delta=f"+{correct}")
    with col3:
        st.metric(label="错误数", value=wrong, delta=f"-{wrong}")
    with col4:
        st.metric(label="正确率", value=f"{accuracy:.1f}%")

    # ── MAB 策略权重 ─────────────────────────────────────
    st.divider()
    st.caption("🎰 MAB 策略权重 (Epsilon-Greedy + UCB)")
    _render_mab_weights(stats.strategy_weights)

    # ── 薄弱知识点热力图 ─────────────────────────────────
    st.divider()
    st.caption("🔥 薄弱知识点错题热力图")
    _render_weak_heatmap(user_id)

    # ── 知识点掌握度 ────────────────────────────────────
    st.divider()
    st.caption("🧩 知识点掌握度图谱")
    concepts = db_pool.list_concepts(user_id)
    if not concepts:
        st.info("暂无知识点记录。开始问答后自动构建认知图谱。")
    else:
        for cm in concepts[:10]:
            level = cm.mastery_level or 0.0
            status_color = {
                "mastered": "🟢",
                "learning": "🟡",
                "struggling": "🔴",
            }.get(cm.status, "⚪")
            st.progress(
                min(int(level) / 100, 1.0),
                text=f"{status_color} {cm.concept_name}  ({level:.0f}/100)  [{cm.status}]",
            )

    # ── 最近交互日志 ─────────────────────────────────────
    st.divider()
    st.caption("📝 最近交互审计日志")
    logs = db_pool.get_recent_logs(user_id, limit=5)
    if not logs:
        st.info("暂无交互记录。")
    else:
        for log in logs:
            icon = "✅" if log.is_correct == 1 else ("❌" if log.is_correct == 0 else "❓")
            with st.expander(f"{icon} {log.timestamp.strftime('%m-%d %H:%M')} · {log.query[:40]}..."):
                st.markdown(f"**Q:** {log.query}")
                st.markdown(f"**A:** {log.response[:200]}...")
                if log.diagnosis:
                    st.caption(f"诊断: {log.diagnosis}")
                if log.c_load is not None:
                    st.caption(f"c_load={log.c_load:.2f}  e_valence={log.e_valence or 0:.2f}")
                if log.teacher_type:
                    st.caption(f"teacher={log.teacher_type}")


def _render_mab_weights(strategy_weights: Any) -> None:
    """渲染 MAB 策略权重表格。"""
    if not strategy_weights:
        st.info("MAB 尚未有足够数据。完成几次测验后自动学习最优策略。")
        return

    try:
        mab = get_mab_engine(weights=strategy_weights)
        report = mab.report()
    except Exception as e:
        logger.warning("MAB report failed: %s", e)
        st.info("MAB 权重解析中...")
        return

    cols = st.columns(3)
    bandits = [
        ("strategy", "🧠 教学策略", ["socratic", "strict"]),
        ("difficulty", "📐 难度选择", ["easy", "medium", "hard"]),
        ("type", "📝 题型偏好", ["calculation", "concept", "application"]),
    ]

    for idx, (key, title, arms) in enumerate(bandits):
        with cols[idx]:
            st.markdown(f"**{title}**")
            data = report.get(key, {})
            for arm in arms:
                arm_data = data.get(arm, {"pulls": 0, "avg_reward": 0.0})
                pulls = arm_data.get("pulls", 0)
                avg = arm_data.get("avg_reward", 0.0)
                bar = "█" * int(avg * 10) + "░" * (10 - int(avg * 10))
                st.caption(f"{arm}: {bar}  {avg:.2f}  (n={pulls})")


def _render_weak_heatmap(user_id: str) -> None:
    """渲染薄弱知识点错题热力图。"""
    wrong_logs = db_pool.get_wrong_logs(user_id, limit=20)
    if not wrong_logs:
        st.info("暂无错题记录。进入【错题清算】模式开始追踪薄弱点。")
        return

    # 按 query 关键词聚类（简化：取前10个高频词）
    from collections import Counter
    queries = [log.query for log in wrong_logs if log.query]
    words = []
    for q in queries:
        words.extend([w for w in q.split() if len(w) >= 2])
    top_words = Counter(words).most_common(8)

    if not top_words:
        st.info("错题数据尚在积累中。")
        return

    max_count = max(c for _, c in top_words)
    for word, count in top_words:
        intensity = count / max_count
        bar = "🔴" * int(intensity * 5) + "⚪" * (5 - int(intensity * 5))
        st.progress(intensity, text=f"{bar}  {word}  (错{count}次)")

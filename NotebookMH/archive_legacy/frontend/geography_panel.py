import logging
from typing import Any, Dict, List

try:
    import plotly.graph_objects as go
    import streamlit as st
except ImportError:
    go = None  # type: ignore[assignment]
    st = None  # type: ignore[assignment]

from core.geography_engine import get_geography_exam_engine
from core.geography_trainer import get_geography_trainer
from core.geography_short_answer_grader import get_short_answer_grader
from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)

_ENGINE = get_geography_exam_engine()
_TRAINER = get_geography_trainer()
_GRADER = get_short_answer_grader()


def render() -> None:
    if st is None or go is None:
        return

    st.divider()
    st.subheader("🌏 中考地理冲刺训练")
    st.caption("目标：一个月内优先训练读图、因果链、常考地理解释题。")

    tab_daily, tab_topic, tab_template, tab_review = st.tabs([
        "📋 每日冲刺", "📖 专题讲解", "✍️ 模板训练", "🔁 错题回炉"
    ])

    with tab_daily:
        _render_daily_sprint()

    with tab_topic:
        _render_topic_explainer()

    with tab_template:
        _render_template_training()

    with tab_review:
        _render_wrong_answer_review()


def _render_daily_sprint() -> None:
    user_id = binder.get_state("user_id", "anonymous")

    # 检查是否有正在进行的训练包
    active_pack = st.session_state.get("geo_active_pack")
    active_idx = st.session_state.get("geo_active_idx", 0)
    active_results = st.session_state.get("geo_active_results", [])

    if active_pack is None:
        st.info("每日冲刺：系统自动生成一套针对薄弱点的训练题（约8题，预计15分钟）。")
        if st.button("生成今日训练", key="geo_gen_daily"):
            pack = _TRAINER.build_daily_pack(user_id, question_count=8, target_time_min=15)
            st.session_state["geo_active_pack"] = pack
            st.session_state["geo_active_idx"] = 0
            st.session_state["geo_active_results"] = []
            st.rerun()
        return

    # 显示进度
    total = len(active_pack.questions)
    current = active_idx + 1
    st.progress(current / total, text=f"进度：{current}/{total}")

    if active_idx >= total:
        _render_daily_summary(active_results, active_pack)
        return

    q = active_pack.questions[active_idx]
    st.markdown(f"**{current}. [{q.skill_tag}]** {q.question}")

    if q.question_type == "choice":
        user_answer = st.radio("选择答案", q.options, key=f"geo_q_{q.question_id}")
        if st.button("提交答案", key=f"geo_submit_{q.question_id}"):
            result = _TRAINER.check_answer(user_id, q.question_id, user_answer[0])
            active_results.append(result.__dict__)
            st.session_state["geo_active_results"] = active_results
            st.session_state["geo_active_idx"] = active_idx + 1
            if result.is_correct:
                st.success(f"✅ 正确！{result.explanation}")
            else:
                st.error(f"❌ 错误。{result.explanation}")
                st.warning(f"💡 陷阱分析：{result.trap_analysis}")
            st.caption(f"掌握度变化：{result.score_delta:+.1f}")
            st.rerun()
    else:
        user_answer = st.text_input("填写答案", key=f"geo_q_{q.question_id}")
        if st.button("提交答案", key=f"geo_submit_{q.question_id}"):
            result = _TRAINER.check_answer(user_id, q.question_id, user_answer)
            active_results.append(result.__dict__)
            st.session_state["geo_active_results"] = active_results
            st.session_state["geo_active_idx"] = active_idx + 1
            if result.is_correct:
                st.success(f"✅ 正确！{result.explanation}")
            else:
                st.error(f"❌ 错误。正确答案是：{q.answer}")
                st.write(f"解析：{result.explanation}")
                st.warning(f"💡 陷阱分析：{result.trap_analysis}")
            st.caption(f"掌握度变化：{result.score_delta:+.1f}")
            st.rerun()

    if st.button("结束训练", key="geo_end_daily"):
        for key in ["geo_active_pack", "geo_active_idx", "geo_active_results"]:
            st.session_state.pop(key, None)
        st.rerun()


def _render_daily_summary(results: List[Dict[str, Any]], pack: Any) -> None:
    correct = sum(1 for r in results if r.get("is_correct"))
    total = len(results)
    accuracy = (correct / total * 100) if total > 0 else 0

    st.success(f"🎉 今日训练完成！正确率：{correct}/{total} ({accuracy:.0f}%)")

    wrong_skills: Dict[str, int] = {}
    for r in results:
        if not r.get("is_correct"):
            skill = r.get("skill_tag", "其他")
            wrong_skills[skill] = wrong_skills.get(skill, 0) + 1

    if wrong_skills:
        st.warning("**薄弱技能点：**")
        for skill, count in sorted(wrong_skills.items(), key=lambda x: -x[1]):
            st.write(f"- {skill}：错 {count} 题")

    st.info(f"下次训练将优先针对：{', '.join(pack.weak_concepts[:3]) or '全面复习'}")

    if st.button("完成并清空", key="geo_finish_daily"):
        for key in ["geo_active_pack", "geo_active_idx", "geo_active_results"]:
            st.session_state.pop(key, None)
        st.rerun()


def _render_topic_explainer() -> None:
    c_load = float(binder.get_state("c_load", 0.0) or 0.0)
    scenarios = _ENGINE.causal_atlas.list_scenarios()
    scenario_labels = {item.title: item.scenario_id for item in scenarios}
    selected_title = st.selectbox(
        "选择中考地理专题",
        options=list(scenario_labels.keys()),
        key="geo_exam_scenario_title",
    )
    scenario_id = scenario_labels[selected_title]
    revision_pack = _ENGINE.build_revision_pack(scenario_id, c_load=c_load)

    if c_load > 0.85:
        st.warning("检测到认知负荷偏高：已切换为因果链降维模式。")

    _render_causal_chain(revision_pack)
    _render_key_points(revision_pack)

    if scenario_id in {"contour_dam", "sea_level"}:
        _render_terrain_training(scenario_id)


def _render_causal_chain(revision_pack: Dict[str, Any]) -> None:
    st.markdown(f"**题目：** {revision_pack['question']}")
    st.info(revision_pack["advice"])

    chain = revision_pack.get("causal_chain", [])
    labels = [item["name"] for item in chain]
    if labels:
        st.markdown("**必背因果链：** " + " → ".join(labels))

    for index, item in enumerate(chain, start=1):
        with st.expander(f"{index}. {item['name']}", expanded=index == 1):
            st.write(item["explanation"])


def _render_key_points(revision_pack: Dict[str, Any]) -> None:
    st.markdown("**中考关键词：**")
    cols = st.columns(min(4, max(1, len(revision_pack.get("key_points", [])))))
    for index, point in enumerate(revision_pack.get("key_points", [])):
        with cols[index % len(cols)]:
            st.success(point)


def _render_terrain_training(scenario_id: str) -> None:
    st.divider()
    st.caption("🗺️ 等高线/海平面读图训练")

    dem_matrix = _ENGINE.haptic_engine.generate_teaching_dem(size=80)

    if scenario_id == "sea_level":
        sea_level = st.slider("海平面高度模拟", min_value=20, max_value=160, value=80, step=5, key="geo_sea_level")
        flooded = _ENGINE.haptic_engine.simulate_sea_level(dem_matrix, sea_level)
        fig = go.Figure()
        fig.add_trace(go.Contour(z=dem_matrix, colorscale="Earth", contours=dict(showlabels=True)))
        fig.add_trace(
            go.Heatmap(
                z=flooded.astype(int),
                colorscale=[[0.0, "rgba(0,0,0,0)"], [1.0, "rgba(0,120,255,0.55)"]],
                showscale=False,
                hoverinfo="skip",
            )
        )
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10), title="海平面上升淹没区模拟")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("蓝色区域表示低于当前海平面的潜在淹没区。重点观察：低海拔、坡度小、范围扩张快。")
        return

    fig = go.Figure(data=[go.Contour(z=dem_matrix, colorscale="Earth", contours=dict(showlabels=True))])
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10), title="等高线教学地形：选择你认为适合建坝的位置")
    st.plotly_chart(fig, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        point_x = st.slider("坝址 X 坐标", min_value=0, max_value=79, value=40, key="geo_dam_x")
    with col_b:
        point_y = st.slider("坝址 Y 坐标", min_value=0, max_value=79, value=36, key="geo_dam_y")

    if st.button("判定坝址是否合理", key="geo_validate_dam"):
        result = _ENGINE.haptic_engine.validate_dam_placement(point_x, point_y, dem_matrix)
        user_id = binder.get_state("user_id", "anonymous")
        db_pool.update_user_stats(user_id=user_id, correct=result.is_valid)
        db_pool.update_concept_mastery(
            user_id=user_id,
            concept_name=result.concept_name,
            mastery_delta=result.score_delta,
            correct=result.is_valid,
        )
        if result.is_valid:
            st.success(result.reason)
        else:
            st.warning(result.reason)
        st.caption(f"掌握度变化：{result.score_delta:+.1f}")


def _render_template_training() -> None:
    st.info("中考地理简答题判分训练：对照标准答题模板，训练得分点意识。")

    templates = _GRADER.library.list_templates()
    template_labels = {t.template_name: t.template_id for t in templates}
    selected_name = st.selectbox(
        "选择答题模板类型",
        options=list(template_labels.keys()),
        key="geo_template_select",
    )
    template_id = template_labels[selected_name]
    template = _GRADER.library.get_template(template_id)

    if not template:
        return

    st.markdown(f"**📌 题目类型：** {template.template_name}")
    st.markdown(f"**题干：** {template.question_stem}")
    st.caption(f"💡 {template.tips}")

    with st.expander("查看标准答题要点（训练时建议先隐藏）"):
        for point in template.score_points:
            st.write(f"• {point}")

    st.divider()
    st.markdown("**请作答：**")
    student_answer = st.text_area(
        "输入你的答案",
        placeholder="例如：该地地势平坦，耕地面积广；气候雨热同期，利于农作物生长...",
        key=f"geo_answer_{template_id}",
        height=120,
    )

    if st.button("提交判分", key=f"geo_grade_{template_id}"):
        if not student_answer.strip():
            st.warning("请输入答案后再提交。")
            return

        result = _GRADER.grade(student_answer, template_id)

        col1, col2 = st.columns(2)
        with col1:
            st.metric("得分", f"{result.earned_score}/{result.full_score}")
        with col2:
            hit_rate = (len(result.hit_points) / max(1, len(template.score_points)) * 100)
            st.metric("得分点命中率", f"{hit_rate:.0f}%")

        st.divider()
        st.markdown("**✅ 已命中得分点：**")
        for point in result.hit_points:
            st.success(point)

        if result.missed_points:
            st.markdown("**❌ 遗漏得分点：**")
            for point in result.missed_points:
                st.error(point)

        st.divider()
        st.markdown("**📝 建议标准答案：**")
        st.info(result.suggested_answer)

        if result.weak_spots:
            st.warning("**薄弱点分析：**")
            for spot in result.weak_spots:
                st.write(f"• {spot}")

        if result.next_template_suggestion:
            next_t = _GRADER.library.get_template(result.next_template_suggestion)
            if next_t:
                st.caption(f"建议下一步练习：{next_t.template_name}")


def _render_wrong_answer_review() -> None:
    user_id = binder.get_state("user_id", "anonymous")
    st.info("从最近错题中抽取薄弱知识点进行回炉训练。")

    wrong_logs = db_pool.get_wrong_logs(user_id, limit=10)
    if not wrong_logs:
        st.success("暂无错题记录，继续保持！")
        return

    st.markdown(f"**最近错题 {len(wrong_logs)} 道**")

    for idx, log in enumerate(wrong_logs[:5], 1):
        with st.expander(f"{idx}. {log.query[:60]}..."):
            st.markdown(f"**你的回答：** {log.user_answer or '无'}")
            st.markdown(f"**系统诊断：** {log.diagnosis or '无'}")
            if log.is_correct == 0:
                st.error("❌ 错误")
            st.caption(f"时间：{log.timestamp.strftime('%m-%d %H:%M')}")

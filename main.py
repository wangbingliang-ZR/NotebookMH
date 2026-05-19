"""
main.py - NotebookMH FastAPI 入口
提供 /chat 等接口，驱动 AI 讲解、出题、判断流程。
"""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from prompt import build_explain_prompt, build_judge_prompt, build_proactive_prompt, UserMode
from ai import ask_model
from memory import state_manager, SILENCE_THRESHOLD
from database import db_manager, init_db
from teacher_profiles import TeacherType, generate_teacher_prompt, get_teacher_label


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="NotebookMH AI 学习系统", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# ---------------------------------------------------------------------------
# 请求/响应模型
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    user_id: str = Field(default="default_user", description="用户唯一标识")
    query: str = Field(..., description="用户输入")
    mode: UserMode = Field(default=UserMode.ADULT, description="学习模式")
    teacher_type: TeacherType = Field(default=TeacherType.AUTO, description="教师角色：socratic / strict / auto")
    emotion_state: str = Field(default="", description="用户情绪状态，空时由系统自动推断")
    answer_to_question: str = Field(default="", description="若用户在回答题目，填写答案")


class ProactiveRequest(BaseModel):
    user_id: str = Field(default="default_user", description="用户唯一标识")


class ChatResponse(BaseModel):
    explanation: str
    question: str = ""
    hint: str = ""
    is_correct: Optional[bool] = None
    diagnosis: str = ""
    encouragement: str = ""
    mode: str = ""
    teacher_type: str = ""
    teacher_label: str = ""


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    user_id = req.user_id
    mode = req.mode

    # 确保会话存在并设置模式与教师角色
    state_manager.set_mode(user_id, mode)
    state_manager.set_teacher_type(user_id, req.teacher_type)
    if req.emotion_state:
        state_manager.set_emotion_state(user_id, req.emotion_state)
    sess = state_manager.get_session(user_id)

    # 若 emotion_state 为空，自动推断
    if not sess.emotion_state:
        inferred = state_manager.auto_infer_emotion(user_id)
        state_manager.set_emotion_state(user_id, inferred)

    # 生成教师人格 system prompt
    system_prompt = generate_teacher_prompt(
        teacher_type=sess.teacher_type,
        user_mode=sess.mode,
        emotion_state=sess.emotion_state,
    )
    teacher_label = get_teacher_label(sess.teacher_type, sess.mode)

    # ---------------------------------------------------------------
    # 情况 A：用户正在回答系统出的题目
    # ---------------------------------------------------------------
    if req.answer_to_question and sess.current_question:
        is_correct = state_manager.check_answer(user_id, req.answer_to_question)

        # 更新知识点掌握度
        if sess.current_concept:
            delta = 10.0 if is_correct else -5.0
            db_manager.update_concept_mastery(
                user_id=user_id,
                concept_name=sess.current_concept,
                mastery_delta=delta,
                correct=is_correct,
            )

        # 更新用户统计
        db_manager.update_user_stats(user_id, correct=is_correct)

        # 生成判断反馈 + 下一题
        prompt = build_judge_prompt(
            question=sess.current_question,
            correct_answer=sess.current_answer,
            user_answer=req.answer_to_question,
            consecutive_wrong=sess.consecutive_wrong,
        )
        ai_resp = await ask_model(prompt, system_prompt=system_prompt)

        # 保存交互日志
        db_manager.log_interaction(
            user_id=user_id,
            query=sess.current_question,
            response=ai_resp.explanation,
            mode=mode.value,
            question=sess.current_question,
            user_answer=req.answer_to_question,
            is_correct=is_correct,
            c_load=ai_resp.c_load,
            e_valence=ai_resp.e_valence,
            diagnosis=ai_resp.diagnosis,
        )

        # 更新当前题目
        if ai_resp.question:
            state_manager.set_current_question(user_id, ai_resp.question, ai_resp.answer or "")

        state_manager.record_exchange(user_id, "user", req.answer_to_question)
        state_manager.record_exchange(user_id, "assistant", ai_resp.explanation)

        return ChatResponse(
            explanation=ai_resp.explanation,
            question=ai_resp.question or "",
            hint=ai_resp.hint or "",
            is_correct=is_correct,
            diagnosis=ai_resp.diagnosis or "",
            encouragement=ai_resp.encouragement or "",
            mode=mode.value,
            teacher_type=sess.teacher_type.value,
            teacher_label=teacher_label,
        )

    # ---------------------------------------------------------------
    # 情况 B：用户提出新问题 / 请求讲解
    # ---------------------------------------------------------------
    prompt = build_explain_prompt(req.query, concept_hint="")
    ai_resp = await ask_model(prompt, system_prompt=system_prompt)

    # 记录知识点（从 query 中简单推断）
    concept = req.query[:20]
    state_manager.update_concept(user_id, concept)
    state_manager.set_current_question(user_id, ai_resp.question or "", ai_resp.answer or "")

    # 写入数据库
    db_manager.log_interaction(
        user_id=user_id,
        query=req.query,
        response=ai_resp.explanation,
        mode=mode.value,
        question=ai_resp.question,
        c_load=ai_resp.c_load,
        e_valence=ai_resp.e_valence,
        diagnosis=ai_resp.diagnosis,
    )

    state_manager.record_exchange(user_id, "user", req.query)
    state_manager.record_exchange(user_id, "assistant", ai_resp.explanation)

    return ChatResponse(
        explanation=ai_resp.explanation,
        question=ai_resp.question or "",
        hint=ai_resp.hint or "",
        diagnosis=ai_resp.diagnosis or "",
        mode=mode.value,
        teacher_type=sess.teacher_type.value,
        teacher_label=teacher_label,
    )


@app.post("/proactive")
async def proactive(req: ProactiveRequest):
    """检测思考空窗并触发主动提示"""
    user_id = req.user_id
    sess = state_manager.get_session(user_id)
    if not state_manager.is_silence(user_id):
        return {"triggered": False}

    state_manager.mark_silence_triggered(user_id)
    silence_seconds = int(60)  # 简化计算

    # 为空窗场景生成 system_prompt（基于当前角色）
    sys_prompt = generate_teacher_prompt(
        teacher_type=sess.teacher_type,
        user_mode=sess.mode,
        emotion_state=sess.emotion_state or "专注",
    )

    prompt = build_proactive_prompt(
        last_question=sess.current_question or "当前练习",
        silence_seconds=silence_seconds,
    )
    ai_resp = await ask_model(prompt, system_prompt=sys_prompt, require_structured=True)

    return {
        "triggered": True,
        "hint": ai_resp.hint or "",
        "encouragement": ai_resp.encouragement or "",
        "explanation": ai_resp.explanation or "",
    }


# ---------------------------------------------------------------------------
# 学习进度与角色管理
# ---------------------------------------------------------------------------

class TeacherSwitchRequest(BaseModel):
    user_id: str = Field(default="default_user")
    teacher_type: TeacherType = Field(..., description="要切换到的教师角色")
    emotion_state: str = Field(default="", description="可选：手动指定情绪状态")


class UserStatsResponse(BaseModel):
    user_id: str
    total_questions: int
    correct_count: int
    wrong_count: int
    accuracy: float
    current_teacher: str
    emotion: str
    consecutive_wrong: int
    current_concept: str = ""
    concepts: list = []


@app.post("/switch_teacher")
async def switch_teacher(req: TeacherSwitchRequest):
    """手动切换教师角色或情绪状态"""
    state_manager.set_teacher_type(req.user_id, req.teacher_type)
    if req.emotion_state:
        state_manager.set_emotion_state(req.user_id, req.emotion_state)
    sess = state_manager.get_session(req.user_id)
    label = get_teacher_label(sess.teacher_type, sess.mode)
    return {
        "success": True,
        "teacher_type": sess.teacher_type.value,
        "teacher_label": label,
        "emotion_state": sess.emotion_state,
    }


@app.get("/stats", response_model=UserStatsResponse)
async def get_stats(user_id: str = "default_user"):
    """获取用户学习进度统计"""
    stats = db_manager.get_or_create_user_stats(user_id)
    sess = state_manager.get_session(user_id)
    concepts = db_manager.list_concepts(user_id)

    total = stats.total_questions or 1
    accuracy = round((stats.correct_count / total) * 100, 1) if total > 0 else 0.0

    concept_list = [
        {
            "name": c.concept_name,
            "mastery": round(c.mastery_level, 1),
            "status": c.status,
            "consecutive_wrong": c.consecutive_wrong,
        }
        for c in concepts
    ]

    return UserStatsResponse(
        user_id=user_id,
        total_questions=stats.total_questions,
        correct_count=stats.correct_count,
        wrong_count=stats.wrong_count,
        accuracy=accuracy,
        current_teacher=get_teacher_label(sess.teacher_type, sess.mode),
        emotion=sess.emotion_state or "专注",
        consecutive_wrong=sess.consecutive_wrong,
        current_concept=sess.current_concept or "",
        concepts=concept_list,
    )


# ---------------------------------------------------------------------------
# 调试端点
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "mock_mode": __import__("ai").USE_MOCK}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

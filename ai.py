"""
ai.py - AI 模型调用封装层
支持 DeepSeek / OpenAI，返回结构化 JSON 并使用 Pydantic 校验。
"""

import os
import json
from typing import Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

# ---------------------------------------------------------------------------
# 1. Pydantic 返回结构
# ---------------------------------------------------------------------------

class AIResponse(BaseModel):
    """AI 返回的标准化结构"""
    explanation: str = Field(..., description="对知识点的讲解或引导")
    question: Optional[str] = Field(None, description="生成的练习题")
    answer: Optional[str] = Field(None, description="练习题的标准答案")
    hint: Optional[str] = Field(None, description="若用户卡住，可给出的提示")
    c_load: Optional[float] = Field(None, ge=0.0, le=1.0, description="认知负荷")
    e_valence: Optional[float] = Field(None, ge=-1.0, le=1.0, description="情感效价")
    diagnosis: Optional[str] = Field(None, description="系统诊断说明")
    encouragement: Optional[str] = Field(None, description="鼓励或引导语")
    difficulty_adjustment: Optional[str] = Field(None, description="难度调整建议")


class AISimpleResponse(BaseModel):
    """极简模式下仅需文本回答"""
    content: str = Field(..., description="AI 的纯文本回复")


# ---------------------------------------------------------------------------
# 2. 配置与底层请求
# ---------------------------------------------------------------------------

API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1")
MODEL_NAME = os.getenv("AI_MODEL", "deepseek-chat")
TIMEOUT = 60.0

# Mock 模式：无 API Key 时自动启用
USE_MOCK = os.getenv("AI_MOCK", "false").lower() == "true" or not API_KEY


# ---------------------------------------------------------------------------
# 2.5 Mock 响应数据池（用于无 API Key 本地测试）
# ---------------------------------------------------------------------------

_mock_responses = [
    {
        "explanation": "这是个很棒的问题！让我们一起想想看——如果太阳给植物提供了能量，那植物是用什么'工具'把这些能量储存起来的呢？你觉得是叶子、根还是茎？",
        "question": "如果把植物比作一个小工厂，叶子就像接收太阳能的'太阳能板'。那你知道这个工厂生产出来的'产品'叫什么吗？",
        "answer": "葡萄糖（或有机物/淀粉）",
        "hint": "想想植物身体里那种甜甜的、能给其他动物提供能量的东西，它通常是从叶子开始制造的。",
        "c_load": 0.45,
        "e_valence": 0.3,
        "diagnosis": "学习者表现积极，认知负荷适中",
    },
    {
        "explanation": "不错，已经接近核心了！植物确实用叶子来接收阳光。但我们再深入一步：阳光进入叶子后，植物身体里发生了什么'化学变化'，才把那些能量真正'锁住'的？",
        "question": "植物用叶子里的什么绿色物质来'捕捉'阳光？这种绿色物质的名字是什么？",
        "answer": "叶绿素",
        "hint": "它是让叶子看起来绿色的东西，名字里有'绿'这个字哦。",
        "c_load": 0.55,
        "e_valence": 0.2,
        "diagnosis": "学习者理解较好，需要强化关键概念记忆",
    },
    {
        "explanation": "嗯，让我们再梳理一下思路。光合作用其实有两个关键步骤：先'捕捉'阳光，然后'转化'成能量。你刚才说的阳光属于第一步。那第二步里，植物还需要从空气中吸收什么呢？",
        "question": "除了阳光，植物在进行光合作用时还需要从空气中吸收什么气体？",
        "answer": "二氧化碳",
        "hint": "我们每次呼气时，身体会排出一种气体，植物正好需要它来'吃饭'。",
        "c_load": 0.6,
        "e_valence": 0.1,
        "diagnosis": "学习者对整体流程理解还不够完整，需要拆解步骤",
    },
]

_mock_index = 0


def _mock_ask() -> dict:
    """轮询返回模拟数据"""
    global _mock_index
    resp = _mock_responses[_mock_index % len(_mock_responses)]
    _mock_index += 1
    return resp.copy()


def _parse_json_content(raw: str) -> dict:
    """尝试从 AI 返回的文本中提取 JSON 对象"""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"content": raw}


async def _post_chat(messages: list, temperature: float = 0.7) -> str:
    """向模型发送请求，返回原始字符串"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        # 强制要求 JSON 输出（若供应商支持）
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# 3. 对外接口
# ---------------------------------------------------------------------------

async def ask_model(
    prompt: str,
    system_prompt: str = "",
    require_structured: bool = True,
    temperature: float = 0.7,
) -> AIResponse:
    """
    向 AI 模型提问，返回结构化结果。
    无 API Key 时自动进入 Mock 模式，返回模拟数据。
    system_prompt: 教师人格 system message，为空时退化为默认提示。
    若 require_structured=False，则仅返回 content 字段。
    """
    # Mock 模式：无真实 API Key，返回预设模拟数据
    if USE_MOCK:
        mocked = _mock_ask()
        if not require_structured:
            return AIResponse(explanation=mocked.get("explanation", ""))
        try:
            return AIResponse.model_validate(mocked)
        except ValidationError:
            return AIResponse(explanation=str(mocked))

    sys_msg = system_prompt or "You are a helpful AI tutor. Always respond in valid JSON."
    messages = [
        {"role": "system", "content": sys_msg},
        {"role": "user", "content": prompt},
    ]
    raw = await _post_chat(messages, temperature=temperature)
    parsed = _parse_json_content(raw)

    if not require_structured:
        return AIResponse(explanation=parsed.get("content", ""))

    try:
        return AIResponse.model_validate(parsed)
    except ValidationError:
        # 若校验失败，降级为包裹到 explanation 字段
        return AIResponse(explanation=raw)


async def ask_simple(prompt: str, system_prompt: str = "", temperature: float = 0.7) -> str:
    """仅需要纯文本回答时使用"""
    resp = await ask_model(prompt, system_prompt=system_prompt, require_structured=False, temperature=temperature)
    return resp.explanation

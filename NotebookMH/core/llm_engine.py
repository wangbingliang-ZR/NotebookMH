"""
core/llm_engine.py - 大模型路由与结构化调用 (Phase 2)

职责：
  - 多供应商模型路由 (DeepSeek / OpenAI)
  - Pydantic 结构化响应校验
  - Mock 模式（无 API Key 时自动启用）
  - system_prompt 注入（教师人格）

迁移自根目录 ai.py，去除根目录依赖，适配 NotebookMH 架构。
"""

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

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
# 2. 配置
# ---------------------------------------------------------------------------

_API_KEY = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1")
_MODEL_NAME = os.getenv("AI_MODEL", "deepseek-chat")
_TIMEOUT = 60.0
_USE_MOCK = os.getenv("AI_MOCK", "false").lower() == "true" or not _API_KEY


# ---------------------------------------------------------------------------
# 3. Mock 响应数据池
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


# ---------------------------------------------------------------------------
# 4. 内部工具函数
# ---------------------------------------------------------------------------

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


async def _post_chat(
    messages: list,
    temperature: float = 0.7,
    require_json: bool = True,
) -> str:
    """向模型发送请求，返回原始字符串"""
    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": _MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(f"{_BASE_URL}/chat/completions", headers=headers, json=payload)
        if r.status_code >= 400:
            logger.error("LLM request failed: status=%s body=%s", r.status_code, r.text[:1000])
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# 5. 统一 LLM 引擎
# ---------------------------------------------------------------------------

class UnifiedLLMEngine:
    """统一大模型引擎 —— 支持多供应商路由 + 人格注入 + Mock 降级。"""

    def __init__(self, provider: str = "deepseek") -> None:
        self.provider = provider
        self._registry: Dict[str, Any] = {}

    def register_function(self, name: str, handler: Any) -> None:
        self._registry[name] = handler

    async def chat(
        self,
        prompt: str,
        system_prompt: str = "",
        require_structured: bool = True,
        temperature: float = 0.7,
    ) -> AIResponse:
        """
        向 AI 模型提问，返回结构化结果。
        system_prompt: 教师人格 system message，为空时退化为默认提示。
        """
        if _USE_MOCK:
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
        raw = await _post_chat(
            messages,
            temperature=temperature,
            require_json=require_structured,
        )
        parsed = _parse_json_content(raw)

        if not require_structured:
            return AIResponse(explanation=parsed.get("content", ""))

        try:
            return AIResponse.model_validate(parsed)
        except ValidationError:
            return AIResponse(explanation=raw)

    async def structured_extract[
        T: BaseModel
    ](
        self,
        prompt: str,
        model: type[T],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> T:
        """
        通用结构化提取：将 LLM 输出解析并校验为任意 Pydantic 模型。

        自动注入 JSON Mode，失败时抛出 ValidationError。
        """
        sys_msg = (
            system_prompt
            or "You are a structured data extractor. Always respond in valid JSON matching the requested schema."
        )
        messages = [
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": prompt},
        ]
        raw = await _post_chat(messages, temperature=temperature)
        parsed = _parse_json_content(raw)

        # 某些模型可能嵌套在 extra 字段中
        if "content" in parsed and not any(
            k in parsed for k in model.model_fields.keys()
        ):
            parsed = _parse_json_content(parsed["content"])

        return model.model_validate(parsed)

    async def ask_simple(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        """仅需要纯文本回答时使用"""
        resp = await self.chat(
            prompt,
            system_prompt=system_prompt,
            require_structured=False,
            temperature=temperature,
        )
        return resp.explanation

    async def rag_answer(
        self,
        question: str,
        context_chunks: list[dict],
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> AIResponse:
        """
        RAG 问答专用入口：将检索到的 chunks 拼接为上下文，
        连同 system_prompt 一起发送给 LLM 生成回答。
        """
        # 构建上下文字符串
        context_lines: list[str] = []
        for i, chunk in enumerate(context_chunks, start=1):
            text = chunk.get("chunk_text", "").strip()
            meta = chunk.get("metadata", {})
            source = chunk.get("source", "?")
            if text:
                header = f"[知识片段 #{i}] source={source}"
                if meta.get("header_hierarchy"):
                    header += f" hierarchy={meta['header_hierarchy']}"
                context_lines.append(f"{header}\n{text}")

        context_str = "\n\n---\n\n".join(context_lines) if context_lines else "（无相关知识）"

        rag_prompt = f"""请根据以下检索到的知识片段回答问题。

【用户问题】
{question}

【检索到的知识片段】
{context_str}

【要求】
- 仅基于上述知识片段作答，不要引入外部知识
- 如果知识片段不足以回答，请诚实说明
- 保持你作为教师的人格风格（已在 system prompt 中设定）
- 返回 JSON 格式，包含 explanation 字段
"""
        return await self.chat(
            rag_prompt,
            system_prompt=system_prompt,
            require_structured=True,
            temperature=temperature,
        )


# ---------------------------------------------------------------------------
# 6. 模块级单例
# ---------------------------------------------------------------------------

_llm_singleton: Optional[UnifiedLLMEngine] = None


def get_llm_engine() -> UnifiedLLMEngine:
    """获取全局唯一的 UnifiedLLMEngine 实例。"""
    global _llm_singleton
    if _llm_singleton is None:
        _llm_singleton = UnifiedLLMEngine()
    return _llm_singleton


# ===========================================================================
# Phase 5: Unified Neural Core (兼容式新增，零破坏)
# ===========================================================================
# 职责：
#   - 双轴评估管线 (c_load / e_valence / diagnosis)
#   - 四象限动态策略注入
#   - 用户认知画像聚合 (Phase 3 DB)
#   - 状态穿透 callback (state_sink)
#
# 约束：
#   - 不 import streamlit
#   - LLM JSON 评估 + deterministic fallback 双保险
#   - 旧 API (UnifiedLLMEngine / AIResponse / get_llm_engine) 100% 保留
# ===========================================================================

from typing import Callable, List

from utils.db_manager import db_pool


# ---------------------------------------------------------------------------
# 7. 神经评估数据结构
# ---------------------------------------------------------------------------

class UserCognitiveProfile(BaseModel):
    """用户认知画像 —— 从 Phase 3 DB 聚合。"""
    user_id: str = Field(..., description="用户唯一标识")
    concept_name: Optional[str] = Field(None, description="当前知识点")
    mastery_level: float = Field(50.0, ge=0.0, le=100.0, description="掌握度 0~100")
    total_questions: int = Field(0, description="总答题数")
    correct_count: int = Field(0, description="正确数")
    wrong_count: int = Field(0, description="错误数")
    accuracy: float = Field(0.0, ge=0.0, le=1.0, description="正确率")
    consecutive_wrong: int = Field(0, description="当前连续错误次数")
    recent_diagnoses: List[str] = Field(default_factory=list, description="最近诊断摘要")
    recent_wrong_queries: List[str] = Field(default_factory=list, description="最近错题 query")
    strategy_stats: Any = Field(default=None, description="进化策略基因库 (StrategyGenome)")


class NeuralEvaluation(BaseModel):
    """神经态评估结果 —— 双轴坐标 + 诊断 + 策略。"""
    c_load: float = Field(0.5, ge=0.0, le=1.0, description="认知负荷")
    e_valence: float = Field(0.0, ge=-1.0, le=1.0, description="情感效价")
    diagnosis: str = Field("neutral", description="诊断说明")
    quadrant: str = Field("baseline", description="四象限分类")
    strategy: str = Field("base_learning", description="策略名称")
    concept_name: Optional[str] = Field(None, description="关联知识点")
    mastery_level: float = Field(50.0, description="参考掌握度")


class NeuralStrategy(BaseModel):
    """四象限策略配置。"""
    name: str = Field(..., description="策略标识")
    system_prompt: str = Field(..., description="注入的 system prompt")
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    policy: str = Field("", description="策略描述")


# ---------------------------------------------------------------------------
# 8. 四象限策略 Prompt 常量
# ---------------------------------------------------------------------------

_NEURAL_EVALUATION_PROMPT = """你是认知状态评估器。只输出 JSON，不输出 Markdown 代码块。

输入：
【用户本轮输入】
{user_input}

【最近对话历史】
{chat_history}

【用户认知画像】
- 知识点: {concept_name}
- 掌握度: {mastery_level}/100
- 正确率: {accuracy:.1%}
- 连续错误: {consecutive_wrong} 次
- 最近诊断: {recent_diagnoses}

法则：
1. 同样的问题，对新手(mastery<40)是高负荷，对老手(mastery>70)是低负荷。
2. 连续错误越多，c_load 越高，e_valence 越低。
3. 用户输入含"不会/烦/看不懂/太难了" → e_valence 显著下调。
4. 用户输入很短且消极 → 低 c_load + 负 e_valence（懈怠）。

输出 JSON（严格字段）：
{{
  "c_load": 0.0~1.0,
  "e_valence": -1.0~1.0,
  "diagnosis": "不超过80字的状态诊断"
}}
"""

_STRATEGY_SIMPLIFICATION_EMPATHY = """【降维安抚模式】
用户处于高负荷+负效价，濒临认知崩溃。
你必须：
- 立即降低复杂度，退回生活化类比。
- 用不超过30字给出最小可理解单元。
- 绝对禁止追问、禁止苏格拉底、禁止极端边界问题。
- 语气温和但不过度安慰，聚焦重建信心。
"""

_STRATEGY_PROVOCATION = """【刺探唤醒模式】
用户处于低负荷+负效价，认知懈怠或无聊。
你必须：
- 用一个反直觉的边界问题(Edge-case)打断惯性。
- 不安慰，不迎合，不人身攻击。
- 问题必须简短（≤40字），直接暴露逻辑缺口。
- 禁止长篇解释。
"""

_STRATEGY_SOCRATIC_PRESSURE = """【苏格拉底极压模式】
用户处于高负荷+正效价，深度心流区。
你必须：
- 持续推演，不给最终答案。
- 每次回复以追问结尾。
- 允许最小提示、反例、伪代码片段。
- 禁止完整答案、禁止类比。
"""

_STRATEGY_BASE_LEARNING = """【基础学习模式】
常规区间，维持标准教学流。
- 正常引导、正常追问。
- 结合人格 prompt 和 RAG 上下文作答。
"""

# 四象限策略映射表
_QUADRANT_STRATEGIES: Dict[str, NeuralStrategy] = {
    "collapse": NeuralStrategy(
        name="simplification_empathy",
        system_prompt=_STRATEGY_SIMPLIFICATION_EMPATHY,
        temperature=0.5,
        policy="高负荷+负效价 → 降维安抚",
    ),
    "provocation": NeuralStrategy(
        name="provocation",
        system_prompt=_STRATEGY_PROVOCATION,
        temperature=0.8,
        policy="低负荷+负效价 → 刺探唤醒",
    ),
    "socratic_pressure": NeuralStrategy(
        name="socratic_pressure",
        system_prompt=_STRATEGY_SOCRATIC_PRESSURE,
        temperature=0.6,
        policy="高负荷+正效价 → 苏格拉底极压",
    ),
    "baseline": NeuralStrategy(
        name="base_learning",
        system_prompt=_STRATEGY_BASE_LEARNING,
        temperature=0.7,
        policy="常规区间 → 基础学习",
    ),
}


# ---------------------------------------------------------------------------
# 9. 统一神经核心
# ---------------------------------------------------------------------------

class UnifiedNeuralCore:
    """
    统一神经核心 —— 认知调度中枢 (Phase 5)。

    架构位置：
      位于 UnifiedLLMEngine 之上，负责：
      1. 聚合用户认知画像 (Phase 3 DB)
      2. 双轴神经评估 (c_load / e_valence)
      3. 四象限策略选择
      4. 动态 prompt 注入 → 调用底层 UnifiedLLMEngine
      5. 状态穿透 (通过 state_sink callback)

    零 Streamlit 依赖，零 UI 逻辑。
    """

    def __init__(
        self,
        llm: Optional[UnifiedLLMEngine] = None,
    ) -> None:
        self._llm = llm or get_llm_engine()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def generate_response(
        self,
        user_input: str,
        user_id: str = "anonymous",
        chat_history: Optional[List[dict]] = None,
        context_chunks: Optional[List[dict]] = None,
        concept_name: Optional[str] = None,
        state_sink: Optional[Callable[[NeuralEvaluation], None]] = None,
    ) -> AIResponse:
        """
        统一神经响应入口。

        执行链：
          1. 构建 UserCognitiveProfile
          2. evaluate_state() → NeuralEvaluation
          3. _select_strategy() → NeuralStrategy
          4. 动态 system_prompt 注入
          5. LLM 生成回答
          6. state_sink(evaluation) 状态穿透

        Args:
            user_input: 用户本轮输入文本。
            user_id: 用户标识，用于 DB 画像聚合。
            chat_history: 最近对话历史（建议最后 5 轮）。
            context_chunks: RAG 检索到的知识片段（可选）。
            concept_name: 当前知识点名称（可选）。
            state_sink: 状态穿透回调，接收 NeuralEvaluation。
                          由 UI 层传入，用于写入 st.session_state。

        Returns:
            AIResponse: 结构化 AI 回复。
        """
        # 1. 认知画像
        profile = self._build_profile(user_id, concept_name)

        # 2. 神经评估
        evaluation = await self.evaluate_state(
            user_input=user_input,
            profile=profile,
            chat_history=chat_history or [],
        )

        # 3. 策略选择
        strategy = self._select_strategy(evaluation, profile)
        evaluation.strategy = strategy.name
        evaluation.quadrant = self._classify_quadrant(evaluation)
        # Phase 7: 遥测事件
        from utils.telemetry_events import log_route
        log_route(arm=strategy.name, quadrant=evaluation.quadrant, score=strategy.policy)

        # 4. 动态 prompt 构建 (Phase 6A: PromptCompiler JIT 编译)
        from utils.prompt_templates import PromptCompiler
        compiler = PromptCompiler()
        genome = profile.strategy_stats
        arm_stats = genome.arms.get(strategy.name) if genome else None
        arm_score = f"pulls={arm_stats.pulls} reward={arm_stats.reward:.1f}" if arm_stats else "N/A"
        system_prompt = compiler.compile(
            selected_arm=strategy.name,
            task_prompt="",  # 通用入口，无特定任务 prompt
            c_load=evaluation.c_load,
            e_valence=evaluation.e_valence,
            mastery_level=profile.mastery_level,
            arm_score=arm_score,
        )

        # 5. 生成回答
        if context_chunks:
            resp = await self._llm.rag_answer(
                question=user_input,
                context_chunks=context_chunks,
                system_prompt=system_prompt,
                temperature=strategy.temperature,
            )
        else:
            resp = await self._llm.chat(
                prompt=user_input,
                system_prompt=system_prompt,
                require_structured=True,
                temperature=strategy.temperature,
            )

        # 6. 状态穿透
        if state_sink is not None:
            try:
                state_sink(evaluation)
            except Exception as e:
                logger.warning("state_sink failed (ignored): %s", e)

        logger.info(
            "NeuralCore generated: quadrant=%s strategy=%s c_load=%.2f e_val=%.2f",
            evaluation.quadrant, strategy.name, evaluation.c_load, evaluation.e_valence,
        )
        return resp

    async def evaluate_state(
        self,
        user_input: str,
        profile: UserCognitiveProfile,
        chat_history: List[dict],
    ) -> NeuralEvaluation:
        """
        双轴神经评估 —— LLM JSON + deterministic fallback。

        Args:
            user_input: 用户输入。
            profile: 认知画像。
            chat_history: 最近对话历史。

        Returns:
            NeuralEvaluation: 包含 c_load / e_valence / diagnosis。
        """
        # 构建历史文本
        history_text = self._format_chat_history(chat_history)
        recent_diagnoses = "; ".join(profile.recent_diagnoses[:3]) or "无"

        eval_prompt = _NEURAL_EVALUATION_PROMPT.format(
            user_input=user_input,
            chat_history=history_text,
            concept_name=profile.concept_name or "未指定",
            mastery_level=profile.mastery_level,
            accuracy=profile.accuracy,
            consecutive_wrong=profile.consecutive_wrong,
            recent_diagnoses=recent_diagnoses,
        )

        try:
            # LLM 评估
            eval_resp = await self._llm.chat(
                prompt="请评估当前用户的认知状态和情感效价。",
                system_prompt=eval_prompt,
                require_structured=True,
                temperature=0.3,  # 低温度，减少幻觉
            )
            raw = eval_resp.explanation
            data = _parse_json_content(raw)

            c_load = float(data.get("c_load", 0.5))
            e_valence = float(data.get("e_valence", 0.0))
            diagnosis = str(data.get("diagnosis", "neutral"))

            # 边界裁剪
            c_load = max(0.0, min(1.0, c_load))
            e_valence = max(-1.0, min(1.0, e_valence))

            evaluation = NeuralEvaluation(
                c_load=c_load,
                e_valence=e_valence,
                diagnosis=diagnosis,
                concept_name=profile.concept_name,
                mastery_level=profile.mastery_level,
            )

        except Exception as e:
            logger.warning("LLM evaluation failed, using fallback: %s", e)
            evaluation = self._fallback_evaluation(user_input, profile)

        # 用确定性启发式二次修正（mastery-level-aware）
        evaluation = self._heuristic_adjust(evaluation, user_input, profile)
        return evaluation

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _build_profile(
        self,
        user_id: str,
        concept_name: Optional[str] = None,
    ) -> UserCognitiveProfile:
        """从 Phase 3 DB 聚合用户认知画像。"""
        stats = db_pool.get_or_create_user_stats(user_id)
        concepts = db_pool.list_concepts(user_id)

        # 查找当前知识点
        target_concept = None
        if concept_name:
            target_concept = db_pool.get_concept(user_id, concept_name)
        if not target_concept and concepts:
            # 取最近交互的知识点
            from datetime import datetime, timezone
            target_concept = max(
                concepts,
                key=lambda c: c.last_interaction or datetime.min.replace(tzinfo=timezone.utc),
            )

        mastery = target_concept.mastery_level if target_concept else 50.0
        consecutive_wrong = target_concept.consecutive_wrong if target_concept else 0
        total = stats.total_questions or 0
        correct = stats.correct_count or 0
        accuracy = (correct / total) if total > 0 else 0.0

        # 最近错题诊断
        wrong_logs = db_pool.get_wrong_logs(user_id, limit=5)
        recent_diagnoses = [log.diagnosis for log in wrong_logs if log.diagnosis]
        recent_queries = [log.query for log in wrong_logs if log.query]

        # ── Phase 6A: 进化策略基因库 ──────────────────────────
        genome = None
        try:
            from utils.evolutionary_strategy import (
                StrategyGenome,
                genome_from_dict,
            )
            raw_weights = stats.weights or "{}"
            import json
            weights = json.loads(raw_weights) if isinstance(raw_weights, str) else raw_weights
            if weights and "evolutionary_prompt_stats" in weights:
                genome = genome_from_dict(weights["evolutionary_prompt_stats"])
            else:
                genome = StrategyGenome()  # 默认初始化四条臂
        except Exception as e:
            logger.warning("Failed to load strategy genome for user %s: %s", user_id, e)
            from utils.evolutionary_strategy import StrategyGenome
            genome = StrategyGenome()

        return UserCognitiveProfile(
            user_id=user_id,
            concept_name=concept_name or (target_concept.concept_name if target_concept else None),
            mastery_level=mastery,
            total_questions=total,
            correct_count=correct,
            wrong_count=stats.wrong_count or 0,
            accuracy=accuracy,
            consecutive_wrong=consecutive_wrong,
            recent_diagnoses=recent_diagnoses,
            recent_wrong_queries=recent_queries,
            strategy_stats=genome,
        )

    def _select_strategy(
        self,
        evaluation: NeuralEvaluation,
        profile: UserCognitiveProfile,
    ) -> NeuralStrategy:
        """
        基于评估结果选择四象限策略。
        Phase 6A 升级: 先四象限过滤，再用 UCB1 在允许的臂中选择最优。
        """
        quadrant = self._classify_quadrant(evaluation)

        # UCB1 动态选择（在允许的安全臂集合中）
        from utils.evolutionary_strategy import select_arm_ucb1
        genome = profile.strategy_stats
        if genome is None:
            from utils.evolutionary_strategy import StrategyGenome
            genome = StrategyGenome()

        selected_arm = select_arm_ucb1(genome, quadrant=quadrant, exploration_c=1.5)

        # 映射到 NeuralStrategy（温度由臂特性决定）
        _ARM_TEMPERATURE = {
            "Socratic_Pressure": 0.6,
            "First_Principles": 0.5,
            "Concrete_Analogy": 0.5,
            "Pragmatic_Execution": 0.7,
        }

        stats = genome.arms.get(selected_arm)
        arm_score_str = f"pulls={stats.pulls} reward={stats.reward:.1f}" if stats else "N/A"

        return NeuralStrategy(
            name=selected_arm.value,
            system_prompt="",  # 占位: 由 PromptCompiler 在调用方 JIT 编译
            temperature=_ARM_TEMPERATURE.get(selected_arm.value, 0.7),
            policy=f"UCB1 arm={selected_arm.value} quadrant={quadrant} score={arm_score_str}",
        )

    @staticmethod
    def _classify_quadrant(evaluation: NeuralEvaluation) -> str:
        """返回象限分类字符串（仅用于日志/遥测）。"""
        c = evaluation.c_load
        e = evaluation.e_valence
        if c > 0.75 and e < -0.4:
            return "collapse"
        if c < 0.4 and e < -0.4:
            return "provocation"
        if c > 0.7 and e > 0.4:
            return "socratic_pressure"
        return "baseline"

    @staticmethod
    def _build_system_prompt(
        strategy: NeuralStrategy,
        profile: UserCognitiveProfile,
    ) -> str:
        """组装最终 system_prompt：策略 + 画像上下文。"""
        profile_ctx = (
            f"\n\n【用户画像】掌握度 {profile.mastery_level:.0f}/100，"
            f"正确率 {profile.accuracy:.0%}，连续错误 {profile.consecutive_wrong} 次。"
        )
        return strategy.system_prompt + profile_ctx

    @staticmethod
    def _format_chat_history(history: List[dict]) -> str:
        """格式化对话历史为评估器可读的文本。"""
        lines = []
        for turn in history[-5:]:  # 最后 5 轮
            role = turn.get("role", "?")
            content = turn.get("content", "")
            lines.append(f"[{role}] {content[:100]}")
        return "\n".join(lines) if lines else "（无历史）"

    @staticmethod
    def _fallback_evaluation(
        user_input: str,
        profile: UserCognitiveProfile,
    ) -> NeuralEvaluation:
        """
        确定性 Fallback 评估 —— LLM 失败或 Mock 模式时兜底。

        规则：
          - mastery < 40 → c_load +0.2
          - consecutive_wrong >= 2 → c_load +0.2, e_valence -0.3
          - 用户输入含消极词 → e_valence -0.4
          - 用户输入很短(<5字) + 消极 → 低负荷懈怠 (provocation 区)
        """
        c_load = 0.5
        e_valence = 0.0
        diagnosis = "fallback: neutral"

        # mastery 修正
        if profile.mastery_level < 40:
            c_load = min(1.0, c_load + 0.2)
            diagnosis = "fallback: low mastery → elevated load"
        elif profile.mastery_level > 75:
            c_load = max(0.0, c_load - 0.15)

        # 连续错误修正
        if profile.consecutive_wrong >= 2:
            c_load = min(1.0, c_load + 0.2)
            e_valence = max(-1.0, e_valence - 0.3)
            diagnosis = f"fallback: {profile.consecutive_wrong} consecutive wrong"

        # 语言情绪修正
        negative_words = ["不会", "烦", "看不懂", "太难了", "没意思", "放弃", "无聊"]
        positive_words = ["懂了", "明白", "有趣", "简单", "喜欢", "再来"]

        lowered = user_input.lower()
        if any(w in lowered for w in negative_words):
            e_valence = max(-1.0, e_valence - 0.4)
            c_load = min(1.0, c_load + 0.1)
            diagnosis = "fallback: negative sentiment detected"
        elif any(w in lowered for w in positive_words):
            e_valence = min(1.0, e_valence + 0.3)
            diagnosis = "fallback: positive sentiment detected"

        # 极短输入 + 消极 → 懈怠
        if len(user_input.strip()) < 6 and e_valence < -0.2:
            c_load = max(0.0, c_load - 0.3)  # 低负荷
            diagnosis = "fallback: short input + negative → boredom"

        return NeuralEvaluation(
            c_load=round(c_load, 2),
            e_valence=round(e_valence, 2),
            diagnosis=diagnosis,
            concept_name=profile.concept_name,
            mastery_level=profile.mastery_level,
        )

    @staticmethod
    def _heuristic_adjust(
        evaluation: NeuralEvaluation,
        user_input: str,
        profile: UserCognitiveProfile,
    ) -> NeuralEvaluation:
        """
        用确定性启发式二次修正 LLM 评估结果。
        确保 mastery-level-aware 和 sentiment-aware。
        """
        c = evaluation.c_load
        e = evaluation.e_valence

        # mastery 修正
        if profile.mastery_level < 40:
            c = min(1.0, c + 0.1)
        elif profile.mastery_level > 75:
            c = max(0.0, c - 0.1)

        # 连续错误修正
        if profile.consecutive_wrong >= 2:
            c = min(1.0, c + 0.1)
            e = max(-1.0, e - 0.2)

        # 消极语言二次确认
        negative_words = ["不会", "烦", "看不懂", "太难了", "没意思"]
        if any(w in user_input.lower() for w in negative_words):
            e = max(-1.0, e - 0.2)

        # 极短输入 → 降负荷（可能是懒得打）
        if len(user_input.strip()) < 6:
            c = max(0.0, c - 0.15)

        evaluation.c_load = round(max(0.0, min(1.0, c)), 2)
        evaluation.e_valence = round(max(-1.0, min(1.0, e)), 2)
        return evaluation


# ---------------------------------------------------------------------------
# 10. 神经核心模块级单例
# ---------------------------------------------------------------------------

_neural_singleton: Optional[UnifiedNeuralCore] = None


def get_neural_core() -> UnifiedNeuralCore:
    """获取全局唯一的 UnifiedNeuralCore 实例。"""
    global _neural_singleton
    if _neural_singleton is None:
        _neural_singleton = UnifiedNeuralCore()
    return _neural_singleton

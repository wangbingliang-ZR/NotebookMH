"""
core/cognitive_engine.py - 认知控制引擎 (Phase 2B)

职责：
  - 认知状态机：learning / quizzing / review 三态严格路由
  - 苏格拉底压制协议：绝不直接给答案
  - 结构化出题：JSON Schema 强制约束
  - 概念诊断：手术刀式剖析混淆点

架构：
  - 底层调用 UnifiedLLMEngine.chat() / rag_answer()
  - 检索调用 rag_pipeline.get_pipeline().retrieve()
  - Prompt 全部来自 utils.prompt_templates

零 UI 逻辑，纯后端路由引擎。
"""

import json
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pydantic import BaseModel, Field, ValidationError

from core.llm_engine import (
    UnifiedLLMEngine,
    UnifiedNeuralCore,
    get_llm_engine,
    get_neural_core,
)
from core.mab_engine import MABEngine, get_mab_engine
from core.rag_pipeline import get_pipeline
from utils.db_manager import db_pool
from utils.prompt_templates import (
    DIAGNOSTIC_EVALUATOR_PROMPT,
    QUIZ_GENERATOR_PROMPT,
    SOCRATIC_TEACHER_PROMPT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. 认知状态枚举
# ---------------------------------------------------------------------------

class CognitiveState(str, Enum):
    LEARNING = "learning"      # 深度剖析
    QUIZZING = "quizzing"      # 实战测验
    REVIEW = "review"          # 错题清算


# ---------------------------------------------------------------------------
# 2. 结构化数据模型
# ---------------------------------------------------------------------------

class QuizItem(BaseModel):
    """测验题的标准化结构 —— 由 LLM 按 QUIZ_GENERATOR_PROMPT 生成。"""
    question: str = Field(..., description="场景应用题")
    hidden_answer: str = Field(..., description="标准答案要点（对用户不可见）")
    difficulty: str = Field(default="medium", description="难度标签")
    hint_for_stuck: str = Field(default="", description="最小提示")
    diagnosis_template: str = Field(default="", description="答错诊断模板句")


class DiagnosticResult(BaseModel):
    """诊断结果 —— 由 LLM 按 DIAGNOSTIC_EVALUATOR_PROMPT 生成。"""
    diagnosis: str = Field(..., description="概念混淆点精确剖析")
    gap: str = Field(default="", description="与标准答案的具体差距")
    retry_prompt: str = Field(..., description="引导重试的追问句")
    mastery_delta: float = Field(default=0.0, description="掌握度修正值")


# ---------------------------------------------------------------------------
# 3. 认知控制引擎
# ---------------------------------------------------------------------------

class CognitiveEngine:
    """
    认知控制引擎 —— 决定论的 LLM 路由层。

    核心约束：
      - current_state 必须是 CognitiveState 之一，否则直接抛出 ValueError。
      - 不允许任何 "默认兜底" 的宽松处理；阻断性错误必须暴露确切原因。
      - 所有 LLM 输出必须经 Pydantic 校验，校验失败即抛 ValidationError。
    """

    def __init__(
        self,
        llm: Optional[UnifiedLLMEngine] = None,
        mab: Optional[MABEngine] = None,
        neural_core: Optional[UnifiedNeuralCore] = None,
    ) -> None:
        self._llm = llm or get_llm_engine()
        self._pipeline = get_pipeline()
        self._mab = mab or get_mab_engine()
        self._neural_core = neural_core or get_neural_core()
        # 内存态：当前测验题（quizzing 模式下使用）
        self._active_quiz: Optional[QuizItem] = None
        # 连续答错计数（用于苏格拉底模式的类比解锁）
        self._consecutive_wrong = 0
        # 当前 MAB 选择记录（用于后续更新）
        self._last_mab_choice: Optional[Dict[str, str]] = None
        # Phase 6B: 启动 decay 标记（每用户每 session 只执行一次）
        self._decay_done_for_user: Set[str] = set()
        # Phase 6B: 上轮 e_valence 缓存（用于 delta 计算）
        self._last_e_valence: float = 0.0

    # ------------------------------------------------------------------
    # 公共 API：状态路由入口
    # ------------------------------------------------------------------

    async def generate_response(
        self,
        user_input: str,
        current_state: CognitiveState,
        vault_uuid: str = "default_vault",
        top_k: int = 5,
        user_id: str = "anonymous",
        chat_history: Optional[List[dict]] = None,
        state_sink: Optional[Callable[[Any], None]] = None,
        selected_sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        认知状态机的唯一入口。

        返回值结构：
          learning  → {"type": "socratic", "text": str, "probe": str}
          quizzing  → {"type": "quiz",    "quiz": QuizItem}
          review    → {"type": "diagnostic", "result": DiagnosticResult}
        """
        if not isinstance(current_state, CognitiveState):
            raise ValueError(
                f"current_state 必须是 CognitiveState 枚举值，"
                f"收到 {type(current_state).__name__}({current_state!r})"
            )

        # ── Phase 6B: 启动 Time Decay（每用户每 session 一次）
        self._apply_startup_decay(user_id)

        # ── Phase 5: 神经评估 ───────────────────────────────
        # 构建认知画像并做四象限评估
        profile = self._neural_core._build_profile(user_id)
        evaluation = await self._neural_core.evaluate_state(
            user_input=user_input,
            profile=profile,
            chat_history=chat_history or [],
        )
        strategy = self._neural_core._select_strategy(evaluation, profile)
        evaluation.strategy = strategy.name
        evaluation.quadrant = self._neural_core._classify_quadrant(evaluation)

        # 状态穿透
        if state_sink is not None:
            try:
                state_sink(evaluation)
            except Exception as e:
                logger.warning("state_sink failed (ignored): %s", e)

        logger.info(
            "Neural evaluation: quadrant=%s strategy=%s c_load=%.2f e_val=%.2f",
            evaluation.quadrant, strategy.name, evaluation.c_load, evaluation.e_valence,
        )

        # 统一检索上下文（learning / quizzing / review 都需要）
        # 空列表视为未选择（不过滤），只有非空列表才过滤
        filter_hashes = selected_sources if selected_sources else None
        chunks = await self._pipeline.retrieve(user_input, vault_uuid, top_k=top_k, content_hashes=filter_hashes)
        context = self._build_context(chunks)

        if current_state == CognitiveState.LEARNING:
            if chat_history:
                recent_history = ""
                for msg in chat_history[-10:]:
                    role_label = "用户" if msg.get("role") == "user" else "助手"
                    recent_history += f"{role_label}: {msg.get('content', '')}\n"
                context = f"对话历史:\n{recent_history}\n\n参考资料:\n{context}"
            return await self._learning_flow(user_input, context, chunks, strategy, profile, evaluation)

        if current_state == CognitiveState.QUIZZING:
            return await self._quizzing_flow(user_input, context, strategy, profile, evaluation)

        if current_state == CognitiveState.REVIEW:
            return await self._review_flow(user_input, context, user_id, strategy, profile, evaluation)

        # 不可达，但保留防御
        raise RuntimeError(f"未处理的状态: {current_state}")

    # ------------------------------------------------------------------
    # 状态流：Learning（苏格拉底压制）
    # ------------------------------------------------------------------

    async def _learning_flow(
        self, user_input: str, context: str, chunks: List[Dict[str, Any]],
        strategy: Any, profile: Any, evaluation: Any,
    ) -> Dict[str, Any]:
        """
        强制调用 SOCRATIC_TEACHER_PROMPT + 四象限策略注入。
        Phase 6A: 使用 PromptCompiler JIT 编译 system_prompt。
        返回 {"type": "socratic", "text": ..., "probe": ..., "source_chunks": [...]}
        """
        from utils.prompt_templates import PromptCompiler
        compiler = PromptCompiler()

        # 获取该臂的 UCB1 统计摘要
        genome = profile.strategy_stats
        stats = genome.arms.get(strategy.name) if genome else None
        arm_score = f"pulls={stats.pulls} reward={stats.reward:.1f}" if stats else "N/A"

        task_prompt = SOCRATIC_TEACHER_PROMPT.format(context=context, question=user_input)
        system_prompt = compiler.compile(
            selected_arm=strategy.name,
            task_prompt=task_prompt,
            c_load=evaluation.c_load,
            e_valence=evaluation.e_valence,
            mastery_level=profile.mastery_level,
            arm_score=arm_score,
        )
        system_prompt += "\n\n请根据上述编号的知识片段回答问题。在回答中用 [1] [2] 等标注你引用了哪个片段。"

        resp = await self._llm.chat(
            prompt=user_input,
            system_prompt=system_prompt,
            require_structured=False,
            temperature=strategy.temperature,
        )

        text = resp.explanation.strip()
        # 提取最后一个反问句作为 probe
        probe = self._extract_probe(text)

        return {
            "type": "socratic",
            "text": text,
            "probe": probe,
            "context_snippets": len(context.split("---")),
        }

    # ------------------------------------------------------------------
    # 状态流：Quizzing（结构化出题 + 诊断）
    # ------------------------------------------------------------------

    async def _quizzing_flow(
        self, user_input: str, context: str,
        strategy: Any, profile: Any, evaluation: Any,
    ) -> Dict[str, Any]:
        """
        如果当前没有 active_quiz，则出题；
        如果已有 active_quiz，则进入诊断流程。

        返回 {"type": "quiz", ...} 或 {"type": "diagnostic", ...}
        """
        # 若用户尚未回答任何题目（首次进入 quizzing 或上一轮已清算）
        if self._active_quiz is None:
            return await self._generate_quiz(context, strategy, profile, evaluation)

        # 否则：用户已作答，进入诊断
        return await self._evaluate_answer(user_input, strategy, profile, evaluation)

    async def _generate_quiz(
        self, context: str, strategy: Any, profile: Any, evaluation: Any,
    ) -> Dict[str, Any]:
        # MAB 动态选择策略组合
        mab_choice = self._mab.select_all()
        self._last_mab_choice = mab_choice
        difficulty_hint = self._resolve_difficulty_hint(mab_choice.get("difficulty"))

        from utils.prompt_templates import PromptCompiler
        compiler = PromptCompiler()
        genome = profile.strategy_stats
        stats = genome.arms.get(strategy.name) if genome else None
        arm_score = f"pulls={stats.pulls} reward={stats.reward:.1f}" if stats else "N/A"

        task_prompt = QUIZ_GENERATOR_PROMPT.format(
            context=context,
            difficulty_hint=difficulty_hint,
        )
        system_prompt = compiler.compile(
            selected_arm=strategy.name,
            task_prompt=task_prompt,
            c_load=evaluation.c_load,
            e_valence=evaluation.e_valence,
            mastery_level=profile.mastery_level,
            arm_score=arm_score,
        )

        resp = await self._llm.chat(
            prompt="请基于检索到的知识片段生成一道场景应用题。",
            system_prompt=system_prompt,
            require_structured=True,
            temperature=strategy.temperature,
        )

        raw = resp.explanation
        # 尝试从 explanation 中解析 JSON
        quiz_data = self._safe_parse_json(raw)
        if not quiz_data:
            raise ValidationError(
                f"QUIZ_GENERATOR_PROMPT 未返回可解析 JSON: {raw[:200]}"
            )

        quiz = QuizItem.model_validate(quiz_data)
        self._active_quiz = quiz
        self._consecutive_wrong = 0

        return {
            "type": "quiz",
            "quiz": quiz.model_dump(),
            "display": quiz.question,
        }

    async def _evaluate_answer(
        self, user_answer: str, strategy: Any, profile: Any, evaluation: Any,
    ) -> Dict[str, Any]:
        if self._active_quiz is None:
            raise RuntimeError("_evaluate_answer 被调用但 _active_quiz 为 None")

        from utils.prompt_templates import PromptCompiler
        compiler = PromptCompiler()
        genome = profile.strategy_stats
        stats = genome.arms.get(strategy.name) if genome else None
        arm_score = f"pulls={stats.pulls} reward={stats.reward:.1f}" if stats else "N/A"

        task_prompt = DIAGNOSTIC_EVALUATOR_PROMPT.format(
            question=self._active_quiz.question,
            hidden_answer=self._active_quiz.hidden_answer,
            user_answer=user_answer,
        )
        system_prompt = compiler.compile(
            selected_arm=strategy.name,
            task_prompt=task_prompt,
            c_load=evaluation.c_load,
            e_valence=evaluation.e_valence,
            mastery_level=profile.mastery_level,
            arm_score=arm_score,
        )

        resp = await self._llm.chat(
            prompt="请诊断用户的答案。",
            system_prompt=system_prompt,
            require_structured=True,
            temperature=strategy.temperature,
        )

        raw = resp.explanation
        diag_data = self._safe_parse_json(raw)
        if not diag_data:
            raise ValidationError(
                f"DIAGNOSTIC_EVALUATOR_PROMPT 未返回可解析 JSON: {raw[:200]}"
            )

        result = DiagnosticResult.model_validate(diag_data)

        # 更新连续错误计数
        if result.mastery_delta <= 0:
            self._consecutive_wrong += 1
        else:
            self._consecutive_wrong = 0

        # 诊断后清除当前题目，等待下一轮出题
        self._active_quiz = None

        # MAB 更新
        if self._last_mab_choice:
            self._mab.update(
                strategy=self._last_mab_choice.get("strategy", "socratic"),
                difficulty=self._last_mab_choice.get("difficulty", "medium"),
                qtype=self._last_mab_choice.get("type", "concept"),
                is_correct=result.mastery_delta > 0,
                c_load=None,
                e_valence=None,
            )
            # 持久化到 SQLite（读取当前用户，避免硬编码）
            from utils.state_manager import binder
            _current_user = binder.get_state("user_id", "anonymous")
            db_pool.update_user_stats(
                user_id=_current_user,
                weights=self._mab.serialize(),
            )

        # ── Phase 6B: Reward 反向传播 ─────────────────────────
        self._update_strategy_reward(profile, strategy, evaluation, result)

        return {
            "type": "diagnostic",
            "result": result.model_dump(),
            "display": result.diagnosis,
            "retry": result.retry_prompt,
            "mab_report": self._mab.report(),
        }

    # ------------------------------------------------------------------
    # 状态流：Review（错题清算）
    # ------------------------------------------------------------------

    async def _review_flow(
        self, user_input: str, context: str, user_id: str,
        strategy: Any, profile: Any, evaluation: Any,
    ) -> Dict[str, Any]:
        """
        Review 模式：从 SQLite 读取真实错题，基于薄弱知识点重新出题并追问。
        """
        # 读取最近错题
        wrong_logs = db_pool.get_wrong_logs(user_id, limit=10)

        # 构建薄弱知识点诊断文本
        review_fragments: List[str] = []
        if wrong_logs:
            for i, log in enumerate(wrong_logs[:5], 1):
                diagnosis = (log.diagnosis or "未记录诊断")[:60]
                review_fragments.append(
                    f"[错题 #{i}] 问题: {log.query[:50]}... 诊断: {diagnosis}"
                )
            weak_points = "\n".join(review_fragments)
            review_context = (
                f"【用户最近错题记录】\n{weak_points}\n\n"
                f"【检索到的相关知识】\n{context}"
            )
        else:
            review_context = context

        from utils.prompt_templates import PromptCompiler
        compiler = PromptCompiler()
        genome = profile.strategy_stats
        stats = genome.arms.get(strategy.name) if genome else None
        arm_score = f"pulls={stats.pulls} reward={stats.reward:.1f}" if stats else "N/A"

        task_prompt = (
            SOCRATIC_TEACHER_PROMPT.format(context=review_context, question=user_input)
            + "\n\n【当前为 Review 模式】\n"
            "你的任务是帮助用户清算之前的错误知识点。"
            "不要重复之前讲过的完整内容，只针对用户最薄弱的环节进行追问。"
            "如果用户答对了薄弱点的追问，给予简短肯定并继续深挖下一个薄弱点。"
        )
        system_prompt = compiler.compile(
            selected_arm=strategy.name,
            task_prompt=task_prompt,
            c_load=evaluation.c_load,
            e_valence=evaluation.e_valence,
            mastery_level=profile.mastery_level,
            arm_score=arm_score,
        )

        resp = await self._llm.chat(
            prompt=user_input,
            system_prompt=system_prompt,
            require_structured=False,
            temperature=strategy.temperature,
        )

        text = resp.explanation.strip()
        probe = self._extract_probe(text)

        return {
            "type": "review",
            "text": text,
            "probe": probe,
        }

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(chunks: List[Dict[str, Any]]) -> str:
        """将检索 chunks 拼接为上下文字符串。"""
        lines: List[str] = []
        for i, chunk in enumerate(chunks, start=1):
            text = chunk.get("chunk_text", "").strip()
            if text:
                lines.append(f"[{i}] {text}")
        return "\n\n".join(lines) if lines else "（无相关知识）"

    @staticmethod
    def _extract_probe(text: str) -> str:
        """从回复文本中提取最后一个反问句作为追问 probe。"""
        # 简单启发式：找最后一个以 "?" 或 "？" 结尾的句子
        sentences = [s.strip() for s in text.replace("？", "?").split("?") if s.strip()]
        if sentences:
            last = sentences[-1]
            # 取最后一句前面的部分作为完整句子
            # 这里简化处理：返回最后一个问号前面的整句
            return last.split("\n")[-1].strip() + "?"
        return "你能再深入一步，说明背后的原因吗？"

    @staticmethod
    def _safe_parse_json(raw: str) -> Optional[dict]:
        """尝试从文本中提取 JSON 对象。"""
        raw = raw.strip()
        # 尝试去 markdown 代码块
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
            return None

    def _resolve_difficulty_hint(self, mab_difficulty: Optional[str] = None) -> str:
        """根据连续错误次数 + MAB 难度选择，决定出题难度提示。"""
        # MAB 优先
        if mab_difficulty == "easy":
            return "MAB 建议简单难度，出基础概念题"
        if mab_difficulty == "hard":
            return "MAB 建议困难难度，出深度应用题"
        # 兜底：连续错误自适应
        if self._consecutive_wrong >= 2:
            return "用户连续答错，请降低难度，出极简单的基础概念题"
        if self._consecutive_wrong == 1:
            return "用户上一次答错，请出中等难度题，聚焦之前混淆的知识点"
        return "用户状态正常，出中等难度场景应用题"

    # ------------------------------------------------------------------
    # Phase 6B: 进化策略奖励与衰减
    # ------------------------------------------------------------------

    def _apply_startup_decay(self, user_id: str) -> None:
        """每用户每 session 只执行一次的 Time Decay。"""
        if user_id in self._decay_done_for_user:
            return

        try:
            from utils.evolutionary_strategy import (
                StrategyGenome,
                apply_time_decay,
                genome_from_dict,
                genome_to_dict,
            )
            stats = db_pool.get_or_create_user_stats(user_id)
            raw_weights = stats.weights or "{}"
            weights = json.loads(raw_weights) if isinstance(raw_weights, str) else (raw_weights or {})

            if "evolutionary_prompt_stats" in weights:
                genome = genome_from_dict(weights["evolutionary_prompt_stats"])
                if isinstance(genome, StrategyGenome):
                    decayed = apply_time_decay(genome, decay=0.95)
                    weights["evolutionary_prompt_stats"] = genome_to_dict(decayed)
                    db_pool.update_user_stats(user_id=user_id, weights=weights)
                    # Phase 7: 遥测事件
                    from utils.telemetry_events import log_decay
                    log_decay()
                    logger.info("Time decay applied for user %s", user_id)
        except Exception as e:
            logger.warning("Startup decay failed for user %s: %s", user_id, e)

        self._decay_done_for_user.add(user_id)

    def _update_strategy_reward(
        self,
        profile: Any,
        strategy: Any,
        evaluation: Any,
        result: "DiagnosticResult",
    ) -> None:
        """Reward 反向传播 —— diagnostic 结束时更新被选臂的 reward。"""
        try:
            from utils.evolutionary_strategy import (
                NeuralRewardCalculator,
                StrategyArm,
                StrategyGenome,
                genome_to_dict,
            )

            genome = profile.strategy_stats
            if not isinstance(genome, StrategyGenome):
                logger.debug("No StrategyGenome available, skipping reward update")
                return

            try:
                arm = StrategyArm(strategy.name)
            except ValueError:
                logger.warning("Unknown strategy arm for reward: %s", strategy.name)
                return

            # 简化第一版：delta_e_valence = current - last
            # 首轮 last_e_valence == 0.0 时强制为 0
            if self._last_e_valence == 0.0:
                delta_e_valence = 0.0
            else:
                delta_e_valence = evaluation.e_valence - self._last_e_valence

            breakdown = NeuralRewardCalculator.calculate(
                mastery_delta=result.mastery_delta,
                delta_e_valence=delta_e_valence,
                c_load=evaluation.c_load,
                selected_arm=strategy.name,
            )
            reward = breakdown.final_reward

            # 更新 genome
            genome.arms[arm] = genome.arms[arm].pull(reward)

            # 增量持久化到 DB（不覆盖 MAB weights）
            existing = db_pool.get_or_create_user_stats(profile.user_id)
            raw_weights = existing.weights or "{}"
            weights = json.loads(raw_weights) if isinstance(raw_weights, str) else (raw_weights or {})
            weights["evolutionary_prompt_stats"] = genome_to_dict(genome)
            db_pool.update_user_stats(user_id=profile.user_id, weights=weights)

            # Phase 7: 遥测事件
            from utils.telemetry_events import log_reward
            log_reward(
                arm=str(arm),
                reward=reward,
                mastery_delta=result.mastery_delta,
                delta_e=delta_e_valence,
            )

            logger.info(
                "Reward updated: arm=%s pulls=%d reward=%.2f mastery_delta=%.1f delta_e=%.2f",
                arm, genome.arms[arm].pulls, genome.arms[arm].reward,
                result.mastery_delta, delta_e_valence,
            )

            # 缓存当前 e_valence 供下一轮 delta 计算
            self._last_e_valence = evaluation.e_valence

        except Exception as e:
            logger.warning("Reward update failed (ignored): %s", e)

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def reset_quiz(self) -> None:
        """手动重置测验状态（如用户切换模式时调用）。"""
        self._active_quiz = None
        self._consecutive_wrong = 0

    def get_active_quiz(self) -> Optional[QuizItem]:
        return self._active_quiz


# ---------------------------------------------------------------------------
# 4. 模块级单例
# ---------------------------------------------------------------------------

_cognitive_singleton: Optional[CognitiveEngine] = None


def get_cognitive_engine() -> CognitiveEngine:
    """获取全局唯一的 CognitiveEngine 实例。"""
    global _cognitive_singleton
    if _cognitive_singleton is None:
        _cognitive_singleton = CognitiveEngine()
    return _cognitive_singleton

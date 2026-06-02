"""
core/language_engine.py - 具身英语交互引擎 (Phase 6 English Embodiment)

职责：
  - 将英语文本/语音转录映射为工业孪生的物理指令
  - 事件驱动架构：publish signal → renderer 消费
  - 零 UI 逻辑，零 Streamlit 依赖
  - 本阶段不接真实麦克风，只处理已转录文本

架构约束：
  - process_voice_command() 接收 transcript，输出 EmbodiedCommand
  - 本地 fast parser 优先（<10ms），LLM 诊断走异步/后台
  - 所有物理动作抽象为 EmbodiedSignal，由事件总线派发
  - 新增 3D 动作只需在 Registry 注册，不改主链路 IF-ELSE
"""

import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. Pydantic 数据协议
# ===========================================================================


class EmbodiedContext(BaseModel):
    """具身交互上下文。"""

    scenario_tag: str = "general"           # 场景标签，用于消歧
    c_load: float = 0.0                     # 认知负荷 0~1
    e_valence: float = 0.0                  # 情感效价 -1~+1
    consecutive_errors: int = 0             # 连续语法错误次数
    current_focus_mesh: Optional[str] = None  # 当前聚焦 Mesh
    user_id: str = "anonymous"

    @validator("c_load")
    def _clamp_c_load(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @validator("e_valence")
    def _clamp_e_valence(cls, v: float) -> float:
        return max(-1.0, min(1.0, float(v)))


class EmbodiedAnchor(BaseModel):
    """语义锚点：token → 3D 实体映射。"""

    token: str                              # 英文词汇/短语（小写）
    mesh_id: str                            # 3D 模型中的 Mesh ID
    physical_action: str = "highlight"      # 默认物理动作
    part_of_speech: str = "noun"            # noun / verb / modifier
    scenario_tags: Tuple[str, ...] = ()     # 适用场景标签
    disambiguation_hint: str = ""           # 消歧提示


class EmbodiedToken(BaseModel):
    """已解析的具身标记，供前端安全渲染。"""

    surface_text: str                       # 原文
    mesh_id: Optional[str] = None
    part_of_speech: str = "unknown"
    action_hint: str = "highlight"
    is_clickable: bool = False


class EmbodiedCommand(BaseModel):
    """解析后的物理指令。"""

    target_mesh: str = ""
    physical_action: str = ""
    syntax_valid: bool = True
    diagnosis: str = ""
    tokens: List[EmbodiedToken] = Field(default_factory=list)
    raw_transcript: str = ""
    confidence: float = 1.0                 # 解析置信度 0~1


class EmbodiedSignal(BaseModel):
    """事件总线上的物理信号。renderer 订阅消费。"""

    mesh_id: str
    action: str                             # open / close / highlight / rotate / failure_smoke / restart_ignition / ...
    intensity: float = 1.0                  # 动作强度 0~1
    duration_ms: int = 500                  # 建议持续时间
    payload: Dict[str, Any] = Field(default_factory=dict)


class SyntacticBlock(BaseModel):
    """句法俄罗斯方块的积木块。"""

    block_id: str                           # 唯一标识
    label: str                              # 显示文本
    pos_tag: str                            # S / V / O / Adj / Adv
    color_hex: str = "#1E293B"              # 前端着色
    order_index: int = 0                    # 正确顺序索引


class SyntacticTetrisState(BaseModel):
    """句法修复状态机快照。"""

    sentence: str = ""
    available_blocks: List[SyntacticBlock] = Field(default_factory=list)
    submitted_order: List[str] = Field(default_factory=list)  # block_id 列表
    is_complete: bool = False
    is_correct: bool = False
    attempt_count: int = 0


# ===========================================================================
# 2. 语义 DAG 注册表
# ===========================================================================


class SemanticDAGRegistry:
    """
    词汇 → 工业 Mesh / 动作 / 场景 的映射注册表。

    支持：
      - 多义词消歧（scenario_tag 区分）
      - 动词/名词分类
      - 运行时注册（OCP 开闭原则）
    """

    def __init__(self) -> None:
        self._anchors: Dict[str, List[EmbodiedAnchor]] = {}
        self._scenario_index: Dict[str, List[str]] = {}  # scenario_tag -> token list
        self._load_builtin_registry()

    # ------------------------------------------------------------------
    # 内置词汇库（工业管道/机械场景）
    # ------------------------------------------------------------------

    def _load_builtin_registry(self) -> None:
        builtins = [
            # 名词 - 机械部件
            EmbodiedAnchor(token="valve", mesh_id="valve_01", physical_action="highlight", part_of_speech="noun", scenario_tags=("pipeline", "mechanical")),
            EmbodiedAnchor(token="pipe", mesh_id="pipe_main", physical_action="highlight", part_of_speech="noun", scenario_tags=("pipeline",)),
            EmbodiedAnchor(token="pump", mesh_id="pump_01", physical_action="highlight", part_of_speech="noun", scenario_tags=("pipeline", "mechanical")),
            EmbodiedAnchor(token="gauge", mesh_id="gauge_01", physical_action="highlight", part_of_speech="noun", scenario_tags=("pipeline",)),
            EmbodiedAnchor(token="tank", mesh_id="tank_01", physical_action="highlight", part_of_speech="noun", scenario_tags=("pipeline",)),
            EmbodiedAnchor(token="sensor", mesh_id="sensor_01", physical_action="highlight", part_of_speech="noun", scenario_tags=("pipeline", "mechanical")),
            EmbodiedAnchor(token="filter", mesh_id="filter_01", physical_action="highlight", part_of_speech="noun", scenario_tags=("pipeline",)),
            EmbodiedAnchor(token="engine", mesh_id="engine_01", physical_action="highlight", part_of_speech="noun", scenario_tags=("mechanical",)),
            # coupling 多义词消歧
            EmbodiedAnchor(token="coupling", mesh_id="coupling_shaft", physical_action="highlight", part_of_speech="noun", scenario_tags=("mechanical",), disambiguation_hint="联轴器"),
            EmbodiedAnchor(token="coupling", mesh_id="semantic_coupling", physical_action="highlight", part_of_speech="noun", scenario_tags=("abstract",), disambiguation_hint="耦合关系"),
            # 动词 - 动作
            EmbodiedAnchor(token="open", mesh_id="valve_01", physical_action="open", part_of_speech="verb", scenario_tags=("pipeline", "mechanical")),
            EmbodiedAnchor(token="close", mesh_id="valve_01", physical_action="close", part_of_speech="verb", scenario_tags=("pipeline", "mechanical")),
            EmbodiedAnchor(token="inspect", mesh_id="", physical_action="inspect", part_of_speech="verb", scenario_tags=("pipeline", "mechanical", "abstract")),
            EmbodiedAnchor(token="check", mesh_id="", physical_action="inspect", part_of_speech="verb", scenario_tags=("pipeline", "mechanical", "abstract")),
            EmbodiedAnchor(token="start", mesh_id="engine_01", physical_action="start", part_of_speech="verb", scenario_tags=("mechanical",)),
            EmbodiedAnchor(token="stop", mesh_id="engine_01", physical_action="stop", part_of_speech="verb", scenario_tags=("mechanical",)),
            EmbodiedAnchor(token="rotate", mesh_id="", physical_action="rotate", part_of_speech="verb", scenario_tags=("mechanical",)),
            EmbodiedAnchor(token="vent", mesh_id="pipe_main", physical_action="vent", part_of_speech="verb", scenario_tags=("pipeline",)),
            EmbodiedAnchor(token="pressurize", mesh_id="tank_01", physical_action="pressurize", part_of_speech="verb", scenario_tags=("pipeline",)),
            # 修饰语
            EmbodiedAnchor(token="main", mesh_id="pipe_main", physical_action="highlight", part_of_speech="modifier", scenario_tags=("pipeline",)),
            EmbodiedAnchor(token="emergency", mesh_id="valve_01", physical_action="highlight", part_of_speech="modifier", scenario_tags=("pipeline",)),
        ]
        for a in builtins:
            self.register(a)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def register(self, anchor: EmbodiedAnchor) -> None:
        """注册新锚点（OCP：新增动作只需注册，不改主链路）。"""
        token = anchor.token.lower().strip()
        self._anchors.setdefault(token, []).append(anchor)
        for tag in anchor.scenario_tags:
            self._scenario_index.setdefault(tag, []).append(token)
        logger.debug("Registered anchor: %s -> %s", token, anchor.mesh_id)

    def resolve_token(
        self,
        token: str,
        scenario_tag: str = "general",
    ) -> Optional[EmbodiedAnchor]:
        """
        词汇解析，支持场景消歧。

        策略：
          1. 精确匹配 token
          2. 优先 scenario_tag 匹配的锚点
          3. 无场景匹配时返回通用锚点
        """
        token = token.lower().strip()
        candidates = self._anchors.get(token, [])
        if not candidates:
            return None

        # 优先场景匹配
        if scenario_tag and scenario_tag != "general":
            for c in candidates:
                if scenario_tag in c.scenario_tags:
                    return c

        # fallback 到第一个
        return candidates[0]

    def resolve_sentence(
        self,
        sentence: str,
        scenario_tag: str = "general",
    ) -> List[EmbodiedToken]:
        """整句解析为具身标记列表。"""
        tokens: List[EmbodiedToken] = []
        words = re.findall(r"[a-zA-Z']+", sentence.lower())
        for w in words:
            anchor = self.resolve_token(w, scenario_tag)
            if anchor:
                tokens.append(
                    EmbodiedToken(
                        surface_text=w,
                        mesh_id=anchor.mesh_id or None,
                        part_of_speech=anchor.part_of_speech,
                        action_hint=anchor.physical_action,
                        is_clickable=bool(anchor.mesh_id),
                    )
                )
            else:
                tokens.append(EmbodiedToken(surface_text=w))
        return tokens


# ===========================================================================
# 3. 事件总线
# ===========================================================================


class EmbodiedEventBus:
    """
    内存型事件总线。

    language_engine 只 publish signal，不直接控制 renderer。
    renderer 侧通过 drain() 消费待处理信号。
    """

    def __init__(self, max_queue: int = 256) -> None:
        self._queue: List[EmbodiedSignal] = []
        self._max_queue = max_queue

    def publish(self, signal: EmbodiedSignal) -> None:
        """发布物理信号。队列满时丢弃最旧信号。"""
        if len(self._queue) >= self._max_queue:
            dropped = self._queue.pop(0)
            logger.warning("EventBus overflow, dropped: %s", dropped.action)
        self._queue.append(signal)
        logger.info(
            "Signal published: mesh=%s action=%s intensity=%.2f",
            signal.mesh_id, signal.action, signal.intensity,
        )

    def drain(self) -> List[EmbodiedSignal]:
        """消费并清空全部待处理信号。"""
        batch = self._queue[:]
        self._queue.clear()
        return batch

    def peek(self) -> List[EmbodiedSignal]:
        """只查看不消费。"""
        return self._queue[:]

    def clear(self) -> None:
        self._queue.clear()


# ===========================================================================
# 4. 声学效价补偿器
# ===========================================================================


class AcousticValenceCompensator:
    """
    检测犹豫特征，输出 prompt 自适应策略。
    本阶段只处理文本转录，不做真实音频分析。
    """

    _HESITATION_PATTERNS = [
        re.compile(r"\b(uh|um|eh|ah|er)\b", re.IGNORECASE),
        re.compile(r"\.{3,}"),               # 长停顿 ...
        re.compile(r"\b(like\s+you\s+know|sort\s+of|kind\s+of|maybe|perhaps)\b", re.IGNORECASE),
    ]

    @classmethod
    def detect_hesitation(cls, transcript: str) -> Dict[str, Any]:
        """检测犹豫指标。"""
        hesitation_count = 0
        for pat in cls._HESITATION_PATTERNS:
            hesitation_count += len(pat.findall(transcript))

        # 停顿密度
        words = transcript.split()
        density = hesitation_count / max(1, len(words))

        return {
            "hesitation_count": hesitation_count,
            "word_count": len(words),
            "density": round(density, 3),
            "is_fluent": density < 0.08,
        }

    @classmethod
    def adapt_prompt_policy(
        cls,
        transcript: str,
        context: EmbodiedContext,
    ) -> Dict[str, Any]:
        """
        根据犹豫和认知状态，输出 LLM prompt 调整策略。

        Returns:
            lexical_density: str  (high / medium / low)
            tone: str               (directive / guiding / encouraging)
            guidance_hint: str      # 给 system prompt 的附加指令
        """
        hes = cls.detect_hesitation(transcript)
        c_load = context.c_load
        e_val = context.e_valence

        # 规则矩阵
        if not hes["is_fluent"] or c_load > 0.7 or e_val < -0.5:
            lexical_density = "low"
            tone = "guiding"
            guidance_hint = (
                "Use short sentences. Avoid technical jargon. "
                "Guide the user step by step. Ask one question at a time."
            )
        elif c_load > 0.4:
            lexical_density = "medium"
            tone = "directive"
            guidance_hint = (
                "Use clear, direct instructions. One action per sentence."
            )
        else:
            lexical_density = "high"
            tone = "directive"
            guidance_hint = "Proceed with standard technical vocabulary."

        return {
            "lexical_density": lexical_density,
            "tone": tone,
            "guidance_hint": guidance_hint,
            "hesitation": hes,
        }


# ===========================================================================
# 5. 句法俄罗斯方块状态机
# ===========================================================================


class SyntacticTetrisStateMachine:
    """
    紧急修复模式：将句子拆分为 S/V/O 积木块，用户按正确顺序提交。

    触发条件（由调用方判断）：
      c_load > 0.85 and e_valence < -0.7 and consecutive_errors >= 3
    """

    def __init__(self) -> None:
        self._state: Optional[SyntacticTetrisState] = None

    # ------------------------------------------------------------------
    # 触发判断
    # ------------------------------------------------------------------

    @staticmethod
    def check_emergency(context: EmbodiedContext) -> bool:
        """判断是否应进入紧急修复模式。"""
        return (
            context.c_load > 0.85
            and context.e_valence < -0.7
            and context.consecutive_errors >= 3
        )

    # ------------------------------------------------------------------
    # 状态机操作
    # ------------------------------------------------------------------

    def start(self, sentence: str) -> SyntacticTetrisState:
        """拆解句子为 S/V/O 积木。"""
        blocks = self._decompose(sentence)
        self._state = SyntacticTetrisState(
            sentence=sentence,
            available_blocks=blocks,
            submitted_order=[],
            is_complete=False,
            is_correct=False,
            attempt_count=0,
        )
        return self._state

    def submit_block(self, block_id: str) -> SyntacticTetrisState:
        """提交一个积木块（由前端按钮触发）。"""
        if self._state is None:
            raise RuntimeError("State machine not started")

        self._state.submitted_order.append(block_id)
        self._state.attempt_count += 1

        # 检查是否提交完所有块
        if len(self._state.submitted_order) == len(self._state.available_blocks):
            self._state.is_complete = True
            self._state.is_correct = self._validate_order()

        return self._state

    def reset(self) -> None:
        self._state = None

    @property
    def state(self) -> Optional[SyntacticTetrisState]:
        return self._state

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _decompose(self, sentence: str) -> List[SyntacticBlock]:
        """极简 SVO 拆解（基于正则启发式）。"""
        words = sentence.lower().split()
        blocks: List[SyntacticBlock] = []

        # 简单启发：第一个名词短语=S，第一个动词=V，剩余=O
        # 实际教学中应更精细，当前先做 MVP
        subject_words = []
        verb_words = []
        object_words = []

        verb_hit = False
        for w in words:
            w_clean = re.sub(r"[^a-z0-9']", "", w)
            if not w_clean:
                continue
            # 非常简单的动词检测（内置词表）
            if w_clean in {"open", "close", "inspect", "check", "start", "stop", "rotate", "vent", "pressurize"}:
                verb_words.append(w_clean)
                verb_hit = True
            elif not verb_hit:
                subject_words.append(w_clean)
            else:
                object_words.append(w_clean)

        idx = 0
        if subject_words:
            blocks.append(
                SyntacticBlock(
                    block_id=f"s_{idx}",
                    label=" ".join(subject_words).title(),
                    pos_tag="S",
                    color_hex="#00A3FF",  # 蓝
                    order_index=idx,
                )
            )
            idx += 1
        if verb_words:
            blocks.append(
                SyntacticBlock(
                    block_id=f"v_{idx}",
                    label=" ".join(verb_words).title(),
                    pos_tag="V",
                    color_hex="#FF003C",  # 红
                    order_index=idx,
                )
            )
            idx += 1
        if object_words:
            blocks.append(
                SyntacticBlock(
                    block_id=f"o_{idx}",
                    label=" ".join(object_words).title(),
                    pos_tag="O",
                    color_hex="#00FF41",  # 绿
                    order_index=idx,
                )
            )

        # 如果啥都没拆出来，按整句=S
        if not blocks:
            blocks.append(
                SyntacticBlock(
                    block_id="s_0",
                    label=sentence,
                    pos_tag="S",
                    color_hex="#00A3FF",
                    order_index=0,
                )
            )

        return blocks

    def _validate_order(self) -> bool:
        """验证提交顺序是否与 order_index 一致。"""
        if self._state is None or not self._state.is_complete:
            return False

        expected = sorted(self._state.available_blocks, key=lambda b: b.order_index)
        expected_ids = [b.block_id for b in expected]
        return self._state.submitted_order == expected_ids


# ===========================================================================
# 6. 语音命令处理器
# ===========================================================================


class VoiceCommandProcessor:
    """
    文本 → 物理指令 的核心处理器。

    设计原则：
      1. Fast Path：本地 regex / registry 立即解析 target_mesh + action（<10ms）
      2. Slow Path：LLM 生成 diagnosis / 纠错建议（后台异步）
      3. 所有物理动作通过 EventBus 发 signal，不直接调用 renderer
    """

    def __init__(self) -> None:
        self.registry = SemanticDAGRegistry()
        self.event_bus = EmbodiedEventBus()
        self.tetris = SyntacticTetrisStateMachine()
        self.compensator = AcousticValenceCompensator()

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def process_voice_command(
        self,
        transcript: str,
        context: EmbodiedContext,
    ) -> EmbodiedCommand:
        """
        处理已转录文本，输出具身指令。

        Args:
            transcript: STT 或手动输入的英文文本
            context: 交互上下文

        Returns:
            EmbodiedCommand
        """
        if not transcript or not transcript.strip():
            return EmbodiedCommand(
                syntax_valid=False,
                diagnosis="Empty transcript received.",
                raw_transcript=transcript,
            )

        # 1. 犹豫检测 + prompt 策略调整（记录日志，供后续 LLM 调用参考）
        policy = self.compensator.adapt_prompt_policy(transcript, context)
        logger.info(
            "VoiceCommand policy: density=%s tone=%s hes_density=%.3f",
            policy["lexical_density"], policy["tone"], policy["hesitation"]["density"],
        )

        # 2. 本地 Fast Parser：提取动词+名词
        tokens = self.registry.resolve_sentence(transcript, context.scenario_tag)

        # 3. 构造命令
        cmd = self._assemble_command(tokens, transcript, context)

        # 4. 根据语法有效性发布信号
        if cmd.syntax_valid:
            self._publish_action_signal(cmd, context)
        else:
            self._publish_failure_signal(context)

        return cmd

    # ------------------------------------------------------------------
    # 组装命令
    # ------------------------------------------------------------------

    def _assemble_command(
        self,
        tokens: List[EmbodiedToken],
        transcript: str,
        context: EmbodiedContext,
    ) -> EmbodiedCommand:
        """从解析出的 tokens 组装 EmbodiedCommand。"""

        # 提取动词（动词可以不带 mesh_id，如 inspect / check）
        verbs = [t for t in tokens if t.part_of_speech == "verb"]
        # 提取名词（mesh 明确的）
        nouns = [t for t in tokens if t.part_of_speech == "noun" and t.mesh_id]

        # 策略：动词优先决定 action，名词决定 target_mesh
        target_mesh = ""
        physical_action = ""

        if verbs:
            physical_action = verbs[0].action_hint
            # 动词自带 mesh 则优先，否则 fallback 到最近的名词
            if verbs[0].mesh_id:
                target_mesh = verbs[0].mesh_id
            elif nouns:
                target_mesh = nouns[0].mesh_id or ""
        elif nouns:
            target_mesh = nouns[0].mesh_id or ""
            physical_action = nouns[0].action_hint

        # 语法有效性：必须有 target_mesh 和 action
        syntax_valid = bool(target_mesh and physical_action)

        diagnosis = ""
        if not syntax_valid:
            if not target_mesh:
                diagnosis = "无法识别目标设备。请使用已注册的设备名称（如 valve, pump, pipe）。"
            elif not physical_action:
                diagnosis = "无法识别动作。请使用已注册的动作词（如 open, close, inspect）。"
            else:
                diagnosis = "指令不完整。"

        return EmbodiedCommand(
            target_mesh=target_mesh,
            physical_action=physical_action,
            syntax_valid=syntax_valid,
            diagnosis=diagnosis,
            tokens=tokens,
            raw_transcript=transcript,
            confidence=1.0 if syntax_valid else 0.3,
        )

    # ------------------------------------------------------------------
    # 信号发布
    # ------------------------------------------------------------------

    def _publish_action_signal(
        self,
        cmd: EmbodiedCommand,
        context: EmbodiedContext,
    ) -> None:
        """发布成功动作信号。"""
        self.event_bus.publish(
            EmbodiedSignal(
                mesh_id=cmd.target_mesh,
                action=cmd.physical_action,
                intensity=1.0,
                duration_ms=800,
                payload={
                    "user_id": context.user_id,
                    "scenario_tag": context.scenario_tag,
                    "raw_transcript": cmd.raw_transcript,
                },
            )
        )

    def _publish_failure_signal(self, context: EmbodiedContext) -> None:
        """发布语法失败信号（renderer 可触发卡壳/冒黑烟特效）。"""
        self.event_bus.publish(
            EmbodiedSignal(
                mesh_id=context.current_focus_mesh or "engine_01",
                action="failure_smoke",
                intensity=min(1.0, 0.4 + context.consecutive_errors * 0.15),
                duration_ms=1200,
                payload={
                    "user_id": context.user_id,
                    "reason": "syntax_invalid",
                },
            )
        )

    # ------------------------------------------------------------------
    # 紧急修复模式
    # ------------------------------------------------------------------

    def enter_emergency_repair(
        self,
        sentence: str,
        context: EmbodiedContext,
    ) -> SyntacticTetrisState:
        """
        进入句法俄罗斯方块紧急修复模式。
        调用方应先通过 SyntacticTetrisStateMachine.check_emergency() 判断。
        """
        state = self.tetris.start(sentence)
        logger.warning(
            "Emergency repair entered: sentence='%s' blocks=%d user=%s",
            sentence, len(state.available_blocks), context.user_id,
        )
        return state

    def submit_tetris_block(self, block_id: str) -> SyntacticTetrisState:
        """提交一个句法积木块。"""
        return self.tetris.submit_block(block_id)

    def resolve_tetris(self) -> Optional[EmbodiedSignal]:
        """
        如果句法修复成功，发布 restart_ignition 信号。
        否则返回 None。
        """
        state = self.tetris.state
        if state and state.is_complete and state.is_correct:
            sig = EmbodiedSignal(
                mesh_id="engine_01",
                action="restart_ignition",
                intensity=1.0,
                duration_ms=1500,
                payload={"repair_success": True},
            )
            self.event_bus.publish(sig)
            self.tetris.reset()
            return sig
        return None


# ===========================================================================
# 7. 模块级单例 & Public API
# ===========================================================================

_processor_singleton: Optional[VoiceCommandProcessor] = None


def get_voice_command_processor() -> VoiceCommandProcessor:
    """获取全局唯一的 VoiceCommandProcessor 实例。"""
    global _processor_singleton
    if _processor_singleton is None:
        _processor_singleton = VoiceCommandProcessor()
    return _processor_singleton


def process_voice_command(
    transcript: str,
    context: Optional[EmbodiedContext] = None,
) -> EmbodiedCommand:
    """
    处理语音/文本指令的便捷入口。

    Args:
        transcript: 英文文本
        context: 交互上下文（可选，默认 general）

    Returns:
        EmbodiedCommand
    """
    if context is None:
        context = EmbodiedContext()
    processor = get_voice_command_processor()
    return processor.process_voice_command(transcript, context)


def check_emergency_repair(context: EmbodiedContext) -> bool:
    """判断是否应进入紧急修复模式。"""
    return SyntacticTetrisStateMachine.check_emergency(context)


def enter_emergency_repair(sentence: str, context: EmbodiedContext) -> SyntacticTetrisState:
    """进入句法俄罗斯方块紧急修复模式。"""
    processor = get_voice_command_processor()
    return processor.enter_emergency_repair(sentence, context)


def submit_tetris_block(block_id: str) -> SyntacticTetrisState:
    """提交一个句法积木块。"""
    processor = get_voice_command_processor()
    return processor.submit_tetris_block(block_id)


def resolve_tetris() -> Optional[EmbodiedSignal]:
    """若修复成功，发布 restart_ignition 信号。"""
    processor = get_voice_command_processor()
    return processor.resolve_tetris()


def drain_signals() -> List[EmbodiedSignal]:
    """消费并清空事件总线中的所有信号。"""
    processor = get_voice_command_processor()
    return processor.event_bus.drain()

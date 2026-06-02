"""
core/llm_engine.py - 核心抽象层（扩展预留）
实现 UnifiedNeuralCore，用于封装复杂推理流水线：
  - 双轴评估管线（认知负荷 C_load、情感效价 E_valence）
  - 认知诊断与策略选择
  - 可插拔的 LLM 后端
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

import httpx


class DiagnosisLevel(str, Enum):
    FLOW = "flow"           # 心流状态，最佳学习区
    STRESS = "stress"       # 高负荷，需减压
    BOREDOM = "boredom"     # 低负荷，需加难
    CONFUSED = "confused"   # 困惑，需重讲


@dataclass
class CognitiveProfile:
    """用户实时认知画像"""
    c_load: float          # 0.0 ~ 1.0
    e_valence: float       # -1.0 ~ 1.0
    diagnosis: DiagnosisLevel
    suggested_strategy: str


@dataclass
class UnifiedResponse:
    """核心引擎的统一输出结构"""
    content: str
    profile: CognitiveProfile
    metadata: Dict[str, Any]


class UnifiedNeuralCore:
    """
    统一神经网络核心：
    1. 接收原始用户输入 + 历史上下文
    2. 调用 LLM 生成教学响应
    3. 对响应进行双轴评估（C_load / E_valence）
    4. 根据评估结果调整输出策略
    5. 返回带诊断信息的统一结构
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = base_url or "https://api.deepseek.com/v1"
        self.model = "deepseek-chat"
        self.timeout = 60.0

    async def generate(
        self,
        prompt: str,
        system_message: str = "You are an AI tutor.",
        temperature: float = 0.7,
        context: Optional[str] = None,
    ) -> UnifiedResponse:
        """生成教学响应并附带认知诊断"""
        messages = [{"role": "system", "content": system_message}]
        if context:
            messages.append({"role": "system", "content": f"历史上下文：\n{context}"})
        messages.append({"role": "user", "content": prompt})

        raw = await self._call_llm(messages, temperature)

        # 简易双轴评估（未来可接入更精细的评估模型）
        profile = self._evaluate(raw)

        # 策略调整：根据诊断微调输出
        adjusted = self._apply_strategy(raw, profile)

        return UnifiedResponse(
            content=adjusted,
            profile=profile,
            metadata={
                "model": self.model,
                "temperature": temperature,
                "tokens_used": None,
            },
        )

    async def _call_llm(self, messages: list, temperature: float) -> str:
        if not self.api_key:
            raise RuntimeError("API key not configured")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
            return data["choices"][0]["message"]["content"]

    def _evaluate(self, raw_response: str) -> CognitiveProfile:
        """
        双轴评估管线（当前为启发式，可替换为更精细的评估模型）
        - c_load: 响应长度、复杂度、新信息量
        - e_valence: 语气正向度
        """
        length = len(raw_response)
        c_load = min(1.0, length / 800.0)   # 越长越复杂，负荷越高
        e_valence = 0.1                      # 默认略正向
        diagnosis = DiagnosisLevel.FLOW

        if c_load > 0.8:
            diagnosis = DiagnosisLevel.STRESS
        elif c_load < 0.2:
            diagnosis = DiagnosisLevel.BOREDOM

        suggested = {
            DiagnosisLevel.FLOW: "保持当前节奏",
            DiagnosisLevel.STRESS: "简化步骤，增加鼓励",
            DiagnosisLevel.BOREDOM: "增加挑战，引入新类比",
            DiagnosisLevel.CONFUSED: "重述概念，拆分更细",
        }[diagnosis]

        return CognitiveProfile(
            c_load=round(c_load, 2),
            e_valence=round(e_valence, 2),
            diagnosis=diagnosis,
            suggested_strategy=suggested,
        )

    def _apply_strategy(self, raw: str, profile: CognitiveProfile) -> str:
        """根据诊断结果，对原始响应进行微调（预留扩展点）"""
        # 当前阶段直接透传；未来可在此处注入策略标记
        return raw

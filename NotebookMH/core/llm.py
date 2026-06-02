"""core/llm.py — DeepSeek LLM 客户端"""
import asyncio
import json
import logging
from typing import AsyncIterator, Optional

import httpx

from config import DEEPSEEK_API_KEY, AI_BASE_URL, AI_MODEL, USE_MOCK_LLM

log = logging.getLogger(__name__)
_TIMEOUT = 90.0


class LLMClient:
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

    def _build_messages(self, prompt: str, system: str, history: list) -> list:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        for h in (history or [])[-10:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": h["content"]})
        msgs.append({"role": "user", "content": prompt})
        return msgs

    async def chat(self, prompt: str, system: str = "",
                   history: Optional[list] = None,
                   temperature: float = 0.7) -> str:
        if USE_MOCK_LLM:
            return "（当前为模拟模式，配置 DEEPSEEK_API_KEY 后启用真实 AI 回答）"
        messages = self._build_messages(prompt, system, history or [])
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{AI_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={"model": AI_MODEL, "messages": messages,
                      "temperature": temperature},
            )
            if r.status_code >= 400:
                log.error("LLM failed: %s %s", r.status_code, r.text[:500])
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]

    async def chat_stream(self, prompt: str, system: str = "",
                          history: Optional[list] = None,
                          temperature: float = 0.7) -> AsyncIterator[str]:
        if USE_MOCK_LLM:
            mock = "（当前为模拟模式，配置 DEEPSEEK_API_KEY 后启用真实 AI 回答）"
            for ch in mock:
                yield ch
                await asyncio.sleep(0.015)
            return
        messages = self._build_messages(prompt, system, history or [])
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            async with c.stream(
                "POST", f"{AI_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={"model": AI_MODEL, "messages": messages,
                      "temperature": temperature, "stream": True},
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def chat_json(self, prompt: str, system: str = "",
                        temperature: float = 0.3) -> dict:
        if USE_MOCK_LLM:
            # 返回模拟数据，让 UI 能正常预览
            if "闪卡" in prompt or "flashcard" in prompt.lower():
                return {"cards": [
                    {"question": "（模拟）什么是资料的核心主题？",
                     "answer": "（模拟）这是 Mock 模式下的示例答案，配置 API Key 后生成真实内容。"},
                    {"question": "（模拟）资料包含哪些关键要点？",
                     "answer": "（模拟）Mock 示例：要点包括背景、方法、结论三部分。"},
                ]}
            if "测验" in prompt or "quiz" in prompt.lower() or "单选题" in prompt:
                return {"items": [
                    {"question": "（模拟）资料的主要结论是什么？",
                     "options": ["A. 结论一", "B. 结论二", "C. 结论三", "D. 以上都不是"],
                     "correct": "A",
                     "explanation": "（模拟）这是示例解析。"},
                ]}
            if "演示文稿" in prompt or "presentation" in prompt.lower() or "slide" in prompt.lower() or "PPT" in prompt:
                return {"slides": [
                    {"title": "（模拟）资料概览", "bullets": ["背景介绍", "核心问题", "研究意义"], "speaker_notes": "开场页"},
                    {"title": "（模拟）关键发现", "bullets": ["发现一", "发现二", "发现三"], "speaker_notes": "核心内容页"},
                    {"title": "（模拟）总结与展望", "bullets": ["核心结论", "后续方向"], "speaker_notes": "收尾页"},
                ]}
            if "摘要" in prompt or "summary" in prompt.lower() or "推荐问题" in prompt:
                return {"summary": "（模拟）这是一份示例摘要，配置 API Key 后生成真实内容。",
                        "suggested_questions": [
                            "（模拟）资料的核心主题是什么？",
                            "（模拟）资料包含哪些关键要点？",
                            "（模拟）资料的主要结论是什么？",
                        ]}
            return {"mock": True, "preview": prompt[:80]}
        messages = self._build_messages(prompt, system, [])
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(
                f"{AI_BASE_URL}/chat/completions",
                headers=self._headers(),
                json={"model": AI_MODEL, "messages": messages,
                      "temperature": temperature,
                      "response_format": {"type": "json_object"}},
            )
            r.raise_for_status()
            raw = r.json()["choices"][0]["message"]["content"]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                log.warning("LLM 返回非 JSON: %s", raw[:200])
                return {"raw": raw}


llm = LLMClient()

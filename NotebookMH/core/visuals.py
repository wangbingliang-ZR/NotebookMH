"""core/visuals.py — 配图能力（组合方案）

两种来源：
1. SVG 示意图：由 LLM 生成 SVG 代码，适合几何/电路/化学装置/流程/坐标图（免费）。
2. 联网真实图片：用 Tavily 图片搜索，适合实物/场景/地图照片。

对外主入口：
- async generate_svg(description) -> str            # 返回 <svg>...</svg>
- search_real_image(query) -> Optional[str]         # 返回图片 URL
- async make_visual(spec) -> dict                   # 根据 spec 统一产出可渲染数据
"""
import logging
import re
from typing import Optional

from core.llm import llm
from core.websearch import search_images

log = logging.getLogger(__name__)

_SVG_RE = re.compile(r"<svg[\s\S]*?</svg>", re.IGNORECASE)


async def generate_svg(description: str) -> str:
    """让 LLM 生成一段干净的 SVG 示意图代码。失败返回空串。"""
    prompt = (
        f"请为以下教学需求绘制一张【SVG 示意图】：\n「{description}」\n\n"
        "要求：\n"
        "- 直接输出合法的 SVG 代码，根元素 <svg> 必须带 viewBox 和合适的 width/height\n"
        "- 适合白底显示，线条清晰，必要的标注用 <text> 写中文标签\n"
        "- 几何图形用 <line>/<polygon>/<circle>/<path>，电路/装置用规范符号\n"
        "- 不要任何解释文字，不要 Markdown 代码块，只输出 <svg>…</svg>"
    )
    try:
        raw = await llm.chat(
            prompt,
            system="你是精通 SVG 的教学绘图助手，只输出 SVG 代码。",
            temperature=0.3,
        )
    except Exception:
        log.warning("SVG 生成失败", exc_info=True)
        return ""
    m = _SVG_RE.search(raw or "")
    return m.group(0) if m else ""


def search_real_image(query: str) -> Optional[str]:
    """联网搜一张相关真实图片，返回 URL。"""
    imgs = search_images(query, max_results=4)
    return imgs[0]["url"] if imgs else None


async def make_visual(spec: dict) -> dict:
    """根据配图规格统一产出渲染数据。

    spec: {"kind": "svg"|"image", "query": "描述或搜索词"}
    返回:
      {"kind":"svg", "svg":"<svg...>"}  或
      {"kind":"image", "url":"http..."} 或
      {"kind":"none"}（失败兜底）
    """
    kind = spec.get("kind")
    query = (spec.get("query") or "").strip()
    if not query:
        return {"kind": "none"}

    if kind == "svg":
        svg = await generate_svg(query)
        if svg:
            return {"kind": "svg", "svg": svg}
        # SVG 失败时兜底找真实图片
        url = search_real_image(query)
        return {"kind": "image", "url": url} if url else {"kind": "none"}

    if kind == "image":
        url = search_real_image(query)
        return {"kind": "image", "url": url} if url else {"kind": "none"}

    return {"kind": "none"}

# Phase D — Studio 生成（Step 25-32）

> **执行前必读**: `ARCHITECTURE.md` 第 6 节 `core/studio.py` 接口
> **本阶段目标**: 摘要 / FAQ / 学习指南 / 简报 / 时间线 / 思维导图 / 闪卡 / 测验 / 错题本
> **Checkpoint**: Step 25、30 完成后做

---

## Step 25：实现 core/studio.py（生成函数库）

**目标**: 暴露 ARCHITECTURE 第 6 节定义的 8 个生成函数。

**操作**: `core/studio.py` 完全替换:

```python
"""core/studio.py — Studio 内容生成"""
import json
import logging
from typing import Optional

from core.db import db_manager
from core.llm import llm

log = logging.getLogger(__name__)


def _gather_context(vault_uuid: str, max_chars: int = 8000) -> str:
    """收集 vault 内所有文档的代表性文本作为上下文。"""
    docs = db_manager.list_documents(vault_uuid)
    if not docs:
        return ""
    chunks_per_doc = max(1, 8000 // max(1, len(docs)) // 200)
    parts: list[str] = []
    for d in docs[:20]:
        chunks = db_manager.get_chunks(vault_uuid, d.content_hash)
        text_parts = [c.chunk_text for c in chunks[:chunks_per_doc]]
        parts.append(f"《{d.file_name}》\n{chr(10).join(text_parts)}")
    text = "\n\n---\n\n".join(parts)
    return text[:max_chars]


async def _gen_text(vault_uuid: str, system: str, task: str,
                    temperature: float = 0.5) -> str:
    ctx = _gather_context(vault_uuid)
    if not ctx:
        return "（当前笔记库没有来源，请先上传资料）"
    prompt = f"{task}\n\n以下是来源资料：\n\n{ctx}"
    return await llm.chat(prompt, system=system, temperature=temperature)


async def _gen_json(vault_uuid: str, system: str, task: str) -> dict:
    ctx = _gather_context(vault_uuid)
    if not ctx:
        return {}
    prompt = f"{task}\n\n以下是来源资料：\n\n{ctx}\n\n请严格返回 JSON。"
    return await llm.chat_json(prompt, system=system, temperature=0.3)


async def generate_summary(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是文档总结助手，仅基于资料作答，用中文。",
        task="请用 300 字左右总结这份资料的核心内容，分 3-5 个要点。",
    )


async def generate_faq(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是 FAQ 生成助手，仅基于资料作答。",
        task="基于资料生成 6-8 个常见问题及答案，格式：\n**Q1: 问题**\nA: 答案\n\n**Q2: ...**\n",
    )


async def generate_study_guide(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是学习指导助手。",
        task=(
            "基于资料生成一份学习指南，包含：\n"
            "1. 核心概念清单（5-8 个，每个一句话解释）\n"
            "2. 学习路径建议（先学什么再学什么）\n"
            "3. 重点难点提示\n"
            "4. 自测问题 3-5 个"
        ),
    )


async def generate_briefing(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是简报撰写助手。",
        task="把这份资料浓缩成 200 字简报，适合三分钟阅读。包含：背景、要点、结论。",
    )


async def generate_timeline(vault_uuid: str) -> str:
    return await _gen_text(
        vault_uuid,
        system="你是时间线整理助手。",
        task=(
            "如果资料含时间信息，提取关键事件并按时间排序，输出 markdown 列表：\n"
            "- **时间**: 事件描述\n\n"
            "如果资料不含明显时间，提取关键步骤/阶段按逻辑顺序排序。"
        ),
    )


async def generate_mindmap(vault_uuid: str) -> str:
    """返回 Mermaid mindmap 源码字符串。"""
    raw = await _gen_text(
        vault_uuid,
        system=(
            "你是思维导图生成器，仅返回 Mermaid mindmap 源码，"
            "不要任何额外解释、不要 markdown 代码块标记。"
        ),
        task=(
            "把资料的核心结构转成 Mermaid mindmap。格式：\n"
            "mindmap\n  root((中心主题))\n    分支1\n      子节点\n    分支2\n"
            "层级不超过 3，节点数 12-20 个。"
        ),
        temperature=0.3,
    )
    # 清理代码块标记
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    if not text.lstrip().startswith("mindmap"):
        text = "mindmap\n  root((笔记内容))\n    " + text.replace("\n", "\n    ")
    return text


async def generate_flashcards(vault_uuid: str, count: int = 10) -> list[dict]:
    data = await _gen_json(
        vault_uuid,
        system="你是闪卡生成器，仅返回 JSON。",
        task=(
            f"基于资料生成 {count} 张学习闪卡。"
            "返回 JSON：{\"cards\": [{\"question\": \"...\", \"answer\": \"...\"}, ...]}"
        ),
    )
    cards = data.get("cards") or []
    return [c for c in cards if isinstance(c, dict)
            and c.get("question") and c.get("answer")][:count]


async def generate_quiz(vault_uuid: str, count: int = 5) -> list[dict]:
    data = await _gen_json(
        vault_uuid,
        system="你是测验题生成器，仅返回 JSON。",
        task=(
            f"基于资料生成 {count} 道单选题。每题 4 个选项，标注正确答案字母（A/B/C/D），"
            "并给出简要解析。返回 JSON：{\"items\": ["
            "{\"question\":\"...\", \"options\":[\"A. ...\",\"B. ...\",\"C. ...\",\"D. ...\"],"
            "\"correct\":\"A\", \"explanation\":\"...\"}]}"
        ),
    )
    items = data.get("items") or []
    valid: list[dict] = []
    for it in items[:count]:
        if (isinstance(it, dict) and it.get("question")
                and isinstance(it.get("options"), list) and len(it["options"]) >= 2
                and it.get("correct")):
            valid.append(it)
    return valid
```

**验收**（Mock 模式可跳过，建议有 Key 时测）:
```powershell
python -c "
import asyncio
from core.db import db_manager
from core.ingest import ingest_text
from core.studio import generate_summary, generate_flashcards
u = db_manager.create_vault('studio_t','t')
asyncio.run(ingest_text(u,'t','光合作用是植物利用阳光合成有机物的过程。它分为光反应和暗反应。光反应在类囊体进行，产生 ATP 和 NADPH。暗反应在基质进行，固定 CO2。'))
print('摘要:', asyncio.run(generate_summary(u))[:200])
print('闪卡:', asyncio.run(generate_flashcards(u, count=3)))
db_manager.delete_vault(u)
"
```

**预期**:
- 摘要返回 200+ 字中文
- 闪卡返回 list of `{question, answer}` dict

---

## Step 25 完成 → CHECKPOINT 5

按规则重读 + 写 Checkpoint 5。

---

## Step 26：实现 ui/studio_panel.py 框架

**目标**: 右侧栏: 工具卡片 2x4 网格 + 我的笔记区。

**操作**: `ui/studio_panel.py` 完全替换:

```python
"""ui/studio_panel.py — Studio 右侧面板"""
import asyncio
import traceback

import streamlit as st

from core.db import db_manager

# 工具元数据：标题 → studio 模块函数名
_TOOLS = [
    ("summary",      "📝 摘要",       "generate_summary"),
    ("faq",          "❓ 常见问题",   "generate_faq"),
    ("study_guide",  "📚 学习指南",   "generate_study_guide"),
    ("briefing",     "📰 简报",       "generate_briefing"),
    ("timeline",     "🕒 时间线",     "generate_timeline"),
    ("mindmap",      "🧠 思维导图",   "generate_mindmap"),
    ("flashcards",   "🃏 闪卡",       "generate_flashcards"),
    ("quiz",         "📋 测验",       "generate_quiz"),
]


def _run_tool(tool_key: str, vault_uuid: str):
    from core import studio as studio_mod
    func_name = dict((k, fn) for k, _, fn in _TOOLS)[tool_key]
    fn = getattr(studio_mod, func_name)
    return asyncio.run(fn(vault_uuid))


def _save_note(vault_uuid: str, user_id: str, title: str, content: str):
    db_manager.save_note(vault_uuid, user_id, title, content)


def _render_tools_grid(vault_uuid: str, user_id: str) -> None:
    cols = st.columns(2)
    for i, (key, label, _) in enumerate(_TOOLS):
        with cols[i % 2]:
            if st.button(label, key=f"studio_tool_{key}",
                         use_container_width=True):
                st.session_state[f"_studio_running_{key}"] = True
                st.rerun()

    # 真正的执行（避免 button 后 rerun 丢失结果）
    for key, label, _ in _TOOLS:
        running_flag = f"_studio_running_{key}"
        if st.session_state.get(running_flag):
            st.session_state[running_flag] = False
            with st.spinner(f"生成 {label}..."):
                try:
                    result = _run_tool(key, vault_uuid)
                    st.session_state[f"_studio_result_{key}"] = result
                except Exception:
                    st.session_state[f"_studio_result_{key}"] = traceback.format_exc()
            st.rerun()

    # 渲染结果
    for key, label, _ in _TOOLS:
        result_key = f"_studio_result_{key}"
        if result_key in st.session_state:
            res = st.session_state[result_key]
            with st.expander(f"{label} 结果", expanded=True):
                _render_result(key, label, res, vault_uuid, user_id)
                if st.button("清除", key=f"clear_{key}"):
                    del st.session_state[result_key]
                    st.rerun()


def _render_result(key: str, label: str, res, vault_uuid: str, user_id: str):
    if isinstance(res, str) and res.startswith("Traceback"):
        st.error("生成失败：")
        st.code(res)
        return

    if key == "mindmap":
        st.markdown("**Mermaid 源码:**")
        st.code(res, language="mermaid")
        # 简单 HTML 渲染
        import html
        safe = html.escape(res)
        st.components.v1.html(
            f"""
            <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
            <div class="mermaid">{safe}</div>
            <script>mermaid.initialize({{startOnLoad: true}});</script>
            """,
            height=400, scrolling=True,
        )
        if st.button("保存为笔记", key=f"save_{key}"):
            _save_note(vault_uuid, user_id, label, f"```mermaid\n{res}\n```")
            st.success("已保存")

    elif key == "flashcards":
        if not isinstance(res, list) or not res:
            st.warning("未生成闪卡")
            return
        for i, card in enumerate(res):
            with st.container(border=True):
                st.markdown(f"**Q{i+1}:** {card['question']}")
                with st.expander("答案"):
                    st.markdown(card["answer"])
        if st.button("保存到闪卡库", key=f"save_{key}"):
            db_manager.save_flashcards(vault_uuid, res)
            st.success(f"已保存 {len(res)} 张闪卡")

    elif key == "quiz":
        if not isinstance(res, list) or not res:
            st.warning("未生成测验题")
            return
        for i, q in enumerate(res):
            with st.container(border=True):
                st.markdown(f"**Q{i+1}:** {q['question']}")
                for opt in q.get("options", []):
                    st.markdown(f"- {opt}")
                with st.expander("答案与解析"):
                    st.markdown(f"**正确答案**: {q.get('correct')}")
                    st.markdown(q.get("explanation", ""))
        if st.button("保存到测验库", key=f"save_{key}"):
            db_manager.save_quiz_items(vault_uuid, res)
            st.success(f"已保存 {len(res)} 道题")

    else:
        # 纯文本（摘要 / FAQ / 学习指南 / 简报 / 时间线）
        st.markdown(res)
        if st.button("保存为笔记", key=f"save_{key}"):
            _save_note(vault_uuid, user_id, label, res)
            st.success("已保存")


def _render_notes_section(vault_uuid: str, user_id: str) -> None:
    st.markdown("### 我的笔记")
    notes = db_manager.list_notes(vault_uuid, user_id)
    if not notes:
        st.caption("还没有保存的笔记")
        return
    for n in notes[:20]:
        with st.expander(f"{'📌 ' if n.pinned else ''}{n.title}"):
            st.markdown(n.content)
            c1, c2 = st.columns(2)
            if c1.button("置顶/取消", key=f"pin_{n.id}"):
                db_manager.toggle_pin_note(n.id)
                st.rerun()
            if c2.button("删除", key=f"del_note_{n.id}"):
                db_manager.delete_note(n.id)
                st.rerun()


def render() -> None:
    st.markdown("### Studio")
    vault_uuid = st.session_state.get("vault_uuid", "")
    user_id = st.session_state.get("user_id", "anonymous")
    if not vault_uuid:
        st.caption("请先选择笔记库")
        return

    _render_tools_grid(vault_uuid, user_id)
    st.divider()
    _render_notes_section(vault_uuid, user_id)
```

更新 `app.py`:
```python
from ui import sidebar, chat_panel, studio_panel

# ...
with right:
    studio_panel.render()
```

**验收**: 浏览器看到右侧 8 个工具按钮 2x4 网格 + "我的笔记"区。点任一按钮（如"摘要"）→ 显示 spinner → 显示结果 → 可保存为笔记 → 笔记区出现。

---

## Step 27：摘要 / FAQ / 学习指南 / 简报 / 时间线 联调

**目标**: 5 个纯文本工具端到端跑通。

**操作**: 仅做联调验证，无代码改动。

**验收**:
1. 库中有真实内容（如 1 个 PDF）
2. 依次点击: 摘要、FAQ、学习指南、简报、时间线
3. 每个都返回合理中文内容（不少于 100 字）
4. 各自的"保存为笔记"按钮 → 笔记区新增条目

**记录**: 在 PROGRESS.md 贴一张笔记区截图或文字描述。

---

## Step 28：思维导图渲染验证

**目标**: Mermaid 源码 → 浏览器渲染为图。

**操作**: 仅验证。

**验收**:
1. 点"思维导图"按钮
2. 展开结果区
3. 应看到:
   - 上半部分: `mindmap` 源码（code block）
   - 下半部分: 渲染后的图形（圆形节点连线）
4. 若图不渲染 → 检查浏览器控制台是否报 Mermaid 错误；可能源码格式不对，调 prompt 让 LLM 输出更严格的 mindmap

**若失败**:
- 检查 `_render_result` 中 mermaid 部分的 HTML
- 检查 LLM 输出是否真以 `mindmap\n  root((...))` 开头

---

## Step 29：闪卡生成 + 翻卡 + 保存

**目标**: 生成闪卡 → 可翻卡 → 可保存到 DB。

**操作**: Step 26 已实现"保存到闪卡库"。**补充闪卡库浏览面板**到 `studio_panel.py`，在 `_render_notes_section` 前加:

```python
def _render_flashcard_library(vault_uuid: str) -> None:
    cards = db_manager.list_flashcards(vault_uuid)
    if not cards:
        return
    with st.expander(f"闪卡库 ({len(cards)} 张)"):
        for c in cards[:20]:
            with st.container(border=True):
                st.markdown(f"**Q:** {c.question}")
                with st.expander("答案"):
                    st.markdown(c.answer)
                    cols = st.columns(3)
                    if cols[0].button("未掌握", key=f"fc0_{c.id}"):
                        db_manager.update_flashcard_mastery(c.id, 0); st.rerun()
                    if cols[1].button("半懂", key=f"fc1_{c.id}"):
                        db_manager.update_flashcard_mastery(c.id, 1); st.rerun()
                    if cols[2].button("已掌握", key=f"fc2_{c.id}"):
                        db_manager.update_flashcard_mastery(c.id, 2); st.rerun()
```

在 `render()` 中 `st.divider()` 后调用 `_render_flashcard_library(vault_uuid)`。

**验收**:
1. 生成闪卡 → 保存
2. 闪卡库展开 → 看到卡片
3. 点"已掌握"等按钮 → mastery 字段更新
4. `python -c "from core.db import db_manager; [print(c.question, c.mastery) for c in db_manager.list_flashcards('<uuid>')]"` 验证

---

## Step 30：测验 + 答题 + 错题自动入库

**目标**: 测验题可答 → 答对/错有反馈 → 答错自动入 wrong_answer_registry。

**操作**: 在 `_render_result` 的 `key == "quiz"` 分支后扩展，把生成的题 cached 保存后用专门答题面板。改为:

```python
    elif key == "quiz":
        if not isinstance(res, list) or not res:
            st.warning("未生成测验题")
            return
        st.markdown(f"生成了 {len(res)} 道题")
        if st.button("加入测验库开始答题", key=f"save_{key}"):
            db_manager.save_quiz_items(vault_uuid, res)
            del st.session_state[f"_studio_result_{key}"]
            st.success("已加入测验库")
            st.rerun()
```

新增测验库面板，加到 `studio_panel.py`，在 flashcard_library 前调用:

```python
def _render_quiz_library(vault_uuid: str) -> None:
    items = db_manager.list_quiz_items(vault_uuid, only_unanswered=True)
    if not items:
        return
    with st.expander(f"待答测验 ({len(items)} 题)"):
        for q in items[:10]:
            with st.container(border=True):
                st.markdown(f"**Q:** {q.question}")
                for opt in (q.options or []):
                    st.markdown(f"- {opt}")
                ans = st.radio("你的答案", options=["A","B","C","D"],
                               key=f"qz_{q.id}", horizontal=True,
                               label_visibility="collapsed")
                if st.button("提交", key=f"qz_submit_{q.id}"):
                    ok = db_manager.answer_quiz(q.id, ans)
                    if ok:
                        st.success("答对了！")
                    else:
                        st.error(f"答错了。正确答案: {q.correct}")
                        st.caption(q.explanation or "")
                    st.rerun()
```

`render()` 中调用顺序: tools_grid → divider → quiz_library → flashcard_library → notes_section。

**验收**:
1. 生成测验 → 加入测验库
2. 测验库展开 → 选答案 → 提交
3. 答错时:
   - 显示正确答案和解析
   - `db_manager.list_wrong_answers(vault_uuid)` 新增一条
4. 答对/错后该题从待答列表消失

---

## Step 30 完成 → CHECKPOINT 6

按规则重读 + 写 Checkpoint 6。

---

## Step 31：错题本面板

**目标**: 展示错题，可标记"已掌握"。

**操作**: 在 `studio_panel.py` 加:

```python
def _render_wrong_answers(vault_uuid: str) -> None:
    wrongs = db_manager.list_wrong_answers(vault_uuid, only_unmastered=True)
    if not wrongs:
        return
    with st.expander(f"错题本 ({len(wrongs)} 题)"):
        for w in wrongs[:20]:
            with st.container(border=True):
                st.markdown(f"**Q:** {w.question}")
                st.caption(f"你的答案: {w.user_answer} | 正确: {w.correct_answer}")
                if w.explanation:
                    st.markdown(f"**解析**: {w.explanation}")
                if st.button("已掌握", key=f"wa_{w.id}"):
                    db_manager.mark_wrong_mastered(w.id)
                    st.rerun()
```

`render()` 中调用顺序补充: `_render_wrong_answers(vault_uuid)`，位于 quiz_library 之后、flashcard_library 之前。

**验收**:
1. 故意答错 1 道题
2. 错题本出现该题
3. 点"已掌握" → 错题本减少

---

## Step 32：阶段 D 集成验收

**目标**: Studio 8 大工具 + 闪卡库 + 测验库 + 错题本 + 笔记区，完整跑一遍。

**操作**（人工）:
1. 已有库 + ≥1 个真实来源
2. 8 个工具按钮各点 1 次，确认每个都返回结果
3. 摘要、FAQ → 保存为笔记
4. 思维导图 → 看到 Mermaid 图
5. 闪卡 → 保存 → 翻卡 → 标记掌握度
6. 测验 → 加入测验库 → 答错 1 道 → 进错题本
7. 错题本 → 标记已掌握 → 消失

**DB 全量验证**:
```powershell
python -c "
from core.db import db_manager
vs = db_manager.list_vaults('alice')
u = vs[0].vault_uuid
print('笔记:', len(db_manager.list_notes(u, 'alice')))
print('闪卡:', len(db_manager.list_flashcards(u)))
print('测验:', len(db_manager.list_quiz_items(u)))
print('错题:', len(db_manager.list_wrong_answers(u, only_unmastered=False)))
"
```

**记录 PROGRESS.md**:
```
[Step 32] ✅ 阶段 D 集成
- 12 项进度: F8=✅ F9=✅ F10=✅ F11=✅
```

---

## 阶段 D 完成

阅读 `plans/phase_e_polish.md`。

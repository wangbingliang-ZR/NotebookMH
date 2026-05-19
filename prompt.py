"""
prompt.py - 提示词模板管理
各模板函数只负责生成 user prompt（任务指令 + JSON 格式要求）。
教师人格、通用教学原则通过 teacher_profiles.generate_teacher_prompt() 生成 system prompt，
由 ai.ask_model() 的 system_prompt 参数注入。
"""

from enum import Enum


class UserMode(str, Enum):
    CHILD = "child"
    ADULT = "adult"


# ---------------------------------------------------------------------------
# 1. 讲解 + 出题 模板
# ---------------------------------------------------------------------------

def build_explain_prompt(query: str, concept_hint: str = "") -> str:
    """生成讲解 + 自动出题的 user prompt"""
    concept_part = f"\n【本次涉及的知识点】{concept_hint}\n" if concept_hint else ""
    return f"""学习者问了一个问题："{query}"
{concept_part}
请按以下 JSON 结构返回：
{{
  "explanation": "对知识点的讲解或引导，不要直接给答案，用提问和类比引导学生自己得出结论",
  "question": "根据讲解内容自动生成一道难度适中的练习题",
  "answer": "标准答案（仅用于系统校验，不直接展示给学习者）",
  "hint": "若学习者卡住，可给出的1~2条提示",
  "c_load": 0.5,
  "e_valence": 0.2,
  "diagnosis": "学习者当前状态的简要诊断"
}}
"""


# ---------------------------------------------------------------------------
# 2. 答题判断 + 反馈 模板
# ---------------------------------------------------------------------------

def build_judge_prompt(
    question: str,
    correct_answer: str,
    user_answer: str,
    consecutive_wrong: int = 0,
) -> str:
    tone_hint = ""
    if consecutive_wrong >= 2:
        tone_hint = "学习者已连续答错多次，请显著降低语气难度，给出更具体的生活类比，拆分更细的步骤。"
    elif consecutive_wrong == 1:
        tone_hint = "学习者上次答错了，请温和引导，点出关键误区但不要直接给答案。"

    return f"""练习题：{question}
标准答案：{correct_answer}
学习者的回答：{user_answer}
{tone_hint}

请按以下 JSON 结构返回：
{{
  "explanation": "对学习者回答的反馈：若正确则鼓励并稍作拓展；若错误则引导发现关键误区",
  "question": "根据当前掌握情况生成下一道练习题（答对则略增难度，答错则降低难度或换角度）",
  "answer": "新标准答案",
  "hint": "提示",
  "encouragement": "一句具体的鼓励或引导语",
  "difficulty_adjustment": "建议系统如何调整难度：increase / decrease / same",
  "c_load": 0.5,
  "e_valence": 0.0,
  "diagnosis": "本次答题表现的诊断"
}}
"""


# ---------------------------------------------------------------------------
# 3. 主动提示 模板（思考空窗）
# ---------------------------------------------------------------------------

def build_proactive_prompt(last_question: str, silence_seconds: int) -> str:
    time_desc = f"已经沉默了 {silence_seconds} 秒" if silence_seconds else "似乎有些犹豫"
    return f"""学习者{time_desc}，当前题目是：{last_question}
请给出一句温和的鼓励或一个极小的提示，帮学习者迈出下一步。
注意：不要直接给答案，最多给一个"脚手架"线索。

请按以下 JSON 结构返回：
{{
  "explanation": "给学习者的引导语",
  "hint": "一个极小的提示",
  "encouragement": "一句鼓励的话"
}}
"""


# ---------------------------------------------------------------------------
# 4. 开场 / 寒暄 模板
# ---------------------------------------------------------------------------

def build_greeting_prompt() -> str:
    return """学习者刚刚进入学习系统，请用一句话热情而简洁地打招呼，并邀请他们提出想学的知识点或问题。

请按以下 JSON 结构返回：
{
  "explanation": "打招呼的内容"
}
"""

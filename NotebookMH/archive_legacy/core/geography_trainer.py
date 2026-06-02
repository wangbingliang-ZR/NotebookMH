import logging
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from core.geography_exam_bank import GeographyQuestion, get_exam_bank
from utils.db_manager import ConceptMasteryORM, db_pool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnswerResult:
    is_correct: bool
    score_delta: float
    wrong_reason: str  # 错因标签
    explanation: str
    trap_analysis: str
    concept_name: str
    skill_tag: str
    difficulty: str


@dataclass(frozen=True)
class DailyPack:
    pack_id: str
    questions: List[GeographyQuestion]
    weak_concepts: List[str]
    target_time_min: int


class GeographyTrainer:
    def __init__(self) -> None:
        self.bank = get_exam_bank()

    def diagnose_weakness(self, user_id: str) -> Tuple[List[str], Dict[str, float]]:
        concepts = self.bank.list_concepts()
        weak_concepts: List[str] = []
        mastery_map: Dict[str, float] = {}
        for concept in concepts:
            record = db_pool.get_concept(user_id, concept)
            if record:
                mastery_map[concept] = record.mastery_level
                if record.mastery_level < 70.0 or record.status in ("learning", "struggling"):
                    weak_concepts.append(concept)
            else:
                mastery_map[concept] = 0.0
                weak_concepts.append(concept)
        weak_concepts.sort(key=lambda c: mastery_map.get(c, 0.0))
        return weak_concepts, mastery_map

    def select_difficulty(self, mastery_level: float) -> str:
        if mastery_level < 40.0:
            return "easy"
        elif mastery_level < 70.0:
            return "medium"
        else:
            return "hard"

    def build_daily_pack(
        self,
        user_id: str,
        question_count: int = 8,
        target_time_min: int = 15,
    ) -> DailyPack:
        weak_concepts, mastery_map = self.diagnose_weakness(user_id)
        selected: List[GeographyQuestion] = []
        used_ids: Set[str] = set()

        # 优先从薄弱概念出题
        for concept in weak_concepts:
            if len(selected) >= question_count:
                break
            candidates = self.bank.by_concept(concept)
            difficulty = self.select_difficulty(mastery_map.get(concept, 0.0))
            filtered = [q for q in candidates if q.difficulty == difficulty and q.question_id not in used_ids]
            if not filtered:
                filtered = [q for q in candidates if q.question_id not in used_ids]
            if filtered:
                q = random.choice(filtered)
                selected.append(q)
                used_ids.add(q.question_id)

        # 补充到目标题量
        all_questions = self.bank.all_questions()
        remaining = [q for q in all_questions if q.question_id not in used_ids]
        random.shuffle(remaining)
        for q in remaining:
            if len(selected) >= question_count:
                break
            selected.append(q)
            used_ids.add(q.question_id)

        pack_id = f"geo_pack_{user_id}_{hash(tuple(used_ids)) & 0x7FFFFFFF}"
        return DailyPack(
            pack_id=pack_id,
            questions=selected,
            weak_concepts=weak_concepts[:3],
            target_time_min=target_time_min,
        )

    def check_answer(
        self, user_id: str, question_id: str, user_answer: str
    ) -> AnswerResult:
        question = self.bank.get_question(question_id)
        if not question:
            return AnswerResult(
                is_correct=False,
                score_delta=-2.0,
                wrong_reason="题目未找到",
                explanation="",
                trap_analysis="",
                concept_name="",
                skill_tag="",
                difficulty="",
            )

        is_correct = user_answer.strip().upper() == question.answer.strip().upper()
        score_delta = 8.0 if is_correct else -4.0
        wrong_reason = question.common_mistake if not is_correct else ""

        # 更新掌握度
        db_pool.update_concept_mastery(
            user_id=user_id,
            concept_name=question.concept_name,
            mastery_delta=score_delta,
            correct=is_correct,
        )
        db_pool.update_user_stats(user_id=user_id, correct=is_correct)

        return AnswerResult(
            is_correct=is_correct,
            score_delta=score_delta,
            wrong_reason=wrong_reason,
            explanation=question.explanation,
            trap_analysis=question.trap_analysis,
            concept_name=question.concept_name,
            skill_tag=question.skill_tag,
            difficulty=question.difficulty,
        )

    def build_review_pack(self, user_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """从最近错题中构建回炉列表。"""
        logs = db_pool.get_wrong_logs(user_id, limit=limit * 3)
        review_items: List[Dict[str, Any]] = []
        seen_concepts: Set[str] = set()
        for log in logs:
            if log.diagnosis and "concept_name" in log.diagnosis:
                import json
                try:
                    diag = json.loads(log.diagnosis)
                    concept = diag.get("concept_name", "")
                    if concept and concept not in seen_concepts:
                        questions = self.bank.by_concept(concept)
                        if questions:
                            review_items.append({
                                "concept": concept,
                                "question": questions[0],
                                "hint": f"上次错因：{log.diagnosis[:60]}...",
                            })
                            seen_concepts.add(concept)
                except Exception:
                    continue
            if len(review_items) >= limit:
                break
        return review_items


_TRAINER_INSTANCE: Optional[GeographyTrainer] = None


def get_geography_trainer() -> GeographyTrainer:
    global _TRAINER_INSTANCE
    if _TRAINER_INSTANCE is None:
        _TRAINER_INSTANCE = GeographyTrainer()
    return _TRAINER_INSTANCE

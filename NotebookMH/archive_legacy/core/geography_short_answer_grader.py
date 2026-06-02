import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from core.geography_answer_templates import (
    AnswerTemplate,
    get_template_library,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScorePointResult:
    point_text: str
    is_hit: bool
    hit_keywords: List[str]


@dataclass(frozen=True)
class GradingResult:
    template_id: str
    template_name: str
    student_answer: str
    full_score: int
    earned_score: int
    hit_points: List[str]
    missed_points: List[str]
    suggested_answer: str
    weak_spots: List[str]
    next_template_suggestion: Optional[str]


class GeographyShortAnswerGrader:
    def __init__(self) -> None:
        self.library = get_template_library()

    def grade(self, student_answer: str, template_id: str) -> GradingResult:
        template = self.library.get_template(template_id)
        if not template:
            return GradingResult(
                template_id=template_id,
                template_name="",
                student_answer=student_answer,
                full_score=0,
                earned_score=0,
                hit_points=[],
                missed_points=[],
                suggested_answer="",
                weak_spots=["模板未找到"],
                next_template_suggestion=None,
            )

        hit_results, missed_results = self._match_score_points(
            student_answer, template
        )
        hit_points = [r.point_text for r in hit_results]
        missed_points = [r.point_text for r in missed_results]
        earned = self._calculate_score(hit_points, template.full_score)
        suggested = self._build_suggested_answer(hit_points, missed_points, template)
        weak_spots = self._identify_weak_spots(hit_results, missed_results, template)
        next_suggestion = self._suggest_next_template(template_id, weak_spots)

        return GradingResult(
            template_id=template_id,
            template_name=template.template_name,
            student_answer=student_answer,
            full_score=template.full_score,
            earned_score=earned,
            hit_points=hit_points,
            missed_points=missed_points,
            suggested_answer=suggested,
            weak_spots=weak_spots,
            next_template_suggestion=next_suggestion,
        )

    def _match_score_points(
        self, student_answer: str, template: AnswerTemplate
    ) -> Tuple[List[ScorePointResult], List[ScorePointResult]]:
        hit_results: List[ScorePointResult] = []
        missed_results: List[ScorePointResult] = []
        normalized_answer = self._normalize(student_answer)

        for point in template.score_points:
            point_hit, keywords = self._check_point(normalized_answer, point, template.synonym_map)
            if point_hit:
                hit_results.append(
                    ScorePointResult(point_text=point, is_hit=True, hit_keywords=keywords)
                )
            else:
                missed_results.append(
                    ScorePointResult(point_text=point, is_hit=False, hit_keywords=[])
                )
        return hit_results, missed_results

    def _check_point(
        self, normalized_answer: str, point: str, synonym_map: Dict[str, List[str]]
    ) -> Tuple[bool, List[str]]:
        all_keywords: Set[str] = set()
        for key, synonyms in synonym_map.items():
            if key in point:
                all_keywords.add(self._normalize(key))
                all_keywords.update(self._normalize(s) for s in synonyms)

        if not all_keywords:
            all_keywords = {self._normalize(point)}

        found: List[str] = []
        for kw in all_keywords:
            if kw in normalized_answer and len(kw) >= 2:
                found.append(kw)

        return len(found) > 0, found

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.lower().strip()
        text = re.sub(r"[^\u4e00-\u9fff\u3000-\u303f\uff00-\uffefa-zA-Z0-9]", "", text)
        return text

    def _calculate_score(self, hit_points: List[str], full_score: int) -> int:
        per_point = max(1, full_score // max(1, len(hit_points) + 1))
        raw = len(hit_points) * per_point
        return min(raw, full_score)

    def _build_suggested_answer(
        self,
        hit_points: List[str],
        missed_points: List[str],
        template: AnswerTemplate,
    ) -> str:
        lines: List[str] = []
        lines.append(f"【{template.template_name}】标准答题要点：")
        for point in template.score_points:
            if point in hit_points:
                lines.append(f"✅ {point}")
            else:
                lines.append(f"❌ {point}")
        if missed_points:
            lines.append("\n建议补充：")
            for mp in missed_points:
                lines.append(f"  • {mp}")
        lines.append(f"\n💡 {template.tips}")
        return "\n".join(lines)

    def _identify_weak_spots(
        self,
        hit_results: List[ScorePointResult],
        missed_results: List[ScorePointResult],
        template: AnswerTemplate,
    ) -> List[str]:
        weak: List[str] = []
        if len(missed_results) >= 3:
            weak.append(f"{template.template_name}掌握不牢，遗漏了{len(missed_results)}个得分点")
        natural_miss = sum(1 for m in missed_results if "自然" in m.point_text)
        social_miss = sum(1 for m in missed_results if "社会经济" in m.point_text or "社会经济" in m.point_text)
        if natural_miss > 0 and social_miss > 0:
            weak.append("自然条件和社会经济条件都写不完整")
        elif natural_miss > 0:
            weak.append("自然条件遗漏较多")
        elif social_miss > 0:
            weak.append("社会经济条件遗漏较多")
        for miss in template.common_misses:
            weak.append(miss)
        return weak[:4]

    def _suggest_next_template(self, current_id: str, weak_spots: List[str]) -> Optional[str]:
        suggestions: Dict[str, str] = {
            "agriculture_location": "soil_erosion",
            "industry_location": "transport_location",
            "river_governance": "soil_erosion",
            "soil_erosion": "river_governance",
            "population_city": "regional_development",
            "transport_location": "industry_location",
            "climate_cause": "regional_development",
            "regional_development": "climate_cause",
        }
        return suggestions.get(current_id)

    def quick_check(self, student_answer: str, template_id: str) -> Dict[str, any]:
        result = self.grade(student_answer, template_id)
        return {
            "template_name": result.template_name,
            "score": f"{result.earned_score}/{result.full_score}",
            "hit_count": len(result.hit_points),
            "miss_count": len(result.missed_points),
            "weak_spots": result.weak_spots,
            "next": result.next_template_suggestion,
        }


_GRADER_INSTANCE: Optional[GeographyShortAnswerGrader] = None


def get_short_answer_grader() -> GeographyShortAnswerGrader:
    global _GRADER_INSTANCE
    if _GRADER_INSTANCE is None:
        _GRADER_INSTANCE = GeographyShortAnswerGrader()
    return _GRADER_INSTANCE

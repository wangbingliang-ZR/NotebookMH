import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class GeoCausalNode:
    name: str
    explanation: str


@dataclass(frozen=True)
class DamValidationResult:
    is_valid: bool
    score_delta: float
    reason: str
    concept_name: str


@dataclass(frozen=True)
class GeographyPracticeScenario:
    scenario_id: str
    title: str
    question: str
    concept_name: str
    key_points: List[str]
    causal_chain: List[GeoCausalNode]


class GeographyCausalAtlas:
    def __init__(self) -> None:
        self._scenarios = self._build_scenarios()

    def list_scenarios(self) -> List[GeographyPracticeScenario]:
        return list(self._scenarios.values())

    def get_scenario(self, scenario_id: str) -> GeographyPracticeScenario:
        return self._scenarios.get(scenario_id, self._scenarios["monsoon_rainfall"])

    def explain(self, scenario_id: str) -> Dict[str, Any]:
        scenario = self.get_scenario(scenario_id)
        return {
            "title": scenario.title,
            "question": scenario.question,
            "concept_name": scenario.concept_name,
            "key_points": scenario.key_points,
            "causal_chain": [node.__dict__ for node in scenario.causal_chain],
        }

    @staticmethod
    def _build_scenarios() -> Dict[str, GeographyPracticeScenario]:
        return {
            "monsoon_rainfall": GeographyPracticeScenario(
                scenario_id="monsoon_rainfall",
                title="季风与降水",
                question="夏季风增强时，我国东部降水为什么通常增多？",
                concept_name="中考地理-季风降水",
                key_points=["海陆热力差异", "夏季风", "水汽输送", "迎风坡降水"],
                causal_chain=[
                    GeoCausalNode("海陆热力差异", "夏季陆地升温快，形成较强低压。"),
                    GeoCausalNode("夏季风增强", "来自海洋的暖湿气流更容易深入陆地。"),
                    GeoCausalNode("水汽输送增加", "空气中水汽含量上升，遇冷抬升后凝结。"),
                    GeoCausalNode("东部降水增多", "东部沿海和迎风坡更容易形成降水。"),
                ],
            ),
            "contour_dam": GeographyPracticeScenario(
                scenario_id="contour_dam",
                title="等高线与水库选址",
                question="水坝为什么常建在峡谷口，而不是宽阔平原中央？",
                concept_name="中考地理-等高线水库选址",
                key_points=["峡谷口", "两侧高地", "上游盆地", "工程量小蓄水多"],
                causal_chain=[
                    GeoCausalNode("等高线密集", "坡度陡，常对应山谷或峡谷地形。"),
                    GeoCausalNode("峡谷口狭窄", "坝体较短，工程量相对小。"),
                    GeoCausalNode("上游盆地宽阔", "蓄水空间大，形成水库。"),
                    GeoCausalNode("坝址合理", "兼顾工程成本和蓄水效益。"),
                ],
            ),
            "sea_level": GeographyPracticeScenario(
                scenario_id="sea_level",
                title="海平面上升与沿海低地",
                question="为什么海平面上升最先威胁三角洲和沿海平原？",
                concept_name="中考地理-海平面上升",
                key_points=["低海拔", "地势平坦", "河口三角洲", "风暴潮风险"],
                causal_chain=[
                    GeoCausalNode("海拔低", "三角洲和沿海平原接近海平面。"),
                    GeoCausalNode("坡度小", "水面上升一点，淹没范围会扩大很多。"),
                    GeoCausalNode("人口产业密集", "沿海地区常有城市、农田和港口。"),
                    GeoCausalNode("风险放大", "海平面上升叠加风暴潮，会增加洪涝灾害。"),
                ],
            ),
            "trade_wind_amazon": GeographyPracticeScenario(
                scenario_id="trade_wind_amazon",
                title="气压带风带与雨林降水",
                question="信风带和赤道低压带移动会怎样影响热带雨林降水？",
                concept_name="中考地理-气压带风带移动",
                key_points=["太阳直射点移动", "赤道低压带", "信风", "水汽辐合上升"],
                causal_chain=[
                    GeoCausalNode("太阳直射点季节移动", "全球热量分布随季节变化。"),
                    GeoCausalNode("气压带风带移动", "赤道低压带和信风带随之南北摆动。"),
                    GeoCausalNode("水汽辐合位置变化", "暖湿气流汇聚并上升的位置发生变化。"),
                    GeoCausalNode("降水带移动", "雨林区降水强弱和季节分配会改变。"),
                ],
            ),
        }


class GeoHapticEngine:
    def generate_teaching_dem(self, size: int = 80) -> np.ndarray:
        safe_size = max(20, min(200, int(size)))
        axis = np.linspace(-1.0, 1.0, safe_size)
        grid_x, grid_y = np.meshgrid(axis, axis)
        ridge_left = 90.0 * np.exp(-((grid_x + 0.45) ** 2) / 0.08)
        ridge_right = 90.0 * np.exp(-((grid_x - 0.45) ** 2) / 0.08)
        upstream_basin = -35.0 * np.exp(-((grid_y + 0.35) ** 2 + grid_x ** 2) / 0.22)
        river_valley = -45.0 * np.exp(-(grid_x ** 2) / 0.018)
        downstream_slope = 25.0 * (1.0 - grid_y)
        dem_matrix = ridge_left + ridge_right + upstream_basin + river_valley + downstream_slope + 80.0
        return np.clip(dem_matrix, 0.0, 220.0)

    def simulate_sea_level(self, dem_matrix: np.ndarray, sea_level: float) -> np.ndarray:
        matrix = np.asarray(dem_matrix, dtype=float)
        return matrix <= float(sea_level)

    def validate_dam_placement(self, point_x: int, point_y: int, dem_matrix: np.ndarray) -> DamValidationResult:
        matrix = np.asarray(dem_matrix, dtype=float)
        if matrix.ndim != 2 or matrix.size == 0:
            return DamValidationResult(False, -3.0, "地形数据无效，无法判定坝址。", "中考地理-等高线水库选址")

        row_count, col_count = matrix.shape
        column = max(2, min(col_count - 3, int(point_x)))
        row = max(2, min(row_count - 3, int(point_y)))

        center_altitude = float(matrix[row, column])
        left_altitude = float(matrix[row, column - 2])
        right_altitude = float(matrix[row, column + 2])
        upstream_altitude = float(matrix[max(0, row - 8):row, max(0, column - 8):min(col_count, column + 9)].mean())
        downstream_altitude = float(matrix[row:min(row_count, row + 8), max(0, column - 8):min(col_count, column + 9)].mean())

        side_wall_strength = min(left_altitude - center_altitude, right_altitude - center_altitude)
        upstream_storage = center_altitude - upstream_altitude
        downstream_drop = downstream_altitude - center_altitude

        is_narrow_valley = side_wall_strength >= 12.0
        has_storage_basin = upstream_storage >= 2.0
        has_outlet_drop = downstream_drop >= -8.0
        score = sum([is_narrow_valley, has_storage_basin, has_outlet_drop])

        if score >= 3:
            return DamValidationResult(
                True,
                8.0,
                "判断正确：该点两侧地势较高，上游具备蓄水空间，符合峡谷口建坝的核心逻辑。",
                "中考地理-等高线水库选址",
            )
        if score == 2:
            return DamValidationResult(
                False,
                2.0,
                "接近正确：你找到了部分谷地特征，但还要同时观察两侧高地和上游是否足够开阔。",
                "中考地理-等高线水库选址",
            )
        return DamValidationResult(
            False,
            -4.0,
            "暂不合适：坝址通常应选在狭窄峡谷口，并让上游有较大蓄水空间。请重新读等高线疏密和谷地形态。",
            "中考地理-等高线水库选址",
        )


class GeographyExamEngine:
    def __init__(self) -> None:
        self.causal_atlas = GeographyCausalAtlas()
        self.haptic_engine = GeoHapticEngine()

    def build_revision_pack(self, scenario_id: str, c_load: float = 0.0) -> Dict[str, Any]:
        scenario_data = self.causal_atlas.explain(scenario_id)
        if c_load > 0.85:
            scenario_data["mode"] = "降维因果链"
            scenario_data["advice"] = "先背因果链，不急着看复杂图。按箭头复述一遍即可。"
        else:
            scenario_data["mode"] = "读图训练"
            scenario_data["advice"] = "先看图，再用因果链解释现象。"
        return scenario_data


_geo_exam_engine: Optional[GeographyExamEngine] = None


def get_geography_exam_engine() -> GeographyExamEngine:
    global _geo_exam_engine
    if _geo_exam_engine is None:
        _geo_exam_engine = GeographyExamEngine()
    return _geo_exam_engine

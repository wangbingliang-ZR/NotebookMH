import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeographyQuestion:
    question_id: str
    question_type: str  # "choice" | "map_reading" | "causal" | "fill_blank"
    concept_name: str
    skill_tag: str
    difficulty: str  # "easy" | "medium" | "hard"
    question: str
    options: List[str]
    answer: str
    explanation: str
    trap_analysis: str
    common_mistake: str


class GeographyExamBank:
    def __init__(self) -> None:
        self._questions = self._build_bank()
        self._concept_index: Dict[str, List[GeographyQuestion]] = {}
        self._skill_index: Dict[str, List[GeographyQuestion]] = {}
        self._difficulty_index: Dict[str, List[GeographyQuestion]] = {}
        self._rebuild_indexes()

    def _rebuild_indexes(self) -> None:
        self._concept_index.clear()
        self._skill_index.clear()
        self._difficulty_index.clear()
        for q in self._questions:
            self._concept_index.setdefault(q.concept_name, []).append(q)
            self._skill_index.setdefault(q.skill_tag, []).append(q)
            self._difficulty_index.setdefault(q.difficulty, []).append(q)

    def all_questions(self) -> List[GeographyQuestion]:
        return list(self._questions)

    def by_concept(self, concept_name: str) -> List[GeographyQuestion]:
        return list(self._concept_index.get(concept_name, []))

    def by_skill(self, skill_tag: str) -> List[GeographyQuestion]:
        return list(self._skill_index.get(skill_tag, []))

    def by_difficulty(self, difficulty: str) -> List[GeographyQuestion]:
        return list(self._difficulty_index.get(difficulty, []))

    def get_question(self, question_id: str) -> Optional[GeographyQuestion]:
        for q in self._questions:
            if q.question_id == question_id:
                return q
        return None

    def list_concepts(self) -> Set[str]:
        return set(self._concept_index.keys())

    def list_skills(self) -> Set[str]:
        return set(self._skill_index.keys())

    @staticmethod
    def _build_bank() -> List[GeographyQuestion]:
        return [
            # === 等高线判读 ===
            GeographyQuestion(
                question_id="contour_001",
                question_type="choice",
                concept_name="中考地理-等高线山谷山脊",
                skill_tag="读图判断",
                difficulty="easy",
                question="在等高线地形图中，等高线向高处凸出的部位表示什么地形？",
                options=["A. 山脊", "B. 山谷", "C. 鞍部", "D. 陡崖"],
                answer="B",
                explanation="等高线向海拔高处凸出表示山谷（集水线），向低处凸出表示山脊（分水线）。",
                trap_analysis="混淆山谷与山脊的等高线形态，山谷向高处凸，山脊向低处凸。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="contour_002",
                question_type="choice",
                concept_name="中考地理-等高线山谷山脊",
                skill_tag="读图判断",
                difficulty="easy",
                question="等高线密集的地方表示什么？",
                options=["A. 坡度缓", "B. 坡度陡", "C. 海拔高", "D. 海拔低"],
                answer="B",
                explanation="等高线密集表示坡度陡，稀疏表示坡度缓。",
                trap_analysis="容易把密集和海拔高低混淆，密集只和坡度有关。",
                common_mistake="读图失误",
            ),
            GeographyQuestion(
                question_id="contour_003",
                question_type="choice",
                concept_name="中考地理-等高线水库选址",
                skill_tag="综合分析",
                difficulty="medium",
                question="水库大坝最理想的选址是？",
                options=[
                    "A. 等高线密集的峡谷口，上游盆地宽阔",
                    "B. 等高线稀疏的平原中央",
                    "C. 山顶鞍部",
                    "D. 陡崖下方",
                ],
                answer="A",
                explanation="峡谷口等高线密集，坝体短工程量小；上游盆地宽阔，蓄水量大。",
                trap_analysis="容易选平原，认为施工方便，但平原蓄不住水。",
                common_mistake="因果断裂",
            ),
            GeographyQuestion(
                question_id="contour_004",
                question_type="choice",
                concept_name="中考地理-等高线山谷山脊",
                skill_tag="读图判断",
                difficulty="medium",
                question="图中 AB 两点为山脊和山谷，若河流从 A 流向 B，则 A、B 分别是什么地形？",
                options=[
                    "A. A 山脊 B 山谷",
                    "B. A 山谷 B 山脊",
                    "C. A 鞍部 B 陡崖",
                    "D. A 山顶 B 山脊",
                ],
                answer="B",
                explanation="河流发育在山谷中，从高处流向低处，所以上游 A 是山谷，下游 B 是山脊或谷口。",
                trap_analysis="河流只会出现在山谷，不会出现在山脊。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="contour_005",
                question_type="fill_blank",
                concept_name="中考地理-等高线山谷山脊",
                skill_tag="读图判断",
                difficulty="hard",
                question="等高线重合的地方表示____，适合开展____活动。（填地形名称和一种人类活动）",
                options=["陡崖;攀岩或瀑布观光", "鞍部;露营", "山顶;滑雪", "山谷;漂流"],
                answer="陡崖;攀岩或瀑布观光",
                explanation="等高线重合为陡崖，地势陡峭，可发展攀岩或观光瀑布。",
                trap_analysis="容易把重合和交叉混淆，等高线不会交叉，只会重合。",
                common_mistake="概念混淆",
            ),
            # === 气候类型判断 ===
            GeographyQuestion(
                question_id="climate_001",
                question_type="choice",
                concept_name="中考地理-气候类型判断",
                skill_tag="读图判断",
                difficulty="easy",
                question="全年高温，分明显的干湿两季，这是哪种气候类型？",
                options=["A. 热带雨林气候", "B. 热带草原气候", "C. 热带季风气候", "D. 热带沙漠气候"],
                answer="B",
                explanation="热带草原气候全年高温，有明显的干湿两季；热带雨林全年多雨，季风气候全年高温分旱雨两季但有季风环流。",
                trap_analysis="容易和热带季风混淆，草原气候是信风和赤道低压交替控制，季风是海陆热力差异。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="climate_002",
                question_type="choice",
                concept_name="中考地理-气候类型判断",
                skill_tag="读图判断",
                difficulty="medium",
                question="读某地气温曲线和降水柱状图：夏季炎热干燥，冬季温和多雨。这是哪种气候？",
                options=["A. 地中海气候", "B. 温带海洋性气候", "C. 亚热带季风气候", "D. 温带季风气候"],
                answer="A",
                explanation="地中海气候典型特征：夏季炎热干燥（副热带高压控制），冬季温和多雨（西风带控制）。",
                trap_analysis="和温带海洋性气候混淆，后者全年温和湿润。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="climate_003",
                question_type="choice",
                concept_name="中考地理-气候类型判断",
                skill_tag="读图判断",
                difficulty="medium",
                question="温带季风气候和亚热带季风气候的主要区别是什么？",
                options=[
                    "A. 降水量多少",
                    "B. 冬季气温是否低于0℃",
                    "C. 夏季长短",
                    "D. 风向",
                ],
                answer="B",
                explanation="温带季风最冷月均温低于0℃，亚热带季风最冷月均温高于0℃，这是分界线标准。",
                trap_analysis="容易选降水量，但两者降水都集中在夏季。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="climate_004",
                question_type="causal",
                concept_name="中考地理-气候成因",
                skill_tag="因果解释",
                difficulty="hard",
                question="为什么青藏高原夏季气温比同纬度的长江中下游平原低得多？",
                options=[
                    "A. 海拔高，气温随高度升高而降低",
                    "B. 远离海洋",
                    "C. 纬度高",
                    "D. 冬季风影响",
                ],
                answer="A",
                explanation="海拔每升高100米，气温约下降0.6℃。青藏高原平均海拔4000米以上，夏季凉爽。",
                trap_analysis="容易选远离海洋，但海洋影响的是年较差，不是夏季温度低的主因。",
                common_mistake="因果断裂",
            ),
            # === 河流与地形 ===
            GeographyQuestion(
                question_id="river_001",
                question_type="choice",
                concept_name="中考地理-河流与地形",
                skill_tag="读图判断",
                difficulty="easy",
                question="河流上游通常是什么地貌？",
                options=["A. 平原", "B. 峡谷", "C. 三角洲", "D. 冲积扇"],
                answer="B",
                explanation="河流上游地势落差大，流速快，下切侵蚀为主，常形成峡谷。",
                trap_analysis="容易和平原混淆，平原一般在下游。",
                common_mistake="读图失误",
            ),
            GeographyQuestion(
                question_id="river_002",
                question_type="choice",
                concept_name="中考地理-河流与地形",
                skill_tag="综合分析",
                difficulty="medium",
                question="水电站大坝为什么多建在河流上游？",
                options=[
                    "A. 上游水量大",
                    "B. 上游落差大，水能丰富",
                    "C. 上游人口少",
                    "D. 上游交通方便",
                ],
                answer="B",
                explanation="水能资源取决于水量和落差。上游落差大，水流急，水能蕴藏量丰富。",
                trap_analysis="容易选水量大，但上游水量通常不如中下游。",
                common_mistake="因果断裂",
            ),
            GeographyQuestion(
                question_id="river_003",
                question_type="choice",
                concept_name="中考地理-河流与地形",
                skill_tag="综合分析",
                difficulty="medium",
                question="黄河下游成为'地上河'的主要原因是什么？",
                options=[
                    "A. 下游降水量大",
                    "B. 中游水土流失，下游泥沙淤积",
                    "C. 下游地势低洼",
                    "D. 下游人工筑堤",
                ],
                answer="B",
                explanation="黄河中游流经黄土高原，水土流失严重，大量泥沙在下游淤积，河床抬高。",
                trap_analysis="容易只选地势低洼或人工筑堤，忽略了中游水土流失这一根本原因。",
                common_mistake="因果断裂",
            ),
            GeographyQuestion(
                question_id="river_004",
                question_type="causal",
                concept_name="中考地理-河流与地形",
                skill_tag="因果解释",
                difficulty="hard",
                question="长江三峡段水能极为丰富的原因是什么？（多因素）",
                options=[
                    "A. 落差大 + 水量丰富",
                    "B. 落差大 + 河道弯曲",
                    "C. 水量大 + 流速慢",
                    "D. 河道宽 + 落差大",
                ],
                answer="A",
                explanation="三峡地处我国地势第二、三级阶梯交界处，落差大；同时长江流域降水丰富，水量大，水能极为丰富。",
                trap_analysis="容易忽略水量因素，只考虑落差。",
                common_mistake="因果断裂",
            ),
            # === 农业区位 ===
            GeographyQuestion(
                question_id="agri_001",
                question_type="choice",
                concept_name="中考地理-农业区位",
                skill_tag="综合分析",
                difficulty="easy",
                question="我国南方地区发展水稻种植的有利自然条件不包括？",
                options=[
                    "A. 雨热同期",
                    "B. 水源充足",
                    "C. 市场广阔",
                    "D. 地形平坦",
                ],
                answer="C",
                explanation="市场广阔属于社会经济条件，不是自然条件。题目问的是自然条件。",
                trap_analysis="审题粗心！注意题目问的是'不包括'和'自然条件'两个限定。",
                common_mistake="审题粗心",
            ),
            GeographyQuestion(
                question_id="agri_002",
                question_type="fill_blank",
                concept_name="中考地理-农业区位",
                skill_tag="因果解释",
                difficulty="medium",
                question="新疆发展棉花种植的有利条件：光照____，昼夜温差____，利于棉花生长和纤维发育。",
                options=["充足;大", "不足;小", "充足;小", "不足;大"],
                answer="充足;大",
                explanation="新疆深居内陆，晴天多光照充足；昼夜温差大，白天光合作用强，夜间呼吸作用弱，利于有机质积累。",
                trap_analysis="容易忽略昼夜温差这个关键因素。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="agri_003",
                question_type="causal",
                concept_name="中考地理-农业区位",
                skill_tag="因果解释",
                difficulty="hard",
                question="东北地区发展商品粮基地的优势条件有哪些？",
                options=[
                    "A. 黑土肥沃、地广人稀、机械化水平高",
                    "B. 热量充足、一年三熟",
                    "C. 降水丰富、水田为主",
                    "D. 交通便利、市场广阔",
                ],
                answer="A",
                explanation="东北黑土肥沃；地广人稀，人均耕地多；机械化水平高，适合大规模商品粮生产。",
                trap_analysis="容易选热量充足一年三熟，但东北热量不足，只能一年一熟。",
                common_mistake="概念混淆",
            ),
            # === 中国区域地理 ===
            GeographyQuestion(
                question_id="region_001",
                question_type="choice",
                concept_name="中考地理-中国区域地理",
                skill_tag="区域定位",
                difficulty="easy",
                question="我国四大地理区域中，以干旱为主要自然特征的是？",
                options=["A. 北方地区", "B. 南方地区", "C. 西北地区", "D. 青藏地区"],
                answer="C",
                explanation="西北地区深居内陆，远离海洋，降水稀少，以干旱为主要特征。",
                trap_analysis="容易和青藏地区混淆，青藏地区是高寒。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="region_002",
                question_type="choice",
                concept_name="中考地理-中国区域地理",
                skill_tag="区域定位",
                difficulty="medium",
                question="青藏地区农作物主要分布在河谷地带的主要原因是？",
                options=[
                    "A. 河谷土壤肥沃",
                    "B. 河谷海拔较低，热量条件较好",
                    "C. 河谷水源充足",
                    "D. 河谷交通便利",
                ],
                answer="B",
                explanation="青藏高原海拔高、气温低，热量不足是农业限制因素。河谷海拔较低，热量条件相对较好。",
                trap_analysis="容易选土壤或水源，但河谷地区热量才是最大限制因素。",
                common_mistake="因果断裂",
            ),
            GeographyQuestion(
                question_id="region_003",
                question_type="causal",
                concept_name="中考地理-中国区域地理",
                skill_tag="综合分析",
                difficulty="hard",
                question="为什么秦岭-淮河一线是我国重要的地理分界线？（至少说出3个意义）",
                options=[
                    "A. 1月0℃等温线、800mm等降水量线、亚热带与暖温带分界线",
                    "B. 季风区与非季风区分界线",
                    "C. 地势第一、二级阶梯分界线",
                    "D. 内流区与外流区分界线",
                ],
                answer="A",
                explanation="秦岭-淮河是1月0℃等温线、800mm等降水量线、亚热带与暖温带、湿润区与半湿润区、亚热带季风与温带季风的分界线。",
                trap_analysis="容易和季风区界线混淆，季风区界线是大兴安岭-阴山-贺兰山-巴颜喀拉山-冈底斯山。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="region_004",
                question_type="choice",
                concept_name="中考地理-中国区域地理",
                skill_tag="区域定位",
                difficulty="medium",
                question="黄土高原水土流失严重的人为原因主要是？",
                options=[
                    "A. 土质疏松",
                    "B. 降水集中且多暴雨",
                    "C. 过度开垦、过度放牧、破坏植被",
                    "D. 地形崎岖",
                ],
                answer="C",
                explanation="A、B、D都是自然原因。C是人类活动对植被的破坏，导致水土流失加剧。",
                trap_analysis="审题粗心！注意题目问的是'人为原因'。",
                common_mistake="审题粗心",
            ),
            # === 季风与降水 ===
            GeographyQuestion(
                question_id="monsoon_001",
                question_type="choice",
                concept_name="中考地理-季风降水",
                skill_tag="因果解释",
                difficulty="easy",
                question="我国东部地区的降水主要受什么影响？",
                options=["A. 冬季风", "B. 夏季风", "C. 西风带", "D. 信风带"],
                answer="B",
                explanation="我国东部地区受夏季风影响，从海洋带来大量水汽，形成降水。",
                trap_analysis="容易选冬季风，但冬季风来自内陆，干燥少雨。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="monsoon_002",
                question_type="causal",
                concept_name="中考地理-季风降水",
                skill_tag="因果解释",
                difficulty="medium",
                question="为什么夏季风强的年份，北方地区容易洪涝，而南方地区容易干旱？",
                options=[
                    "A. 夏季风强则雨带快速北推，北方降水多，南方受副高控制干旱",
                    "B. 夏季风强则全国都多雨",
                    "C. 夏季风强则雨带停滞在南方",
                    "D. 夏季风强则北方干旱",
                ],
                answer="A",
                explanation="夏季风强，雨带推移快，迅速到达北方并在北方滞留，北方降水偏多；南方受副热带高压控制，降水偏少。",
                trap_analysis="容易认为夏季风强全国都多雨，实际上雨带位置和夏季风强弱密切相关。",
                common_mistake="因果断裂",
            ),
            GeographyQuestion(
                question_id="monsoon_003",
                question_type="choice",
                concept_name="中考地理-季风降水",
                skill_tag="综合分析",
                difficulty="hard",
                question="我国降水空间分布的总趋势是？",
                options=[
                    "A. 从东南沿海向西北内陆递减",
                    "B. 从西北向东南递减",
                    "C. 从南向北递增",
                    "D. 从东向西递增",
                ],
                answer="A",
                explanation="受夏季风影响，我国降水从东南沿海向西北内陆递减。",
                trap_analysis="容易记反方向。",
                common_mistake="概念混淆",
            ),
            # === 海平面与沿海 ===
            GeographyQuestion(
                question_id="sea_001",
                question_type="choice",
                concept_name="中考地理-海平面上升",
                skill_tag="综合分析",
                difficulty="medium",
                question="全球气候变暖导致海平面上升，对沿海地区威胁最大的自然原因是？",
                options=[
                    "A. 沿海地区经济发达",
                    "B. 沿海地势低平，海拔接近海平面",
                    "C. 沿海地区人口多",
                    "D. 沿海风暴多",
                ],
                answer="B",
                explanation="自然威胁的根本原因是沿海地势低平。A、C是社会经济原因，D是叠加因素但不是根本原因。",
                trap_analysis="审题粗心！注意题目问的是'自然原因'。",
                common_mistake="审题粗心",
            ),
            GeographyQuestion(
                question_id="sea_002",
                question_type="causal",
                concept_name="中考地理-海平面上升",
                skill_tag="因果解释",
                difficulty="hard",
                question="为什么河口三角洲最容易受到海平面上升的威胁？",
                options=[
                    "A. 三角洲海拔低、地势平坦，水面上升一点淹没范围大",
                    "B. 三角洲土壤肥沃",
                    "C. 三角洲河流多",
                    "D. 三角洲经济发达",
                ],
                answer="A",
                explanation="三角洲海拔低、地势平坦，坡度极小，海平面稍微上升就会导致大范围淹没。",
                trap_analysis="容易选河流多或经济发达，但题目问的是为什么'最容易受到威胁'，关键是地势。",
                common_mistake="因果断裂",
            ),
            # === 气压带风带 ===
            GeographyQuestion(
                question_id="pressure_001",
                question_type="choice",
                concept_name="中考地理-气压带风带移动",
                skill_tag="因果解释",
                difficulty="medium",
                question="气压带和风带位置的季节移动是由什么引起的？",
                options=[
                    "A. 地球自转",
                    "B. 太阳直射点的季节移动",
                    "C. 海陆热力差异",
                    "D. 地形阻挡",
                ],
                answer="B",
                explanation="太阳直射点随季节南北移动，导致全球热量分布变化，气压带和风带随之移动。",
                trap_analysis="容易选地球自转或海陆热力差异，前者产生地转偏向力，后者产生季风。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="pressure_002",
                question_type="causal",
                concept_name="中考地理-气压带风带移动",
                skill_tag="因果解释",
                difficulty="hard",
                question="当太阳直射点北移时，赤道低压带和信风带如何移动？对热带雨林区降水有什么影响？",
                options=[
                    "A. 赤道低压带北移，信风带北移，雨林区降水带北移",
                    "B. 都南移",
                    "C. 赤道低压带北移，信风带南移",
                    "D. 都不移动",
                ],
                answer="A",
                explanation="太阳直射点北移 → 气压带风带北移 → 赤道低压带和信风带北移 → 雨林区降水带随之北移。",
                trap_analysis="容易认为气压带不动或只动一部分。",
                common_mistake="因果断裂",
            ),
            # === 工业区位 ===
            GeographyQuestion(
                question_id="industry_001",
                question_type="choice",
                concept_name="中考地理-工业区位",
                skill_tag="综合分析",
                difficulty="easy",
                question="高新技术产业布局的首要考虑因素是？",
                options=["A. 原料", "B. 劳动力", "C. 科技和人才", "D. 能源"],
                answer="C",
                explanation="高新技术产业依赖科技和人才，对知识创新能力要求高。",
                trap_analysis="容易选劳动力或原料，这是传统工业的考虑因素。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="industry_002",
                question_type="causal",
                concept_name="中考地理-工业区位",
                skill_tag="因果解释",
                difficulty="medium",
                question="钢铁工业从靠近煤矿/铁矿，转向靠近沿海港口，主要原因是什么？",
                options=[
                    "A. 原料消耗量减少，交通技术进步",
                    "B. 沿海地区劳动力便宜",
                    "C. 沿海地区能源丰富",
                    "D. 沿海地区科技发达",
                ],
                answer="A",
                explanation="随着冶炼技术进步，单位钢铁原料消耗减少；加上交通便利，原料和产品运输成本降低，钢铁工业趋向沿海港口。",
                trap_analysis="容易选科技发达，但钢铁工业不是高新技术产业。",
                common_mistake="概念混淆",
            ),
            # === 人口与城市 ===
            GeographyQuestion(
                question_id="pop_001",
                question_type="choice",
                concept_name="中考地理-人口与城市",
                skill_tag="综合分析",
                difficulty="easy",
                question="我国人口分布的地理界线是？",
                options=[
                    "A. 秦岭-淮河",
                    "B. 黑河-腾冲",
                    "C. 大兴安岭-太行山",
                    "D. 昆仑山-祁连山",
                ],
                answer="B",
                explanation="黑河-腾冲一线是我国人口地理分界线，东南多、西北少。",
                trap_analysis="容易和秦岭-淮河混淆。",
                common_mistake="概念混淆",
            ),
            GeographyQuestion(
                question_id="pop_002",
                question_type="causal",
                concept_name="中考地理-人口与城市",
                skill_tag="因果解释",
                difficulty="medium",
                question="为什么我国东部沿海地区人口密集，而西部地区人口稀疏？",
                options=[
                    "A. 东部地形平坦、气候适宜、经济发达、交通便利",
                    "B. 东部面积更大",
                    "C. 东部降水更少",
                    "D. 东部海拔更高",
                ],
                answer="A",
                explanation="东部地形平坦、气候适宜、水源充足、经济发达、交通便利，适合人类居住和生产活动。",
                trap_analysis="容易把原因和结果说反。",
                common_mistake="因果断裂",
            ),
            # === 交通与地形 ===
            GeographyQuestion(
                question_id="transport_001",
                question_type="choice",
                concept_name="中考地理-交通与地形",
                skill_tag="读图判断",
                difficulty="easy",
                question="山区公路为什么多呈'之'字形？",
                options=[
                    "A. 为了美观",
                    "B. 为了减缓坡度，保证行车安全",
                    "C. 为了增加路程收费",
                    "D. 为了连接更多村庄",
                ],
                answer="B",
                explanation="'之'字形公路通过延长路程来减缓坡度，使车辆能够安全爬坡。",
                trap_analysis="容易选连接村庄，但主要目的是减缓坡度。",
                common_mistake="因果断裂",
            ),
            GeographyQuestion(
                question_id="transport_002",
                question_type="causal",
                concept_name="中考地理-交通与地形",
                skill_tag="综合分析",
                difficulty="medium",
                question="青藏铁路建设面临的主要困难有哪些？",
                options=[
                    "A. 高寒缺氧、冻土广布、生态脆弱",
                    "B. 地势平坦、施工方便",
                    "C. 气候温暖、水源充足",
                    "D. 人口稠密、劳动力充足",
                ],
                answer="A",
                explanation="青藏高原海拔高、气温低、缺氧、冻土广布、生态环境脆弱，施工条件极为恶劣。",
                trap_analysis="容易选B、C、D等正面描述，但这些都是青藏地区不具备的条件。",
                common_mistake="审题粗心",
            ),
        ]


_BANK_INSTANCE: Optional[GeographyExamBank] = None


def get_exam_bank() -> GeographyExamBank:
    global _BANK_INSTANCE
    if _BANK_INSTANCE is None:
        _BANK_INSTANCE = GeographyExamBank()
    return _BANK_INSTANCE

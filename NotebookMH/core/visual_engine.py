"""
core/visual_engine.py - 认知态→视觉参数映射引擎 (Phase 4)

职责：
  - 将 GlobalState + DB 认知数据映射为 Three.js 粒子系统参数
  - 颜色：e_valence (冷暖映射)
  - 湍流：c_load (认知负荷→粒子扰动)
  - 密度：mastery_level (掌握度→结构秩序)
  - 脉动：情绪状态→呼吸频率

零 UI 逻辑，纯后端参数计算引擎。
"""

import logging
import math
from dataclasses import dataclass
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from utils.db_manager import db_pool
from utils.state_manager import binder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. 视觉参数数据类
# ---------------------------------------------------------------------------

@dataclass
class FluidParams:
    """Three.js 粒子系统可消费的视觉参数。"""
    particle_count: int = 2000          # 粒子数量
    base_color: List[float] = None      # [r, g, b] 0.0~1.0
    turbulence: float = 0.5             # 湍流强度 0.0~1.0
    speed: float = 0.5                  # 基础流速
    coherence: float = 0.5              # 结构秩序度 0.0(混沌)~1.0(有序)
    pulse_rate: float = 1.0             # 呼吸脉动频率 Hz
    background_gradient: List[str] = None  # CSS 渐变起止色

    def __post_init__(self):
        if self.base_color is None:
            self.base_color = [0.2, 0.6, 1.0]
        if self.background_gradient is None:
            self.background_gradient = ["#0a0a1a", "#1a1a2e"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "particle_count": self.particle_count,
            "base_color": self.base_color,
            "turbulence": round(self.turbulence, 3),
            "speed": round(self.speed, 3),
            "coherence": round(self.coherence, 3),
            "pulse_rate": round(self.pulse_rate, 3),
            "background_gradient": self.background_gradient,
        }


# ---------------------------------------------------------------------------
# 2. 视觉引擎
# ---------------------------------------------------------------------------

class VisualEngine:
    """
    认知态→视觉参数映射引擎。

    映射规则：
      e_valence  → 色相 (蓝=-1, 绿=0, 金=+1)
      c_load     → 湍流 + 脉动频率 (高负荷=高湍流+快脉动)
      mastery    → 结构秩序度 + 粒子密度 (高掌握=有序+致密)
      emotion    → 整体流速 (专注=平稳, 挫败=紊乱)
    """

    def __init__(self, user_id: str = "anonymous") -> None:
        self.user_id = user_id

    def compute(self) -> FluidParams:
        """基于当前认知态计算视觉参数。"""
        # 读取 GlobalState
        c_load = binder.get_state("c_load", 0.0)
        e_valence = binder.get_state("e_valence", 0.0)
        emotion = binder.get_state("emotion_state", "专注")
        tier = binder.get_state("render_tier", "ULTRA_3D")

        # 读取 DB 掌握度
        concepts = db_pool.list_concepts(self.user_id)
        avg_mastery = self._avg_mastery(concepts)

        # 计算粒子数量 (渲染等级)
        particle_count = self._tier_to_particles(tier)

        # 颜色映射: e_valence → 冷暖
        base_color = self._valence_to_color(e_valence)

        # 湍流: c_load 直接映射
        turbulence = min(1.0, max(0.1, c_load * 1.2))

        # 流速: 情绪驱动
        speed = self._emotion_to_speed(emotion)

        # 秩序度: mastery 驱动
        coherence = min(1.0, max(0.1, avg_mastery / 100))

        # 脉动: 高负荷时加速，正向情绪时放缓
        pulse_rate = 0.5 + c_load * 2.0 - e_valence * 0.3
        pulse_rate = max(0.3, min(3.0, pulse_rate))

        # 背景: 认知负荷高时偏暗红，低时偏深蓝
        bg = self._load_to_background(c_load, e_valence)

        params = FluidParams(
            particle_count=particle_count,
            base_color=base_color,
            turbulence=turbulence,
            speed=speed,
            coherence=coherence,
            pulse_rate=pulse_rate,
            background_gradient=bg,
        )

        logger.info(
            "VisualEngine computed: particles=%d color=%s turbulence=%.2f coherence=%.2f",
            params.particle_count, params.base_color, params.turbulence, params.coherence
        )
        return params

    # ------------------------------------------------------------------
    # 映射函数
    # ------------------------------------------------------------------

    @staticmethod
    def _valence_to_color(e: float) -> List[float]:
        """情绪效价 → RGB。"""
        # -1(挫败/冷)=蓝紫, 0(中性)=青绿, +1(愉悦/暖)=金黄
        e = max(-1.0, min(1.0, e))
        if e < 0:
            # 蓝紫渐变
            t = -e  # 0→1
            return [0.1 + t * 0.1, 0.2, 0.8 - t * 0.2]
        else:
            # 青绿→金黄
            t = e  # 0→1
            return [0.2 + t * 0.6, 0.7 + t * 0.2, 0.6 - t * 0.5]

    @staticmethod
    def _emotion_to_speed(emotion: str) -> float:
        mapping = {
            "专注": 0.5,
            "挫败": 2.0,
            "困惑": 1.2,
            "懒散": 0.2,
        }
        return mapping.get(emotion, 0.5)

    @staticmethod
    def _tier_to_particles(tier: str) -> int:
        mapping = {
            "LOW_2D": 200,
            "MEDIUM_CSS": 800,
            "HIGH_CANVAS": 1500,
            "ULTRA_3D": 3000,
        }
        return mapping.get(tier, 2000)

    @staticmethod
    def _avg_mastery(concepts: List[Any]) -> float:
        if not concepts:
            return 50.0
        levels = [c.mastery_level or 0.0 for c in concepts]
        return sum(levels) / len(levels)

    @staticmethod
    def _load_to_background(c_load: float, e_valence: float) -> List[str]:
        """背景渐变: 高负荷偏暗, 正向情绪偏暖。"""
        if c_load > 0.7:
            return ["#0d0000", "#1a0505"]  # 暗红
        if c_load > 0.4:
            return ["#0a0a1a", "#1a1520"]  # 暗紫
        if e_valence > 0.5:
            return ["#0a1a0a", "#15201a"]  # 暗绿
        return ["#0a0a1a", "#1a1a2e"]  # 深蓝


# ---------------------------------------------------------------------------
# 3. 模块级单例
# ---------------------------------------------------------------------------

_visual_singleton: Optional[VisualEngine] = None


def get_visual_engine(user_id: str = "anonymous") -> VisualEngine:
    """获取全局唯一的 VisualEngine 实例。"""
    global _visual_singleton
    if _visual_singleton is None:
        _visual_singleton = VisualEngine(user_id=user_id)
    return _visual_singleton


# ===========================================================================
# Phase 6: LandscapeRenderer — 3D 认知地形图
# ===========================================================================

try:
    import streamlit as _st
except Exception:
    _st = None

_COGNITIVE_TERRAIN_COLORSCALE = [
    [0.0, "#4A0000"],
    [0.25, "#1A0033"],
    [0.55, "#1E293B"],
    [0.8, "#0B5A3C"],
    [1.0, "#00FF41"],
]

_HOLO_TEXT_COLOR = "#00FF41"
_HOLO_BG = "rgba(0,0,0,0)"
_HOLO_GRID = "rgba(0,255,65,0.18)"


class _NodeData:
    """标准化后的 DAG 节点内部结构。"""

    __slots__ = ("node_id", "depends_on", "mastery_level")

    def __init__(self, node_id: str, depends_on: List[str], mastery_level: float) -> None:
        self.node_id = node_id
        self.depends_on = depends_on
        self.mastery_level = max(0.0, min(100.0, float(mastery_level or 50.0)))


# ---------------------------------------------------------------------------
# 地形网格计算（纯函数，支持 Streamlit cache）
# ---------------------------------------------------------------------------


def _compute_terrain_mesh(
    semantic_x_values: Tuple[float, ...],
    semantic_y_values: Tuple[float, ...],
    mastery_altitudes: Tuple[float, ...],
    grid_resolution: int = 50,
) -> Optional[Tuple[Any, Any, Any]]:
    """
    使用 scipy.interpolate.griddata 从离散节点生成连续地形网格。
    返回值: (grid_x, grid_y, grid_z) 或 None（计算失败时）
    """
    try:
        from scipy.interpolate import griddata
    except Exception as e:
        logger.warning("scipy.interpolate unavailable: %s", e)
        return None

    if len(semantic_x_values) < 4:
        return None

    x_min, x_max = min(semantic_x_values), max(semantic_x_values)
    y_min, y_max = min(semantic_y_values), max(semantic_y_values)

    # 提供 padding，避免边界截断
    pad_x = max(0.1, (x_max - x_min) * 0.15)
    pad_y = max(0.1, (y_max - y_min) * 0.15)

    xi = np.linspace(x_min - pad_x, x_max + pad_x, grid_resolution)
    yi = np.linspace(y_min - pad_y, y_max + pad_y, grid_resolution)
    grid_x, grid_y = np.meshgrid(xi, yi)

    points = np.column_stack([semantic_x_values, semantic_y_values])
    values = np.asarray(mastery_altitudes, dtype=float)

    try:
        grid_z = griddata(points, values, (grid_x, grid_y), method="cubic")
    except Exception:
        try:
            grid_z = griddata(points, values, (grid_x, grid_y), method="linear")
        except Exception:
            return None

    # cubic 可能在边缘产生 NaN，fallback 到 nearest
    if grid_z is not None and np.isnan(grid_z).any():
        grid_z = np.where(
            np.isnan(grid_z),
            griddata(points, values, (grid_x, grid_y), method="nearest"),
            grid_z,
        )

    return grid_x, grid_y, grid_z


# 尝试包装缓存
if _st is not None:
    try:
        _compute_terrain_mesh = _st.cache_data(max_entries=5, show_spinner=False)(
            _compute_terrain_mesh
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# LandscapeRenderer
# ---------------------------------------------------------------------------


class LandscapeRenderer:
    """
    3D 认知地形图渲染器。

    将 DAG 节点 + mastery_level 渲染为 Plotly go.Figure。
    零 UI 逻辑，纯 backend 渲染。
    """

    def __init__(self) -> None:
        pass

    @staticmethod
    def _normalize_dag_nodes(raw_nodes: Sequence[Dict[str, Any]]) -> List[_NodeData]:
        """将输入字典列表标准化为内部节点结构，并自动补全外部依赖节点。"""
        nodes: List[_NodeData] = []
        seen_ids: set = set()
        all_dep_ids: set = set()

        for item in raw_nodes:
            node_id = str(item.get("node_id", "")).strip()
            if not node_id:
                continue

            raw_deps = item.get("depends_on", [])
            if isinstance(raw_deps, str):
                try:
                    raw_deps = json.loads(raw_deps)
                except Exception:
                    raw_deps = []
            if not isinstance(raw_deps, (list, tuple)):
                raw_deps = []

            deps = [str(d).strip() for d in raw_deps if str(d).strip()]
            mastery = float(item.get("mastery_level", 50.0) or 50.0)

            nodes.append(_NodeData(node_id=node_id, depends_on=deps, mastery_level=mastery))
            seen_ids.add(node_id)
            all_dep_ids.update(deps)

        # 补全外部依赖节点（不在 nodes 中但被别人依赖）
        missing = all_dep_ids - seen_ids
        for dep_id in missing:
            nodes.append(_NodeData(node_id=dep_id, depends_on=[], mastery_level=50.0))

        return nodes

    @staticmethod
    def _build_graph(nodes: Sequence[_NodeData]) -> "nx.DiGraph":
        """构建有向图：前置知识 -> 后续概念。"""
        import networkx as nx

        graph = nx.DiGraph()
        for n in nodes:
            graph.add_node(n.node_id, mastery=n.mastery_level)
            for dep in n.depends_on:
                if dep != n.node_id:
                    graph.add_edge(dep, n.node_id)
        return graph

    @staticmethod
    def _compute_layout(graph: "nx.DiGraph") -> Dict[str, Tuple[float, float]]:
        """使用 spring_layout 生成确定性 2D 坐标。"""
        import networkx as nx

        if not graph or len(graph.nodes) == 0:
            return {}

        try:
            layout = nx.spring_layout(graph, dim=2, seed=42)
        except Exception as e:
            logger.warning("spring_layout failed (%s), using circular fallback", e)
            nodes = list(graph.nodes)
            count = len(nodes)
            radius = 1.0
            layout = {
                node: (
                    radius * math.cos(2 * math.pi * i / count),
                    radius * math.sin(2 * math.pi * i / count),
                )
                for i, node in enumerate(nodes)
            }
        return layout

    @staticmethod
    def _mastery_to_color(mastery: float) -> str:
        if mastery < 40:
            return "#FF003C"
        if mastery <= 80:
            return "#00A3FF"
        return "#00FF41"

    @staticmethod
    def _node_to_trace(
        graph: "nx.DiGraph",
        layout: Dict[str, Tuple[float, float]],
        current_node_id: Optional[str],
    ) -> List[Any]:
        import plotly.graph_objects as go

        traces = []

        node_x, node_y, node_z, node_text, node_color, node_size = [], [], [], [], [], []
        for node_id in graph.nodes:
            sx, sy = layout.get(node_id, (0.0, 0.0))
            mastery = float(graph.nodes[node_id].get("mastery", 50.0))
            node_x.append(sx)
            node_y.append(sy)
            node_z.append(mastery)
            node_text.append(node_id)
            node_color.append(LandscapeRenderer._mastery_to_color(mastery))
            node_size.append(14 if node_id == current_node_id else 10)

        traces.append(
            go.Scatter3d(
                x=node_x,
                y=node_y,
                z=node_z,
                mode="markers+text",
                marker=dict(size=node_size, color=node_color, opacity=0.95, symbol="circle"),
                text=node_text,
                textposition="top center",
                textfont=dict(color=_HOLO_TEXT_COLOR, size=11),
                name="概念节点",
                hovertemplate="%{text}<br>掌握度: %{z:.1f}<extra></extra>",
            )
        )
        return traces

    @staticmethod
    def _edges_to_trace(
        graph: "nx.DiGraph", layout: Dict[str, Tuple[float, float]]
    ) -> Optional[Any]:
        import plotly.graph_objects as go

        if not graph.edges:
            return None

        edge_x, edge_y, edge_z = [], [], []
        for src, dst in graph.edges:
            x0, y0 = layout.get(src, (0.0, 0.0))
            x1, y1 = layout.get(dst, (0.0, 0.0))
            # Z 取两端 mastery 平均值，使连线贴在地形表面
            z0 = float(graph.nodes[src].get("mastery", 50.0))
            z1 = float(graph.nodes[dst].get("mastery", 50.0))
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])
            edge_z.extend([z0, z1, None])

        return go.Scatter3d(
            x=edge_x,
            y=edge_y,
            z=edge_z,
            mode="lines",
            line=dict(color="rgba(0,255,65,0.35)", width=2),
            name="依赖连线",
            hoverinfo="skip",
        )

    @staticmethod
    def _beacon_trace(
        graph: "nx.DiGraph",
        layout: Dict[str, Tuple[float, float]],
        current_node_id: Optional[str],
    ) -> Optional[Any]:
        import plotly.graph_objects as go

        if not current_node_id or current_node_id not in layout:
            return None

        sx, sy = layout[current_node_id]
        mastery = float(graph.nodes[current_node_id].get("mastery", 50.0))

        return go.Scatter3d(
            x=[sx, sx],
            y=[sy, sy],
            z=[0, 100],
            mode="lines",
            line=dict(color="#FFD700", width=8),
            name="当前攻克节点 Beacon",
            hovertemplate="当前节点: %{text}<extra></extra>",
            text=[current_node_id, current_node_id],
        )

    @staticmethod
    def _apply_holo_layout(fig: Any, title: str) -> None:
        fig.update_layout(
            title=dict(text=title, font=dict(color=_HOLO_TEXT_COLOR, size=14)),
            paper_bgcolor=_HOLO_BG,
            plot_bgcolor=_HOLO_BG,
            font=dict(color=_HOLO_TEXT_COLOR, family="Fira Code, monospace"),
            margin=dict(l=20, r=20, t=40, b=20),
            scene=dict(
                xaxis=dict(
                    title="Semantic X",
                    backgroundcolor=_HOLO_BG,
                    gridcolor=_HOLO_GRID,
                    showbackground=False,
                    zerolinecolor=_HOLO_GRID,
                ),
                yaxis=dict(
                    title="Semantic Y",
                    backgroundcolor=_HOLO_BG,
                    gridcolor=_HOLO_GRID,
                    showbackground=False,
                    zerolinecolor=_HOLO_GRID,
                ),
                zaxis=dict(
                    title="Mastery Altitude",
                    backgroundcolor=_HOLO_BG,
                    gridcolor=_HOLO_GRID,
                    showbackground=False,
                    zerolinecolor=_HOLO_GRID,
                ),
            ),
        )

    # ------------------------------------------------------------------
    # 核心入口
    # ------------------------------------------------------------------

    def render(
        self,
        dag_nodes: Sequence[Dict[str, Any]],
        current_node_id: Optional[str],
    ) -> Any:
        import plotly.graph_objects as go

        # 空图占位
        if not dag_nodes:
            fig = go.Figure()
            fig.add_annotation(
                x=0.5,
                y=0.5,
                text="认知地形暂无数据：请先完成文档摄入与 DAG 抽取",
                showarrow=False,
                font=dict(size=16, color="#FF003C"),
                xref="paper",
                yref="paper",
            )
            self._apply_holo_layout(fig, "3D 认知地形图 — Cognitive Landscape")
            return fig

        # 标准化
        nodes = self._normalize_dag_nodes(dag_nodes)
        if not nodes:
            return self.render([], current_node_id)

        # 构建图
        graph = self._build_graph(nodes)
        layout = self._compute_layout(graph)

        # 节点数限制（只渲染前 200 个，但 layout 保留完整）
        render_nodes = list(graph.nodes)[:200]
        subgraph = graph.subgraph(render_nodes).copy()

        # 布局可能缺失 subgraph 中的节点（极少见），安全获取
        safe_layout = {n: layout[n] for n in subgraph.nodes if n in layout}
        if not safe_layout:
            safe_layout = self._compute_layout(subgraph)

        fig = go.Figure()

        # 地形 Surface
        if len(subgraph.nodes) >= 4:
            sx_vals = tuple(safe_layout[n][0] for n in subgraph.nodes if n in safe_layout)
            sy_vals = tuple(safe_layout[n][1] for n in subgraph.nodes if n in safe_layout)
            mz_vals = tuple(float(subgraph.nodes[n].get("mastery", 50.0)) for n in subgraph.nodes)

            mesh = _compute_terrain_mesh(sx_vals, sy_vals, mz_vals)
            if mesh is not None:
                grid_x, grid_y, grid_z = mesh
                fig.add_trace(
                    go.Surface(
                        x=grid_x,
                        y=grid_y,
                        z=grid_z,
                        colorscale=_COGNITIVE_TERRAIN_COLORSCALE,
                        opacity=0.75,
                        showscale=False,
                        hoverinfo="skip",
                        name="认知地形",
                    )
                )
            else:
                logger.info("Terrain mesh unavailable; rendering scatter-only landscape")
        else:
            logger.info("Node count < 4; skipping terrain surface")

        # 连线
        edge_trace = self._edges_to_trace(subgraph, safe_layout)
        if edge_trace is not None:
            fig.add_trace(edge_trace)

        # 节点
        for trace in self._node_to_trace(subgraph, safe_layout, current_node_id):
            fig.add_trace(trace)

        # Beacon
        beacon = self._beacon_trace(subgraph, safe_layout, current_node_id)
        if beacon is not None:
            fig.add_trace(beacon)

        self._apply_holo_layout(fig, "3D 认知地形图 — Cognitive Landscape")
        return fig


# ---------------------------------------------------------------------------
# 模块级单例
# ---------------------------------------------------------------------------

_landscape_renderer: Optional[LandscapeRenderer] = None


def get_landscape_renderer() -> LandscapeRenderer:
    """获取全局唯一的 LandscapeRenderer 实例。"""
    global _landscape_renderer
    if _landscape_renderer is None:
        _landscape_renderer = LandscapeRenderer()
    return _landscape_renderer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_cognitive_landscape(
    dag_nodes: Sequence[Dict[str, Any]],
    current_node_id: Optional[str],
) -> Any:
    """
    3D 认知地形图渲染入口。

    Args:
        dag_nodes: 标准化 DAG 节点列表。
        current_node_id: 当前攻克节点 ID（可选）。

    Returns:
        plotly.graph_objects.Figure
    """
    renderer = get_landscape_renderer()
    return renderer.render(dag_nodes, current_node_id)


def assemble_dag_nodes(vault_uuid: str, user_id: str) -> List[Dict[str, Any]]:
    """
    从数据库拼装标准化 DAG 节点列表。

    流程：
      1. 通过 db_pool.get_vault_dag(vault_uuid) 取回概念依赖关系
      2. 遍历每个 concept_name，通过 db_pool.get_concept(user_id, concept_name)
         取回 mastery_level（0.0 ~ 100.0）
      3. mastery 缺失时 fallback 到 50.0

    Returns:
        dag_nodes: 符合 render_cognitive_landscape 输入合约的列表
    """
    import json

    if not vault_uuid or not user_id:
        logger.warning("assemble_dag_nodes: vault_uuid or user_id empty")
        return []

    try:
        raw_dag = db_pool.get_vault_dag(vault_uuid)
    except Exception as e:
        logger.error("get_vault_dag failed: %s", e)
        return []

    if not raw_dag:
        return []

    dag_nodes: List[Dict[str, Any]] = []
    for node in raw_dag:
        concept = str(node.get("concept_name", ""))
        if not concept:
            continue

        # 取掌握度
        mastery_level = 50.0
        try:
            cm = db_pool.get_concept(user_id, concept)
            if cm is not None:
                mastery_level = float(cm.mastery_level or 50.0)
        except Exception as e:
            logger.warning("get_concept failed for %s: %s", concept, e)

        # 解析依赖
        deps = node.get("depends_on", [])
        if isinstance(deps, str):
            try:
                deps = json.loads(deps)
            except json.JSONDecodeError:
                deps = []
        elif not isinstance(deps, list):
            deps = list(deps) if deps else []

        dag_nodes.append({
            "node_id": concept,
            "depends_on": deps,
            "mastery_level": mastery_level,
        })

    logger.info(
        "assemble_dag_nodes: vault=%s user=%s nodes=%d",
        vault_uuid, user_id, len(dag_nodes),
    )
    return dag_nodes


def render_cognitive_landscape_from_vault(
    vault_uuid: str,
    user_id: str,
    current_node_id: Optional[str] = None,
) -> Any:
    """
    直接从 Vault + User 数据生成 3D 认知地形图。

    这是 assemble_dag_nodes → render_cognitive_landscape 的便捷封装。

    Args:
        vault_uuid: 笔记库 UUID
        user_id: 当前用户 ID
        current_node_id: 高亮当前聚焦概念（可选）

    Returns:
        plotly.graph_objects.Figure
    """
    dag_nodes = assemble_dag_nodes(vault_uuid, user_id)
    if not dag_nodes:
        logger.warning("No dag nodes assembled for vault=%s user=%s", vault_uuid, user_id)
    return render_cognitive_landscape(dag_nodes, current_node_id)

"""
core/holographic_sandbox.py - 概念降维 3D 沙盒 (P2 UI/UX 增强，DAG-ready)

职责：
  - 根据 SimulationContext 动态生成 Plotly 3D 交互模型
  - 工厂模式路由：概念关键词 → 渲染器
  - 全息控制台配色（#00FF41 / #FF003C / #FFAA00）
  - 数据降采样：>5000 顶点自动子采样
  - 零 Streamlit 依赖，纯后端参数计算 + Plotly Figure 生成

架构：
  - 当前阶段使用 current_concept + mastery + c_load 作为数据源
  - 未来 DAG 完成后通过 SimulationContext.source="dag_safe_anchor" 切换数据源
"""

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

import numpy as np
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. 数据协议 —— 当前 & 未来兼容
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SimulationContext:
    """沙盒渲染的输入上下文。来源可切换，接口保持不变。"""

    concept_name: str
    mastery_level: float
    c_load: float
    e_valence: float
    source: Literal["current_concept", "dag_safe_anchor", "manual"] = "current_concept"
    dependency_path: Tuple[str, ...] = ()
    ontology_summary: str = ""
    embodied_signals: Tuple[Any, ...] = ()


# ---------------------------------------------------------------------------
# 2. 全局常量
# ---------------------------------------------------------------------------

_MAX_VERTICES: int = 5000
_HOLO_COLORS = {
    "grid": "#00FF41",
    "highlight": "#FF003C",
    "warn": "#FFAA00",
    "bg": "rgba(0,0,0,0)",
    "text": "#00FF41",
    "surface_low": "#003300",
    "surface_mid": "#005500",
    "surface_high": "#00FF41",
}


# ---------------------------------------------------------------------------
# 3. 数据降采样
# ---------------------------------------------------------------------------

def _subsample(data: np.ndarray, max_points: int = _MAX_VERTICES) -> np.ndarray:
    """均匀子采样，防止 Plotly 浏览器内存溢出。"""
    if data.size <= max_points:
        return data
    step = int(np.ceil(data.size / max_points))
    return data[::step]


# ---------------------------------------------------------------------------
# 4. 渲染器注册表（工厂模式）
# ---------------------------------------------------------------------------

class SimulationRegistry:
    """
    概念-视觉拓扑映射器。

    根据 concept_name 关键词路由到对应 Plotly 渲染器。
    未来 DAG 接入时只需切换 SimulationContext 来源，无需改动此处。
    """

    _RENDERERS: Dict[str, Callable[[SimulationContext], Any]] = {}

    # 关键词 → 渲染器名称 映射矩阵
    _KEYWORD_MAP: List[Tuple[List[str], str]] = [
        (["损失", "梯度", "优化", "loss", "gradient", "sgd", "adam", "momentum"], "loss_landscape"),
        (["并发", "线程", "异步", "锁", "调度", "async", "thread", "concurrent", "mutex"], "async_timeline"),
        (["向量", "矩阵", "空间", "投影", "vector", "matrix", "eigen", "projection"], "vector_field"),
        (["概率", "分布", "贝叶斯", "采样", "probability", "distribution", "bayes", "sampling"], "probability_cloud"),
        (["安全", "设备", "机床", "阀门", "管线", "压力", "超压", "隐患", "装置", "传感器", "安全阀", "工业", "机械", "装置"], "industrial_twin"),
    ]

    def __init__(self) -> None:
        # 注册内置渲染器
        self._register("loss_landscape", _render_loss_landscape)
        self._register("async_timeline", _render_async_timeline)
        self._register("vector_field", _render_vector_field)
        self._register("probability_cloud", _render_probability_cloud)
        self._register("force_graph", _render_force_graph)
        self._register("industrial_twin", _render_industrial_twin)

    def _register(self, name: str, renderer: Callable[[SimulationContext], Any]) -> None:
        self._RENDERERS[name] = renderer

    def render(self, ctx: SimulationContext) -> Any:
        """根据概念关键词路由到对应渲染器。"""
        renderer_name = self._match_renderer(ctx.concept_name)
        renderer = self._RENDERERS.get(renderer_name, _render_force_graph)
        try:
            return renderer(ctx)
        except Exception as e:
            logger.error("Sandbox render failed: %s", e, exc_info=True)
            return _render_fallback_placeholder(ctx)

    def _match_renderer(self, concept_name: str) -> str:
        """关键词匹配，无法命中时返回 force_graph。"""
        lowered = concept_name.lower()
        for keywords, renderer_name in self._KEYWORD_MAP:
            if any(kw in lowered for kw in keywords):
                return renderer_name
        return "force_graph"


# ---------------------------------------------------------------------------
# 5. 渲染器实现
# ---------------------------------------------------------------------------

def _render_loss_landscape(ctx: SimulationContext) -> Any:
    """
    3D 损失函数曲面。
    小球位置由 mastery_level 决定（高掌握=谷底，低掌握=随机起点）。
    """
    import plotly.graph_objects as go

    # 生成曲面网格
    x = np.linspace(-3, 3, 80)
    y = np.linspace(-3, 3, 80)
    X, Y = np.meshgrid(x, y)

    # 多峰损失函数
    Z = (
        np.sin(X) * np.cos(Y) * 2
        + 0.5 * (X ** 2 + Y ** 2)
        + np.sin(3 * X) * 0.3
    )

    # 小球位置：mastery 高时趋近 (0,0) 谷底
    mastery_norm = ctx.mastery_level / 100.0
    ball_x = (1 - mastery_norm) * 2.5 * np.random.randn()
    ball_y = (1 - mastery_norm) * 2.5 * np.random.randn()
    ball_z = np.sin(ball_x) * np.cos(ball_y) * 2 + 0.5 * (ball_x ** 2 + ball_y ** 2)

    fig = go.Figure()

    # 曲面
    fig.add_trace(
        go.Surface(
            x=X, y=Y, z=Z,
            colorscale=[
                [0, _HOLO_COLORS["surface_low"]],
                [0.5, _HOLO_COLORS["surface_mid"]],
                [1, _HOLO_COLORS["surface_high"]],
            ],
            opacity=0.7,
            showscale=False,
            hoverinfo="skip",
        )
    )

    # 小球（当前认知位置）
    ball_color = _HOLO_COLORS["highlight"] if ctx.c_load > 0.7 else _HOLO_COLORS["warn"]
    fig.add_trace(
        go.Scatter3d(
            x=[ball_x], y=[ball_y], z=[ball_z],
            mode="markers",
            marker=dict(size=8, color=ball_color, symbol="diamond"),
            name="当前认知位置",
        )
    )

    _apply_holo_layout(fig, f"损失曲面 — {ctx.concept_name}")
    return fig


def _render_async_timeline(ctx: SimulationContext) -> Any:
    """多线程时序甘特图。"""
    import plotly.graph_objects as go

    # 模拟 4 个线程的时间线
    threads = ["主线程", "Worker-A", "Worker-B", "I/O 线程"]
    tasks = [
        [(0, 3, "初始化"), (5, 2, "计算")],
        [(1, 2, "任务1"), (4, 3, "任务2")],
        [(2, 1, "预热"), (6, 2, "收尾")],
        [(0, 6, "网络请求")],
    ]

    fig = go.Figure()
    for i, (thread, task_list) in enumerate(zip(threads, tasks)):
        for start, duration, label in task_list:
            # c_load 高时颜色偏红（冲突感）
            color = _HOLO_COLORS["highlight"] if ctx.c_load > 0.7 else _HOLO_COLORS["grid"]
            fig.add_trace(
                go.Bar(
                    x=[duration],
                    y=[thread],
                    base=[start],
                    orientation="h",
                    marker_color=color,
                    opacity=0.8,
                    name=label,
                    showlegend=False,
                    hovertemplate=f"{label}<br>开始: {start}s<br>持续: {duration}s",
                )
            )

    _apply_holo_layout(fig, f"并发时序 — {ctx.concept_name}")
    return fig


def _render_vector_field(ctx: SimulationContext) -> Any:
    """3D 向量场，力线可视化。"""
    import plotly.graph_objects as go

    # 生成网格
    grid = np.linspace(-2, 2, 15)
    X, Y, Z = np.meshgrid(grid, grid, grid)

    # 定义向量场（旋度场）
    U = -Y
    V = X
    W = Z * 0.5

    # 降采样
    x_flat = _subsample(X.flatten())
    y_flat = _subsample(Y.flatten())
    z_flat = _subsample(Z.flatten())
    u_flat = _subsample(U.flatten())[:len(x_flat)]
    v_flat = _subsample(V.flatten())[:len(y_flat)]
    w_flat = _subsample(W.flatten())[:len(z_flat)]

    fig = go.Figure(data=go.Cone(
        x=x_flat, y=y_flat, z=z_flat,
        u=u_flat, v=v_flat, w=w_flat,
        colorscale=[[0, _HOLO_COLORS["surface_low"]], [1, _HOLO_COLORS["grid"]]],
        showscale=False,
        sizemode="absolute",
        sizeref=2,
    ))

    _apply_holo_layout(fig, f"向量场 — {ctx.concept_name}")
    return fig


def _render_probability_cloud(ctx: SimulationContext) -> Any:
    """概率密度等高线 + 采样点云。"""
    import plotly.graph_objects as go

    # 二维高斯混合
    x = np.linspace(-3, 3, 100)
    y = np.linspace(-3, 3, 100)
    X, Y = np.meshgrid(x, y)

    Z = (
        np.exp(-((X - 1) ** 2 + (Y - 1) ** 2) / 0.5)
        + np.exp(-((X + 1) ** 2 + (Y + 1) ** 2) / 0.5)
        + np.exp(-(X ** 2 + Y ** 2) / 2.0)
    )

    # 采样点：mastery 高时集中在峰值附近
    n_samples = 200
    mastery_norm = ctx.mastery_level / 100.0
    samples_x = np.random.randn(n_samples) * (1.5 - mastery_norm) + np.random.choice([1, -1, 0], n_samples)
    samples_y = np.random.randn(n_samples) * (1.5 - mastery_norm) + np.random.choice([1, -1, 0], n_samples)

    fig = go.Figure()

    fig.add_trace(
        go.Contour(
            z=Z, x=x, y=y,
            colorscale=[[0, _HOLO_COLORS["surface_low"]], [1, _HOLO_COLORS["grid"]]],
            showscale=False,
            contours=dict(coloring="heatmap"),
            opacity=0.6,
        )
    )

    fig.add_trace(
        go.Scatter(
            x=samples_x, y=samples_y,
            mode="markers",
            marker=dict(size=5, color=_HOLO_COLORS["highlight"], opacity=0.7),
            name="采样点",
        )
    )

    _apply_holo_layout(fig, f"概率云 — {ctx.concept_name}")
    return fig


def _render_force_graph(ctx: SimulationContext) -> Any:
    """力导向关系图（通用降级）。"""
    import plotly.graph_objects as go
    import networkx as nx

    # 构建简单图：当前概念为中心，辐射状连接
    G = nx.Graph()
    center = ctx.concept_name or "未知概念"
    G.add_node(center)

    # 依赖路径中的节点作为邻居
    neighbors = list(ctx.dependency_path) if ctx.dependency_path else ["基础概念A", "基础概念B", "进阶概念C"]
    for n in neighbors:
        G.add_edge(center, n)

    pos = nx.spring_layout(G, seed=42)

    # 边
    edge_x, edge_y = [], []
    for edge in G.edges():
        x0, y0 = pos[edge[0]]
        x1, y1 = pos[edge[1]]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=edge_x, y=edge_y,
            mode="lines",
            line=dict(color=_HOLO_COLORS["grid"], width=1),
            hoverinfo="none",
        )
    )

    # 节点
    node_x, node_y, node_text = [], [], []
    for node in G.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)

    fig.add_trace(
        go.Scatter(
            x=node_x, y=node_y,
            mode="markers+text",
            marker=dict(
                size=[20 if n == center else 12 for n in G.nodes()],
                color=[_HOLO_COLORS["highlight"] if n == center else _HOLO_COLORS["warn"] for n in G.nodes()],
            ),
            text=node_text,
            textposition="top center",
            textfont=dict(color=_HOLO_COLORS["text"], size=10),
        )
    )

    _apply_holo_layout(fig, f"概念图谱 — {ctx.concept_name}")
    return fig


def _render_industrial_twin(ctx: SimulationContext) -> Any:
    """工业孪生：调用 IndustrialTwinAdapter，默认 Plotly 后端。"""
    from core.industrial_twin import TwinContext, generate_twin_sandbox

    twin_ctx = TwinContext(
        node_id=ctx.concept_name,
        c_load=ctx.c_load,
        mastery_level=ctx.mastery_level,
        embodied_signals=ctx.embodied_signals,
    )
    return generate_twin_sandbox(twin_ctx)


def _render_fallback_placeholder(ctx: SimulationContext) -> Any:
    """渲染失败时的文本占位符。"""
    import plotly.graph_objects as go

    fig = go.Figure()
    fig.add_annotation(
        x=0.5, y=0.5,
        text="[视觉生成失败，已切换文本讲解模式]",
        showarrow=False,
        font=dict(size=16, color=_HOLO_COLORS["highlight"]),
        xref="paper", yref="paper",
    )
    _apply_holo_layout(fig, f"降维补课 — {ctx.concept_name}")
    return fig


# ---------------------------------------------------------------------------
# 6. 通用布局
# ---------------------------------------------------------------------------

def _apply_holo_layout(fig: Any, title: str) -> None:
    """统一应用全息控制台风格布局。"""
    fig.update_layout(
        title=dict(text=title, font=dict(color=_HOLO_COLORS["text"], size=14)),
        paper_bgcolor=_HOLO_COLORS["bg"],
        plot_bgcolor=_HOLO_COLORS["bg"],
        font=dict(color=_HOLO_COLORS["text"], family="Fira Code, monospace"),
        margin=dict(l=20, r=20, t=40, b=20),
        scene=dict(
            xaxis=dict(
                backgroundcolor=_HOLO_COLORS["bg"],
                gridcolor=_HOLO_COLORS["grid"],
                showbackground=False,
                zerolinecolor=_HOLO_COLORS["grid"],
            ),
            yaxis=dict(
                backgroundcolor=_HOLO_COLORS["bg"],
                gridcolor=_HOLO_COLORS["grid"],
                showbackground=False,
                zerolinecolor=_HOLO_COLORS["grid"],
            ),
            zaxis=dict(
                backgroundcolor=_HOLO_COLORS["bg"],
                gridcolor=_HOLO_COLORS["grid"],
                showbackground=False,
                zerolinecolor=_HOLO_COLORS["grid"],
            ),
        ) if hasattr(fig.layout, "scene") else {},
    )


# ---------------------------------------------------------------------------
# 7. 模块级单例
# ---------------------------------------------------------------------------

_registry_singleton: Optional[SimulationRegistry] = None


def get_simulation_registry() -> SimulationRegistry:
    """获取全局唯一的 SimulationRegistry 实例。"""
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = SimulationRegistry()
    return _registry_singleton

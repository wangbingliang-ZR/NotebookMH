"""
core/industrial_twin.py - 轻量工业孪生适配器 (IndustrialTwinAdapter)

职责：
  - 为"物理/空间实体概念"提供降维可视化
  - 默认使用 Plotly 程序化几何（零环境依赖）
  - PyVista 作为可选后端，通过环境变量切换

架构：
  - 当前阶段：Plotly 模拟工业设备（Box + Cylinder + 危险球体）
  - 未来阶段：PyVista 真实 3D 模型（需环境验证后启用）

约束：
  - 零 Streamlit 依赖
  - 内存安全：不持久化 Plotly Figure
  - 降级：mesh 缺失时自动使用程序化占位符
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_BACKENDS = Literal["plotly", "pyvista"]
_DEFAULT_BACKEND: _BACKENDS = os.getenv("TWIN_BACKEND", "plotly")  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 1. 数据协议
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TwinContext:
    """工业孪生渲染上下文。"""

    node_id: str                          # 概念/隐患节点标识
    c_load: float                         # 认知负荷 0.0~1.0
    spatial_anchor: Optional[Tuple[float, float, float]] = None
    mesh_asset_id: str = ""               # 未来真实模型路径
    mastery_level: float = 0.0             # 掌握度（影响设备透明度）
    embodied_signals: Tuple[Any, ...] = ()


# ---------------------------------------------------------------------------
# 2. 公共 API
# ---------------------------------------------------------------------------

def generate_twin_sandbox(
    ctx: TwinContext,
    backend: Optional[_BACKENDS] = None,
) -> Any:
    """
    生成工业孪生 3D 场景。

    默认返回 Plotly go.Figure，可直接嵌入 st.plotly_chart()。
    若 backend="pyvista" 且环境支持，返回 HTML 字符串。
    """
    selected = backend or _DEFAULT_BACKEND

    if selected == "pyvista":
        try:
            return _pyvista_backend(ctx)
        except Exception as e:
            logger.warning("PyVista backend failed: %s; falling back to Plotly", e)
            return _plotly_backend(ctx)

    return _plotly_backend(ctx)


# ---------------------------------------------------------------------------
# 3. Plotly 后端（默认，零依赖）
# ---------------------------------------------------------------------------

def _plotly_backend(ctx: TwinContext) -> Any:
    """
    用 Plotly 程序化几何模拟工业设备。

    场景组成：
      - 机床主体（Box）
      - 管线（Cylinder）
      - 危险锚点（Sphere，c_load>0.8 时红色高亮）
      - 网格地面
    """
    import plotly.graph_objects as go

    fig = go.Figure()

    # ── 设备主体（Box）────────────────────────────────
    _add_box_mesh(fig, center=(0, 0, 1.5), size=(3, 2, 3), opacity=_mastery_to_opacity(ctx.mastery_level))

    # ── 管线（Cylinder）───────────────────────────────
    _add_cylinder_mesh(fig, start=(1.5, 0, 0), end=(1.5, 0, 3), radius=0.15)
    _add_cylinder_mesh(fig, start=(-1.5, 0, 0), end=(-1.5, 0, 3), radius=0.15)

    # ── 危险锚点（Sphere）────────────────────────────
    hazard_coords = ctx.spatial_anchor or (0, 0, 3.5)
    hazard_color = _HOLO_COLORS["hazard"] if ctx.c_load > 0.8 else _HOLO_COLORS["grid"]
    hazard_size = 0.4 + ctx.c_load * 0.4  # c_load 越高球越大

    fig.add_trace(
        go.Scatter3d(
            x=[hazard_coords[0]],
            y=[hazard_coords[1]],
            z=[hazard_coords[2]],
            mode="markers",
            marker=dict(size=hazard_size * 20, color=hazard_color, symbol="diamond"),
            name="隐患锚点",
        )
    )

    # ── 网格地面 ──────────────────────────────────────
    _add_grid_ground(fig)

    # ── 具身英语物理信号 ─────────────────────────────
    signal_focus = _apply_embodied_signals(fig, ctx.embodied_signals)

    # ── 布局 ─────────────────────────────────────────
    _apply_industrial_layout(fig, f"赛博孪生 — {ctx.node_id}")

    # 相机焦点强制锁定危险锚点或语言信号目标
    camera_focus = signal_focus or hazard_coords
    fig.update_layout(
        scene_camera=dict(
            eye=dict(x=4, y=4, z=3),
            center=dict(
                x=camera_focus[0],
                y=camera_focus[1],
                z=camera_focus[2],
            ),
        )
    )

    return fig


# ---------------------------------------------------------------------------
# 4. PyVista 后端（可选，需环境验证）
# ---------------------------------------------------------------------------

def _pyvista_backend(ctx: TwinContext) -> str:
    """
    PyVista 真实 3D 渲染。
    
    WARNING: 需要服务器安装 vtk-osmesa / mesa-libGL。
    返回 HTML 字符串，供 st.components.v1.html() 嵌入。
    """
    import pyvista as pv

    pv.OFF_SCREEN = True
    plotter = pv.Plotter(window_size=[800, 600])

    try:
        # 尝试加载真实 mesh
        if ctx.mesh_asset_id and os.path.exists(ctx.mesh_asset_id):
            mesh = pv.read(ctx.mesh_asset_id)
            plotter.add_mesh(mesh, color=_HOLO_COLORS["device"], style="wireframe")
        else:
            # 程序化占位符
            _build_procedural_dummy_device(plotter)
            logger.info("[SYS_OVERRIDE] 物理资产缺失，已启用程序化赛博孪生")

        # 危险锚点
        hazard_coords = ctx.spatial_anchor or (0, 0, 2)
        hazard_color = _HOLO_COLORS["hazard"] if ctx.c_load > 0.8 else _HOLO_COLORS["grid"]
        sphere = pv.Sphere(radius=0.3 + ctx.c_load * 0.2, center=hazard_coords)
        plotter.add_mesh(sphere, color=hazard_color, lighting=True, opacity=0.8)

        # 相机锁定
        plotter.camera.focal_point = hazard_coords
        plotter.camera_position = [(4, 4, 3), hazard_coords, (0, 0, 1)]

        html_str = plotter.export_html()
        return html_str
    finally:
        plotter.close()
        del plotter


# ---------------------------------------------------------------------------
# 5. 程序化几何辅助
# ---------------------------------------------------------------------------

_HOLO_COLORS = {
    "device": "#334155",
    "grid": "#00FF41",
    "hazard": "#FF003C",
    "warn": "#FFAA00",
    "bg": "rgba(0,0,0,0)",
    "text": "#00FF41",
}

_MESH_ANCHORS = {
    "valve_01": (1.5, 0.0, 2.2),
    "pipe_main": (1.5, 0.0, 1.5),
    "pump_01": (-1.5, 0.0, 1.2),
    "gauge_01": (0.0, -1.1, 2.4),
    "tank_01": (0.0, 0.0, 1.8),
    "sensor_01": (0.0, 1.1, 2.6),
    "filter_01": (-1.5, 0.0, 2.2),
    "engine_01": (0.0, 0.0, 1.5),
    "coupling_shaft": (0.0, 0.0, 0.9),
    "semantic_coupling": (0.0, 0.0, 3.2),
}


def _apply_embodied_signals(fig: Any, signals: Tuple[Any, ...]) -> Optional[Tuple[float, float, float]]:
    """将 language_engine 的 EmbodiedSignal 映射为 Plotly 可视反馈。"""
    if not signals:
        return None

    focus: Optional[Tuple[float, float, float]] = None
    for sig in signals:
        mesh_id = getattr(sig, "mesh_id", "") or ""
        action = getattr(sig, "action", "highlight") or "highlight"
        intensity = float(getattr(sig, "intensity", 1.0) or 1.0)
        anchor = _MESH_ANCHORS.get(mesh_id, (0.0, 0.0, 3.5))
        focus = anchor

        if action == "failure_smoke":
            _add_signal_marker(fig, anchor, "#111111", "语法卡壳 / 黑烟", size=24 * intensity, symbol="x")
        elif action == "restart_ignition":
            _add_signal_marker(fig, anchor, "#00FF41", "重新点火", size=22, symbol="diamond")
        elif action in {"open", "close", "start", "stop", "vent", "pressurize", "rotate"}:
            _add_signal_marker(fig, anchor, "#FFD700", f"{mesh_id}: {action}", size=20, symbol="diamond")
            _add_action_beam(fig, anchor, action)
        else:
            _add_signal_marker(fig, anchor, "#FFD700", f"{mesh_id}: highlight", size=18, symbol="circle")
    return focus


def _add_signal_marker(
    fig: Any,
    anchor: Tuple[float, float, float],
    color: str,
    name: str,
    size: float,
    symbol: str,
) -> None:
    import plotly.graph_objects as go

    fig.add_trace(
        go.Scatter3d(
            x=[anchor[0]],
            y=[anchor[1]],
            z=[anchor[2]],
            mode="markers+text",
            marker=dict(size=size, color=color, symbol=symbol),
            text=[name],
            textposition="top center",
            textfont=dict(color=color, size=11),
            name=name,
        )
    )


def _add_action_beam(fig: Any, anchor: Tuple[float, float, float], action: str) -> None:
    import plotly.graph_objects as go

    fig.add_trace(
        go.Scatter3d(
            x=[anchor[0], anchor[0]],
            y=[anchor[1], anchor[1]],
            z=[0.0, anchor[2] + 0.8],
            mode="lines",
            line=dict(color="#FFD700", width=6),
            name=f"Action Beam: {action}",
            hoverinfo="skip",
        )
    )


def _add_box_mesh(
    fig: Any,
    center: Tuple[float, float, float],
    size: Tuple[float, float, float],
    opacity: float = 0.7,
) -> None:
    """在 Plotly 中添加 Box 网格。"""
    import plotly.graph_objects as go

    x, y, z = center
    dx, dy, dz = size
    # 8 个顶点
    vertices = [
        (x - dx / 2, y - dy / 2, z - dz / 2),
        (x + dx / 2, y - dy / 2, z - dz / 2),
        (x + dx / 2, y + dy / 2, z - dz / 2),
        (x - dx / 2, y + dy / 2, z - dz / 2),
        (x - dx / 2, y - dy / 2, z + dz / 2),
        (x + dx / 2, y - dy / 2, z + dz / 2),
        (x + dx / 2, y + dy / 2, z + dz / 2),
        (x - dx / 2, y + dy / 2, z + dz / 2),
    ]
    # 12 个三角面
    faces = [
        (0, 1, 2), (0, 2, 3),  # 底
        (4, 5, 6), (4, 6, 7),  # 顶
        (0, 1, 5), (0, 5, 4),  # 前
        (2, 3, 7), (2, 7, 6),  # 后
        (0, 3, 7), (0, 7, 4),  # 左
        (1, 2, 6), (1, 6, 5),  # 右
    ]
    _add_mesh_from_faces(fig, vertices, faces, color=_HOLO_COLORS["device"], opacity=opacity)


def _add_cylinder_mesh(
    fig: Any,
    start: Tuple[float, float, float],
    end: Tuple[float, float, float],
    radius: float = 0.1,
    segments: int = 12,
) -> None:
    """在 Plotly 中添加 Cylinder 网格。"""
    import plotly.graph_objects as go

    import numpy as np

    # 轴线向量
    s = np.array(start, dtype=float)
    e = np.array(end, dtype=float)
    axis = e - s
    height = np.linalg.norm(axis)
    if height < 1e-6:
        return
    axis = axis / height

    # 构造正交基
    if abs(axis[2]) < 0.9:
        ortho = np.array([0, 0, 1], dtype=float)
    else:
        ortho = np.array([1, 0, 0], dtype=float)
    u = np.cross(axis, ortho)
    u = u / np.linalg.norm(u)
    v = np.cross(axis, u)

    # 生成圆周点
    theta = np.linspace(0, 2 * np.pi, segments, endpoint=False)
    circle = np.stack([np.cos(theta), np.sin(theta)], axis=1)  # (segments, 2)

    # 底部和顶部圆周
    bottom = s + radius * (circle[:, 0:1] * u + circle[:, 1:2] * v)
    top = e + radius * (circle[:, 0:1] * u + circle[:, 1:2] * v)

    # 合并顶点
    vertices = np.vstack([bottom, top, s.reshape(1, 3), e.reshape(1, 3)])
    n = segments

    # 侧面三角面
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, j + n))
        faces.append((i, j + n, i + n))

    # 底面和顶面（扇形）
    bottom_center = 2 * n
    top_center = 2 * n + 1
    for i in range(n):
        j = (i + 1) % n
        faces.append((i, j, bottom_center))
        faces.append((i + n, j + n, top_center))

    _add_mesh_from_faces(fig, vertices.tolist(), faces, color=_HOLO_COLORS["device"], opacity=0.6)


def _add_grid_ground(fig: Any, size: int = 10, step: float = 1.0) -> None:
    """添加网格地面。"""
    import plotly.graph_objects as go

    import numpy as np

    x = np.arange(-size, size + step, step)
    z = np.zeros_like(x)
    for i in range(-size, size + 1, int(step)):
        fig.add_trace(
            go.Scatter3d(
                x=[i, i], y=[-size, size], z=[0, 0],
                mode="lines", line=dict(color=_HOLO_COLORS["grid"], width=1),
                hoverinfo="skip", showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter3d(
                x=[-size, size], y=[i, i], z=[0, 0],
                mode="lines", line=dict(color=_HOLO_COLORS["grid"], width=1),
                hoverinfo="skip", showlegend=False,
            )
        )


def _add_mesh_from_faces(
    fig: Any,
    vertices: list,
    faces: list,
    color: str,
    opacity: float = 0.7,
) -> None:
    """通用三角面渲染器。"""
    import plotly.graph_objects as go

    import numpy as np

    x, y, z = [], [], []
    for face in faces:
        for idx in face:
            v = vertices[idx]
            x.append(v[0])
            y.append(v[1])
            z.append(v[2])
        x.append(None)
        y.append(None)
        z.append(None)

    fig.add_trace(
        go.Mesh3d(
            x=np.array([v[0] for v in vertices]),
            y=np.array([v[1] for v in vertices]),
            z=np.array([v[2] for v in vertices]),
            i=[f[0] for f in faces],
            j=[f[1] for f in faces],
            k=[f[2] for f in faces],
            color=color,
            opacity=opacity,
            hoverinfo="skip",
            showlegend=False,
        )
    )


def _build_procedural_dummy_device(plotter: Any) -> None:
    """PyVista 程序化占位符：Cylinder 管线 + Box 机床。"""
    import pyvista as pv

    body = pv.Cylinder(center=(0, 0, 1.5), direction=(0, 0, 1), radius=1.0, height=3.0)
    pipe = pv.Cylinder(center=(1.5, 0, 1.5), direction=(0, 0, 1), radius=0.15, height=3.0)
    plotter.add_mesh(body, color=_HOLO_COLORS["device"], style="wireframe")
    plotter.add_mesh(pipe, color=_HOLO_COLORS["grid"])


def _mastery_to_opacity(mastery: float) -> float:
    """掌握度越高，设备越不透明（用户越'看清'设备结构）。"""
    return 0.3 + (mastery / 100.0) * 0.5


def _apply_industrial_layout(fig: Any, title: str) -> None:
    """统一工业孪生布局。"""
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
        ),
    )

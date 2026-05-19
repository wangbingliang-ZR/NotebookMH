"""
frontend/visual_sandbox.py - 3D 流体粒子沙箱 + ASMR 遥测 (Phase 4)

职责：
  - 嵌入 Three.js 3D 粒子系统，实时反映认知态
  - ASMR 遥测：呼吸脉动环、认知负荷波形、状态徽章
  - 调用 core.visual_engine.compute() 获取视觉参数

严禁在 app.py 中写入具体 UI 逻辑。
"""

import json
import logging
from typing import Any, Dict

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None  # type: ignore[assignment]

from core.visual_engine import get_visual_engine
from utils.state_manager import binder

logger = logging.getLogger(__name__)

_VISUAL = get_visual_engine()


# ---------------------------------------------------------------------------
# 公共渲染接口
# ---------------------------------------------------------------------------

def render() -> None:
    """渲染 3D 流体沙箱 + ASMR 遥测面板。"""
    if st is None:
        return

    st.divider()
    st.subheader("🌊 3D 流体认知沙箱 (Phase 4)")

    # 计算视觉参数
    params = _VISUAL.compute()
    pdict = params.to_dict()

    # ── 状态徽章栏 ────────────────────────────────────────
    cols = st.columns(4)
    with cols[0]:
        emotion = binder.get_state("emotion_state", "专注")
        st.caption(f"情绪: **{emotion}**")
    with cols[1]:
        tier = binder.get_state("render_tier", "UNKNOWN")
        st.caption(f"渲染: `{tier}`")
    with cols[2]:
        st.caption(f"粒子: **{params.particle_count}**")
    with cols[3]:
        st.caption(f"脉动: **{params.pulse_rate:.1f} Hz**")

    # ── 3D 粒子画布 (Three.js iframe) ─────────────────────
    _render_threejs_canvas(pdict)

    # ── ASMR 遥测 ─────────────────────────────────────────
    st.divider()
    st.caption("🫧 ASMR 认知遥测")
    _render_asmr_telemetry(params)


# ---------------------------------------------------------------------------
# Three.js 嵌入
# ---------------------------------------------------------------------------

def _render_threejs_canvas(params: Dict[str, Any]) -> None:
    """使用 st.components.v1.html 嵌入 Three.js 粒子系统。"""
    import streamlit.components.v1 as components

    color = params["base_color"]
    bg = params["background_gradient"]

    html = _THREEJS_TEMPLATE.format(
        particle_count=params["particle_count"],
        color_r=color[0],
        color_g=color[1],
        color_b=color[2],
        turbulence=params["turbulence"],
        speed=params["speed"],
        coherence=params["coherence"],
        pulse_rate=params["pulse_rate"],
        bg_from=bg[0],
        bg_to=bg[1],
    )

    # 渲染 iframe，高度固定 420px
    components.html(html, height=420, scrolling=False)


# ---------------------------------------------------------------------------
# ASMR 遥测
# ---------------------------------------------------------------------------

def _render_asmr_telemetry(params: Any) -> None:
    """渲染 ASMR 风格遥测：呼吸环、认知负荷条、情绪波形。"""
    col1, col2, col3 = st.columns(3)

    # 呼吸环: pulse_rate → 动画速度
    with col1:
        st.markdown("##### 🫁 呼吸节律")
        pr = params.pulse_rate
        # 使用 CSS 动画 + HTML 实现脉动环
        period = max(0.5, 3.0 / pr) if pr > 0 else 2.0
        _render_breathing_ring(period)

    # 认知负荷波形
    with col2:
        st.markdown("##### 🧠 认知负荷")
        c_load = binder.get_state("c_load", 0.0)
        st.progress(min(c_load, 1.0), text=f"c_load: {c_load:.2f}")
        st.caption("负荷越高，粒子越湍急")

    # 情绪效价仪表盘
    with col3:
        st.markdown("##### 💫 情绪效价")
        e_val = binder.get_state("e_valence", 0.0)
        # -1~+1 映射到 0~1
        val_pos = (e_val + 1.0) / 2.0
        st.progress(val_pos, text=f"e_valence: {e_val:+.2f}")
        st.caption("偏暖=正向，偏冷=负向")


def _render_breathing_ring(period_sec: float) -> None:
    """使用 HTML/CSS 渲染脉动呼吸环。"""
    import streamlit.components.v1 as components

    css_period = f"{period_sec:.1f}s"
    html = f"""
    <style>
    .breath-container {{
        display: flex;
        align-items: center;
        justify-content: center;
        height: 120px;
    }}
    .breath-ring {{
        width: 60px;
        height: 60px;
        border-radius: 50%;
        background: radial-gradient(circle, rgba(100,200,255,0.3) 0%, rgba(0,0,0,0) 70%);
        border: 2px solid rgba(100,200,255,0.5);
        animation: breathe {css_period} ease-in-out infinite;
    }}
    @keyframes breathe {{
        0%, 100% {{ transform: scale(1); opacity: 0.6; }}
        50% {{ transform: scale(1.4); opacity: 1.0; }}
    }}
    </style>
    <div class="breath-container">
        <div class="breath-ring"></div>
    </div>
    """
    components.html(html, height=130)


# ---------------------------------------------------------------------------
# Three.js HTML 模板
# ---------------------------------------------------------------------------

_THREEJS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
body {{
    margin: 0;
    overflow: hidden;
    background: linear-gradient(135deg, {bg_from}, {bg_to});
}}
#canvas-container {{
    width: 100%;
    height: 100%;
}}
canvas {{ display: block; }}
</style>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
</head>
<body>
<div id="canvas-container"></div>
<script>
(function() {{
    const PARTICLE_COUNT = {particle_count};
    const TURBULENCE = {turbulence};
    const SPEED = {speed};
    const COHERENCE = {coherence};
    const PULSE_RATE = {pulse_rate};
    const BASE_COLOR = [{color_r}, {color_g}, {color_b}];

    const container = document.getElementById('canvas-container');
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, container.clientWidth / container.clientHeight, 0.1, 1000);
    camera.position.z = 50;

    const renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // 粒子几何体
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const colors = new Float32Array(PARTICLE_COUNT * 3);
    const originalPositions = new Float32Array(PARTICLE_COUNT * 3);

    for (let i = 0; i < PARTICLE_COUNT; i++) {{
        const i3 = i * 3;
        // 球形分布，coherence 高时更集中
        const radius = 20 + (1 - COHERENCE) * Math.random() * 25;
        const theta = Math.random() * Math.PI * 2;
        const phi = Math.acos(2 * Math.random() - 1);

        positions[i3] = radius * Math.sin(phi) * Math.cos(theta);
        positions[i3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
        positions[i3 + 2] = radius * Math.cos(phi);

        originalPositions[i3] = positions[i3];
        originalPositions[i3 + 1] = positions[i3 + 1];
        originalPositions[i3 + 2] = positions[i3 + 2];

        // 颜色微调
        colors[i3] = Math.min(1, BASE_COLOR[0] + (Math.random() - 0.5) * 0.2);
        colors[i3 + 1] = Math.min(1, BASE_COLOR[1] + (Math.random() - 0.5) * 0.2);
        colors[i3 + 2] = Math.min(1, BASE_COLOR[2] + (Math.random() - 0.5) * 0.2);
    }}

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({{
        size: 0.4,
        vertexColors: true,
        transparent: true,
        opacity: 0.8,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
    }});

    const particles = new THREE.Points(geometry, material);
    scene.add(particles);

    // 鼠标交互
    let mouseX = 0, mouseY = 0;
    document.addEventListener('mousemove', (e) => {{
        mouseX = (e.clientX / window.innerWidth - 0.5) * 2;
        mouseY = (e.clientY / window.innerHeight - 0.5) * 2;
    }});

    // 动画循环
    const clock = new THREE.Clock();

    function animate() {{
        requestAnimationFrame(animate);
        const t = clock.getElapsedTime();
        const pos = geometry.attributes.position.array;

        for (let i = 0; i < PARTICLE_COUNT; i++) {{
            const i3 = i * 3;
            const ox = originalPositions[i3];
            const oy = originalPositions[i3 + 1];
            const oz = originalPositions[i3 + 2];

            // 湍流噪声模拟 (叠加正弦波)
            const noise = Math.sin(t * SPEED + ox * 0.1) * Math.cos(t * SPEED * 0.7 + oy * 0.1);
            const displacement = noise * TURBULENCE * 3.0;

            // 脉动呼吸 (整体缩放)
            const breath = 1.0 + Math.sin(t * PULSE_RATE * Math.PI * 2) * 0.05;

            pos[i3] = ox * breath + displacement;
            pos[i3 + 1] = oy * breath + displacement * 0.7;
            pos[i3 + 2] = oz * breath + displacement * 0.5;
        }}

        geometry.attributes.position.needsUpdate = true;

        // 整体缓慢旋转
        particles.rotation.y += 0.001 * SPEED;
        particles.rotation.x += 0.0005 * SPEED;

        // 鼠标影响相机
        camera.position.x += (mouseX * 5 - camera.position.x) * 0.02;
        camera.position.y += (-mouseY * 5 - camera.position.y) * 0.02;
        camera.lookAt(scene.position);

        renderer.render(scene, camera);
    }}

    animate();

    // 响应式
    window.addEventListener('resize', () => {{
        camera.aspect = container.clientWidth / container.clientHeight;
        camera.updateProjectionMatrix();
        renderer.setSize(container.clientWidth, container.clientHeight);
    }});
}})();
</script>
</body>
</html>
"""

/**
 * frontend/telemetry.js - 前端遥测暗网
 *
 * Phase 0 预留：FPS监控、鼠标动力学与 WebAudio 引擎。
 * 职责：
 *   - requestAnimationFrame FPS 采样
 *   - 鼠标移动/点击热力图采集
 *   - WebAudio 上下文初始化与 ASMR 预备
 */

(function () {
    'use strict';

    const Telemetry = {
        fps: [],
        mouse: [],
        audioCtx: null,

        initFPS() {
            let last = performance.now();
            let frames = 0;
            const loop = (now) => {
                frames++;
                if (now - last >= 1000) {
                    this.fps.push(frames);
                    if (this.fps.length > 60) this.fps.shift();
                    frames = 0;
                    last = now;
                }
                requestAnimationFrame(loop);
            };
            requestAnimationFrame(loop);
        },

        initMouse() {
            document.addEventListener('mousemove', (e) => {
                this.mouse.push({ x: e.clientX, y: e.clientY, t: Date.now() });
                if (this.mouse.length > 1000) this.mouse.shift();
            });
        },

        initAudio() {
            try {
                this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            } catch (_) {
                console.warn('[Telemetry] WebAudio not available');
            }
        },

        report() {
            const avgFPS = this.fps.length
                ? (this.fps.reduce((a, b) => a + b, 0) / this.fps.length).toFixed(1)
                : 'N/A';
            return { avgFPS, mouseSamples: this.mouse.length, audioReady: !!this.audioCtx };
        },
    };

    // Phase 0: 延迟初始化，避免阻塞页面加载
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => Telemetry.initFPS());
    } else {
        Telemetry.initFPS();
    }
    Telemetry.initMouse();
    Telemetry.initAudio();

    // 挂载到全局供后续 Phase 调用
    window.NB_MH_Telemetry = Telemetry;
})();

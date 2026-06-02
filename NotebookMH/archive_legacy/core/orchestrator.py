"""
core/orchestrator.py - 衔尾蛇事件总线 (Ouroboros Pub/Sub)

Phase 0 预留：未来 Phase 1~N 的业务模块通过此总线解耦通信。
职责：
  - 事件发布/订阅
  - 模块生命周期管理
  - 跨模块消息路由
"""

from typing import Any, Callable, Dict, List


class OuroborosBus:
    """衔尾蛇事件总线 —— 零依赖的轻量级 Pub/Sub 实现。"""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[..., Any]]] = {}

    def subscribe(self, event_type: str, handler: Callable[..., Any]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, payload: Any = None) -> None:
        for handler in self._handlers.get(event_type, []):
            try:
                handler(payload)
            except Exception:
                # Phase 0: 静默容错，后续接入日志与降级策略
                pass

    def reset(self) -> None:
        self._handlers.clear()


# 模块级单例
ouroboros = OuroborosBus()

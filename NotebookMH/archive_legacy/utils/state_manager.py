"""
utils/state_manager.py - 量子态会话单例 (Quantum State Singleton)

用 Pydantic V2 构建强类型的 GlobalState Schema，
通过 SessionStateBinder 单例封装对 st.session_state 的绝对控制权。
任何状态修改必须通过 binder.update_state(key, value)，
内部触发 Pydantic model_validate 校验。

核心数据点：
  - vault_uuid: 当前激活的数据容器 ID
  - c_load: 认知负荷探针 (0.0 ~ 1.0)
  - e_valence: 情绪效价探针 (-1.0 ~ 1.0)
  - render_tier: 自适应渲染等级
"""

import logging
from typing import Any, Dict, Optional, Self

from pydantic import BaseModel, Field, field_validator, ValidationError, ConfigDict

# 强制要求运行环境持有 streamlit
try:
    import streamlit as st
except ImportError as _e:  # pragma: no cover
    st = None  # type: ignore[assignment]
    logging.getLogger(__name__).warning(
        "streamlit not available in this environment: %s", _e
    )

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. GlobalState Schema - 强类型状态定义
# ---------------------------------------------------------------------------

class GlobalState(BaseModel):
    """GlobalState 定义 NotebookMH 运行时的全部量子态。

    字段说明：
      vault_uuid (str): 当前激活的数据容器 ID（默认空串表示未加载）。
      c_load (float): 认知负荷探针，必须 0.0~1.0。
      e_valence (float): 情绪效价探针，必须 -1.0~1.0。
      render_tier (str): 自适应渲染等级，枚举如下。
    """
    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    vault_uuid: str = Field(default="", description="当前激活的数据容器 ID")
    c_load: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="认知负荷探针 (0.0=空载, 1.0=过载)",
    )
    e_valence: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="情绪效价探针 (-1.0=负向, 1.0=正向)",
    )
    render_tier: str = Field(
        default="ULTRA_3D",
        description="自适应渲染等级: LOW_2D | MEDIUM_CSS | HIGH_CANVAS | ULTRA_3D",
    )
    # Phase 2: 教师人格态
    teacher_type: str = Field(
        default="auto",
        description="教师人格: socratic | strict | auto",
    )
    emotion_state: str = Field(
        default="专注",
        description="用户情绪状态: 沮丧 | 挫败 | 困惑 | 开心 | 专注 | 走神 | 懒散 | 疲倦",
    )
    user_mode: str = Field(
        default="adult",
        description="用户模式: child | adult",
    )
    user_id: str = Field(
        default="anonymous",
        description="当前用户标识",
    )

    @field_validator("c_load")
    @classmethod
    def _clamp_c_load(cls, v: float) -> float:
        """死锁 c_load 在 0.0 ~ 1.0 之间。"""
        return max(0.0, min(1.0, float(v)))

    @field_validator("e_valence")
    @classmethod
    def _clamp_e_valence(cls, v: float) -> float:
        """死锁 e_valence 在 -1.0 ~ 1.0 之间。"""
        return max(-1.0, min(1.0, float(v)))

    @field_validator("render_tier")
    @classmethod
    def _validate_render_tier(cls, v: str) -> str:
        """只允许预定义的渲染等级。"""
        allowed = {"LOW_2D", "MEDIUM_CSS", "HIGH_CANVAS", "ULTRA_3D"}
        if v not in allowed:
            raise ValueError(
                f"render_tier must be one of {allowed}, got {v!r}"
            )
        return v

    @field_validator("teacher_type")
    @classmethod
    def _validate_teacher_type(cls, v: str) -> str:
        """只允许预定义的教师人格。"""
        allowed = {"socratic", "strict", "auto"}
        if v not in allowed:
            raise ValueError(
                f"teacher_type must be one of {allowed}, got {v!r}"
            )
        return v

    @field_validator("user_mode")
    @classmethod
    def _validate_user_mode(cls, v: str) -> str:
        """只允许预定义的用户模式。"""
        allowed = {"child", "adult"}
        if v not in allowed:
            raise ValueError(
                f"user_mode must be one of {allowed}, got {v!r}"
            )
        return v


# ---------------------------------------------------------------------------
# 2. SessionStateBinder - 量子态会话单例
# ---------------------------------------------------------------------------

class SessionStateBinder:
    """
    SessionStateBinder 封装对 st.session_state 的绝对控制权。

    职责：
      1. 将 GlobalState 映射到 st.session_state 的一个命名空间下。
      2. 所有写操作都经过 Pydantic 校验。
      3. 提供类型安全的状态读取。

    使用方式：
        binder = SessionStateBinder()
        binder.update_state("c_load", 0.75)
        val = binder.get_state("c_load")
    """

    _instance: Optional[Self] = None
    _NAMESPACE: str = "__nb_mh_state__"

    def __new__(cls, *args: Any, **kwargs: Any) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, auto_init: bool = True) -> None:
        if self._initialized:
            return
        self._initialized = True
        if auto_init:
            self._init_state()

    def _init_state(self) -> None:
        """将 Pydantic 默认值水合到 st.session_state 命名空间中。"""
        if st is None:
            return
        defaults = GlobalState.model_construct().model_dump()
        for key, value in defaults.items():
            if key not in self._raw_state():
                self._raw_state()[key] = value

    def _raw_state(self) -> Dict[str, Any]:
        """获取命名空间下的原始字典引用。"""
        if st is None:
            return {}
        if self._NAMESPACE not in st.session_state:
            st.session_state[self._NAMESPACE] = {}
        return st.session_state[self._NAMESPACE]  # type: ignore[return-value]

    # ------------------ 公共 API ------------------

    def update_state(self, key: str, value: Any) -> None:
        """
        更新单个状态字段。内部重建 GlobalState 以触发 Pydantic 校验。

        Raises:
            ValidationError: 当值不符合字段约束时抛出，且不会被吞掉。
        """
        raw = self._raw_state()
        draft = dict(raw)
        draft[key] = value

        # 通过 Pydantic 校验 —— 任何非法值都会被拦截
        validated = GlobalState.model_validate(draft)
        # 校验通过后写回
        raw[key] = validated.model_dump()[key]
        logger.debug("State updated: %s = %r", key, raw[key])

    def update_states(self, updates: Dict[str, Any]) -> None:
        """批量更新多个状态字段，整体原子校验。"""
        raw = self._raw_state()
        draft = dict(raw)
        draft.update(updates)

        validated = GlobalState.model_validate(draft)
        for k, v in validated.model_dump().items():
            raw[k] = v
        logger.debug("States bulk-updated: %s", list(updates.keys()))

    def get_state(self, key: str, default: Any = None) -> Any:
        """安全读取状态字段。"""
        return self._raw_state().get(key, default)

    def get_all(self) -> Dict[str, Any]:
        """读取当前完整状态快照。"""
        return dict(self._raw_state())

    def reset(self) -> None:
        """重置为 Pydantic 默认值。"""
        raw = self._raw_state()
        defaults = GlobalState.model_construct().model_dump()
        raw.clear()
        raw.update(defaults)
        logger.info("State reset to defaults.")

    def snapshot(self) -> GlobalState:
        """返回当前状态的 Pydantic 模型实例（只读快照）。"""
        return GlobalState.model_validate(self._raw_state())


# ---------------------------------------------------------------------------
# 3. 模块级单例快捷入口
# ---------------------------------------------------------------------------

binder = SessionStateBinder(auto_init=True)

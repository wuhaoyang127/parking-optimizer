"""Thin, read-only Streamlit and Plotly presentation layer."""

from parking_opt.app.data import (
    DemoCatalog,
    load_builtin_adaptation_report,
    load_builtin_catalog,
    load_builtin_evidence,
    load_builtin_replay,
)
from parking_opt.app.design import (
    POSITION_STATUS_SPECS,
    ScreenshotState,
    StatusSpec,
)
from parking_opt.app.metrics_view import build_ratio_comparison_figure
from parking_opt.app.static_layout import (
    ReplayLayoutView,
    StaticLayoutView,
    StaticPositionView,
    build_layout_figure,
    build_replay_view,
    build_static_view,
)

__all__ = [
    "POSITION_STATUS_SPECS",
    "DemoCatalog",
    "ReplayLayoutView",
    "ScreenshotState",
    "StaticLayoutView",
    "StaticPositionView",
    "StatusSpec",
    "build_layout_figure",
    "build_ratio_comparison_figure",
    "build_replay_view",
    "build_static_view",
    "load_builtin_adaptation_report",
    "load_builtin_catalog",
    "load_builtin_evidence",
    "load_builtin_replay",
]

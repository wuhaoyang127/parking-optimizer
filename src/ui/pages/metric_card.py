"""指标卡片小工具（系统状态页 / 指标分析页共用）。"""
from ui.common import *


def _metric(label, value, variant=""):
    cls = f"metric-card {variant}" if variant else "metric-card"
    st.markdown(f'<div class="{cls}"><div class="val">{value}</div><div class="lbl">{label}</div></div>',
                unsafe_allow_html=True)

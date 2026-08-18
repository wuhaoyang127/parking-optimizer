"""仿真与环境参数的权威默认值。

app.py 的 ENV_PARAM_SPECS、arrival.generate_demand、engine.SimulationEngine
的默认参数均引用此处，避免多处硬编码导致不一致。修改默认值时只改这里即可。
"""

CAR_SPEED = 1.39          # 车速 m/s (5 km/h)
MAX_WAIT_TIME = 1800      # 排队等待上限 s (30 分钟)
SIM_DURATION = 21600.0    # 仿真时长 s (6 小时)
DURATION_MIN = 600.0      # 停车时长下限 s (10 分钟)
DURATION_MAX = 7200.0     # 停车时长上限 s (2 小时)
PEAK_RATIO = 0.7          # 高峰时段车辆占比
ERROR_RATIO = 0.3         # 预估时长相对真实时长的误差 ±比例

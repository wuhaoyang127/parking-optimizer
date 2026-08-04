---
status: completed
stage: C
created: 2026-08-04
---

# 阶段C执行计划

## 目标
实现阶段B冻结的全部模块：领域模型、路网、仿真、策略、优化、评估。

## 里程碑
- [x] C1: pyproject.toml + domain/ (Spot, Vehicle, RoadNetwork, Event)
- [x] C2: routing/ (PathEngine) + io/ (JSON读写)
- [x] C3: simulation/ (SimPy引擎, ParkingLot, arrival) + baselines (FCFS, nearest, random)
- [x] C4: optimization/ (CP-SAT小规模基准)
- [x] C5: strategies/greedy.py (主方法) + departure_order.py
- [x] C6: evaluation/metrics.py + cli/main.py
- [ ] C7: 全面复核（性能、复现、文档一致性）

## 测试结果
✅ 6/6 单元测试通过

## 仿真结果
15车位×60车: 贪心满足率 68.3% > FCFS 63.3% > 最近 58.3% > 随机 56.7%

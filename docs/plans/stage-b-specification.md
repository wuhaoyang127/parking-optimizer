---
status: completed
stage: B
created: 2026-08-04
completed: 2026-08-04
---

# 阶段B执行计划：数学模型与工程设计

## 目标
冻结停车场优化项目的全部数学模型、数据契约、软件架构、实验协议。

## 里程碑

- [x] B1. 问题定义与假设
- [x] B2. 符号变量与数学模型
- [x] B3. 纵深阻挡与移位模型
- [x] B4. 离线在线与动态决策模式
- [x] B5. 算法伪代码
- [x] B6. 数据契约 (JSON Schema)
- [x] B7. 软件架构
- [x] B8. 实验协议、验收标准、极小验证例、阶段C输入清单

## 修改文件 (12个新增)
docs/model/01-07, docs/data/01, docs/architecture/01, docs/experiments/01-02, PROJECT_STATUS.md

## 冻结的核心定义
- 动态缓冲位（征用空闲车位）
- 分层目标（词典序）
- 信息边界（离线oracle / 在线贪心 / 降级FCFS）
- 统一车位模型（stack_group_id + depth）
- 6策略对比实验矩阵（12场景 × ≥5种子）

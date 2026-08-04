# 智能停车场优化研究项目：Codex 启动包

本启动包用于在 **ChatGPT 桌面应用中的 Codex（原 Codex App）** 中，分阶段完成“智能停车场车位分配与纵深车位移位优化”项目。客户端界面名称可能继续更新，本文中的“Codex”均指桌面端的 Codex 工作区。

## 当前处于什么状态

项目还没有冻结最终算法。当前优先考察的候选路线是：

> 路网成本预处理 + 可校准的事件仿真 + 小规模高质量基准 + 动态车位分配优化 + 确定性降级策略。

NetworkX、SimPy、OR-Tools CP-SAT 和滚动时域优化只是可能选项。阶段 A 必须真正审查原方案、检索文献和比较候选路线；阶段 B 才冻结数学模型、求解方法和工程方案。

## 正确文件名

Codex 项目级规则文件必须命名为：

```text
AGENTS.md
```

不是 `agent.md`、`AGEND.md` 或 `AGENG.md`。

## 包内已经包含

- `AGENTS.md`：长期规则；
- `PROJECT_STATUS.md`：跨对话进度入口；
- `.agent/PLANS.md`：ExecPlan 规范；
- A—D 阶段提示词；
- 阶段验收和状态交接提示词；
- 两份原始 Word，位于 `references/original/`；
- Git、归档、项目结构和桌面端 Codex 使用说明；
- `.gitignore`；
- `scripts/validate_starter_package.py`：启动包结构与一致性检查。

## 第一次使用

建议安装：

1. Git for Windows；
2. Python 3.11 64 位；
3. 带有 Codex 的 ChatGPT 桌面应用；
4. 可选：VS Code。

阶段 A、B 主要进行研究和设计，不必安装全部算法依赖。阶段 C1 再根据阶段 B 批准的技术路线建立 `pyproject.toml` 和虚拟环境。

压缩包已经包含最外层 `parking-optimizer/` 目录和两份原始 Word。解压后直接进入该目录，不要再次创建同名文件夹，也不要重复复制 Word。

先运行只读的初始检查：

```powershell
cd <解压位置>\parking-optimizer
python scripts/validate_starter_package.py --initial
```

通过后初始化 Git：

```powershell
git init -b main
git add .
git commit -m "chore: initialize parking optimizer project"
git switch -c stage-a-research
```

随后把 `PROJECT_STATUS.md` 中以下字段更新为：

```yaml
git_initialized: true
current_branch: stage-a-research
```

## 每个新对话的固定开场

先让 Codex 读取：

```text
AGENTS.md
PROJECT_STATUS.md
.agent/PLANS.md
```

仅当状态中的路径不为 `null` 时，再读取：

```text
current_exec_plan 指向的文件
latest_handoff 指向的文件
```

然后使用：

```text
prompts/项目状态更新与新对话交接.md
```

Codex必须先复述当前阶段、当前阶段阻断项、下游阻断项、唯一下一步、本次范围和验证方式，再开始工作。

## 正确推进顺序

1. 打开整个 `parking-optimizer` 根目录；
2. 新建或切换到当前阶段分支；
3. 执行 `PROJECT_STATUS.md` 中的 `next_prompt`；
4. 先建立 ExecPlan；
5. 分小步实施；
6. 查看 Diff 和实际测试输出；
7. 使用 `prompts/阶段验收与复核.md`；
8. 用户批准后合并到 `main`、打标签并更新状态；
9. 再进入下一阶段。

不要把 A、B、C、D 一次塞给 Codex。

## 阶段门禁

### A：研究与路线决策

只做原方案审查、文献核验、候选路线比较、最终路线选择和数据缺口分析。不写完整程序。

### B：模型与工程设计

冻结问题定义、数学模型、数据契约、软件架构、测试和实验协议。只允许极小验证原型，不预设 CP-SAT、滚动时域或其他具体方法。

### C：核心实现与验证

根据阶段 B 批准结果重新检查或重生成 C1—C7 提示词，然后逐步实现环境、领域模型、数据、仿真/事件机制、基准方法、动态算法、实验和复核。当前包内的 C 提示词是通用模板，不是技术选型依据。

### D：应用与交付

在核心系统稳定后，实现 CLI/API、真实数据适配、交互展示和交付材料。Streamlit 是当前暂定偏好，阶段 D0 必须再次确认。

## 关键目录

```text
parking-optimizer/
├─ AGENTS.md
├─ PROJECT_STATUS.md
├─ README.md
├─ .gitignore
├─ .agent/
├─ prompts/
├─ references/
├─ docs/
├─ prototypes/
├─ data/
├─ configs/
├─ src/parking_opt/
├─ tests/
├─ scripts/
├─ app/
└─ outputs/
```

完整说明见 `docs/项目结构说明.md`。

## 自检命令

刚解压、尚未初始化 Git 时：

```powershell
python scripts/validate_starter_package.py --initial
```

初始化 Git、切换分支并同步 `PROJECT_STATUS.md` 后：

```powershell
python scripts/validate_starter_package.py
```

以上两条命令默认只读，不会更新报告或污染 Git 工作区。确实需要保存新的 JSON 快照时才使用：

```powershell
python scripts/validate_starter_package.py --write-report
```

文件统计只计算受控项目文件，排除 `.git`、虚拟环境、缓存、运行输出和被忽略的数据。
该检查只验证结构、状态、指针和文档一致性，不证明未来数学模型、算法或实验结论正确。

## 最重要的防错原则

- 阶段 A 不得为预设路线寻找佐证；
- 当前阶段阻断项和下游阻断项必须区分；
- 仿真器可以知道未来，动态算法不能读取未来真值；
- 不把 Dijkstra 当车位分配算法；
- 不把预测模型或机器学习模型当成组合优化器；
- 不静默降级；
- 不修改原始 Word 和原始真实数据；
- 不提交密钥、环境文件或未经脱敏的真实数据；
- 不隐藏失败、超时或主算法不如基线的结果；
- 所有结论限定数据、场景、指标和计算预算。

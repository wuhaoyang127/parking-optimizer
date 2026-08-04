# ChatGPT 桌面端 Codex 分阶段使用指南

截至 2026 年 7 月，原 Codex App 正在并入新的 ChatGPT 桌面应用。本文使用“桌面端 Codex”指 ChatGPT 桌面应用中的 Codex 工作区；具体按钮名称可能随客户端版本变化。

## 1. 解压和初始化

压缩包已经包含：

```text
parking-optimizer/
```

以及 `references/original/` 下的两份原始 Word。不要再次创建同名项目目录，也不要重复复制原始材料。

将压缩包解压到独立位置，例如：

```text
D:\Projects\parking-optimizer
```

不要把整个桌面、文档目录或包含其他重要文件的上级目录授权给 Codex。

PowerShell：

```powershell
cd D:\Projects\parking-optimizer
python scripts/validate_starter_package.py --initial
git init -b main
git add .
git commit -m "chore: initialize parking optimizer project"
git switch -c stage-a-research
```

随后更新 `PROJECT_STATUS.md`：

```yaml
git_initialized: true
current_branch: stage-a-research
```

再运行持续检查：

```powershell
python scripts/validate_starter_package.py
```

两种默认检查都只读，不会修改 JSON 报告。只有明确需要保存检查快照时才加 `--write-report`。

在 ChatGPT 桌面应用中打开整个 `parking-optimizer` 根目录。

## 2. 第一次状态检查

先发送：

```text
请不要修改任何文件。先读取：

1. AGENTS.md
2. PROJECT_STATUS.md
3. .agent/PLANS.md
4. README.md
5. 当 current_exec_plan 不为 null 时，读取其指向的文件
6. 当 latest_handoff 不为 null 时，读取其指向的文件
7. references/original/ 中的原始材料目录

用不超过十行说明：
- 当前阶段和验收状态；
- 当前阶段阻断项；
- 下游阶段阻断项；
- 已完成内容；
- 已批准或冻结的决定；
- 尚未冻结的问题；
- 当前唯一下一步；
- 当前不能做什么；
- 是否存在需要我确认的关键歧义。

不要开始实施。
```

确认它正确识别 `AGENTS.md` 和状态文件后再运行阶段 A。

## 3. 新对话恢复项目进度

每次新开对话都先读取状态。若 `current_exec_plan` 或 `latest_handoff` 为 `null`，必须跳过，不得猜测路径。

当前阶段阻断项会阻止当前工作；下游阻断项只阻止进入标注的后续阶段，不阻止当前阶段解决这些问题。

## 4. 阶段 A

使用客户端当前提供的计划功能，或直接明确要求“先规划、等待确认后再修改”。粘贴：

```text
prompts/A_研究与路线决策.md
```

要求：

- 允许必要的网页检索；
- 不批准无关依赖安装；
- 先展示 ExecPlan 和检索方法；
- 当前候选路线必须允许被否定；
- 不开始完整程序、界面或正式实验；
- 输出后运行阶段验收提示词。

## 5. 阶段 B

阶段 A 通过并提交 Git 后，新开任务，粘贴：

```text
prompts/B_数学模型与工程设计.md
```

重点检查：

- 是否使用阶段 A 已批准的路线，而非旧模板预设；
- 是否区分离线全信息基准、在线即时策略和已批准的动态方法；
- 是否严格定义纵深阻挡、移位、缓冲位和利用率；
- 是否防止未来信息泄漏；
- 是否给出极小人工例；
- 是否按最终求解方法给出可实现表达；
- 是否冻结实验协议和阶段 C 输入。

## 6. 阶段 C

先执行：

```text
prompts/C/C0_阶段C总控.md
```

C1—C7 只是通用职责模板。阶段 B 验收后必须依据最终路线复核或重生成，不能因为模板示例自动选择 SimPy、CP-SAT 或滚动时域。

每个子阶段：

1. 查看 Diff；
2. 运行实际测试；
3. 更新 ExecPlan；
4. 运行阶段验收；
5. Git 提交；
6. 再进入下一步。

Python 环境通常在 C1 建立，例如：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

具体命令以 C1 最终生成的 `pyproject.toml` 为准。

## 7. 阶段 D

只有核心算法、仿真和实验稳定后才做界面。D0必须复核展示框架。当前暂定优先考虑 Streamlit，但可以根据阶段 C 的稳定接口、部署需求和团队学习成本改用其他方案，并记录理由。

界面不得复制算法逻辑，应调用 `src/parking_opt` 的稳定服务接口。

## 8. Codex 走偏时

出现以下情况应停止：

- 未读状态和阶段文档就开始修改；
- 把下游阻断项误判成当前阶段不能开始；
- 一次修改大量无关文件；
- 用未来真实数据优化在线或动态决策；
- 只画图但没有标准事件日志和原始指标；
- 声称“更优”却没有运行实验；
- 文献缺少作者、出处或真实性核验；
- 强行加入未批准的算法或工具；
- 使用个人绝对路径；
- 覆盖原始 Word 或 raw 数据；
- 测试失败却声称完成。

停止语句：

```text
请暂停，不要继续修改。重新读取 AGENTS.md、PROJECT_STATUS.md 和当前 ExecPlan。
区分 current_stage_blockers 与 downstream_blockers，
列出越界内容并恢复到当前阶段允许的最小范围。
先报告，不要继续实施。
```

## 9. 阶段结束审查

发送：

```text
请以严格代码审查者、运筹建模审查者和科研复现审查者的身份检查当前未提交修改。
重点寻找：未来信息泄漏、约束遗漏、指标错误、伪造数据、静默降级、
基线不公平、Windows 路径问题、未运行测试、文档与代码不一致。
先报告问题，按严重程度排序，并给出文件和行号。
```

确认后再逐项修复。

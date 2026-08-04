# Git 工作流

本项目使用简单分支，不采用复杂 Git Flow。

## 首次初始化

在解压后的项目根目录先检查：

```powershell
python scripts/validate_starter_package.py --initial
```

通过后执行：

```powershell
git init -b main
git add .
git commit -m "chore: initialize parking optimizer project"
git switch -c stage-a-research
```

初始化后更新 `PROJECT_STATUS.md` 中的：

```yaml
git_initialized: true
current_branch: stage-a-research
```

随后运行：

```powershell
python scripts/validate_starter_package.py
```

默认检查只读；不要在每次检查时使用 `--write-report`。

## 分支

- `main`：只放已通过验收的稳定内容；
- `stage-a-research`：阶段 A；
- `stage-b-model`：阶段 B；
- `feature/<功能名>`：阶段 C/D 的独立功能；
- `fix/<问题名>`：已确认缺陷修复。

若以后配置了远程仓库，应先确认当前分支已设置上游，再按需要执行拉取；刚初始化且没有远程仓库时不要执行 `git pull`。

## 里程碑提交

```powershell
git status
git diff
git add .
git commit -m "docs: complete stage A literature matrix"
```

阶段验收通过后，再合并到 `main` 并打标签。

## 规则

- 不在 `main` 上做大规模实验性修改；
- 不让两个 Codex 对话同时编辑同一分支或同一文件；
- 删除、重命名、公共接口变更和大规模重构前先提交恢复点；
- `PROJECT_STATUS.md` 只有主线程或用户指定协调线程可以提交；
- `.env`、密钥、真实原始数据和运行产物不得提交；
- 合并前必须完成当前阶段验收并更新状态文件；
- 合并冲突不得由 Codex 猜测处理，涉及模型或数据含义时先询问用户。

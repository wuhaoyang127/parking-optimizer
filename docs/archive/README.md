# 过期文档归档规则

本目录只存放已被新版本替代、但因研究追溯需要保留的文档。

归档前必须在文件顶部加入：

```yaml
status: superseded
superseded_by: <新权威文件路径>
superseded_date: YYYY-MM-DD
reason: <简要理由>
```

规则：

- `PROJECT_STATUS.md` 和当前 ExecPlan 不得引用已过期文档；
- 新 Codex 对话默认不读取本目录；
- 过期文档不得继续作为数学、数据、实验或接口的权威来源；
- 不用归档代替 Git 历史；只有仍有研究追溯价值的旧文档才保留。

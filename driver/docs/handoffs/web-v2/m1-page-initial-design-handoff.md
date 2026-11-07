---
milestone: M1
status: approved
approved_date: 2026-08-12
approved_by: user
visual_direction: C_fusion
prototype_commit: cadca2b
next_milestone: M2
---

# Web v2 M1 页面初步设计交接

## 验收结论

用户已通过 M1 页面初步设计。当前冻结的是电脑/手机、车主/答辩双模式的页面结构、主要流程、状态文案和首版功能边界，不冻结后端算法、数据契约、并发、安全或部署实现。

## 已批准决定

- 采用 C 融合视觉方向；
- 车主模式使用明亮、地图优先的城市出行结构；
- 答辩模式使用深色科研驾驶舱和克制的动态语言；
- 车主端隐藏算法研究信息；
- 答辩端如实区分“在线规则 M2 待实现”和其他“待接入”算法；
- 纵深车位、普通位备选、30 秒软锁、路线与纵深移位演示保留；
- 电脑和手机保持同一核心功能范围。

## 关键文件

- 原型入口：`prototypes/web-v2/index.html`
- 样式：`prototypes/web-v2/styles.css`
- 交互：`prototypes/web-v2/app.js`
- 运行说明：`prototypes/web-v2/README.md`
- 视觉评审：`docs/design/web-v2/m1-visual-review.md`
- 原型评审：`docs/design/web-v2/m1-prototype-review.md`
- 自动化验证：`scripts/verify_web_v2_prototype.cjs`
- M1 原型实现提交：`cadca2b`

## 实际验证

- Node.js 语法检查：`app.js` 与验证脚本通过；
- Edge Chromium 本地 `file://` 加载与 DOM 输出：通过；
- Playwright + Edge：11 项交互和布局断言通过；
- 390 × 844 手机视口无横向溢出；
- 四张 PNG 可读：桌面 1440 × 1100，手机 390 × 844；
- `git diff --check`：通过。

## 已处理失败案例

- 修复截图命令错误解释 URL 参数导致的 502 错误页；
- 修复截图发生在入场动画中导致的透明度异常；
- 修复答辩截图未正确切换模式；
- 修复 390px 答辩页运行按钮裁切风险。

## 限制

- 当前是零依赖高保真原型，不是正式 React 网站；
- 不调用 FastAPI、真实算法、真实地图或真实数据；
- 软锁、预留和答辩口令均为前端原型交互，不能证明服务端一致性与安全性；
- 页面指标是 synthetic 视觉样例，不是正式实验结果；
- 响应式手机验证不替代 M6 的真实 Safari/iPhone 验收。

## 恢复方式

- M1 实现恢复点：`cadca2b`；
- M1 验收后使用 annotated tag `web-v2-m1-approved`；
- 旧 Streamlit 与 v1 研究资产未修改，可独立恢复。

## 下一阶段条件

M2 尚未开始，也未获得实施授权。只有用户明确授权 M2 后，才建立新的 M2 ExecPlan 和分支，冻结 v2 契约、只读适配器、`OnlineRuleServiceV2` 排序口径及 FastAPI 基础。

# M5 高级模式（车主端登录后扩展）ExecPlan

状态：2026-11-08 用户授权启动（登录方式 B = Supabase 账号密码，与研究端一致；"返回研究端"指向 research 主 app）。

## 目标

车主端（React）加登录入口；登录成功后从"车主模式"切换为"高级模式"，显示四类内容：
1. 算法/研究信息（算法名、版本、参数、执行回执、降级原因）；
2. 试用状态（当前激活算法、试用中版本、比例、试用统计）；
3. 实验对比（同布局同状态多算法指标对比）；
4. 数据与布局（布局/状态/需求导入、场景编辑）。

其余内容后续按需补充。

## 边界与非目标

- 不改变车主模式默认行为（隐藏算法名/参数/权重）；
- 高级模式与车主模式共享停车场 ID 与已发布只读布局；软锁/预留/占用按会话隔离；
- 不实现 PDF 报告、伪 3D、批量评估（留待后续）；
- 登录复用研究端 Supabase `login_user`/`validate_session` RPC，不新建用户体系。

## 阶段与恢复点

### P1 登录认证后端
- driver 新增 `src/parking_opt/api/auth_supabase.py`（≤200 行）：从环境变量读 `SUPABASE_URL`/`SUPABASE_ANON_KEY`，用标准库 `urllib` 直调 Supabase REST RPC（`login_user`/`validate_session`），不新增第三方依赖。
- 新增端点 `POST /api/v2/auth/login`（返回 `{success, username, role, token}`）、`GET /api/v2/auth/session`（校验 token）。
- 测试：`tests/web_v2/test_advanced_auth.py`（登录成功/失败/缺配置 503/会话校验）。

### P2 前端登录入口 + 高级模式切换
- `App.tsx` 顶栏加「登录」按钮与登录表单；登录成功存 token 到内存态并切换高级模式。
- 新增高级模式导航与骨架页；未登录访问高级路由时回退车主模式。
- 前端测试：登录表单渲染、成功切换、退出回退。

### P3 内容 1/2：算法信息 + 试用状态
- 复用后端已有 `/api/admin/v1/execution-receipts`、`/api/admin/v1/driver-algorithm-activations/active`、`/api/admin/v1/algorithms/current`（含 `trial_stats`）。
- 前端高级模式页展示算法名/版本/激活状态、试用中版本/比例/成功/降级统计、最近执行回执。

### P4 内容 3：实验对比
- 后端新增 `POST /api/v2/advanced/compare`：同布局同状态，对已注册算法（`online-rule-v2` + 已验证 research 发布）跑同种子仿真，返回同口径指标；随机方法记录 seed，失败保留。
- 前端对比表展示。

### P5 内容 4：数据与布局
- 后端新增布局/状态/需求导入与场景编辑端点（版本化、失败关闭，未知当空闲不成立的校验）。
- 前端导入/编辑界面。

## 验证

每阶段：`py scripts/check_file_lines.py`（≤200 行）+ `py -m pytest`（driver）+ `npm --prefix apps/web run test`（前端）+ 后端回归；关键恢复点单独提交并推送 `stage-d-deliver`。

## 剩余不确定项

- 实验对比（P4）的指标口径与预算需冻结后再实现；
- 数据布局（P5）的导入 Schema 与校验规则待定。

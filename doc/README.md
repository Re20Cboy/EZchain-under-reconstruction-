# EZchain Documentation Hub

本目录只保留高频入口。详细流程下沉到对应专题文档。

## Start Here
- 项目结构：`doc/PROJECT_STRUCTURE.md`
- 当前状态：`doc/PROJECT_CHECKPOINT_2026-03-20.md`
- 本地快速跑通 V2：`doc/EZchain-V2-quickstart.md`
- 安装与首次使用：`doc/INSTALLATION.md`

## By Role

### 终端用户
- 日常试用入口：`doc/USER_QUICKSTART.md`
- 正式测试网演练：`doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md`
- 常见错误码：`doc/API_ERROR_CODES.md`

### 开发者
- 提交前与 RC 测试：`doc/DEV_TESTING.md`
- V2 默认化判断：`doc/V2_DEFAULT_READINESS.md`
- 发布报告与 readiness 现在会单独展示共识 TCP 正式证据状态，不再把
  “consensus gate 已通过”和“TCP 正式证据已形成”混为一件事
- P2P 现状：`doc/EZ_P2P_Status.md`

### 发布与运维
- 发布检查清单：`doc/RELEASE_CHECKLIST.md`
- 运行与回滚：`doc/MVP_RUNBOOK.md`
- 外部试用记录模板：`doc/OFFICIAL_TESTNET_TRIAL_TEMPLATE.json`
- 发布记录：`doc/releases/`

## Key Topics
- V1 legacy / V2 分层：`doc/V1_LEGACY_STRUCTURE.md`
- V1 物理迁移计划：`doc/V1_PHYSICAL_MIGRATION_PLAN.md`
- 测试网拓扑：`doc/TESTNET_TOPOLOGY.md`
- 后续 MVP 收口计划：`doc/MVP_ROADMAP_NEXT.md`

## Default Flow
1. 用 `doc/EZchain-V2-quickstart.md` 跑通本地 V2。
2. 用 `doc/USER_QUICKSTART.md` 或 `doc/OFFICIAL_TESTNET_TRIAL_RUNBOOK.md` 走用户路径。
3. 提交前执行 `doc/DEV_TESTING.md`。
4. 发版前执行 `doc/RELEASE_CHECKLIST.md`。
5. 判断是否达到默认正式交付路径时，再看 `doc/V2_DEFAULT_READINESS.md`；
   当前要额外关注共识 TCP 证据是否真的已经形成。

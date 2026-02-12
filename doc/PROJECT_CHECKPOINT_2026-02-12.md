# EZchain Checkpoint (2026-02-12)

本检查点基于仓库当前可验证状态（代码、脚本、CI 门禁、文档）整理。

## 目标回顾
MVP 目标：交付“可对外试用”的桌面端版本（CLI 为主 + 简面板），支持本地托管钱包、官方测试网接入、基础安全门禁、可发布流程。

## 当前状态总览
- 总体阶段：`MVP 内测可用`（未进入主网发布）。
- 当前基线：核心测试、交易链路测试、EZ_App 关键测试已纳入 CI。
- 发布能力：已具备 RC 生成、发布门禁、报告生成、回滚手册。

## 按 6 周计划映射（基于当前仓库）
1. 第 1 周（基线修复与发布闸门）：`已完成`
- 测试入口与回归问题已修复。
- `run_ezchain_tests.py` + `scripts/release_gate.py` + CI 已形成阻断链路。

2. 第 2 周（钱包核心与本地存储）：`已完成`
- `EZ_App` 已提供钱包创建/导入/展示、余额与历史。
- 本地存储与恢复脚本可用（`ops_backup.py` / `ops_restore.py`）。

3. 第 3 周（本地轻节点与服务 API）：`已完成`
- 已实现本地节点生命周期与健康探测。
- 已实现 `/health`、`/wallet/*`、`/tx/send`、`/tx/history`、`/metrics` 等最小 API。

4. 第 4 周（测试网接入与简单面板）：`大体完成`
- `official-testnet` profile 已落地，且新增官方模板配置导出脚本。
- 已具备安装与打包脚本（macOS/Windows）。
- 简面板为本地 UI 基础能力，CLI 仍为主入口。

5. 第 5 周（稳定性与安全门禁）：`进行中`
- 已完成威胁模型文档门禁与关键输入校验。
- 已具备稳定性 smoke/gate 脚本。
- 待补强：更完整的长稳场景覆盖、更多异常网络路径的自动化验证。

6. 第 6 周（发布准备与灰度）：`部分完成`
- RC 工具链已具备（`prepare_rc.py` / `rc_gate.py` / `release_candidate.py` / `release_report.py`）。
- 待补强：小流量灰度流程与观测数据沉淀模板。

## 关键能力清单（当前已具备）
- CLI：`wallet/*`、`tx send`、`node start/status/stop`、`network info/check/set-profile`。
- 本地 API：鉴权、nonce、防重放字段校验、错误码规范。
- Profile 体系：`local-dev` / `official-testnet` 模板化配置。
- 安全与发布门禁：`security_gate`、`release_gate`、`testnet_profile_gate`。
- 发布资产：安装脚本、打包脚本、发布清单、运行手册、回滚步骤。

## 未完成项与风险
- P2P 业务消息覆盖仍不完整（详见 `doc/EZ_P2P_Status.md`）。
- 开放式生产级网络准入策略未纳入 MVP。
- 72 小时巡检可按团队策略裁剪，但建议保留轻量指标复盘。

## 下一步优先级（建议）
1. 稳定性补强：将“网络抖动/重复消息/节点重启恢复”长稳场景纳入固定 gate。
2. 测试网演练：按官方 profile 进行安装到转账的外部用户闭环演练。
3. 发布收口：固化 RC 模板、已知风险模板、回滚演练记录格式。

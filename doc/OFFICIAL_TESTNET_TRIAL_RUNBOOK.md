# Official Testnet Trial Runbook

本手册用于一次完整的官方测试网外部试用演练。

目标不是做开发调试，而是验证非开发使用者是否能按文档完成：
- 安装或源码启动
- 配置官方测试网
- 创建或导入钱包
- 网络连通性检查
- faucet / send / history / receipts / balance 对账
- 填写并提交试用记录

## 1. 准备试用记录

建议先初始化一份记录文件：

```bash
python scripts/init_external_trial.py \
  --executor your_name \
  --os macos \
  --install-path source
```

默认会生成到：

```text
doc/trials/official-testnet-YYYYMMDD-01.json
```

后续每完成一项，就更新该 JSON 中对应字段。

推荐不要手工直接改 JSON，而是用：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step install \
  --step-status passed \
  --note "source install completed on macOS"
```

## 2. 安装或源码运行

源码运行：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

二进制安装：

- macOS: `bash scripts/build_macos.sh && bash scripts/install_macos.sh`
- Windows: `powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1` 后执行安装脚本

完成后将记录文件中的：

- `workflow.install`

更新为：

- `passed` 或 `failed`

可直接执行：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step install \
  --step-status passed
```

若失败，把原因写入：

- `issues`
- `notes`

## 3. 生成官方测试网配置

推荐在干净环境下直接生成：

```bash
python scripts/profile_config.py --profile official-testnet --out ezchain.yaml
```

检查配置：

```bash
python ezchain_cli.py network info
python ezchain_cli.py network check
```

若 `network check` 成功：

- `profile.connectivity_checked = true`
- `profile.connectivity_result = "passed"`
- `workflow.network_check = "passed"`

可直接执行：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step network_check \
  --step-status passed \
  --connectivity-checked true \
  --connectivity-result passed
```

若失败：

- `profile.connectivity_checked = true`
- `profile.connectivity_result = "failed"`
- `workflow.network_check = "failed"`

并把可见错误写入 `issues` / `notes`。

## 4. 创建或导入钱包

创建钱包：

```bash
python ezchain_cli.py wallet create --password your_password --name default
```

如需导入，则执行团队实际导入命令并记录方式。

完成后更新：

- `workflow.wallet_create_or_import`

例如：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step wallet_create_or_import \
  --step-status passed \
  --note "created wallet default and confirmed address output"
```

同时在 `notes` 中记录：

- 创建或导入
- 钱包名称
- 是否成功看到地址/助记词提示

## 5. faucet 与余额检查

请求测试资金：

```bash
python ezchain_cli.py tx faucet --amount 1000 --password your_password
python ezchain_cli.py wallet balance --password your_password
```

如果 faucet 或余额查询失败：

- `workflow.faucet = "failed"`

如果成功：

- `workflow.faucet = "passed"`

例如：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step faucet \
  --step-status passed \
  --note "faucet 1000 confirmed by wallet balance"
```

建议在 `notes` 里记录：

- faucet 金额
- 余额查询结果

## 6. 发送交易并检查状态

执行一笔转账：

```bash
python ezchain_cli.py tx send --recipient 0xabc123 --amount 100 --password your_password
python ezchain_cli.py tx receipts --password your_password
python ezchain_cli.py wallet show
```

若发送失败：

- `workflow.send = "failed"`

若发送成功，再检查：

- receipt 是否出现
- history 是否出现
- balance 是否与预期一致

全部一致时：

- `workflow.send = "passed"`
- `workflow.history_receipts_balance_match = "passed"`

例如：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step send \
  --step-status passed \
  --note "send completed with receipt visible"

python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step history_receipts_balance_match \
  --step-status passed \
  --note "history receipts and balance all matched expected values"
```

若发送成功但对账不一致：

- `workflow.send = "passed"`
- `workflow.history_receipts_balance_match = "failed"`

并在 `issues` / `notes` 中记录偏差。

## 7. 收尾并校验记录

完成所有步骤后，把试用记录顶层状态更新为：

- 全部通过：`status = "passed"`
- 有失败：`status = "failed"`

例如：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --status passed \
  --clear-default-notes
```

然后执行校验：

```bash
python scripts/external_trial_gate.py --record doc/trials/official-testnet-YYYYMMDD-01.json --require-passed
```

如果该命令失败，这份记录不能作为 RC 证据。

## 8. 接入发布报告

将真实试用记录接入发布报告：

```bash
python scripts/release_report.py \
  --run-gates \
  --with-stability \
  --allow-bind-restricted-skip \
  --require-official-testnet \
  --official-config ezchain.yaml \
  --official-check-connectivity \
  --external-trial-record doc/trials/official-testnet-YYYYMMDD-01.json
```

RC 流程：

```bash
python scripts/release_candidate.py \
  --version v0.1.0-rc1 \
  --with-stability \
  --allow-bind-restricted-skip \
  --require-official-testnet \
  --official-config ezchain.yaml \
  --official-check-connectivity \
  --external-trial-record doc/trials/official-testnet-YYYYMMDD-01.json
```

## 9. 最低通过标准

一份可用于 RC 的试用记录，至少要满足：

- `profile.name = "official-testnet"`
- `profile.connectivity_checked = true`
- `profile.connectivity_result = "passed"`
- `workflow.install = "passed"`
- `workflow.wallet_create_or_import = "passed"`
- `workflow.network_check = "passed"`
- `workflow.faucet = "passed"`
- `workflow.send = "passed"`
- `workflow.history_receipts_balance_match = "passed"`
- `status = "passed"`

否则只能作为失败样本或问题记录，不能作为发布证据。

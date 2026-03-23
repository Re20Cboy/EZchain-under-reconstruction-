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
  --install-path source \
  --network-environment real-external
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
  --auto-status \
  --note "source install completed on macOS"
```

原因很简单：

- 这份记录后面会被脚本校验
- 顶层状态、每一步状态、连通性结果、系统类型这些字段如果填乱了，记录会直接失效
- 用脚本更新比手改 JSON 更不容易出错

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
  --step-status passed \
  --auto-status
```

若失败，把原因写入：

- `issues`
- `notes`

## 3. 生成官方测试网配置

推荐在干净环境下直接生成：

```bash
python scripts/profile_config.py --profile official-testnet --out ezchain.yaml
```

如果你手头没有第二台机器，只有一台 Mac，也可以先走“单机伪远端”替代路径：

```bash
python scripts/single_host_testnet_config.py --out ezchain.yaml
python run_ez_v2_tcp_consensus.py \
  --root-dir .ezchain_remote_consensus \
  --state-file .ezchain_remote_consensus/state.json \
  --chain-id 1 \
  --endpoint 0.0.0.0:19500
python ezchain_cli.py --config ezchain.yaml node start --mode v2-account
python ezchain_cli.py --config ezchain.yaml node account-status
```

如果你用的是这条单机替代路径，初始化试用记录时要明确写成：

```bash
python scripts/init_external_trial.py \
  --executor your_name \
  --os macos \
  --install-path source \
  --network-environment single-host-rehearsal
```

这条替代路径会自动把配置里的 `bootstrap_nodes` 改成你这台机器的局域网 IP，
同时固定 `protocol_version: "v2"`。它适合先验证：

- 端口是否真的监听成功
- 本机是否能通过局域网 IP 连到这个节点
- `official-testnet` profile 是否写对
- `v2-account` 是否能接上共识节点并报出同步状态

建议顺序：

1. 先 `wallet create` 或 `wallet import`
2. 再启动 `node start --mode v2-account`

这样账户节点会优先复用当前钱包的 V2 地址，不会再额外生成一套独立地址。
如果钱包文件存在，它现在也会优先复用对应的
`wallet_state_v2/<address>/wallet_v2.db`，减少 CLI 和账户节点各写各的状态。

但要注意：

- 这只能证明“单机模拟远端”是通的
- 还不能替代真正两台机器或公网环境的最终确认
- 这类记录现在只算 `single-host-rehearsal`，不能当成 release/readiness 的最终外部证明
- 仅凭这一步，不建议把 `workflow.send` 或 `workflow.history_receipts_balance_match` 直接记成正式通过

检查配置：

```bash
python ezchain_cli.py network info
python ezchain_cli.py network check
python scripts/testnet_profile_gate.py --config ezchain.yaml --check-connectivity
```

如果这是单机伪远端或真实远端 profile，`network info` 现在会更直白地告诉你两件事：

- 当前模式是 `official-testnet`
- `tx_path_ready` 还是 `false`

这表示：

- 网络连通性检查已经在走远端 profile
- 但完整远端交易路径还没有全部接完

现在 CLI 和 service 在这种情况下会直接拦下不该走本地路径的交易动作，
避免你误把本地结果当成远端测试网结果。

- `tx faucet` 这类当前明确不支持的动作，会返回 `tx_action_unsupported`
- `tx send` 如果缺少远端账户节点、缺少 `recipient_endpoint`，或远端状态不完整，
  会返回更具体的错误码，而不是一律压成 `tx_path_not_ready`

不过，如果 `v2-account` 已经在跑，而且它复用了当前钱包对应的
`wallet_state_v2/<address>/wallet_v2.db`，下面这些只读查询现在已经可以先用：

- `wallet balance`
- `wallet checkpoints`
- `tx pending`
- `tx receipts`
- `tx history`

另外，`tx send` 现在也开放了一条最小可用路，但条件必须满足：

- `v2-account` 已经在运行
- 你明确知道收款方账户节点地址，或者已经提前把它记进本地地址簿
- 如果没有保存过，就在命令里显式传入 `--recipient-endpoint`

示例：

```bash
python ezchain_cli.py contacts set \
  --address 0xabc123 \
  --endpoint 192.168.1.20:19500

python ezchain_cli.py tx send \
  --recipient 0xabc123 \
  --amount 100 \
  --password your_password
```

如果你既拿不到收款方账户节点地址，也没有保存过它，那这一步就先不要记成通过。

如果对方已经跑着 `v2-account`，建议直接让对方导出联系卡，再导入本地地址簿：

```bash
python ezchain_cli.py contacts export-self --out bob-contact.json
python ezchain_cli.py contacts import-card --file bob-contact.json
```

这样试用记录里也更容易留下明确证据：你导入的到底是哪一个地址、哪一个端点。

如果对方已经开了服务，也可以直接从服务地址抓联系卡：

```bash
python ezchain_cli.py contacts fetch-card \
  --url http://192.168.1.20:8787 \
  --out bob-contact.json \
  --import-to-contacts
```

为了避免试用时搞混本地已经记住了哪些收款节点，现在也可以直接查：

- `GET /contacts`
- `GET /contacts/<address>`

如果你想在终端里核对，也可以直接用：

- `python ezchain_cli.py contacts list`
- `python ezchain_cli.py contacts show --address 0xabc123`

建议把这部分也直接写进试用记录：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --contact-card-file bob-contact.json \
  --contact-card-imported true \
  --contact-card-used-for-send true \
  --auto-status
```

这样记录里会留下一个单独的 `evidence.contact_card` 证据块，后面的发布报告也能直接读出来。

现在试用记录模板里还会保留 `evidence.tx_send_readiness`。这块不是手工填写用的，主要由 `official_testnet_send_rehearsal.py` 自动写入，记录当时远端 send path 是否 ready、有哪些 blocker。

如果你想把“导入联系卡 + 发交易 + 更新试用记录”一次做完，现在也可以直接用收尾脚本：

```bash
python scripts/official_testnet_send_rehearsal.py \
  --config ezchain.yaml \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --password your_password \
  --contact-card-file bob-contact.json \
  --amount 100 \
  --client-tx-id cid-trial-send-001
```

这条命令会自动做三件事：

- 把联系卡导入本地地址簿
- 用这张联系卡发起一次远端发送
- 把发送结果和联系卡证据写回试用记录

脚本输出里现在还会带 `tx_send_readiness`。如果远端 `v2-account` 没在运行，或者缺少 `consensus_endpoint`、`wallet_db_path`，脚本会先把这些 blocker 暴露出来，不会盲目调用发送。

如果 preflight 没通过，试用记录里的 `workflow.send` 会被标记为 `failed`，同时写入类似 `send_preflight_failed:remote_account_not_running` 的 issue，方便后续汇总和发布报告直接识别。

它们会直接读共享的 V2 钱包库，不再走本地假结果。

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
  --auto-status \
  --connectivity-checked true \
  --connectivity-result passed
```

若失败：

- `profile.connectivity_checked = true`
- `profile.connectivity_result = "failed"`
- `workflow.network_check = "failed"`

并把可见错误写入 `issues` / `notes`。

如果你走的是上面的“单机伪远端”替代路径，建议：

- `workflow.install` 和 `workflow.network_check` 可以照实记录
- 在 `notes` 里明确写明这是单机演练，不是真两机环境
- `workflow.faucet`、`workflow.send`、`workflow.history_receipts_balance_match` 先保持 `pending`
- 等后面有真实可达环境，再补完整试用记录

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
  --auto-status \
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
  --auto-status \
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
  --auto-status \
  --note "send completed with receipt visible"

python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --step history_receipts_balance_match \
  --step-status passed \
  --auto-status \
  --note "history receipts and balance all matched expected values"
```

若发送成功但对账不一致：

- `workflow.send = "passed"`
- `workflow.history_receipts_balance_match = "failed"`

并在 `issues` / `notes` 中记录偏差。

## 7. 收尾并校验记录

完成所有步骤后，可以让脚本自动判断顶层状态：

- 全部通过会自动变成 `passed`
- 只要有一步失败会自动变成 `failed`
- 其他情况保持 `pending`

例如：

```bash
python scripts/update_external_trial.py \
  --record doc/trials/official-testnet-YYYYMMDD-01.json \
  --auto-status \
  --clear-default-notes
```

这条命令还会顺手输出：

- 当前顶层状态
- 建议状态
- 还没完成的步骤列表

然后执行校验：

```bash
python scripts/external_trial_gate.py --record doc/trials/official-testnet-YYYYMMDD-01.json --require-passed
```

如果该命令失败，这份记录不能作为 RC 证据。

常见会导致失败的情况包括：

- `executed_at` 不是合法时间格式
- `environment.os` 不是 `macos` 或 `windows`
- `environment.install_path` 不是 `source` 或 `binary`
- 顶层 `status = "passed"`，但某一步还是 `pending` 或 `failed`
- `profile.connectivity_checked` 没有记成 `true`
- `profile.connectivity_result` 不是 `passed`

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

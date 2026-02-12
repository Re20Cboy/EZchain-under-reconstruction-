# User Quickstart (MVP)

本指南面向终端试用用户，目标是在本地快速完成钱包创建、收款、转账、查询。

## 1. 安装
优先参考：`doc/INSTALLATION.md`

最简流程（源码运行）：
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 生成配置并切换官方测试网
推荐直接生成官方 profile：
```bash
python scripts/profile_config.py --profile official-testnet --out ezchain.yaml
```

查看网络信息：
```bash
python ezchain_cli.py network info
python ezchain_cli.py network check
```

## 3. 创建钱包
```bash
python ezchain_cli.py wallet create --password your_password --name default
```

说明：输出中会包含助记词，请离线安全保存。

## 4. 领取测试资金并转账
先领取测试资金：
```bash
python ezchain_cli.py tx faucet --amount 1000 --password your_password
```

查看余额：
```bash
python ezchain_cli.py wallet balance --password your_password
```

发起转账：
```bash
python ezchain_cli.py tx send --recipient 0xabc123 --amount 100 --password your_password
```

查看历史：
```bash
python ezchain_cli.py wallet show
```

## 5. 启动本地服务（可选）
```bash
python ezchain_cli.py serve
```

查看 API token：
```bash
python ezchain_cli.py auth show-token
```

如果本机支持浏览器访问：
```bash
open http://127.0.0.1:8787/ui
```

## 6. 升级前备份（强烈建议）
```bash
python scripts/ops_backup.py --config ezchain.yaml --out-dir backups --label pre-upgrade
```

回滚恢复：
```bash
python scripts/ops_restore.py --backup-dir backups/<snapshot-dir> --config ezchain.yaml --force
```

## 常见问题
1. `network check` 不通：检查网络、DNS、代理策略；可先切回 `local-dev` 验证本地能力。
2. `tx send` 报参数错误：按 `doc/API_ERROR_CODES.md` 对照字段修复。
3. 忘记备份：先停止服务，再手动备份 `ezchain.yaml` 和数据目录后再升级。

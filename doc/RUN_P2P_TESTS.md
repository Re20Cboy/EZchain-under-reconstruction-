# EZchain 分布式 P2P 集成测试与一键网络启动指南

## 环境准备

- Python: 建议 3.10+
- 依赖：使用 `requirements.txt` 安装
- 端口：本地回环 `127.0.0.1`，TCP 端口需可用（默认从 `19500` 起）

## 安装依赖

macOS/Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows（PowerShell）：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行分布式 P2P 集成测试（一次性）

命令：

```bash
pytest -q EZ_Test/test_p2p_blockchain_integration_distributed.py
```

完成的流程：

- 启动 1 个共识/矿工进程 + 4 个账户进程（默认）
- 控制端通过 P2P 下发创世 VPB、触发真实交易提交、打包出块、广播区块、下发证明、发送/验证/接收 VPB

结束方式：

- 测试自动退出；失败时查看控制台错误信息

## 运行一键网络（持续运行）

基本命令：

```bash
python run_ez_p2p_network.py --consensus 1 --accounts 4 --max-neighbors 16 --start-port 19500
```

完成的流程：

- 从 `--start-port` 连续分配端口：共识节点 N 个端口 + 账户 M 个端口 + 控制器 1 个端口
- 通过 P2P 下发创世 VPB
- 周期性触发交易波（创建+提交），共识节点从 TxPool 打包新区块并广播播发，发送者/接收者完成 VPB 更新和验证

结束方式：

- 按 Ctrl+C 终止全部进程

## 启动参数（run_ez_p2p_network.py）

- `--consensus`: 共识节点数（默认 1）
- `--accounts`: 账户节点数（默认 4）
- `--max-neighbors`: 每节点最大邻居数（默认 16）
- `--host`: 监听地址（默认 `127.0.0.1`）
- `--start-port`: 起始端口（默认 19500）
- `--interval`: 交易波间隔秒数（默认 3.0）
- `--tx-burst`: 每波每个发送者的交易数量（默认 2）

## 目录与数据

- 临时数据：自动创建在 `temp_test_data/<test_name>/session_*`（由 `TempDataManager` 管理）
- 区块链数据、交易池 DB、账户存储均在会话目录下的子目录隔离，测试结束自动清理

## 期望输出

- 控制台会显示节点启动日志、交易提交、出块广播、VPB 传输/验证等关键信息（日志量已做精简）
- 正常情况下，未抛出异常且进程按 Ctrl+C 或测试结束时退出，即为通过

## 常见问题

- 端口占用：修改 `--start-port`，确保连续端口区间足够（共识 N + 账户 M + 1 控制器）
- macOS 防火墙弹窗：允许本地进程接收连接
- Windows 提示：如直接在交互式环境运行一键网络，建议在命令行（cmd/PowerShell）中执行；pytest 测试建议在类 Unix 环境运行以避免多进程事件循环差异

## 快速示例

- 只跑一次性分布式集成测试：

```bash
pytest -q EZ_Test/test_p2p_blockchain_integration_distributed.py
```

- 启动一个 1 共识 + 6 账户的本地网络：

```bash
python run_ez_p2p_network.py --consensus 1 --accounts 6 --start-port 19600 --interval 2.0
```


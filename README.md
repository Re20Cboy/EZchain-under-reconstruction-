# EZchain: A Scale-out Decentralized Blockchain for Web3.0 Inclusivity  
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)  


## 🌟 Our Vision  
At EZchain, we stand firm on the **core principles of decentralization**—the bedrock of Web3. Our mission is to break down barriers that exclude edge devices (mobile phones, IoT gadgets, agents, etc.) from full Web3 participation:  
- No more prohibitive transaction fees for basic wallet usage.  
- No reliance on top-tier consensus nodes or miner cartels—instead, a **self-governing ecosystem** where most participants contribute to network health.  
- Revive the early Bitcoin spirit: enable full-node operation on **consumer-grade hardware** (ordinary laptops, smartphones) with minimal bandwidth and storage demands.  

We believe Web3 should be accessible to *everyone*, not just those with specialized resources. EZchain is built to make this a reality—without compromising on performance, security, or scalability.


## 🚀 What is EZchain?  
EZchain is a novel Layer-1+2 decentralized ledger system designed explicitly for Web3.0. Unlike Layer-2/off-chain solutions that trade security for speed, or sharded blockchains that complicate cross-chain trust, EZchain achieves **scale-out performance** while preserving strict decentralization and security.  

Key innovations powering EZchain:  
1. **Value-Centric Data Structure**: Replaces traditional UTXO/account models with a unique "value" structure (integer sets) to eliminate redundant transaction history tracking.  
2. **Lightweight On-Chain Data**: Blocks are fixed at ~1 MB but theoretically hold *unlimited transactions* via Merkle Tree Roots and Bloom Filters.  
3. **P2P Transaction Verification**: Shifts validation work from consensus nodes to account nodes (end users), reducing network bottlenecks and enabling edge-device participation.  


## ⚡ Core Advantages  
| Feature                  | EZchain Performance                                                                 |
|--------------------------|-------------------------------------------------------------------------------------|
| **Throughput**           | 10,000+ TPS (surpasses bandwidth limits for "scale-out"; far exceeds traditional Layer-1) |
| **Transaction Latency**  | ~10 seconds (meets consumer app needs for mobile/Web3 payments)                     |
| **Hardware Compatibility**| Runs on consumer-grade devices (no need for enterprise servers/mining rigs)         |
| **Cost Efficiency**      | Near-constant storage/bandwidth costs (no infinite growth with transaction volume)  |
| **Security**             | Tolerates up to 1/3 (BFT) or 1/2 (PoW) Byzantine nodes; main-chain consensus integrity preserved |


## 📊 Simulation Progress  
We have completed a full prototype simulation (Python-based) verifying EZchain’s core claims:  
- System throughput exceeds 10,000 TPS with 5 Mb/s bandwidth.  
- Account node storage converges to a fixed value (no unbounded expansion).
- Edge-side nodes can go online or offline freely, conduct transaction verification independently, and submit proofs, with transaction security being fully tied to the main chain.

The simulator code is available at: [github.com/Re20Cboy/Ezchain-py](https://github.com/Re20Cboy/Ezchain-py)  


## 🛠️ Current Work  
We are now **rebuilding and optimizing the codebase** for an official open-source release. This includes:  
- Refactoring for production-grade stability.  
- Enhancing edge-device compatibility (mobile/IoT).  
- Integrating flexible consensus plugins (PoW, BFT, PoS, DPoS).  

## 🧪 P2P One-Click Smoke Test
Run a quick end-to-end P2P smoke test locally:

```bash
python run_ez_p2p_smoke_test.py
```

Common options:

```bash
python run_ez_p2p_smoke_test.py --waves 5 --interval 1.0 --accounts 6 --consensus 2
```

## 🧰 EZ App (CLI + Local API)
An initial product layer now exists under `EZ_App/` with:
- Wallet create/import/show
- Local node lifecycle (`start/status/stop`)
- Local loopback API (`/health`, `/metrics`, `/wallet/*`, `/tx/send`, `/tx/history`, `/node/*`, `/network/info`)

Quick start:

```bash
python ezchain_cli.py wallet create --password your_password --name default
python ezchain_cli.py tx faucet --amount 1000 --password your_password
python ezchain_cli.py wallet balance --password your_password
python ezchain_cli.py tx send --recipient 0xabc123 --amount 100 --password your_password
python ezchain_cli.py wallet show
python ezchain_cli.py node start --consensus 1 --accounts 1 --start-port 19500
python ezchain_cli.py network info
python ezchain_cli.py network check
python ezchain_cli.py network list-profiles
python ezchain_cli.py network set-profile --name official-testnet
python ezchain_cli.py config migrate
```

Start local API server:

```bash
python ezchain_cli.py serve
```

Show local API token:

```bash
python ezchain_cli.py auth show-token
```

Use this token in API calls via header `X-EZ-Token`.
For balance endpoint, also pass wallet password in header `X-EZ-Password`.
For transaction send endpoint, pass anti-replay header `X-EZ-Nonce` and unique body field `client_tx_id`.

Open simple local panel:

```bash
open http://127.0.0.1:8787/ui
```

Default config file: `ezchain.yaml`

Security and release gates:

```bash
python scripts/security_gate.py
python scripts/release_gate.py --skip-slow
python scripts/stability_smoke.py --cycles 20 --interval 1
python scripts/metrics_probe.py --url http://127.0.0.1:8787/metrics
bash scripts/build_macos.sh
# Windows: powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

Additional docs:
- Installation: `doc/INSTALLATION.md`
- API errors: `doc/API_ERROR_CODES.md`
- Runbook: `doc/MVP_RUNBOOK.md`
- Release checklist: `doc/RELEASE_CHECKLIST.md`


## 🤝 How to Support  
EZchain is a community-driven project—your help accelerates our mission:  
1. **Contribute Code**: Join us in refining the core protocol, optimizing edge-device support, or building developer tools. Open issues/PRs on our GitHub once the open-source repo launches!  
2. **Donate a Coffee**: Every bit helps fund development. You can send support to our wallet address:  
    0xec1e068969f9197f46a478ccbb7692dab7dd8428 (ETH)
    bc1pkl7c6l2jppjumt9yyvugs8zl40mwvd0qdh7smamy48e0yhz6v9kqts6wcv (BTC)
    BM3t5W8gA3yBBuZDVEAVfz9VLYPYbn3mBfJu6kXhyPGz (SOL)
3. **Spread the Word**: Share EZchain’s vision with Web3 communities—decentralization thrives on visibility!  


## 📄 Learn More  
- Read the full whitepaper: [EZchain: A Scale-out Decentralized Blockchain Ledger System for Web3.0](https://arxiv.org/abs/2312.00281v1)  
- Prototype simulation: https://github.com/Re20Cboy/Ezchain-py


*"Web3 is for everyone—EZchain makes it possible."*

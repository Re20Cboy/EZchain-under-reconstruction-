# EZchain MVP Installation (macOS/Windows)

## 1. Prerequisites
- Python 3.10+
- pip
- Optional: `pyinstaller` for single-file binary build

## 2. Build from source
macOS:

```bash
bash scripts/build_macos.sh
bash scripts/install_macos.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_windows.ps1
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

## 3. Artifact output
- If PyInstaller is available: `dist/ezchain-cli` (or `.exe` on Windows)
- Fallback package: `dist/ezchain-<target>-python-runner/`

## 4. First run
Using binary:

```bash
./dist/ezchain-cli network info
./dist/ezchain-cli wallet create --password your_password --name default
./dist/ezchain-cli auth show-token
./dist/ezchain-cli serve
```

Using python-runner package:

```bash
cd dist/ezchain-macos-python-runner
python ezchain_cli.py wallet create --password your_password --name default
python ezchain_cli.py serve
```

## 5. Testnet profile
Switch to hosted testnet profile:

```bash
python ezchain_cli.py network set-profile --name official-testnet
python ezchain_cli.py network info
```

Profile templates are versioned under `configs/`:
- `configs/ezchain.local-dev.yaml`
- `configs/ezchain.official-testnet.yaml`

Generate a fresh config from template on a clean machine:

```bash
python scripts/profile_config.py --profile official-testnet --out ezchain.yaml
```

## 6. Backup and Restore
Backup current config and local state:

```bash
python scripts/ops_backup.py --config ezchain.yaml --out-dir backups --label pre-upgrade
```

Restore from a backup snapshot:

```bash
python scripts/ops_restore.py --backup-dir backups/snapshot-YYYYMMDDTHHMMSSZ-pre-upgrade --config ezchain.yaml --force
```

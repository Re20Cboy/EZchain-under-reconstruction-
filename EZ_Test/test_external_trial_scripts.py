from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from EZ_App.runtime import TxResult
from EZ_App.wallet_store import WalletStore
from scripts.official_testnet_send_rehearsal import run_rehearsal
from scripts.external_trial_gate import trial_network_environment, validate_trial_record


def _base_record() -> dict:
    return {
        "trial_id": "official-testnet-20260321-01",
        "executed_at": "2026-03-21T00:00:00Z",
        "executor": "tester",
        "environment": {
            "os": "macos",
            "install_path": "source",
            "network_environment": "real-external",
            "config_path": "ezchain.yaml",
        },
        "profile": {
            "name": "official-testnet",
            "connectivity_checked": True,
            "connectivity_result": "passed",
        },
        "workflow": {
            "install": "passed",
            "wallet_create_or_import": "passed",
            "network_check": "passed",
            "faucet": "passed",
            "send": "passed",
            "history_receipts_balance_match": "passed",
        },
        "evidence": {
            "contact_card": {
                "path": "",
                "address": "",
                "endpoint": "",
                "imported": False,
                "used_for_send": False,
            }
        },
        "status": "passed",
        "issues": [],
        "notes": ["trial completed"],
    }


def test_validate_trial_record_accepts_complete_passed_record():
    failures = validate_trial_record(_base_record(), require_passed=True, require_real_external=True)
    assert failures == []


def test_validate_trial_record_rejects_bad_environment_and_timestamp():
    record = _base_record()
    record["executed_at"] = "not-a-time"
    record["environment"]["os"] = "linux"
    record["environment"]["install_path"] = "manual"
    record["environment"]["config_path"] = ""

    failures = validate_trial_record(record, require_passed=False)

    assert "executed_at must be a valid ISO-8601 timestamp" in failures
    assert "environment.os must be 'macos' or 'windows'" in failures
    assert "environment.install_path must be 'source' or 'binary'" in failures
    assert "environment.config_path must be a non-empty string" in failures


def test_validate_trial_record_rejects_passed_record_without_connectivity_evidence():
    record = _base_record()
    record["profile"]["connectivity_checked"] = False
    record["profile"]["connectivity_result"] = "pending"

    failures = validate_trial_record(record, require_passed=True)

    assert "profile.connectivity_checked must be true for a passed trial record" in failures
    assert "profile.connectivity_result must be 'passed' for a passed trial record" in failures


def test_validate_trial_record_rejects_unknown_workflow_status():
    record = _base_record()
    record["workflow"]["send"] = "done"

    failures = validate_trial_record(record, require_passed=False)

    assert "workflow.send must be one of pending/passed/failed" in failures


def test_update_external_trial_auto_status_and_remaining_steps():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        record_path = Path(td) / "trial.json"
        record_path.write_text(json.dumps(_base_record(), indent=2), encoding="utf-8")

        payload = json.loads(record_path.read_text(encoding="utf-8"))
        payload["status"] = "pending"
        payload["profile"]["connectivity_checked"] = False
        payload["profile"]["connectivity_result"] = "pending"
        payload["workflow"]["send"] = "pending"
        record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/update_external_trial.py",
                "--record",
                str(record_path),
                "--auto-status",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        output = json.loads(proc.stdout)
        assert output["status"] == "pending"
        assert output["suggested_status"] == "pending"
        assert output["network_environment"] == "real-external"
        assert "profile.connectivity_checked" in output["remaining_steps"]
        assert "profile.connectivity_result" in output["remaining_steps"]
        assert "workflow.send" in output["remaining_steps"]


def test_update_external_trial_auto_status_marks_failed_on_failed_step():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        record_path = Path(td) / "trial.json"
        payload = _base_record()
        payload["status"] = "pending"
        payload["workflow"]["faucet"] = "failed"
        record_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/update_external_trial.py",
                "--record",
                str(record_path),
                "--auto-status",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        output = json.loads(proc.stdout)
        assert output["status"] == "failed"
        assert output["suggested_status"] == "failed"


def test_validate_trial_record_rejects_contact_card_used_without_required_fields():
    record = _base_record()
    record["evidence"]["contact_card"]["used_for_send"] = True

    failures = validate_trial_record(record, require_passed=False)

    assert "evidence.contact_card.imported must be true when used_for_send is true" in failures
    assert "evidence.contact_card.address must be set when used_for_send is true" in failures
    assert "evidence.contact_card.endpoint must be set when used_for_send is true" in failures


def test_validate_trial_record_rejects_single_host_rehearsal_when_real_external_is_required():
    record = _base_record()
    record["environment"]["network_environment"] = "single-host-rehearsal"

    failures = validate_trial_record(record, require_passed=True, require_real_external=True)

    assert "environment.network_environment must be 'real-external' for a formal passed trial record" in failures
    assert trial_network_environment(record) == "single-host-rehearsal"


def test_update_external_trial_can_store_contact_card_evidence():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        record_path = Path(td) / "trial.json"
        record_path.write_text(json.dumps(_base_record(), indent=2), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/update_external_trial.py",
                "--record",
                str(record_path),
                "--network-environment",
                "single-host-rehearsal",
                "--contact-card-path",
                "bob-contact.json",
                "--contact-card-address",
                "0xb0b123",
                "--contact-card-endpoint",
                "192.168.1.20:19500",
                "--contact-card-imported",
                "true",
                "--contact-card-used-for-send",
                "true",
                "--auto-status",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        output = json.loads(proc.stdout)
        assert output["network_environment"] == "single-host-rehearsal"
        assert output["contact_card"]["path"] == "bob-contact.json"
        assert output["contact_card"]["address"] == "0xb0b123"
        assert output["contact_card"]["endpoint"] == "192.168.1.20:19500"
        assert output["contact_card"]["imported"] is True
        assert output["contact_card"]["used_for_send"] is True


def test_update_external_trial_can_load_contact_card_file():
    repo_root = Path(__file__).resolve().parent.parent

    with tempfile.TemporaryDirectory() as td:
        record_path = Path(td) / "trial.json"
        card_path = Path(td) / "bob-contact.json"
        record_path.write_text(json.dumps(_base_record(), indent=2), encoding="utf-8")
        card_path.write_text(
            json.dumps(
                {
                    "kind": "ezchain-contact-card/v1",
                    "address": "0xb0b123",
                    "endpoint": "192.168.1.20:19500",
                    "network": "official-testnet",
                    "mode_family": "v2-account",
                    "exported_at": "2026-03-21T00:00:00Z",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        proc = subprocess.run(
            [
                sys.executable,
                "scripts/update_external_trial.py",
                "--record",
                str(record_path),
                "--contact-card-file",
                str(card_path),
                "--contact-card-imported",
                "true",
                "--auto-status",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )

        output = json.loads(proc.stdout)
        assert output["contact_card"]["path"] == str(card_path)
        assert output["contact_card"]["address"] == "0xb0b123"
        assert output["contact_card"]["endpoint"] == "192.168.1.20:19500"
        assert output["contact_card"]["imported"] is True


def test_official_testnet_send_rehearsal_imports_contact_and_updates_trial_record():
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        cfg_path = tmp / "ezchain.yaml"
        data_dir = tmp / ".eztrial"
        record_path = tmp / "trial.json"
        card_path = tmp / "bob-contact.json"
        cfg_path.write_text(
            (
                "network:\n"
                '  name: "testnet"\n'
                '  bootstrap_nodes: ["192.168.1.9:19500"]\n'
                "app:\n"
                f"  data_dir: {data_dir}\n"
                f"  log_dir: {data_dir / 'logs'}\n"
                f"  api_token_file: {data_dir / 'api.token'}\n"
                "  api_port: 8787\n"
                '  protocol_version: "v2"\n'
            ),
            encoding="utf-8",
        )
        record_path.write_text(json.dumps(_base_record(), indent=2), encoding="utf-8")
        card_path.write_text(
            json.dumps(
                {
                    "kind": "ezchain-contact-card/v1",
                    "address": "0xb0b123",
                    "endpoint": "192.168.1.20:19500",
                    "network": "official-testnet",
                    "mode_family": "v2-account",
                    "exported_at": "2026-03-21T00:00:00Z",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        wallet_store = WalletStore(str(data_dir))
        wallet_store.create_wallet(password="pw123", name="demo")
        sender_address = wallet_store.summary(protocol_version="v2").address
        remote_state = {
            "status": "running",
            "mode": "v2-account",
            "mode_family": "v2-account",
            "roles": ["account"],
            "address": sender_address,
            "wallet_db_path": str(data_dir / "wallet_state_v2" / sender_address / "wallet_v2.db"),
            "consensus_endpoint": "192.168.1.9:19500",
        }
        send_result = TxResult(
            tx_hash="0xremotehash4",
            submit_hash="0xremotesubmit4",
            amount=35,
            recipient="0xb0b123",
            status="confirmed",
            client_tx_id="cid-trial-send-1",
            receipt_height=5,
            receipt_block_hash="55" * 32,
        )

        with mock.patch("scripts.official_testnet_send_rehearsal.NodeManager.account_status", return_value=remote_state):
            with mock.patch("scripts.official_testnet_send_rehearsal.TxEngine.send", return_value=send_result) as send_mock:
                result = run_rehearsal(
                    config_path=cfg_path,
                    record_path=record_path,
                    password="pw123",
                    contact_card_file=card_path,
                    amount=35,
                    client_tx_id="cid-trial-send-1",
                    note=["trial wrapper used"],
                )

        assert result["ok"] is True
        assert result["saved_contact"]["address"] == "0xb0b123"
        assert result["saved_contact"]["endpoint"] == "192.168.1.20:19500"
        assert result["tx"]["status"] == "confirmed"
        kwargs = send_mock.call_args.kwargs
        assert kwargs["recipient"] == "0xb0b123"
        assert kwargs["recipient_endpoint"] == "192.168.1.20:19500"

        updated_record = json.loads(record_path.read_text(encoding="utf-8"))
        assert updated_record["workflow"]["send"] == "passed"
        assert updated_record["evidence"]["contact_card"]["path"] == str(card_path)
        assert updated_record["evidence"]["contact_card"]["address"] == "0xb0b123"
        assert updated_record["evidence"]["contact_card"]["endpoint"] == "192.168.1.20:19500"
        assert updated_record["evidence"]["contact_card"]["imported"] is True
        assert updated_record["evidence"]["contact_card"]["used_for_send"] is True

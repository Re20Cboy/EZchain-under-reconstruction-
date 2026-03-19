from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_state_file(state_file: str, payload: dict[str, Any]) -> None:
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def read_state_file(state_file: str) -> dict[str, Any] | None:
    path = Path(state_file)
    if not path.exists():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def read_backend_metadata(root_dir: str) -> dict[str, Any] | None:
    store_path = Path(root_dir) / "consensus.sqlite3"
    if not store_path.exists():
        return None
    try:
        from .consensus_store import ConsensusStateStore

        store = ConsensusStateStore(str(store_path))
        try:
            metadata = store.load_metadata()
        finally:
            store.close()
    except Exception:
        return None
    if metadata is None:
        return None
    return {
        "chain_id": metadata.chain_id,
        "height": metadata.current_height,
        "current_block_hash": metadata.current_block_hash.hex(),
        "current_state_root": metadata.current_state_root.hex(),
        "receipt_cache_blocks": metadata.receipt_cache_blocks,
    }

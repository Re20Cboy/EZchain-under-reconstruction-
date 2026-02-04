from typing import Any, Dict


def block_to_payload(block) -> Dict[str, Any]:
    return {
        "index": getattr(block, "index", 0),
        "nonce": getattr(block, "nonce", 0),
        "m_tree_root": getattr(block, "m_tree_root", None),
        "time": block.time.isoformat() if getattr(block, "time", None) else None,
        "miner": getattr(block, "miner", None),
        "pre_hash": getattr(block, "pre_hash", None),
        "version": getattr(block, "version", "1.0"),
    }


def payload_to_block(payload) -> Any:
    from EZ_Main_Chain.Block import Block
    import datetime

    t = None
    if payload and payload.get("time"):
        try:
            t = datetime.datetime.fromisoformat(payload["time"])  # type: ignore
        except Exception:
            t = None

    return Block(
        index=int(payload.get("index", 0)),
        m_tree_root=payload.get("m_tree_root"),
        miner=payload.get("miner"),
        pre_hash=payload.get("pre_hash"),
        nonce=int(payload.get("nonce", 0)),
        time=t,
        version=payload.get("version", "1.0"),
    )


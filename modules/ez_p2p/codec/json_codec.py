import json
import time
import uuid
from typing import Any, Dict


def new_msg_id() -> str:
    return uuid.uuid4().hex


def encode_message(
    *,
    network: str,
    msg_type: str,
    payload: Dict[str, Any],
    protocol_version: str = "0.1",
    msg_id: str | None = None,
) -> bytes:
    envelope = {
        "version": protocol_version,
        "network": network,
        "type": msg_type,
        "msg_id": msg_id or new_msg_id(),
        "timestamp": int(time.time() * 1000),
        "payload": payload,
    }
    return json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def decode_message(data: bytes) -> Dict[str, Any]:
    return json.loads(data.decode("utf-8"))


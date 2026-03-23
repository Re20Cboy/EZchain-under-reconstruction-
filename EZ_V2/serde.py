from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from .types import (
    AccountLeaf,
    BlockHeaderV2,
    BlockV2,
    BundleEnvelope,
    BundleRef,
    BundleSidecar,
    BundleSubmission,
    Checkpoint,
    CheckpointAnchor,
    ConfirmedBundleUnit,
    DiffEntry,
    DiffPackage,
    GenesisAnchor,
    HeaderLite,
    OffChainTx,
    PendingBundleContext,
    PriorWitnessLink,
    Receipt,
    ReceiptResponse,
    SparseMerkleProof,
    TransferPackage,
    WitnessV2,
)
from .consensus.pacemaker import PacemakerState
from .consensus.sortition import VRFProposerClaim
from .consensus.types import (
    ConsensusGenesisConfig,
    ConsensusValidator,
    Proposal,
    QC,
    TC,
    TimeoutVote,
    Vote,
    VotePhase,
)
from .values import LocalValueRecord, LocalValueStatus, ValueRange
from .networking import (
    ChainSyncCursor,
    NetworkEnvelope,
    PeerInfo,
    ReceiptSyncCursor,
    TransferMailboxEvent,
)


_DATACLASS_REGISTRY = {
    cls.__name__: cls
    for cls in (
        AccountLeaf,
        BlockHeaderV2,
        BlockV2,
        BundleEnvelope,
        BundleRef,
        BundleSidecar,
        BundleSubmission,
        Checkpoint,
        CheckpointAnchor,
        ConfirmedBundleUnit,
        DiffEntry,
        DiffPackage,
        GenesisAnchor,
        HeaderLite,
        ConsensusGenesisConfig,
        ConsensusValidator,
        LocalValueRecord,
        OffChainTx,
        PacemakerState,
        PendingBundleContext,
        PriorWitnessLink,
        Proposal,
        QC,
        Receipt,
        ReceiptResponse,
        ReceiptSyncCursor,
        SparseMerkleProof,
        TC,
        TimeoutVote,
        TransferPackage,
        TransferMailboxEvent,
        VRFProposerClaim,
        Vote,
        ChainSyncCursor,
        PeerInfo,
        NetworkEnvelope,
        ValueRange,
        WitnessV2,
    )
}

_ENUM_REGISTRY = {
    LocalValueStatus.__name__: LocalValueStatus,
    VotePhase.__name__: VotePhase,
}

_LAZY_DATACLASS_LOADERS = {
    "BlockSyncResult": ("EZ_V2.network_host", "BlockSyncResult"),
    "ConsensusRuntimeSnapshot": ("EZ_V2.network_host", "ConsensusRuntimeSnapshot"),
}

_TUPLE_FIELDS = {
    "ConsensusGenesisConfig": {"validators"},
    "OffChainTx": {"value_list"},
    "BundleSidecar": {"tx_list"},
    "DiffPackage": {"diff_entries", "sidecars", "sender_public_keys"},
    "PendingBundleContext": {"pending_record_ids", "outgoing_record_ids", "outgoing_values"},
    "QC": {"signers"},
    "SparseMerkleProof": {"siblings"},
    "TC": {"signers"},
    "WitnessV2": {"confirmed_bundle_chain"},
}


def dumps_json(value: Any) -> str:
    return json.dumps(to_json_obj(value), sort_keys=True, separators=(",", ":"))


def loads_json(raw: str) -> Any:
    return from_json_obj(json.loads(raw))


def to_json_obj(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, bytes):
        return {"__bytes__": value.hex()}
    if isinstance(value, Enum):
        return {"__enum__": value.__class__.__name__, "value": value.value}
    if is_dataclass(value):
        payload = {"__type__": value.__class__.__name__}
        for field in fields(value):
            payload[field.name] = to_json_obj(getattr(value, field.name))
        return payload
    if isinstance(value, tuple):
        return [to_json_obj(item) for item in value]
    if isinstance(value, list):
        return [to_json_obj(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_json_obj(item) for key, item in value.items()}
    raise TypeError(f"Unsupported value for JSON serialization: {type(value)!r}")


def from_json_obj(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [from_json_obj(item) for item in value]
    if isinstance(value, dict):
        if "__bytes__" in value:
            return bytes.fromhex(value["__bytes__"])
        if "__enum__" in value:
            enum_cls = _ENUM_REGISTRY[value["__enum__"]]
            return enum_cls(value["value"])
        if "__type__" in value:
            cls_name = value["__type__"]
            cls = _DATACLASS_REGISTRY.get(cls_name)
            if cls is None:
                lazy_loader = _LAZY_DATACLASS_LOADERS.get(cls_name)
                if lazy_loader is None:
                    raise KeyError(cls_name)
                module_name, attr_name = lazy_loader
                module = __import__(module_name, fromlist=[attr_name])
                cls = getattr(module, attr_name)
                _DATACLASS_REGISTRY[cls_name] = cls
            tuple_fields = _TUPLE_FIELDS.get(cls_name, set())
            kwargs = {}
            for key, raw_item in value.items():
                if key == "__type__":
                    continue
                item = from_json_obj(raw_item)
                if key in tuple_fields and isinstance(item, list):
                    item = tuple(item)
                kwargs[key] = item
            return cls(**kwargs)
        return {str(key): from_json_obj(item) for key, item in value.items()}
    raise TypeError(f"Unsupported value for JSON deserialization: {type(value)!r}")

import copy

from EZ_Tool_Box.SecureSignature import secure_signature_handler
from modules.ez_p2p.config import P2PConfig
from modules.ez_p2p.router import Router
from modules.ez_p2p.security import SUPPORTED_ALGORITHM, sign_envelope, verify_envelope_signature


def _build_signed_message(private_pem: str, public_pem: str):
    msg = {
        "version": "0.1",
        "network": "account",
        "type": "HELLO",
        "msg_id": "msg-1",
        "timestamp": 1700000000000,
        "sender_id": "node-a",
        "payload": {
            "node_id": "node-a",
            "role": "account",
            "protocol_version": "0.1",
            "network_id": "devnet",
            "latest_index": 0,
        },
    }
    signature = sign_envelope(msg, private_pem)
    msg["auth"] = {
        "algorithm": SUPPORTED_ALGORITHM,
        "public_key": public_pem,
        "signature": signature,
    }
    return msg


def test_security_sign_verify_roundtrip():
    private_pem, public_pem = secure_signature_handler.signer.generate_key_pair()
    msg = _build_signed_message(private_pem.decode("utf-8"), public_pem.decode("utf-8"))

    assert verify_envelope_signature(msg, msg["auth"]["signature"], msg["auth"]["public_key"]) is True



def test_security_signature_detects_tamper():
    private_pem, public_pem = secure_signature_handler.signer.generate_key_pair()
    msg = _build_signed_message(private_pem.decode("utf-8"), public_pem.decode("utf-8"))

    tampered = copy.deepcopy(msg)
    tampered["payload"]["latest_index"] = 99

    assert verify_envelope_signature(tampered, msg["auth"]["signature"], msg["auth"]["public_key"]) is False



def test_router_enforces_signed_hello_when_enabled():
    private_pem, public_pem = secure_signature_handler.signer.generate_key_pair()
    router = Router(
        P2PConfig(
            node_role="consensus",
            enforce_identity_verification=True,
            identity_private_key_pem=private_pem.decode("utf-8"),
            identity_public_key_pem=public_pem.decode("utf-8"),
        )
    )

    signed = _build_signed_message(private_pem.decode("utf-8"), public_pem.decode("utf-8"))
    assert router._validate_envelope(signed) is True

    missing_auth = copy.deepcopy(signed)
    missing_auth.pop("auth", None)
    assert router._validate_envelope(missing_auth) is False

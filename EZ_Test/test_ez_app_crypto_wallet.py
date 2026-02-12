import tempfile
from pathlib import Path

from EZ_App.crypto import address_from_public_key, derive_keypair, generate_mnemonic
from EZ_App.wallet_store import WalletStore


def test_mnemonic_and_deterministic_derivation():
    mnemonic = generate_mnemonic()
    d1 = derive_keypair(mnemonic)
    d2 = derive_keypair(mnemonic)
    assert d1.address == d2.address
    assert d1.private_key_pem == d2.private_key_pem
    assert d1.address.startswith("0x")
    assert len(d1.address) == 42
    assert d1.address == address_from_public_key(d1.public_key_pem)


def test_wallet_create_import_and_load():
    with tempfile.TemporaryDirectory() as td:
        store = WalletStore(td)
        created = store.create_wallet(password="pw123", name="alice")
        assert store.exists()
        loaded = store.load_wallet(password="pw123")
        assert loaded["address"] == created["address"]

        mnemonic = created["mnemonic"]
        store2 = WalletStore(str(Path(td) / "other"))
        imported = store2.import_wallet(mnemonic=mnemonic, password="pw123", name="alice")
        assert imported["address"] == created["address"]

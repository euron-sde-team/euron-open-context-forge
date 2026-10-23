import pytest
from cryptography.exceptions import InvalidTag

from contextforge.core.sealing import LocalSealer
from contextforge.core.storage import LocalStorage


async def test_local_sealer_round_trip_and_context_binding() -> None:
    sealer = LocalSealer("test-only-master-key")
    sealed = await sealer.seal("sk-secret", "provider:1")
    assert b"sk-secret" not in sealed
    assert await sealer.open(sealed, "provider:1") == "sk-secret"
    with pytest.raises(InvalidTag):
        await sealer.open(sealed, "provider:2")


async def test_local_sealer_uses_fresh_nonces() -> None:
    sealer = LocalSealer("test-only-master-key")
    assert await sealer.seal("same", "c") != await sealer.seal("same", "c")


async def test_local_sealer_rejects_wrong_key_and_format() -> None:
    sealed = await LocalSealer("key-a").seal("v", "c")
    with pytest.raises(InvalidTag):
        await LocalSealer("key-b").open(sealed, "c")
    with pytest.raises(ValueError, match="unknown sealed format"):
        await LocalSealer("key-a").open(b"\x09" + sealed[1:], "c")


async def test_local_storage_round_trip(tmp_path: object) -> None:
    storage = LocalStorage(str(tmp_path))
    await storage.put("exports/a.csv", b"x,y\n", "text/csv")
    assert await storage.get("exports/a.csv") == b"x,y\n"
    assert await storage.download_url("exports/a.csv", "a.csv") is None


async def test_local_storage_refuses_path_traversal(tmp_path: object) -> None:
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError, match="escapes"):
        await storage.put("../outside.txt", b"x", "text/plain")

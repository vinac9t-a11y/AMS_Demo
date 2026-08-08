"""Store discipline: atomic writes, append-only ledgers, path safety."""


import pytest

from s7_delivery.factory.store import RunStore, StoreError, next_run_id, sha256_of


@pytest.fixture()
def store(tmp_path):
    return RunStore("S7-00001", root=tmp_path)


def test_write_and_read_json_roundtrip(store):
    store.write_json({"a": 1}, "intake", "requirement.json")
    assert store.read_json("intake", "requirement.json") == {"a": 1}


def test_read_missing_raises(store):
    with pytest.raises(StoreError):
        store.read_json("nope.json")


def test_read_json_or_default(store):
    assert store.read_json_or([], "planning", "stories.json") == []


def test_ledger_appends_never_overwrite(store):
    store.append({"n": 1}, "provenance.jsonl")
    store.append({"n": 2}, "provenance.jsonl")
    rows = store.read_ledger("provenance.jsonl")
    assert [r["n"] for r in rows] == [1, 2]


def test_ledger_must_be_jsonl(store):
    with pytest.raises(StoreError):
        store.append({"n": 1}, "provenance.json")


def test_unsafe_run_id_rejected(tmp_path):
    with pytest.raises(StoreError):
        RunStore("../escape", root=tmp_path)


def test_unsafe_segment_rejected(store):
    with pytest.raises(StoreError):
        store.path("..", "escape.json")


def test_atomic_write_leaves_no_tmp_files(store, tmp_path):
    store.write_json({"a": 1}, "run.json")
    leftovers = [p for p in (tmp_path / "S7-00001").rglob("*.tmp")]
    assert leftovers == []


def test_sha256_is_key_order_independent():
    assert sha256_of({"a": 1, "b": 2}) == sha256_of({"b": 2, "a": 1})


def test_sha256_changes_with_content():
    assert sha256_of({"a": 1}) != sha256_of({"a": 2})


def test_next_run_id_sequences(tmp_path):
    assert next_run_id(tmp_path) == "S7-00001"
    (tmp_path / "S7-00001").mkdir()
    (tmp_path / "S7-00007").mkdir()
    assert next_run_id(tmp_path) == "S7-00008"

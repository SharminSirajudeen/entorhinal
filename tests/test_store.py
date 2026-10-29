"""Store, each method against values derived by hand from the three facts below."""
import json
import sqlite3
from dataclasses import asdict, replace

import pytest

from life.store import Store
from life.types import Fact

BIKE = Fact("f1", "user", "commute", "bikes 10 miles to work daily", "2026-03-01 08:30", 0)
CAST = Fact("f2", "user", "health", "leg in a cast for six weeks", "2026-03-22 19:05", 1)
BAKERY = Fact("f3", "user", "job", "works at a bakery", "2026-02-10 12:00", 0)
BIKE_STALE = replace(BIKE, status="stale", invalidated_by="f2", reason="a leg in a cast stops cycling")


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "memory.db"))


def test_round_trip(store):
    store.put(BIKE)
    assert store.get("f1") == BIKE
    assert store.get("f9") is None


def test_active_excludes_stale(store):
    for f in (BIKE, CAST, BIKE_STALE):
        store.put(f)
    assert store.active() == [CAST]


def test_stale_lists_only_stale(store):
    for f in (BIKE, CAST, BIKE_STALE):
        store.put(f)
    assert store.stale() == [BIKE_STALE]


def test_put_stores_every_fact_given(store):
    store.put(BIKE, CAST, BAKERY)
    assert store.timeline() == [BAKERY, BIKE, CAST]  # by time: 10 Feb, 1 Mar, 22 Mar


def test_put_replaces_same_id(store):
    for f in (BIKE, CAST, BIKE_STALE):
        store.put(f)
    assert [f.id for f in store.timeline()] == ["f1", "f2"]
    assert store.get("f1") == BIKE_STALE


def test_timeline_is_chronological(store):
    for f in (CAST, BAKERY, BIKE):
        store.put(f)
    assert [f.id for f in store.timeline()] == ["f3", "f1", "f2"]  # 10 Feb, 1 Mar, 22 Mar


def test_export_keeps_stale_facts(store):
    for f in (BIKE, CAST, BIKE_STALE):
        store.put(f)
    assert json.loads(store.export_json()) == [asdict(BIKE_STALE), asdict(CAST)]


def test_delete_all_empties(store):
    for f in (BIKE, CAST):
        store.put(f)
    store.delete_all()
    assert store.timeline() == []
    assert store.export_json() == "[]"


def test_status_is_constrained(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.put(replace(BIKE, status="deleted"))


def test_memory_survives_reopen(tmp_path):
    path = str(tmp_path / "memory.db")
    Store(path).put(BIKE)
    assert Store(path).get("f1") == BIKE

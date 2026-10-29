"""A stratified, seeded sample of STALE (arXiv 2605.06527; data CC BY 4.0). Seed 7, n=10 reproduces the baseline
pilot's 20 uids (docs/reports/01-baseline-pilot)."""
import json
import random
from pathlib import Path

from life.types import Instance


def sample(records: list[dict], n: int, seed: int, types: list[str] | None = None) -> list[dict]:
    """n records per type, types in sorted order, one shared generator. Every type is drawn even when `types` drops
    it, so a subset is exactly the records the full draw gives for those types."""
    rng = random.Random(seed)
    out = []
    for t in sorted({r["type"] for r in records}):
        picked = rng.sample([r for r in records if r["type"] == t], n)
        if types is None or t in types:
            out += picked
    return out


def load_stale(path: str, n: int, seed: int, types: list[str] | None = None) -> list[Instance]:
    return [Instance(**r) for r in sample(json.loads(Path(path).read_text()), n, seed, types)]

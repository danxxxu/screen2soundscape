# utils/osm_value_resolver.py
import json, os, re
from pathlib import Path
from functools import lru_cache
from typing import Optional, Tuple

# Optional: better fuzzy match if available; else fall back to difflib
try:
    from rapidfuzz import fuzz
    def _sim(a, b): return fuzz.token_set_ratio(a, b)  # 0..100
except Exception:
    import difflib
    def _sim(a, b): return int(100 * difflib.SequenceMatcher(None, a, b).ratio())

DATA_PATH_DEFAULT = Path("../osm_tags/tag_values/all_osm_tags.json")

def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[/_]+", " ", s)
    s = re.sub(r"[^\w\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # naive singularization for common English plurals (enough for pharmacies→pharmacy, toilets→toilet)
    if s.endswith("ies"): s = s[:-3] + "y"
    elif s.endswith("ves"): s = s[:-3] + "f"
    elif s.endswith("s") and len(s) > 3: s = s[:-1]
    return s

@lru_cache()
def _load_values_index(data_path: str) -> dict:
    """Returns {key: set(values)} from your combined cache JSON."""
    path = Path(data_path)
    if not path.exists():
        raise FileNotFoundError(f"Missing tag-values JSON at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    # Keep only POI-ish keys to avoid noise
    allowed = {"amenity","shop","tourism","leisure","healthcare","craft","office","natural","highway"}
    idx = {k: set(vs) for k, vs in data.items() if k in allowed and isinstance(vs, list)}
    return idx

def resolve_tag_from_values(
    phrase: str,
    data_path: str = str(DATA_PATH_DEFAULT),
    threshold: int = 60,
) -> Optional[Tuple[str, str, int]]:
    """
    Map a natural phrase to (key, value, score) by fuzzy matching against known OSM values
    pulled from Overpass (no hardcoding). Returns None if nothing crosses threshold.
    """
    phrase_n = _norm(phrase)
    if not phrase_n:
        return None
    idx = _load_values_index(data_path)

    best = ("", "", -1)
    for key, values in idx.items():
        for val in values:
            val_n = _norm(val)
            score = _sim(phrase_n, val_n)
            if score > best[2]:
                best = (key, val, score)

    return best if best[2] >= threshold else None

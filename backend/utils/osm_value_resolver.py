# utils/osm_value_resolver.py
import json, re
from pathlib import Path
from functools import lru_cache
from typing import Optional, Tuple

try:
    from rapidfuzz import fuzz
    def _sim(a, b): return fuzz.token_set_ratio(a, b)
except Exception:
    import difflib
    def _sim(a, b): return int(100 * difflib.SequenceMatcher(None, a, b).ratio())

DATA_PATH_DEFAULT = Path("../osm_tags/tag_values/all_osm_tags.json")

def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[/_]+", " ", s)
    s = re.sub(r"[^\w\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if s.endswith("ies"): s = s[:-3] + "y"
    elif s.endswith("ves"): s = s[:-3] + "f"
    elif s.endswith("s") and len(s) > 3: s = s[:-1]
    return s

@lru_cache()
def _load_values_index(data_path: str) -> dict:
    p = Path(data_path)
    if not p.exists():
        raise FileNotFoundError(f"Missing tag-values JSON at {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    allowed = {"amenity","shop","tourism","leisure","healthcare","craft","office","natural","highway"}
    return {k: set(vs) for k, vs in data.items() if k in allowed and isinstance(vs, list)}

def resolve_tag_from_values(phrase: str,
                            data_path: str = str(DATA_PATH_DEFAULT),
                            threshold: int = 60) -> Optional[Tuple[str, str, int]]:
    phrase_n = _norm(phrase or "")
    if not phrase_n:
        return None
    idx = _load_values_index(data_path)

    best = ("", "", -1)
    for key, values in idx.items():
        for val in values:
            score = _sim(phrase_n, _norm(val))
            if score > best[2]:
                best = (key, val, score)
    return best if best[2] >= threshold else None

# overpass_to_osm.py
"""
Overpass-to-OSM utilities powered by BitNet.

Changes vs previous version:
- Uses BitNet (backend/utils/bitnet_singleton.py) for BOTH:
  (a) Overpass QL generation fallback, and
  (b) local natural-language rewrite of results.
- Keeps deterministic TAG_MAP → Overpass QL when possible.
- No transformers/flan or llama_singleton required.

Env tips for BitNet:
  - Prefer local GGUF: backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/*.gguf
  - Force HF fallback:    export BITNET_FORCE_HF=1
  - Pick HF model/dir:    export BITNET_HF_MODEL_ID=microsoft/bitnet-b1.58-2B-4T or /path/to/local
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional
from math import hypot
import requests
from requests.exceptions import HTTPError

from utils.osm_tags import TAG_MAP, find_osm_tags
from utils.bitnet_singleton import chat as bitnet_chat

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_RESULT_LIMIT = 5
MAX_ELEMENTS_TO_SCAN = 50
_BITNET_WARMED = False

# ──────────────────────────────────────────────────────────────────────────────
# Small text helpers for nicer phrasing
# ──────────────────────────────────────────────────────────────────────────────
_STREET_TOKENS = (
    "straat lane laan road rd street st avenue ave avenue av boul boulevard "
    "blvd place plein square market markt drive dr weg quai kade dijk gracht"
).split()


def _choose_prep(street: str) -> str:
    s = street.lower()
    return "on" if any(tok in s for tok in _STREET_TOKENS) else "at"


def _place_phrase(name: Optional[str], street: Optional[str]) -> Optional[str]:
    """Return ‘Name on Street’, ‘Name’, or None."""
    if not name and not street:
        return None
    if name and street:
        return f"{name} {_choose_prep(street)} {street}"
    return name or street


def _baseline_sentence(items: List[str], total: int) -> str:
    """
    Deterministic, already-fluent fallback sentence (never crashes).
    items: up to 3 short phrases like "Public Toilet on Kerkstraat"
    total: total count returned by Overpass (may exceed items length)
    """
    if total == 0:
        return "I couldn't find any matching places nearby."
    n = len(items)
    if n == 0:
        # We found places but none had a decent name/street combo.
        return f"I found {total} places nearby."
    if n == 1:
        return f"I found one place nearby: {items[0]}."
    if n == 2:
        return f"I found two places: {items[0]} and {items[1]}."
    examples = ", ".join(items[:-1]) + f", and {items[-1]}"
    return f"I found {total} places nearby; for example {examples}."



# ──────────────────────────────────────────────────────────────────────────────
# BitNet helpers
# ──────────────────────────────────────────────────────────────────────────────
def _warm_bitnet():
    global _BITNET_WARMED
    if _BITNET_WARMED:
        return
    try:
        bitnet_chat(
            [
                {"role": "system", "content": "You are a concise assistant. Reply briefly."},
                {"role": "user", "content": "warm-up"},
            ],
            max_new_tokens=8,
            temperature=0.0,
            top_p=0.95,
        )
    except Exception:
        pass
    _BITNET_WARMED = True


def _bitnet_rewrite(baseline: str) -> str:
    """
    Use BitNet to rewrite a deterministic baseline into ONE concise, spoken sentence.
    Falls back to the baseline on any error or failed validation.
    """
    _warm_bitnet()

    system_inst = (
        "Rewrite the user's baseline into exactly ONE friendly spoken sentence, under 28 words. "
        "No lists, no semicolons, and keep real place names verbatim. "
        "Use plain English and end with a period."
    )

    try:
        out = bitnet_chat(
            [
                {"role": "system", "content": system_inst},
                {"role": "user", "content": baseline},
            ],
            max_new_tokens=48,
            temperature=0.1,
            top_p=0.9,
        ).strip()
    except Exception:
        return baseline

    # Validate; otherwise revert to baseline
    good_end = out.endswith((".", "!", "?"))
    has_verb = re.search(r"\b(is|are|find|found|located|offers|includes|has|features)\b", out.lower())
    within_len = 6 <= len(out.split()) <= 28
    if not (good_end and has_verb and within_len and ";" not in out and "\n" not in out):
        return baseline

    return out


def _bitnet_generate_overpass(question: str, lat: Optional[float], lon: Optional[float], radius: int) -> str:
    """
    Use BitNet to generate an Overpass QL query. We strictly sanitize and enforce
    minimal requirements on the output (header + out center;).
    """
    _warm_bitnet()

    sys_rules = (
        "You are an expert in Overpass QL for OpenStreetMap. "
        "Return ONLY a valid Overpass QL query (no prose, no markdown). "
        "Rules:\n"
        "- Always start with: [out:json][timeout:25];\n"
        "- Always include `out center;` at the end (and a trailing semicolon).\n"
        "- Prefer `node` if unsure, otherwise use both node and way; include relation if appropriate.\n"
        "- If coordinates are provided, use (around:RADIUS,LAT,LON) with the provided values.\n"
        "- Use relevant tags such as amenity, shop, tourism, leisure, highway, public_transport.\n"
        "- Do not include explanations, comments, or code fences."
    )

    if lat is not None and lon is not None:
        user_msg = (
            f"Question: {question}\n"
            f"Coordinates: lat={lat}, lon={lon}, radius={radius} meters.\n"
            "Produce a single Overpass QL query that searches around the coordinates."
        )
    else:
        user_msg = (
            f"Question: {question}\n"
            "No coordinates are provided; produce a single Overpass QL query that still works globally or with reasonable scope."
        )

    try:
        raw = bitnet_chat(
            [
                {"role": "system", "content": sys_rules},
                {"role": "user", "content": user_msg},
            ],
            max_new_tokens=220,
            temperature=0.1,
            top_p=0.9,
        )
    except Exception as e:
        raise RuntimeError(f"BitNet Overpass generation failed: {e}")

    q = _sanitize_overpass_output(raw, lat=lat, lon=lon, radius=radius)
    if not q.strip():
        raise RuntimeError("BitNet Overpass generation returned empty after sanitization.")
    return q


def _ensure_out_center(q: str) -> str:
    """
    Make sure the query ends with an 'out center ...;' clause.
    We do NOT add a limit here; that is enforced by _sanitize_overpass_output.
    """
    q = q.strip()
    if "out center" in q.lower():
        return q if q.endswith(";") else (q + ";")
    # Replace bare 'out;' with 'out center;'
    q = re.sub(r"\bout\s*;\s*$", "out center;", q, flags=re.IGNORECASE)
    if "out center" not in q.lower():
        q = q.rstrip() + "\nout center;"
    return q



def _ensure_final_semicolon(q: str) -> str:
    if not q.rstrip().endswith(";"):
        q = q.rstrip() + "\n;"
    return q


def _maybe_inject_around_clause(q: str, lat: Optional[float], lon: Optional[float], radius: int) -> str:
    """
    If coordinates provided but model didn't use them, inject (around:...) into node/way/relation selectors.
    """
    if lat is None or lon is None:
        return q

    if f"(around:{radius},{lat},{lon})" in q:
        return q  # already present

    # Heuristically insert around-clause after first node/way/relation selectors without an area/around/box.
    def inject(selector: str, text: str) -> str:
        pattern = rf"({selector}\s*(?:\[[^\]]+\]\s*)*)\s*(\([^)]*\))?"
        def _repl(m):
            head = m.group(1)
            paren = m.group(2) or ""
            if "around:" in paren or "area:" in paren or "," in paren:
                return m.group(0)  # leave as is
            return f"{head}(around:{radius},{lat},{lon})"
        return re.sub(pattern, _repl, text, count=1, flags=re.IGNORECASE)

    q2 = q
    for sel in ("node", "way", "relation"):
        q2 = inject(sel, q2)
    return q2

def _sanitize_overpass_output(text: str, lat: Optional[float], lon: Optional[float], radius: int) -> str:
    """
    Take raw model text and force it into a valid, minimal Overpass QL with:
      - header
      - around clause if coords provided but missing
      - 'out center <LIMIT>;' tail
      - final semicolon
    """
    def _strip_code_fences(src: str) -> str:
        m = re.search(r"```(?:[a-zA-Z0-9_+-]*)\s*(.*?)```", src, flags=re.DOTALL)
        if m:
            return m.group(1).strip()
        src = src.replace("```", "").strip("`").strip()
        return src

    def _ensure_header(q: str) -> str:
        return q if q.lstrip().startswith("[out:json]") else "[out:json][timeout:25];\n" + q.lstrip()

    def _ensure_final_semicolon(q: str) -> str:
        return q if q.rstrip().endswith(";") else (q.rstrip() + ";")

    def _maybe_inject_around_clause(q: str, lat_: Optional[float], lon_: Optional[float], r_: int) -> str:
        if lat_ is None or lon_ is None:
            return q
        if f"(around:{r_},{lat_},{lon_})" in q:
            return q
        # Inject a single around clause after the first node/way/relation selector without an explicit area/around
        def inject(selector: str, text: str) -> str:
            pattern = rf"({selector}\s*(?:\[[^\]]+\]\s*)*)(\([^)]*\))?"
            def repl(m):
                head, paren = m.group(1), (m.group(2) or "")
                if "around:" in paren or "area:" in paren or "," in paren:
                    return m.group(0)
                return f"{head}(around:{r_},{lat_},{lon_})"
            return re.sub(pattern, repl, text, count=1, flags=re.IGNORECASE)

        for sel in ("node", "way", "relation"):
            q = inject(sel, q)
        return q

    q = _strip_code_fences(text)
    # Drop obvious line comments
    q = "\n".join([ln for ln in q.splitlines() if not re.match(r"\s*(//|#)", ln)]).strip()

    q = _ensure_header(q)
    q = _maybe_inject_around_clause(q, lat, lon, radius)
    q = _ensure_out_center(q)

    # Enforce the hard top-3 limit on the out clause
    q = re.sub(r"\bout\s+center\b[^;]*;", f"out center {OVERPASS_RESULT_LIMIT};", q, flags=re.IGNORECASE)

    q = _ensure_final_semicolon(q)
    return q


# ──────────────────────────────────────────────────────────────────────────────
# Public functions
# ──────────────────────────────────────────────────────────────────────────────
def generate_overpass_query(question: str, lat: float = None, lon: float = None, radius: int = 1000) -> str:
    """
    Generate an Overpass QL query:
      1) Deterministic TAG_MAP generation (preferred).
      2) Fall back to BitNet-generated QL (then sanitized).
    Always capped to top 3 via the sanitizer.
    """
    from utils.osm_tags import find_osm_tags  # keep the existing import style

    tags = find_osm_tags(question)

    if tags:
        conditions = "".join([f'["{k}"="{v}"]' for k, v in tags.items()])
        if lat is not None and lon is not None:
            q = f"""
[out:json][timeout:25];
(
  node{conditions}(around:{radius},{lat},{lon});
  way{conditions}(around:{radius},{lat},{lon});
  relation{conditions}(around:{radius},{lat},{lon});
);
out center {OVERPASS_RESULT_LIMIT};
"""
        else:
            q = f"""
[out:json][timeout:25];
(
  node{conditions};
  way{conditions};
  relation{conditions};
);
out center {OVERPASS_RESULT_LIMIT};
"""
        return q.strip()

    # No deterministic tags → synthesize and sanitize
    return _bitnet_generate_overpass(question, lat, lon, radius)


def run_overpass_query(query: str) -> dict:
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=20)
        r.raise_for_status()
        return r.json()
    except HTTPError as e:
        raise RuntimeError(f"Overpass API error: {e}") from e


def summarize_results(question: str, data: dict, center: Optional[tuple] = None) -> str:
    """
    Build a clear baseline sentence from OSM tags, then let BitNet polish it.
    We optionally sort by distance to 'center' when provided.
    Always uses at most the top-3 examples for speech.
    """
    def _place_phrase(name: Optional[str], street: Optional[str]) -> Optional[str]:
        if not name and not street:
            return None
        street_tokens = (
            "straat lane laan road rd street st avenue ave boul boulevard blvd place plein square "
            "market markt drive dr weg quai kade dijk gracht"
        ).split()
        def _prep(s: str) -> str:
            s = (s or "").lower()
            return "on" if any(tok in s for tok in street_tokens) else "at"
        if name and street:
            return f"{name} {_prep(street)} {street}"
        return name or street

    elements = data.get("elements", [])
    total = len(elements)
    if total == 0:
        return "Sorry, I couldn't find any relevant places for your query."

    # Optional: sort by distance to search center so examples are truly “closest”
    if center is not None and isinstance(center, tuple) and len(center) == 2:
        clat, clon = center
        def el_coord(el):
            if "center" in el:
                return el["center"].get("lat"), el["center"].get("lon")
            if "lat" in el and "lon" in el:
                return el.get("lat"), el.get("lon")
            return None, None
        def dist(el):
            lat, lon = el_coord(el)
            return 9e9 if lat is None or lon is None else hypot(lat - clat, lon - clon)
        elements = sorted(elements, key=dist)

    # Collect up to 3 decent phrases, scanning only a small subset
    phrases: List[str] = []
    for el in elements[:MAX_ELEMENTS_TO_SCAN]:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        street = tags.get("addr:street") or tags.get("addr:full")
        t = tags.get("amenity") or tags.get("shop") or tags.get("tourism") or tags.get("leisure")
        phrase = _place_phrase(name or (f"a {t}" if t else None), street)
        if phrase:
            phrases.append(phrase)
        if len(phrases) == 3:
            break

    baseline = _baseline_sentence(phrases, total)
    return _bitnet_rewrite(baseline)


def summarize_route(directions_json: dict) -> str:
    try:
        route = directions_json["routes"][0]
        leg = route["legs"][0]
        steps = leg["steps"]

        lines = [
            f"The route is about {round(route['distance'] / 1000, 1)} "
            f"kilometres and will take approximately {round(route['duration'] / 60)} minutes.",
            "Here are the step-by-step directions:",
        ]
        for i, step in enumerate(steps, 1):
            man = step["maneuver"]
            instr = man.get("instruction") or man.get("type", "Move")
            sent = f"{i}. {instr}"
            if step.get("name"):
                sent += f" onto {step['name']}"
            if step.get("duration"):
                sent += f" for about {round(step['duration'] / 60, 1)} minutes"
            lines.append(sent)
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Could not summarise route: {e}"


def process_question(
    question: str,
    save_json: bool = False,
    output_dir: str | Path = "osm_assistant_output",
) -> str:
    ql = generate_overpass_query(question)
    try:
        data = run_overpass_query(ql)
    except RuntimeError as e:
        return f"❌ Error running Overpass query: {e}"

    if save_json:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        with open(Path(output_dir) / "raw.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return summarize_results(question, data)

# backend/utils/overpass_to_osm_bitnet.py
"""
Overpass-to-OSM utilities powered by BitNet.

Exports (for run_assistant.py compatibility):
  - warmup_summariser()
  - run_overpass_query()
  - summarize_results()
  - summarize_route()
Optional:
  - generate_overpass_query()  # BitNet fallback when TAG_MAP doesn't match
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import List, Optional

import requests
from requests.exceptions import HTTPError

from backend.utils.osm_tags import find_osm_tags
from backend.utils.bitnet_singleton import chat as bitnet_chat

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ──────────────────────────────────────────────────────────────────────────────
# Warmup (compat with previous API)
# ──────────────────────────────────────────────────────────────────────────────
_BITNET_WARMED = False

def _warm_bitnet() -> None:
    """Warm BitNet backend to avoid the first-call latency spike."""
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

def warmup_summariser() -> None:
    """
    Backwards-compatible warmup function expected by run_assistant.py.
    No-op if already warmed.
    """
    _warm_bitnet()

# For completeness, US spelling alias (safe to keep)
def warmup_summarizer() -> None:
    _warm_bitnet()


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
    """Deterministic, already-fluent fallback sentence."""
    if total == 0:
        return "I couldn't find any matching places nearby."
    if total == 1:
        return f"I found one place nearby: {items[0]}."
    if total == 2:
        return f"I found two places: {items[0]} and {items[1]}."
    examples = ", ".join(items[:-1]) + f", and {items[-1]}"
    return f"I found {total} places nearby; for example {examples}."


# ──────────────────────────────────────────────────────────────────────────────
# Overpass QL via BitNet (optional helper if you want LLM fallback)
# ──────────────────────────────────────────────────────────────────────────────
def _strip_code_fences(text: str) -> str:
    m = re.search(r"```(?:[a-zA-Z0-9_+-]*)\s*(.*?)```", text, flags=re.DOTALL)
    if m:
        return m.group(1)
    text = re.sub(r"^(\s*(A:|Answer:))", "", text.strip(), flags=re.IGNORECASE)
    return text.replace("```", "").strip("`").strip()

def _ensure_header(q: str) -> str:
    if not q.lstrip().startswith("[out:json]"):
        q = "[out:json][timeout:25];\n" + q.lstrip()
    return q

def _ensure_out_center(q: str) -> str:
    if "out center;" not in q:
        if re.search(r"\bout\s*;\s*$", q, flags=re.IGNORECASE):
            q = re.sub(r"\bout\s*;\s*$", "out center;", q.strip(), flags=re.IGNORECASE)
        else:
            q = q.rstrip() + "\nout center;"
    return q

def _ensure_final_semicolon(q: str) -> str:
    if not q.rstrip().endswith(";"):
        q = q.rstrip() + "\n;"
    return q

def _maybe_inject_around_clause(q: str, lat: Optional[float], lon: Optional[float], radius: int) -> str:
    if lat is None or lon is None:
        return q
    needle = f"(around:{radius},{lat},{lon})"
    if needle in q:
        return q

    def inject(selector: str, text: str) -> str:
        pattern = rf"({selector}\s*(?:\[[^\]]+\]\s*)*)\s*(\([^)]*\))?"
        def _repl(m):
            head = m.group(1)
            paren = m.group(2) or ""
            if any(k in paren for k in ("around:", "area:", ",")):
                return m.group(0)
            return f"{head}{needle}"
        return re.sub(pattern, _repl, text, count=1, flags=re.IGNORECASE)

    for sel in ("node", "way", "relation"):
        q = inject(sel, q)
    return q

def _sanitize_overpass_output(text: str, lat: Optional[float], lon: Optional[float], radius: int) -> str:
    q = _strip_code_fences(text)
    # Remove line comments like // or #
    q = "\n".join(line for line in q.splitlines() if not re.match(r"\s*(//|#)", line)).strip()
    q = _ensure_header(q)
    q = _maybe_inject_around_clause(q, lat, lon, radius)
    q = _ensure_out_center(q)
    q = _ensure_final_semicolon(q)
    return q

def generate_overpass_query(question: str, lat: float = None, lon: float = None, radius: int = 2000) -> str:
    """
    Optional helper: Try deterministic TAG_MAP first (if your caller wants that),
    else ask BitNet to synthesize Overpass QL.
    """
    tags = find_osm_tags(question) or {}
    if tags:
        cond = "".join([f'["{k}"="{v}"]' for k, v in tags.items()])
        if lat is not None and lon is not None:
            return f"""[out:json][timeout:25];
(
  node{cond}(around:{radius},{lat},{lon});
  way{cond}(around:{radius},{lat},{lon});
  relation{cond}(around:{radius},{lat},{lon});
);
out center;
""".strip()
        return f"""[out:json][timeout:25];
(
  node{cond};
  way{cond};
  relation{cond};
);
out center;
""".strip()

    # BitNet fallback
    _warm_bitnet()
    sys_rules = (
        "You are an expert in Overpass QL for OpenStreetMap. "
        "Return ONLY a valid Overpass QL query (no prose, no markdown). "
        "Rules:\n"
        "- Start with [out:json][timeout:25];\n"
        "- Include `out center;` at the end and a trailing semicolon.\n"
        "- Prefer node when unsure; otherwise use node + way, and relation if appropriate.\n"
        "- If coordinates provided, use (around:RADIUS,LAT,LON).\n"
        "- Use relevant tags: amenity, shop, tourism, leisure, highway, public_transport."
    )
    if lat is not None and lon is not None:
        user = (
            f"Question: {question}\n"
            f"Coordinates: lat={lat}, lon={lon}, radius={radius} meters.\n"
            "Produce a single Overpass QL query that searches around the coordinates."
        )
    else:
        user = f"Question: {question}\nNo coordinates provided; produce a single Overpass QL query."

    raw = bitnet_chat(
        [{"role": "system", "content": sys_rules}, {"role": "user", "content": user}],
        max_new_tokens=220,
        temperature=0.1,
        top_p=0.9,
    )
    q = _sanitize_overpass_output(raw, lat=lat, lon=lon, radius=radius)
    if not q.strip():
        raise RuntimeError("BitNet Overpass generation returned empty after sanitization.")
    return q


# ──────────────────────────────────────────────────────────────────────────────
# Overpass API and summaries
# ──────────────────────────────────────────────────────────────────────────────
def run_overpass_query(query: str) -> dict:
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=20)
        r.raise_for_status()
        return r.json()
    except HTTPError as e:
        raise RuntimeError(f"Overpass API error: {e}") from e

def _bitnet_rewrite(baseline: str) -> str:
    _warm_bitnet()
    system_inst = (
        "Rewrite the user's baseline into exactly ONE friendly spoken sentence, under 28 words. "
        "No lists, no semicolons; keep real place names verbatim. "
        "Plain English. End with a period."
    )
    try:
        out = bitnet_chat(
            [{"role": "system", "content": system_inst}, {"role": "user", "content": baseline}],
            max_new_tokens=48,
            temperature=0.1,
            top_p=0.9,
        ).strip()
    except Exception:
        return baseline

    good_end = out.endswith((".", "!", "?"))
    has_verb = re.search(r"\b(is|are|find|found|located|offers|includes|has|features)\b", out.lower())
    within_len = 6 <= len(out.split()) <= 28
    if not (good_end and has_verb and within_len and ";" not in out and "\n" not in out):
        return baseline
    return out

def summarize_results(question: str, data: dict) -> str:
    elements = data.get("elements", [])
    total = len(elements)
    if total == 0:
        return "Sorry, I couldn't find any relevant places for your query."

    phrases: List[str] = []
    for el in elements[:3]:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        street = tags.get("addr:street") or tags.get("addr:full")
        t = tags.get("amenity") or tags.get("shop") or tags.get("tourism") or tags.get("leisure")
        phrase = _place_phrase(name or (f"a {t}" if t else None), street)
        if phrase:
            phrases.append(phrase)

    baseline = _baseline_sentence(phrases, total)
    return _bitnet_rewrite(baseline)

def summarize_route(directions_json: dict) -> str:
    try:
        route = directions_json["routes"][0]
        leg = route["legs"][0]
        steps = leg["steps"]
        lines = [
            f"The route is about {round(route['distance'] / 1000, 1)} kilometres "
            f"and will take approximately {round(route['duration'] / 60)} minutes.",
            "Here are the step-by-step directions:",
        ]
        for i, step in enumerate(steps, 1):
            man = step.get("maneuver", {})
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

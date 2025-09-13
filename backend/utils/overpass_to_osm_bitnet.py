# overpass_to_osm.py
"""
Overpass-to-OSM utilities with a fast local summariser based on BitNet.

- Replaces google/flan-t5-base with BitNet via backend/utils/bitnet_singleton.py
- First call may load the backend (GGUF binary/py runner or HF fallback).
- Subsequent calls are fast; runs fully locally if you have a BitNet GGUF/binary.

Env tips:
  - To force the HF fallback: export BITNET_FORCE_HF=1
  - To point at a local HF dir: export BITNET_HF_MODEL_ID=/path/to/microsoft/bitnet-b1.58-2B-4T
  - To prefer a local GGUF: place it under backend/models/microsoft/bitnet-b1.58-2B-4T-gguf/
"""
from __future__ import annotations

import os
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

import requests
from requests.exceptions import HTTPError

from backend.utils.osm_tags import TAG_MAP, find_osm_tags
from backend.utils.bitnet_singleton import chat as bitnet_chat

_llm = get_llm()  # only used for generating the Overpass QL itself

# ──────────────────────────────────────────────────────────────────────────────
# Constants & globals
# ──────────────────────────────────────────────────────────────────────────────
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# _BITNET_WARMED indicates we've done the first quick call to avoid cold-start
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
# Core public functions
# ──────────────────────────────────────────────────────────────────────────────
def generate_overpass_query(question: str, lat: float = None, lon: float = None, radius: int = 2000) -> str:
    """
    Generate an Overpass QL query.
    1. Try TAG_MAP deterministic generation.
    2. Fall back to LLM if no match found.
    """
    tags = find_osm_tags(question)

    if tags:
        # ✅ Deterministic query
        conditions = "".join([f'["{k}"="{v}"]' for k, v in tags.items()])

        if lat is not None and lon is not None:
            query = f"""
[out:json][timeout:25];
(
  node{conditions}(around:{radius},{lat},{lon});
  way{conditions}(around:{radius},{lat},{lon});
  relation{conditions}(around:{radius},{lat},{lon});
);
out center;
"""
        else:
            # No coordinates, fallback to global search
            query = f"""
[out:json][timeout:25];
(
  node{conditions};
  way{conditions};
  relation{conditions};
);
out center;
"""
        return query.strip()

    # ❌ No TAG_MAP match → use LLM
    prompt = f"""
You are an expert at writing Overpass QL queries for OpenStreetMap.
Rules:
- Always include `out center;` at the end.
- Use relevant tags: `amenity`, `shop`, `tourism`, `leisure`, `highway`, `public_transport`.
- Prefer `node` if you don't know the type; otherwise use `node` + `way`.
- If coordinates are provided, use (around:{radius},{lat},{lon}).
- Output ONLY the Overpass query (no explanation).

Examples:
Q: "Find coffee shops near Times Square"
A:
[out:json][timeout:25];
(
  node["amenity"="cafe"](around:1000,40.7580,-73.9855);
);
out center;

Q: "Where are public toilets in Paris?"
A:
[out:json][timeout:25];
(
  node["amenity"="toilets"](area:3602204096);
  way["amenity"="toilets"](area:3602204096);
);
out center;

Question: "{question}"
"""
    resp = _llm(prompt=prompt, max_tokens=80, temperature=0.1)
    q = resp["choices"][0]["text"].strip()
    if not q.endswith(";"):
        q += "\n;"
    return q


def run_overpass_query(query: str) -> dict:
    try:
        r = requests.post(OVERPASS_URL, data={"data": query}, timeout=20)
        r.raise_for_status()
        return r.json()
    except HTTPError as e:
        raise RuntimeError(f"Overpass API error: {e}") from e


def _bitnet_rewrite(baseline: str) -> str:
    """
    Use BitNet to rewrite a deterministic baseline into ONE concise, spoken sentence.
    Falls back to the baseline on any error.
    """
    global _BITNET_WARMED

    system_inst = (
        "Rewrite the user's baseline into exactly ONE friendly spoken sentence, under 28 words. "
        "No lists, no semicolons, no numbered steps. Keep real place names verbatim. "
        "Finish with a period."
    )

    # Warm-up (optional) to avoid first-call latency spikes.
    if not _BITNET_WARMED:
        try:
            bitnet_chat(
                [
                    {"role": "system", "content": system_inst},
                    {"role": "user", "content": "warm-up example sentence"},
                ],
                max_new_tokens=16,
                temperature=0.0,
                top_p=0.95,
            )
        except Exception:
            pass
        _BITNET_WARMED = True

    try:
        out = bitnet_chat(
            [
                {"role": "system", "content": system_inst},
                {"role": "user", "content": baseline},
            ],
            max_new_tokens=48,
            temperature=0.1,  # mostly deterministic, but allows minor polishing
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


def summarize_results(question: str, data: dict) -> str:
    """
    Build a clear baseline sentence from OSM tags, then let a local
    BitNet model polish it. Falls back to the baseline if the model
    output is malformed.
    """
    elements = data.get("elements", [])
    total = len(elements)
    if total == 0:
        return "Sorry, I couldn't find any relevant places for your query."

    # — Collect up to three formatted item phrases ———————————————
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

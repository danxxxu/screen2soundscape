# overpass_to_osm.py

import os
import json
import requests
from requests.exceptions import HTTPError
from backend.utils.llama_singleton import get_llm

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# _llm = get_llm()


DEN_HAAG_CONTEXT = (
    "All queries should be scoped to Den Haag (’s-Gravenhage), "
    "admin_level=8, Netherlands."
)

def generate_overpass_query(question: str) -> str:
    prompt = (
        f"You are an expert at writing Overpass QL for OpenStreetMap. "
        f"{DEN_HAAG_CONTEXT}\n\n"
        f"Question: \"{question}\"\n\n"
        f"Return ONLY the Overpass QL query (no explanation)."
    )
    resp = _llm(prompt=prompt, max_tokens=60, temperature=0.3, stop=[";export", "; //"])
    q = resp["choices"][0]["text"].strip()
    if not q.endswith(";"):
        q += "\n;"
    return q

def run_overpass_query(query: str) -> dict:
    try:
        r = requests.post(OVERPASS_URL, data={"data": query})
        r.raise_for_status()
        return r.json()
    except HTTPError as e:
        raise RuntimeError(f"Overpass API error: {e}") from e

def summarize_results(question: str, data: dict) -> str:
    elements = data.get("elements", [])
    count = len(elements)

    # Compress context by extracting only top N points of interest
    compressed = []
    for el in elements[:3]:  # top 3 results only
        tags = el.get("tags", {})
        name = tags.get("name")
        type_ = tags.get("amenity") or tags.get("shop") or tags.get("tourism") or tags.get("leisure")
        address = tags.get("addr:street") or tags.get("addr:full") or "(no address)"

        if name and type_:
            compressed.append(f"- {name} ({type_}), located at {address}")
        elif name:
            compressed.append(f"- {name}, located at {address}")
        elif type_:
            compressed.append(f"- A {type_} located at {address}")

    details = "\n".join(compressed) if compressed else "No detailed information available."

    prompt = (
        f"The user asked: \"{question}\"\n"
        f"Here are some matching places:\n"
        f"{details}\n"
        "Summarize this into a short, helpful spoken sentence."
    )

    if not compressed:
        return "Sorry, I couldn't find any relevant places for your query."
    else:
        resp = _llm(prompt=prompt, max_tokens=40, temperature=0.1)
        text = resp["choices"][0]["text"].strip().replace("\n", " ")

        # De-duplicate sentences
        seen, out = set(), []
        for s in text.split(". "):
            s = s.strip().rstrip(".")
            if s and s not in seen:
                seen.add(s)
                out.append(s)

        return ". ".join(out) + "."


def summarize_route(directions_json):
    try:
        route = directions_json["routes"][0]
        leg = route["legs"][0]
        steps = leg["steps"]

        lines = []
        lines.append(f"The route is about {round(route['distance'] / 1000, 1)} kilometers and will take approximately {round(route['duration'] / 60)} minutes.")
        lines.append("Here are the step-by-step directions:")

        for i, step in enumerate(steps, 1):
            maneuver = step["maneuver"]
            instruction = f"{i}. {maneuver['instruction'] if 'instruction' in maneuver else maneuver.get('type', 'Move')}"
            if 'name' in step and step['name']:
                instruction += f" onto {step['name']}"
            if step.get('duration'):
                instruction += f" for about {round(step['duration'] / 60, 1)} minutes"
            lines.append(instruction)

        return "\n".join(lines)

    except Exception as e:
        return f"⚠️ Could not summarize route: {e}"


def process_question(question: str, save_json: bool = False, output_dir: str = "osm_assistant_output") -> str:
    ql = generate_overpass_query(question)
    try:
        data = run_overpass_query(ql)
    except RuntimeError as e:
        return f"❌ Error running Overpass query: {e}"

    if save_json:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "raw.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return summarize_results(question, data)

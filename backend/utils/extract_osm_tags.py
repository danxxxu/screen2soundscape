import requests
import json
from pathlib import Path
import os

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
# Directory for per-key cache files
CACHE_DIR = Path("../osm_tags/tag_values")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# List of core OSM keys to fetch
TAG_KEYS = [
    "amenity",
    "building",
    "highway",
    "landuse",
    "natural",
    "leisure",
    "shop",
    "tourism",
    "waterway",
    "barrier",
    "place",
    "railway",
    "boundary",
]


def fetch_tag_values(key, bbox=None, force_reload=False):
    """
    Fetch all distinct values for a given tag key from Overpass and return as a sorted list.
    Caches each key separately to {key}.json under CACHE_DIR.
    - key: the OSM tag key
    - bbox: tuple (south, west, north, east) to limit area (None = global)
    - force_reload: if True, re-queries Overpass even if cache exists
    """
    key_file = CACHE_DIR / f"{key}.json"
    # Return cached if available
    if key_file.exists() and not force_reload:
        return json.loads(key_file.read_text(encoding='utf-8'))

    # Build optional bbox filter
    bbox_str = f"({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]})" if bbox else ""
    # Overpass QL: fetch elements with the tag
    query = f"""
[out:json][timeout:180];
(
  node["{key}"]{bbox_str};
  way["{key}"]{bbox_str};
  rel["{key}"]{bbox_str};
);
out tags;
"""
    resp = requests.post(OVERPASS_URL, data={"data": query})
    resp.raise_for_status()
    data = resp.json()

    values = {el.get("tags", {}).get(key) for el in data.get("elements", []) if el.get("tags", {}).get(key)}
    result = sorted(values)

    # Write to per-key cache file
    key_file.write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def fetch_all_tag_values(bbox=None, force_reload=False):
    """
    Fetch values for all TAG_KEYS and return a dict mapping key -> list of values.
    """
    all_values = {}
    for key in TAG_KEYS:
        print(f"Fetching values for '{key}'...")
        values = fetch_tag_values(key, bbox=bbox, force_reload=force_reload)
        all_values[key] = values
    return all_values


if __name__ == "__main__":
    # Example: global fetch. Use a bbox tuple to limit (e.g. Paris).
    all_tag_values = fetch_all_tag_values(
        bbox=None,
        force_reload=False
    )
    # Print combined JSON
    print(json.dumps(all_tag_values, indent=2))  # or write to a file if desired
    # Combine into single JSON
    combined_file = CACHE_DIR.parent / 'all_osm_tags.json'
    combined_file.write_text(json.dumps(all_tag_values, indent=2), encoding='utf-8')
    print(f"✅ Wrote combined JSON to: {combined_file}")
    
    input_folder = r"../osm_tags/tag_values"
    output_file = os.path.join(input_folder, "all_osm_tags.json")

    combined_tags = {}

    # Loop through each file in the folder
    for filename in os.listdir(input_folder):
        if filename.endswith(".json") and filename != "all_osm_tags.json":
            file_path = os.path.join(input_folder, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    tag_list = json.load(f)
                    key = os.path.splitext(filename)[0]  # Remove .json extension
                    combined_tags[key] = tag_list
            except Exception as e:
                print(f"⚠️ Could not read {filename}: {e}")

    # Write the combined dictionary to a new JSON file
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(combined_tags, f, ensure_ascii=False, indent=2)
        print(f"✅ Combined JSON saved to {output_file}")
    except Exception as e:
        print(f"❌ Failed to write combined JSON: {e}")

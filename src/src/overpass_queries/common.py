import json
from collections import defaultdict, Counter

# Load the JSON file exported from Overpass Turbo
with open("data.json") as f:
    data = json.load(f)

# Keys of interest
target_keys = [
    "amenity", "shop", "highway", "leisure", "public_transport",
    "tourism", "craft", "office", "place", "building", "railway"
]

# Count values for each key
counts = {key: Counter() for key in target_keys}

for el in data.get("elements", []):
    tags = el.get("tags", {})
    for key in target_keys:
        if key in tags:
            counts[key][tags[key]] += 1

# Print results
for key in target_keys:
    print(f"\n== {key.upper()} ==")
    for value, count in counts[key].most_common():
        print(f"{value}: {count}")
# utils/osm_tags.py

TAG_MAP = {
    # --- Food & Drink ---
    "coffee shop": {"amenity": "cafe"},
    "cafe": {"amenity": "cafe"},
    "restaurant": {"amenity": "restaurant"},
    "fast food": {"amenity": "fast_food"},
    "bar": {"amenity": "bar"},
    "pub": {"amenity": "pub"},
    "bakery": {"shop": "bakery"},
    "supermarket": {"shop": "supermarket"},
    "grocery": {"shop": "convenience"},
    "pizza": {"cuisine": "pizza", "amenity": "restaurant"},
    "ice cream": {"amenity": "ice_cream"},

    # --- Transport ---
    "bus stop": {"highway": "bus_stop"},
    "train station": {"railway": "station"},
    "subway station": {"railway": "station", "station": "subway"},
    "bike rental": {"amenity": "bicycle_rental"},
    "taxi": {"amenity": "taxi"},

    # --- Money & Services ---
    "atm": {"amenity": "atm"},
    "bank": {"amenity": "bank"},
    "post office": {"amenity": "post_office"},
    "pharmacy": {"amenity": "pharmacy"},
    "hospital": {"amenity": "hospital"},
    "clinic": {"amenity": "clinic"},

    # --- Lodging & Tourism ---
    "hotel": {"tourism": "hotel"},
    "motel": {"tourism": "motel"},
    "hostel": {"tourism": "hostel"},
    "camping": {"tourism": "camp_site"},
    "museum": {"tourism": "museum"},
    "park": {"leisure": "park"},
    "playground": {"leisure": "playground"},

    # --- Entertainment ---
    "cinema": {"amenity": "cinema"},
    "theatre": {"amenity": "theatre"},
    "nightclub": {"amenity": "nightclub"},
    "stadium": {"leisure": "stadium"},

    # --- Shopping ---
    "mall": {"shop": "mall"},
    "clothes shop": {"shop": "clothes"},
    "electronics store": {"shop": "electronics"},
    "bookstore": {"shop": "books"},
    "shoe store": {"shop": "shoes"},
    "jewelry": {"shop": "jewelry"},
    "market": {"amenity": "marketplace"},

    # --- Other ---
    "toilets": {"amenity": "toilets"},
    "parking": {"amenity": "parking"},
    "library": {"amenity": "library"},
    "school": {"amenity": "school"},
    "university": {"amenity": "university"},
    "police": {"amenity": "police"},
    "fire station": {"amenity": "fire_station"},
}

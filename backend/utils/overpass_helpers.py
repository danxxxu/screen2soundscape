import heapq, math

def _haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dlmb/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def _elem_coords(el):
    if "lat" in el and "lon" in el:
        return float(el["lat"]), float(el["lon"])
    c = el.get("center")
    if isinstance(c, dict) and "lat" in c and "lon" in c:
        return float(c["lat"]), float(c["lon"])
    return None

def top_k_nearest(elements, center_lat, center_lon, k=5):
    heap = []        # max-heap of (-distance, idx, payload)
    seen = set()     # dedupe by (type,id)
    for idx, el in enumerate(elements or []):
        key = (el.get("type"), el.get("id"))
        if key in seen:
            continue
        seen.add(key)
        xy = _elem_coords(el)
        if not xy:
            continue
        d = _haversine_m(center_lat, center_lon, xy[0], xy[1])
        payload = (d, el, xy)
        if len(heap) < k:
            heapq.heappush(heap, (-d, idx, payload))
        else:
            if d < -heap[0][0]:
                heapq.heapreplace(heap, (-d, idx, payload))
    # to ascending distance
    out = []
    while heap:
        _, _, payload = heapq.heappop(heap)
        out.append(payload)
    out.sort(key=lambda t: t[0])

    results = []
    for d, el, (lat, lon) in out:
        results.append({
            "type": el.get("type"),
            "id": el.get("id"),
            "lat": lat,
            "lon": lon,
            "distance_m": round(d, 1),
            "tags": el.get("tags", {}),
        })
    return results

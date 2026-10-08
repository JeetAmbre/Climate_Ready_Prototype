"""Priority areas (Earth Engine) and recommendation building (plain Python lookup)."""
import ee
import config
from .recommendation_library import RECOMMENDATIONS, HAZARD_LABELS, ADDRESSES

PICK = 0   # which library entry to use when an indicator has several


def level_from_index(value):
    b = config.RISK_BREAKS
    return config.LEVELS[sum(value > x for x in b)]


def find_priority_areas(fw, risk_index, risk_class, area_rows, aoi, crs):
    """Zones of the highest risk class band that exists (High+ if present, otherwise Moderate).
    Returns a list of dicts: lat, lng, area_km2, mean risk, dominant indicators."""
    by_class = {r["class"]: r["area_km2"] for r in area_rows}
    if sum(by_class.get(c, 0) for c in (4, 5)) > 0:
        thr = 4
    elif by_class.get(3, 0) > 0:
        thr = 3
    else:
        return []
    mask = risk_class.gte(thr).selfMask().rename("m")
    zones = mask.reduceToVectors(
        geometry=aoi, scale=config.ANALYSIS_SCALE, crs=crs, geometryType="polygon", eightConnected=True,
        labelProperty="z", reducer=ee.Reducer.countEvery(), maxPixels=1e10, bestEffort=True, tileScale=4)

    def add_props(f):
        g = f.geometry()
        c = g.centroid(maxError=config.ANALYSIS_SCALE).coordinates()
        return f.set({"area_km2": g.area(maxError=config.ANALYSIS_SCALE).divide(1e6),
                      "lng": c.get(0), "lat": c.get(1)})

    zones = (zones.map(add_props).filter(ee.Filter.gte("area_km2", config.PRIORITY_MIN_ZONE_KM2))
             .sort("area_km2", False).limit(60))
    usable = [i for i in fw.indicators if i.available]      # indicators without data cannot be 'dominant'
    contrib = [i.norm.multiply(i.weight).rename(f"c_{i.key}") for i in usable]
    stack = ee.Image.cat([risk_index.rename("risk")] + contrib)
    zones = stack.reduceRegions(collection=zones, reducer=ee.Reducer.mean(), scale=config.ANALYSIS_SCALE,
                                crs=crs, tileScale=4)
    props = ["area_km2", "lng", "lat", "risk"] + [f"c_{i.key}" for i in usable]
    feats = zones.select(props, retainGeometry=False).getInfo()["features"]

    labels = {i.key: i.label for i in fw.indicators}
    out = []
    for f in feats:
        p = f["properties"]
        if p.get("risk") is None or p.get("lat") is None:
            continue
        contribs = sorted(((k[2:], p[k]) for k in p if k.startswith("c_") and p[k] is not None),
                          key=lambda kv: kv[1], reverse=True)
        out.append({"lat": p["lat"], "lng": p["lng"], "area_km2": p["area_km2"], "risk": p["risk"],
                    "level": level_from_index(p["risk"]),
                    "indicators": [{"key": k, "label": labels[k], "contribution": v} for k, v in contribs[:2]]})
    out.sort(key=lambda z: (z["risk"], z["area_km2"]), reverse=True)
    return out[:config.MAX_PINS_PER_HAZARD]


def build_recommendations(priority, place_lookup):
    """priority: {hazard: [zone,...]} -> flat list of recommendation dicts (library lookup only)."""
    recs, n = [], 0
    for hazard in ("uhi", "waterlogging", "air_pollution"):
        for z in priority.get(hazard, []):
            ind = z["indicators"][0]["key"]
            entry = RECOMMENDATIONS[hazard][ind][PICK]
            n += 1
            also = z["indicators"][1]["label"] if len(z["indicators"]) > 1 else ""
            recs.append({
                "id": n, "n": n, "hazard": hazard, "hazard_label": HAZARD_LABELS[hazard],
                "level": z["level"], "priority": f"{z['level'].upper()} PRIORITY",
                "place": place_lookup(z["lng"], z["lat"]) or "Selected area",
                "lat": z["lat"], "lng": z["lng"], "area_km2": z["area_km2"],
                "indicator": z["indicators"][0]["label"], "indicator_key": ind, "also": also,
                "action": entry["action"], "why": entry["why"], "addresses": ADDRESSES[hazard],
            })
    return recs

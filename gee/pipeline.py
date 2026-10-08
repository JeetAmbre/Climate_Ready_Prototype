"""One assessment = hazards + socio-economic -> final risk maps -> statistics -> layers.
Priority areas / recommendations and the hazard / indicator maps are produced later, on demand."""
import io
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee
import requests

import config
from . import common as C
from .uhi import generate_uhi
from .waterlogging import generate_waterlogging
from .air_pollution import generate_air_pollution
from .socioeconomic import generate_socioeconomic
from .statistics import compute_statistics
from .recommendations import find_priority_areas

HAZARDS = ["uhi", "waterlogging", "air_pollution"]
LEVEL_RANGES_RISK = ["0.20-1.16", "1.16-2.12", "2.12-3.08", "3.08-4.04", "4.04-5.00"]


def class_legend(title, palette, ranges=None):
    return {"type": "classes", "title": title,
            "items": [{"label": l, "color": "#" + palette[i], "range": (ranges or [""] * 5)[i]}
                      for i, l in enumerate(config.LEVELS)]}


def ramp_legend(ind):
    return {"type": "ramp", "title": ind.label, "palette": ["#" + c for c in ind.vis["palette"]],
            "min": ind.vis["min"], "max": ind.vis["max"], "unit": ind.unit}


def run_assessment(job):
    aoi = ee.Geometry(job.aoi["geojson"], None, False)
    cen = job.aoi["centroid"]
    crs = config.TARGET_CRS or C.utm_crs(cen["lng"], cen["lat"])
    job.crs = crs
    scale = config.ANALYSIS_SCALE

    job.step("prepare", "active")
    inputs = C.Inputs(aoi, config.START_DATE, config.END_DATE)
    job.step("prepare", "done")

    # The four frameworks are independent, so they run at the same time (much faster than one after another).
    tasks = {"uhi": ("uhi", generate_uhi), "waterlogging": ("water", generate_waterlogging),
             "air_pollution": ("air", generate_air_pollution), "socio": ("socio", generate_socioeconomic)}

    def build(key):
        step, fn = tasks[key]
        job.step(step, "active")
        fw = fn(aoi, inputs)
        job.step(step, "done")
        return fw

    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futures = {k: ex.submit(build, k) for k in tasks}
        fws = {k: f.result() for k, f in futures.items()}
    job.frameworks = fws
    for fw in fws.values():
        for ind in fw.unavailable():
            job.warnings.append(f"{fw.name}: {ind.label}")
        share = sum(i.weight for i in fw.unavailable())
        if share >= 0.5:
            job.warnings.append(f"{fw.name}: more than half of the indicator weight had no data, so this result is not reliable.")

    # ---- final risk: hazard * socio / 5, then 5 classes ----
    job.step("risk", "active")
    fix = lambda img, name: img.rename(name).setDefaultProjection(crs, None, scale).clip(aoi)
    socio_idx = fix(fws["socio"].index, "SocioEconomic_Vulnerability_Index")
    risk, risk_cls, hazard_cls, hazard_idx = {}, {}, {}, {}
    for k in HAZARDS:
        hz = fix(fws[k].index, f"{k}_hazard")
        hazard_idx[k] = hz
        hazard_cls[k] = C.classify(hz, config.INDEX_BREAKS, f"{k}_hazard_class", aoi)
        risk[k] = fix(hz.multiply(socio_idx).divide(5), f"{k}_final_risk")
        risk_cls[k] = C.classify(risk[k], config.RISK_BREAKS, f"{k}_final_risk_class", aoi)
    job.risk, job.risk_cls = risk, risk_cls
    job.step("risk", "done")

    # ---- layer registry (images are rendered lazily / in the background) ----
    job.step("layers", "active")
    names = {"uhi": "UHI", "waterlogging": "Waterlogging", "air_pollution": "Air Pollution"}
    L = job.layers
    for k in HAZARDS:
        pal = C.PALETTES[k]
        L[f"risk_{k}"] = dict(label=f"{names[k]} Risk", group="risk", hazard=k, image=risk_cls[k],
                              vis=dict(min=1, max=5, palette=pal),
                              legend=class_legend(f"{names[k]} Risk", pal, LEVEL_RANGES_RISK))
        L[f"hazard_{k}"] = dict(label=f"{names[k]} Hazard (before socio-economic weighting)", group="hazard", hazard=k,
                                image=hazard_cls[k], vis=dict(min=1, max=5, palette=pal),
                                legend=class_legend(f"{names[k]} Hazard", pal))
    for k, fw in fws.items():
        for ind in fw.indicators:
            L[f"ind_{k}_{ind.key}"] = dict(label=ind.label, group="indicator", hazard=k, image=ind.raw.rename(ind.key),
                                           vis=ind.vis, legend=ramp_legend(ind), unit=ind.unit, available=ind.available)

    # image used for click inspection (all values in one multi-band image)
    bands = []
    for k in HAZARDS:
        bands += [risk[k].rename(f"{k}__risk"), risk_cls[k].rename(f"{k}__riskcls"), hazard_idx[k].rename(f"{k}__hazard")]
    bands += [socio_idx.rename("socio__index")]
    for k, fw in fws.items():
        for ind in fw.indicators:
            bands += [ind.raw.rename(f"{k}__raw__{ind.key}"), ind.norm.rename(f"{k}__score__{ind.key}")]
    job.point_image = ee.Image.cat(bands)
    job.step("layers", "done")

    # ---- statistics and pre-rendering of the three main risk maps ----
    job.step("stats", "active")
    stats = compute_statistics(aoi, risk_cls, fws["socio"].population, crs)
    job.stats = {
        "overview": {"location": job.label, "area_km2": job.aoi["area_km2"],
                     "population": stats["total_population"], "lat": cen["lat"], "lng": cen["lng"]},
        "hazards": {k: dict(stats["hazards"][k], name=fws[k].name) for k in HAZARDS},
    }
    job.step("stats", "done")

    job.step("render", "active")
    render_risk_maps(job)
    job.step("render", "done")


def compute_priority(job, on_done=None):
    """Priority areas for all three hazards (run only when the user asks for recommendations).
    Returns ({hazard: [zones]}, [notes about hazards that failed])."""
    aoi = ee.Geometry(job.aoi["geojson"], None, False)

    def one(k):
        try:
            zones = find_priority_areas(job.frameworks[k], job.risk[k], job.risk_cls[k],
                                        job.stats["hazards"][k]["rows"], aoi, job.crs)
            return k, zones, None
        except Exception as exc:
            print(f"[priority] {k} failed: {exc}")
            return k, [], str(exc)

    result, notes = {}, []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for fut in as_completed([ex.submit(one, k) for k in HAZARDS]):
            k, zones, error = fut.result()
            result[k] = zones
            if error:
                notes.append(f"{job.frameworks[k].name}: priority areas could not be identified.")
            if on_done:
                on_done()
    return {k: result[k] for k in HAZARDS}, notes


# ---------------------------------------------------------------- on-demand helpers
def tile_url(job, layer_id):
    if layer_id not in job.tile_cache:
        lyr = job.layers[layer_id]
        mapid = lyr["image"].getMapId(lyr["vis"])
        job.tile_cache[layer_id] = mapid["tile_fetcher"].url_format
    return job.tile_cache[layer_id]


def point_info(job, lat, lng):
    pt = ee.Geometry.Point([lng, lat])
    vals = job.point_image.reduceRegion(reducer=ee.Reducer.first(), geometry=pt, scale=config.ANALYSIS_SCALE,
                                        maxPixels=1e9).getInfo()
    return vals


OVERLAY_MAX = 650           # longest side (pixels) of the browser overlay image
OVERLAY_CRS = "EPSG:3857"   # same projection as the web map, so the overlay lines up exactly
GRAY_CODES = ["000000", "404040", "808080", "c0c0c0", "ffffff"]   # class 1..5 as plain grey levels

_locks, _locks_guard = {}, threading.Lock()


def _lock_for(job, key):
    with _locks_guard:
        return _locks.setdefault((job.id, key), threading.Lock())


def _thumb(job, visualized, width, crs):
    """Download one Earth Engine thumbnail (PNG bytes) covering the area's bounding box."""
    minx, miny, maxx, maxy = job.aoi["bounds"]
    url = visualized.getThumbURL({
        "region": ee.Geometry.Rectangle([minx, miny, maxx, maxy], "EPSG:4326", False),
        "dimensions": width, "format": "png", "crs": crs})
    data = requests.get(url, timeout=300).content
    if data[:4] != b"\x89PNG":
        raise RuntimeError("Earth Engine did not return an image: " + data[:200].decode("utf-8", "ignore"))
    return data


def map_png(job, layer_id, width=900, outline=True, crs="EPSG:4326"):
    """PNG of one layer clipped to the AOI with a boundary line (used by the PDF report)."""
    key = (layer_id, width, outline, crs)
    with _lock_for(job, key):
        if key in job.png_cache:
            return job.png_cache[key]
        lyr = job.layers[layer_id]
        aoi = ee.Geometry(job.aoi["geojson"], None, False)
        img = lyr["image"].visualize(**lyr["vis"])
        if outline:
            edge = ee.Image().byte().paint(ee.FeatureCollection([ee.Feature(aoi)]), 1, 2).visualize(palette=["17201A"])
            img = ee.ImageCollection([img, edge]).mosaic()
        job.png_cache[key] = _thumb(job, img, width, crs)
        return job.png_cache[key]


def recolor_classes(gray_png, palette):
    """Takes the grey-coded class image from Earth Engine (class 1..5 -> 0/64/128/192/255) and paints it with
    a strong palette, fully opaque. Saved as a small palette PNG (decodes fast, even on phones)."""
    import numpy as np
    from PIL import Image
    a = np.array(Image.open(io.BytesIO(gray_png)).convert("RGBA"))
    code = np.clip(np.rint(a[..., 0].astype(float) / 63.75), 0, 4).astype(np.uint8)
    valid = a[..., 3] > 0                                  # any partial transparency -> fully opaque
    counts = {c + 1: int(((code == c) & valid).sum()) for c in range(5)}
    nz = a[..., 3][valid]
    print(f"[overlay] {a.shape[1]}x{a.shape[0]} px, coloured {100 * valid.mean():.1f}%, class pixel counts {counts}, "
          f"source alpha mean/min {nz.mean() if nz.size else 0:.0f}/{nz.min() if nz.size else 0}")
    if valid.mean() < 0.005:
        raise RuntimeError("the rendered map is empty (no valid pixels)")
    img = Image.fromarray(np.where(valid, code + 1, 0).astype(np.uint8), "P")   # index 0 = transparent
    flat = [0, 0, 0]
    for c in palette:
        flat += [int(c[i:i + 2], 16) for i in (0, 2, 4)]
    img.putpalette(flat + [0] * (768 - len(flat)))
    buf = io.BytesIO()
    img.save(buf, "PNG", transparency=0, optimize=True)
    return buf.getvalue()


def overlay_width(job):
    """About one pixel per 100 m analysis cell (never finer: finer rendering makes Earth Engine redo the
    heavy distance calculations at a higher resolution and it can time out)."""
    minx, miny, maxx, maxy = job.aoi["bounds"]
    km = max((maxx - minx) * 111.32 * math.cos(math.radians((miny + maxy) / 2)), (maxy - miny) * 110.57)
    return int(min(OVERLAY_MAX, max(300, km * 1000 / config.ANALYSIS_SCALE)))


def overlay_png(job, layer_id):
    key = ("overlay", layer_id)
    with _lock_for(job, key):
        if key in job.png_cache:
            return job.png_cache[key]
        lyr = job.layers[layer_id]
        coded = lyr["image"].visualize(min=1, max=5, palette=GRAY_CODES)
        width, last = overlay_width(job), None
        for attempt in range(2):                      # second attempt: smaller image
            try:
                gray = _thumb(job, coded, width, OVERLAY_CRS)
                job.png_cache[key] = recolor_classes(gray, lyr["vis"]["palette"])
                return job.png_cache[key]
            except Exception as exc:
                last = exc
                width = max(300, int(width * 0.6))
        if last is not None:
            raise last
        raise RuntimeError(f"Could not render overlay for {layer_id}")


def render_risk_maps(job):
    """Pre-render all three main risk maps so they are ready
    immediately as soon as the assessment completes."""
    def one(hazard):
        if job.cancelled:
            return
        layer_id = f"risk_{hazard}"
        try:
            overlay_png(job, layer_id)
        except Exception as exc:        # not fatal: the browser falls back to normal map tiles
            print(f"[overlay] {layer_id} could not be pre-rendered: {exc}")

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [ex.submit(one, k) for k in HAZARDS]
        for f in futures:
            f.result()

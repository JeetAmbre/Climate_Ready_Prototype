"""Shared Earth Engine helpers. Ported from ClimateReady_Master_GEE_FINAL.js (methodology unchanged)."""
from dataclasses import dataclass, field

import ee

import config

# ---- Palettes (from the master script) ----
PALETTES = {
    # Class colours: same hue families as the research palettes, but every class is strongly
    # coloured (no near-white) so the five levels stay clearly distinguishable on a base map.
    "uhi": ["ffe600", "ffa000", "ff5400", "d00000", "5c0010"],
    "waterlogging": ["00e5ff", "2f9bff", "1c46e0", "2a0fa8", "0a0a4d"],
    "air_pollution": ["f1a6ff", "c25cff", "8f1fe0", "5b0fa6", "2a0463"],
    "socio": ["e8f8ee", "a8e6c1", "5fd08d", "22a860", "046c3c"],
}
# Indicator colour ramps used in the master script
RAMP_TEMP = ["313695", "74add1", "ffffbf", "f46d43", "a50026"]
RAMP_NDBI = ["2c7bb6", "abd9e9", "ffffbf", "fdae61", "d7191c"]
RAMP_NDVI = ["8c510a", "d8b365", "f6e8c3", "c7eae5", "5ab4ac", "01665e"]
RAMP_ALBEDO = ["081d58", "225ea8", "41b6c4", "a1dab4", "ffffcc"]
RAMP_DEM = ["440154", "31688e", "35b779", "fde725"]
RAMP_BLUES_SLOPE = ["ffffcc", "a1dab4", "41b6c4", "225ea8", "081d58"]
RAMP_DIST = ["08519c", "3182bd", "6baed6", "c6dbef", "f7fbff"]
RAMP_GREENS = ["ffffcc", "a1d76a", "41ab5d", "238443", "005a32"]
RAMP_IMPERV = ["ffffcc", "c2e699", "78c679", "31a354", "006837"]
RAMP_WIND = ["67001f", "b2182b", "f4a582", "fddbc7", "d1e5f0", "67a9cf", "2166ac"]
RAMP_POP = ["e5f5e0", "a1d99b", "74c476", "238b45", "00441b"]
RAMP_POP_REV = list(reversed(RAMP_POP))


@dataclass
class Indicator:
    key: str            # short id, e.g. "LST"
    label: str          # shown to the user
    unit: str
    weight: float
    raw: ee.Image       # what the user sees
    norm: ee.Image      # 1-5 vulnerability score (after any inversion)
    vis: dict           # min / max / palette for display
    higher_means: str = ""   # plain-language note for point popups
    available: bool = True   # False when no data exists for this indicator in the selected area


@dataclass
class Framework:
    key: str            # uhi / waterlogging / air_pollution / socio
    name: str
    index: ee.Image     # continuous 1-5 index
    indicators: list = field(default_factory=list)
    weights: dict = field(default_factory=dict)

    def unavailable(self):
        return [i for i in self.indicators if not i.available]


def init_earth_engine():
    if config.EE_SERVICE_ACCOUNT and (config.EE_PRIVATE_KEY_DATA or config.EE_PRIVATE_KEY_FILE):
        if config.EE_PRIVATE_KEY_DATA:
            creds = ee.ServiceAccountCredentials(config.EE_SERVICE_ACCOUNT, key_data=config.EE_PRIVATE_KEY_DATA)
        else:
            creds = ee.ServiceAccountCredentials(config.EE_SERVICE_ACCOUNT, key_file=config.EE_PRIVATE_KEY_FILE)
        ee.Initialize(creds, project=config.EE_PROJECT or None)
    else:
        ee.Initialize(project=config.EE_PROJECT or None)


def utm_crs(lon, lat):
    zone = int((lon + 180) // 6) + 1
    return f"EPSG:{(32600 if lat >= 0 else 32700) + zone}"


# ---------------- normalisation (same maths as normalizeTo1_5) ----------------
def stretch_values(images, aoi, scale):
    """2nd / 98th percentile of every image, normally in ONE Earth Engine call.
    images: {band_name: ee.Image}. Returns {band_name: (lo, hi)} or {band_name: None} when that layer
    has no valid data in the area (the app then carries on without it instead of failing).
    (The research scripts compute these lazily inside the image graph; we evaluate them once
    so map tiles do not recompute percentiles. The numbers are identical.)"""
    def run(subset):
        stack = ee.Image.cat([img.rename(name) for name, img in subset.items()])
        return stack.reduceRegion(
            reducer=ee.Reducer.percentile([2, 98]), geometry=aoi, scale=scale,
            maxPixels=1e13, bestEffort=True, tileScale=4).getInfo()

    try:
        stats = run(images)
    except Exception as exc:        # e.g. one dataset is unreachable: retry layer by layer
        print(f"[gee] combined percentile call failed ({exc}); retrying layer by layer")
        stats = {}
        for name, img in images.items():
            try:
                stats.update(run({name: img}))
            except Exception as exc2:
                print(f"[gee] {name}: no usable data ({exc2})")
    out = {}
    for name in images:
        lo, hi = stats.get(f"{name}_p2"), stats.get(f"{name}_p98")
        out[name] = None if lo is None or hi is None else (lo, hi)
        if out[name] is None:
            print(f"[gee] WARNING: no valid data for '{name}' in this area - neutral score will be used")
    return out


class Scorer:
    """Turns a raw layer into its 1-5 score. If the layer has no data, returns the neutral midpoint (3),
    the same neutral value the research scripts use for gap-filling, and records the layer as missing."""

    def __init__(self, stretch):
        self.st, self.missing = stretch, []

    def __call__(self, name, img):
        s = self.st.get(name)
        if s is None:
            self.missing.append(name)
            return ee.Image(3).rename(name)
        return normalize(img, *s).rename(name)


def mark_unavailable(indicators, missing, alias=None):
    """Flag indicators whose layer had no data. alias maps indicator key -> stretch name when they differ."""
    alias = alias or {}
    for ind in indicators:
        if alias.get(ind.key, ind.key) in missing:
            ind.available = False


def normalize(image, lo, hi):
    rng = hi - lo
    if rng == 0:
        rng = 1
    return image.subtract(lo).divide(rng).clamp(0, 1).multiply(4).add(1).unmask(3)


def invert(image, name):
    return ee.Image(6).subtract(image).rename(name)


def weighted_sum(pairs, name):
    total = None
    for img, w in pairs:
        part = img.multiply(w)
        total = part if total is None else total.add(part)
    return total.rename(name)


def classify(index, breaks, name, aoi):
    b = breaks
    return (ee.Image(1).where(index.gt(b[0]), 2).where(index.gt(b[1]), 3)
            .where(index.gt(b[2]), 4).where(index.gt(b[3]), 5)
            .rename(name)
            # Make the mask strictly on/off: any pixel with a (partial) value becomes fully opaque.
            # Without this, risk maps (hazard x socio-economic) kept fractional transparency from the
            # resampled population layers and looked faded.
            .updateMask(index.mask().gt(0)).clip(aoi))


def lulc_score(aoi, to_values):
    worldcover = ee.ImageCollection("ESA/WorldCover/v200").first().clip(aoi)
    from_values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100]
    return worldcover.select("Map").remap(from_values, to_values).rename("LULC").clip(aoi)


class Inputs:
    """Sentinel-2 / Landsat inputs shared by several frameworks (built once per assessment)."""

    def __init__(self, aoi, start, end):
        self.aoi, self.start, self.end = aoi, start, end
        s2c = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(aoi)
               .filterDate(start, end).filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 20))
               .map(self._mask_s2))
        s2 = s2c.median().clip(aoi)
        self.ndvi = s2.normalizedDifference(["B8", "B4"]).rename("NDVI")
        self.ndbi = s2.normalizedDifference(["B11", "B8"]).rename("NDBI")
        self.landsat = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                        .merge(ee.ImageCollection("LANDSAT/LC09/C02/T1_L2"))
                        .filterBounds(aoi).filterDate(start, end)
                        .filter(ee.Filter.lt("CLOUD_COVER", 30)).map(self._mask_landsat))
        self.lst = self.landsat.map(
            lambda img: img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")
        ).mean().clip(aoi)

    @staticmethod
    def _mask_s2(image):
        scl = image.select("SCL")
        mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
        return image.updateMask(mask)

    @staticmethod
    def _mask_landsat(image):
        qa = image.select("QA_PIXEL")
        ok = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0)).And(qa.bitwiseAnd(1 << 2).eq(0))
        return image.updateMask(ok)

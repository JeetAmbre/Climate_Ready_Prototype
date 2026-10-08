"""Waterlogging hazard (port of buildWaterlogging). 9 indicators."""
import ee
import config
from . import common as C

WEIGHTS = {"dem": 0.210, "slope": 0.207, "distWater": 0.173, "rainfall": 0.125, "lulc": 0.101,
           "impervious": 0.076, "distDrain": 0.058, "ndvi": 0.031, "soil": 0.019}
PAL = C.PALETTES["waterlogging"]
ACCUMULATION_THRESHOLD = 500   # upstream cells; tune per basin (as in the research script)


def generate_waterlogging(aoi, inputs):
    start, end = inputs.start, inputs.end
    dem = ee.Image("USGS/SRTMGL1_003").clip(aoi).rename("DEM")
    slope = ee.Terrain.slope(dem).rename("Slope")

    gsw = ee.Image("JRC/GSW1_4/GlobalSurfaceWater").clip(aoi)
    water = gsw.select("occurrence").gt(50).unmask(0)
    dist_water = ee.Image(1).cumulativeCost(source=water, maxDistance=10000).rename("DistWater").clip(aoi)

    flow = ee.Image("WWF/HydroSHEDS/15ACC").clip(aoi)
    drain = flow.gt(ACCUMULATION_THRESHOLD).unmask(0)
    dist_drain = ee.Image(1).cumulativeCost(source=drain, maxDistance=10000).rename("DistDrain").clip(aoi)

    rain = (ee.ImageCollection("UCSB-CHG/CHIRPS/DAILY").filterBounds(aoi).filterDate(start, end)
            .sum().clip(aoi).rename("Rainfall"))
    lulc = C.lulc_score(aoi, [1, 2, 2, 3, 5, 3, 1, 5, 5, 4, 2])
    imperv = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(aoi).filterDate(start, end)
              .select("built").mean().clip(aoi).rename("Impervious"))
    soil = ee.Image("projects/soilgrids-isric/clay_mean").select("clay_0-5cm_mean").clip(aoi).rename("Soil")
    ndvi = inputs.ndvi

    st = C.stretch_values({"DEM": dem, "Slope": slope, "DistWater": dist_water, "DistDrain": dist_drain,
                           "NDVI": ndvi, "Rainfall": rain, "Impervious": imperv, "Soil": soil}, aoi, config.STRETCH_SCALE)
    n = C.Scorer(st)
    dem_n = C.invert(n("DEM", dem), "DEM")
    slope_n = C.invert(n("Slope", slope), "Slope")
    dw_n = C.invert(n("DistWater", dist_water), "DistWater")
    dd_n = C.invert(n("DistDrain", dist_drain), "DistDrain")
    ndvi_n = C.invert(n("NDVI", ndvi), "NDVI")
    rain_n, imp_n, soil_n = n("Rainfall", rain), n("Impervious", imperv), n("Soil", soil)
    lulc_n = lulc.unmask(3)

    w = WEIGHTS
    index = C.weighted_sum([(dem_n, w["dem"]), (slope_n, w["slope"]), (dw_n, w["distWater"]),
                            (rain_n, w["rainfall"]), (lulc_n, w["lulc"]), (imp_n, w["impervious"]),
                            (dd_n, w["distDrain"]), (ndvi_n, w["ndvi"]), (soil_n, w["soil"])],
                           "Waterlogging_Vulnerability_Index").clip(aoi)
    I = C.Indicator
    inds = [
        I("DEM", "DEM (Elevation)", "m", w["dem"], dem, dem_n, dict(min=0, max=300, palette=C.RAMP_DEM)),
        I("Slope", "Slope", "°", w["slope"], slope, slope_n, dict(min=0, max=20, palette=C.RAMP_BLUES_SLOPE)),
        I("DistWater", "Distance to water bodies", "m", w["distWater"], dist_water, dw_n, dict(min=0, max=5000, palette=C.RAMP_DIST)),
        I("Rainfall", "Rainfall (annual total)", "mm", w["rainfall"], rain, rain_n, dict(min=500, max=3000, palette=C.RAMP_GREENS)),
        I("LULC", "LULC (waterlogging score)", "score 1-5", w["lulc"], lulc, lulc_n, dict(min=1, max=5, palette=PAL)),
        I("Impervious", "Impervious surface", "", w["impervious"], imperv, imp_n, dict(min=0, max=1, palette=C.RAMP_IMPERV)),
        I("DistDrain", "Distance to drainage", "m", w["distDrain"], dist_drain, dd_n, dict(min=0, max=5000, palette=C.RAMP_DIST)),
        I("NDVI", "NDVI (Vegetation Index)", "", w["ndvi"], ndvi, ndvi_n, dict(min=-0.2, max=1, palette=C.RAMP_NDVI)),
        I("Soil", "Soil (clay content)", "", w["soil"], soil, soil_n, dict(min=0, max=600, palette=C.RAMP_IMPERV)),
    ]
    C.mark_unavailable(inds, n.missing)
    return C.Framework("waterlogging", "Waterlogging", index, inds, WEIGHTS)

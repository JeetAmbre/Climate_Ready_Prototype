"""Air-pollution hazard (port of buildAirPollution). Indicators: road density, LST, NDBI, wind, NDVI."""
import ee
import config
from . import common as C

WEIGHTS = {"roadDens": 0.43, "ndbi": 0.18, "lst": 0.28, "windSPD": 0.07, "ndvi": 0.04}


def generate_air_pollution(aoi, inputs):
    roads = ee.FeatureCollection(f"projects/sat-io/open-datasets/GRIP4/{config.GRIP4_REGION}").filterBounds(aoi)
    road_raster = ee.Image().byte().paint(roads, 1, 2).clip(aoi)
    road_density = (road_raster.unmask(0)
                    .reduceNeighborhood(reducer=ee.Reducer.sum(), kernel=ee.Kernel.circle(radius=500, units="meters"))
                    .rename("RoadDens").clip(aoi))

    era5 = (ee.ImageCollection("ECMWF/ERA5_LAND/MONTHLY_AGGR").filterBounds(aoi)
            .filterDate(inputs.start, inputs.end))
    wind_speed = era5.map(lambda img: img.select("u_component_of_wind_10m")
                          .hypot(img.select("v_component_of_wind_10m")).rename("wind_speed")).mean().clip(aoi)
    wind_vuln = wind_speed.multiply(-1).rename("WindDir")   # low wind speed -> high vulnerability

    st = C.stretch_values({"NDBI": inputs.ndbi, "RoadDens": road_density, "WindDir": wind_vuln,
                           "LST": inputs.lst, "NDVI": inputs.ndvi}, aoi, config.STRETCH_SCALE)
    n = C.Scorer(st)
    ndbi_n, road_n, wind_n, lst_n = n("NDBI", inputs.ndbi), n("RoadDens", road_density), n("WindDir", wind_vuln), n("LST", inputs.lst)
    ndvi_n = C.invert(n("NDVI", inputs.ndvi), "NDVI")

    w = WEIGHTS
    index = C.weighted_sum([(road_n, w["roadDens"]), (ndbi_n, w["ndbi"]), (lst_n, w["lst"]),
                            (wind_n, w["windSPD"]), (ndvi_n, w["ndvi"])], "Vulnerability_Index")
    I = C.Indicator
    inds = [
        I("RoadDens", "Road density", "", w["roadDens"], road_density, road_n, dict(min=0, max=100, palette=C.RAMP_GREENS)),
        I("LST", "LST (Land Surface Temperature)", "°C", w["lst"], inputs.lst, lst_n, dict(min=20, max=45, palette=C.RAMP_TEMP)),
        I("NDBI", "NDBI (Built-up Index)", "", w["ndbi"], inputs.ndbi, ndbi_n, dict(min=-0.5, max=0.8, palette=C.RAMP_NDBI)),
        I("WindSpeed", "Wind speed", "m/s", w["windSPD"], wind_speed, wind_n, dict(min=0, max=8, palette=C.RAMP_WIND)),
        I("NDVI", "NDVI (Vegetation Index)", "", w["ndvi"], inputs.ndvi, ndvi_n, dict(min=-0.2, max=1, palette=C.RAMP_NDVI)),
    ]
    C.mark_unavailable(inds, n.missing, alias={"WindSpeed": "WindDir"})
    return C.Framework("air_pollution", "Air Pollution", index, inds, WEIGHTS)

"""Socio-economic vulnerability (port of buildSocioEconomic). Normalised on the 100 m analysis grid."""
import ee
import config
from . import common as C

WEIGHTS = {"popDens": 0.2851, "hhDens": 0.2355, "children": 0.1848, "lulc": 0.1447,
           "hospital": 0.1130, "residential": 0.0369}
PAL = C.PALETTES["socio"]
WORLDPOP_CELL_AREA = 92.77 * 92.77
MAX_DIST = 10000


def generate_socioeconomic(aoi, inputs):
    pop = (ee.ImageCollection("WorldPop/GP/100m/pop").filterBounds(aoi).filter(ee.Filter.eq("year", 2020))
           .mosaic().select("population"))
    pop_dens = pop.divide(WORLDPOP_CELL_AREA).multiply(1e6).clip(aoi).rename("PopDens")

    age = ee.ImageCollection("WorldPop/GP/100m/pop_age_sex").filterBounds(aoi).mosaic()
    child_count = age.select(["M_0", "M_1", "M_5", "M_10", "F_0", "F_1", "F_5", "F_10"]).reduce(ee.Reducer.sum())
    child_dens = child_count.divide(WORLDPOP_CELL_AREA).multiply(1e6).clip(aoi).rename("Children")

    built_s = ee.Image("JRC/GHSL/P2023A/GHS_BUILT_S/2020")
    res_surface = built_s.select("built_surface").subtract(built_s.select("built_surface_nres"))
    hh_dens = res_surface.divide(100 * 100).clip(aoi).rename("HHDens")

    lulc = C.lulc_score(aoi, [1, 2, 2, 3, 5, 2, 1, 1, 1, 1, 1])

    built_c = ee.Image("JRC/GHSL/P2023A/GHS_BUILT_C/2018").select("built_characteristics")
    residential = built_c.gte(11).And(built_c.lte(15)).clip(aoi).rename("Residential")

    search_area = aoi.buffer(MAX_DIST)
    nodes = ee.FeatureCollection("projects/sat-io/open-datasets/health-site-node").filterBounds(search_area)
    ways = ee.FeatureCollection("projects/sat-io/open-datasets/health-site-way").filterBounds(search_area)
    facilities = ee.Image().byte().paint(nodes, 1).paint(ways, 1).unmask(0)
    hospital = (ee.Image(1).cumulativeCost(source=facilities, maxDistance=MAX_DIST)
                .unmask(MAX_DIST).clip(aoi).rename("Hospital"))

    st = C.stretch_values({"PopDens": pop_dens, "HHDens": hh_dens, "Children": child_dens,
                           "Residential": residential, "Hospital": hospital}, aoi, config.ANALYSIS_SCALE)
    n = C.Scorer(st)
    pop_n, hh_n, child_n = n("PopDens", pop_dens), n("HHDens", hh_dens), n("Children", child_dens)
    res_n, hosp_n = n("Residential", residential), n("Hospital", hospital)
    lulc_n = lulc.unmask(3)

    w = WEIGHTS
    index = C.weighted_sum([(pop_n, w["popDens"]), (hh_n, w["hhDens"]), (child_n, w["children"]),
                            (lulc_n, w["lulc"]), (hosp_n, w["hospital"]), (res_n, w["residential"])],
                           "SocioEconomic_Vulnerability_Index")
    I = C.Indicator
    inds = [
        I("PopDens", "Population density", "persons/km²", w["popDens"], pop_dens, pop_n, dict(min=0, max=20000, palette=C.RAMP_POP)),
        I("HHDens", "Household density (proxy)", "", w["hhDens"], hh_dens, hh_n, dict(min=0, max=1, palette=C.RAMP_POP)),
        I("Children", "Children (0-14) density", "children/km²", w["children"], child_dens, child_n, dict(min=0, max=5000, palette=C.RAMP_POP)),
        I("LULC", "LULC (exposure score)", "score 1-5", w["lulc"], lulc, lulc_n, dict(min=1, max=5, palette=PAL)),
        I("Hospital", "Distance to hospital", "m", w["hospital"], hospital, hosp_n, dict(min=0, max=10000, palette=C.RAMP_POP_REV)),
        I("Residential", "Residential fraction", "", w["residential"], residential, res_n, dict(min=0, max=1, palette=C.RAMP_POP)),
    ]
    C.mark_unavailable(inds, n.missing)
    fw = C.Framework("socio", "Socio-economic", index, inds, WEIGHTS)
    fw.population = pop     # WorldPop 2020 persons per cell, used for population statistics
    return fw

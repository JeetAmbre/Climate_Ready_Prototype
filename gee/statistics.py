"""Area and population statistics, calculated from the FINAL risk class maps (master script section 13).

Speed: all hazards, area and population are computed in ONE Earth Engine reduction. Each pixel gets a
combined code (UHI class, waterlogging class); the per-hazard totals are summed from it in Python.
The numbers are identical to computing each hazard separately, but Earth Engine evaluates the heavy
risk calculation once instead of multiple times."""
import ee
import config


def compute_statistics(aoi, risk_classes, population, crs):
    """risk_classes: {'uhi': ee.Image, 'waterlogging': ...}."""
    keys = list(risk_classes)
    code = None
    for k in keys:                                  # base-5 code, first hazard most significant
        c = risk_classes[k].subtract(1)
        code = c if code is None else code.multiply(5).add(c)
    stack = ee.Image.cat([
        ee.Image.pixelArea().divide(1e6).rename("a"),
        population.rename("p").unmask(0),
        code.rename("k"),
    ])
    groups = stack.reduceRegion(
        reducer=ee.Reducer.sum().repeat(2).group(groupField=2, groupName="k"),
        geometry=aoi, scale=config.ANALYSIS_SCALE, crs=crs, bestEffort=True, maxPixels=1e13, tileScale=4,
    ).get("groups").getInfo() or []

    area = {k: [0.0] * 5 for k in keys}
    pop = {k: [0.0] * 5 for k in keys}
    for g in groups:
        kk, (a, p) = int(g["k"]), g["sum"]
        digits = []
        for _ in keys:
            digits.append(kk % 5)
            kk //= 5
        for hz, d in zip(keys, reversed(digits)):
            area[hz][d] += a or 0
            pop[hz][d] += p or 0

    out = {"total_population": sum(pop[keys[0]]), "hazards": {}}
    for hz in keys:
        a_tot, p_tot = sum(area[hz]), sum(pop[hz])
        rows = [{"class": i + 1, "level": config.LEVELS[i], "area_km2": area[hz][i],
                 "area_pct": 100 * area[hz][i] / a_tot if a_tot else 0,
                 "population": pop[hz][i], "population_pct": 100 * pop[hz][i] / p_tot if p_tot else 0}
                for i in range(5)]
        out["hazards"][hz] = {"rows": rows, "area_total": a_tot, "pop_total": p_tot}
    return out

"""Urban Heat Island hazard (port of buildUHI). Indicators: LST, NDBI, LULC, NDVI, Albedo."""
import ee
import config
from . import common as C

WEIGHTS = {"lst": 0.411, "ndbi": 0.205, "lulc": 0.128, "ndvi": 0.192, "albedo": 0.063}
PAL = C.PALETTES["uhi"]


def generate_uhi(aoi, inputs):
    # Albedo: Liang (2001) broadband formula on Landsat 8/9 SR
    def albedo_fn(img):
        r = img.select(["SR_B2", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]).multiply(0.0000275).add(-0.2)
        return (r.select("SR_B2").multiply(0.356).add(r.select("SR_B4").multiply(0.130))
                .add(r.select("SR_B5").multiply(0.373)).add(r.select("SR_B6").multiply(0.085))
                .add(r.select("SR_B7").multiply(0.072)).subtract(0.0018).rename("Albedo"))
    albedo = inputs.landsat.map(albedo_fn).mean().clip(aoi)
    lulc = C.lulc_score(aoi, [1, 2, 2, 3, 5, 4, 1, 1, 1, 1, 2])

    st = C.stretch_values({"LST": inputs.lst, "NDBI": inputs.ndbi, "NDVI": inputs.ndvi, "Albedo": albedo}, aoi, config.STRETCH_SCALE)
    n = C.Scorer(st)
    lst_n, ndbi_n = n("LST", inputs.lst), n("NDBI", inputs.ndbi)
    ndvi_n = C.invert(n("NDVI", inputs.ndvi), "NDVI")        # high NDVI -> low vulnerability
    albedo_n = C.invert(n("Albedo", albedo), "Albedo")       # high albedo -> low vulnerability
    lulc_n = lulc.unmask(3)

    w = WEIGHTS
    index = C.weighted_sum([(lst_n, w["lst"]), (ndbi_n, w["ndbi"]), (lulc_n, w["lulc"]),
                            (ndvi_n, w["ndvi"]), (albedo_n, w["albedo"])], "UHI_Vulnerability_Index").clip(aoi)
    I = C.Indicator
    inds = [
        I("LST", "LST (Land Surface Temperature)", "°C", w["lst"], inputs.lst, lst_n, dict(min=20, max=45, palette=C.RAMP_TEMP)),
        I("NDBI", "NDBI (Built-up Index)", "", w["ndbi"], inputs.ndbi, ndbi_n, dict(min=-0.5, max=0.8, palette=C.RAMP_NDBI)),
        I("LULC", "LULC (heat-vulnerability score)", "score 1-5", w["lulc"], lulc, lulc_n, dict(min=1, max=5, palette=PAL)),
        I("NDVI", "NDVI (Vegetation Index)", "", w["ndvi"], inputs.ndvi, ndvi_n, dict(min=-0.2, max=1, palette=C.RAMP_NDVI)),
        I("Albedo", "Albedo (Surface reflectivity)", "", w["albedo"], albedo, albedo_n, dict(min=0, max=0.6, palette=C.RAMP_ALBEDO)),
    ]
    C.mark_unavailable(inds, n.missing)
    return C.Framework("uhi", "Urban Heat Island", index, inds, WEIGHTS)

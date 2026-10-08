"""EDITABLE recommendation library.  No AI: each (hazard, indicator) maps to a fixed action and reason.

To change a recommendation, edit the text below. To add one for the same indicator, add another
dictionary to its list - the engine uses the first entry unless you change PICK in recommendations.py.
"""

RECOMMENDATIONS = {
    "uhi": {
        "LST": [{
            "action": "Increase shading and cool surfaces: street trees, shaded public spaces, cool/reflective roofs and green roofs.",
            "why": "Land surface temperature is the strongest contributor to heat risk here, so lowering surface heat gives the largest benefit."}],
        "NDBI": [{
            "action": "Limit further dense built-up expansion and add pocket parks, green corridors and permeable open space within built-up blocks.",
            "why": "High built-up intensity stores and re-radiates heat; breaking up continuous built surface reduces it."}],
        "LULC": [{
            "action": "Protect remaining green and open land from conversion and convert vacant or paved plots to vegetated land.",
            "why": "The land-cover mix in this area (built-up or bare surfaces) is the main driver of heat vulnerability."}],
        "NDVI": [{
            "action": "Expand tree cover and urban greenery: avenue planting, community gardens, vegetated buffers and green walls.",
            "why": "Low vegetation means little shade and evaporative cooling, which raises local temperatures."}],
        "Albedo": [{
            "action": "Promote reflective (cool) roofs and light-coloured pavements on public and municipal buildings and roads.",
            "why": "Low surface reflectivity means more solar energy is absorbed as heat."}],
    },
    "waterlogging": {
        "DEM": [{
            "action": "Identify low-lying pockets and provide storage and pumping: retention ponds, detention basins and local pumping points.",
            "why": "Low elevation lets runoff collect here, making it the leading cause of waterlogging risk."}],
        "Slope": [{
            "action": "Improve drainage in flat areas: re-grade streets where possible, add inlets and clear channels so water can leave.",
            "why": "Very gentle slopes let water stand instead of draining away."}],
        "DistWater": [{
            "action": "Protect and restore nearby water bodies, floodplains and wetland buffers; keep new development out of low-lying margins.",
            "why": "Proximity to water bodies strongly raises the likelihood of water accumulation."}],
        "Rainfall": [{
            "action": "Prepare for heavy-rain events: rainwater harvesting, recharge pits and an early-warning and pre-monsoon desilting plan.",
            "why": "High rainfall totals are the leading contributor, so managing peak runoff matters most."}],
        "LULC": [{
            "action": "Keep open and permeable land uses in drainage paths and restrict filling of wetlands or low-lying open land.",
            "why": "The land-cover pattern here (built-up or wet surfaces) is the main reason water accumulates."}],
        "Impervious": [{
            "action": "Replace paved surfaces with permeable paving, add bioswales, rain gardens and soak pits, and require on-site stormwater management.",
            "why": "Impervious surfaces prevent infiltration and push all rainfall into drains."}],
        "DistDrain": [{
            "action": "Extend and maintain the drainage network: new storm drains, regular desilting and clearing of blocked outfalls.",
            "why": "Long distance from drainage channels means water has no quick path out of the area."}],
        "NDVI": [{
            "action": "Increase vegetation cover with planted drainage verges, urban forests and green infrastructure that slows and absorbs runoff.",
            "why": "Low vegetation reduces interception and infiltration of rainfall."}],
        "Soil": [{
            "action": "Improve infiltration on clay-rich ground: soil amendment, infiltration trenches and storage so water is not left ponding.",
            "why": "High clay content drains slowly, so water remains on the surface longer."}],
    },
    "air_pollution": {
        "RoadDens": [{
            "action": "Reduce traffic pollution exposure: traffic calming, low-emission zones, improved public transport and vegetated road buffers.",
            "why": "Dense road networks are the leading contributor to air-pollution vulnerability in this area."}],
        "LST": [{
            "action": "Reduce surface heat with shade trees and cool surfaces, which also helps limit heat-driven pollutant formation.",
            "why": "High surface temperature is the main contributor in this area."}],
        "NDBI": [{
            "action": "Control dust and emissions from dense built-up areas and construction: dust suppression, cleaner fuels and green screens.",
            "why": "Intense built-up surface is the main contributor to pollution exposure here."}],
        "WindSpeed": [{
            "action": "Keep ventilation corridors open: avoid blocking prevailing airflow with continuous high-rise barriers and keep open-space links.",
            "why": "Low wind speed limits dispersal, so pollutants stay near where they are emitted."}],
        "NDVI": [{
            "action": "Add dense roadside and neighbourhood vegetation, green buffers and urban forests to trap particulates.",
            "why": "Low vegetation cover means little natural filtering of airborne pollutants."}],
    },
}

HAZARD_LABELS = {"uhi": "Urban Heat Island", "waterlogging": "Waterlogging", "air_pollution": "Air Pollution"}
ADDRESSES = {"uhi": "Urban Heat Risk", "waterlogging": "Waterlogging Risk", "air_pollution": "Air Pollution Risk"}

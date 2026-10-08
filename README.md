# ClimateReady — From Climate Risk to Local Action

Flask + Google Earth Engine + Leaflet + ReportLab. No database, no accounts. Assessments live in server memory only.

## 1. Python
Python **3.10 – 3.12** recommended.

## 2. Virtual environment
```
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate
```

## 3. Install
```
pip install -r requirements.txt
```
(`geopandas` pulls in the spatial libraries. If installation fails on Windows, upgrade pip first: `python -m pip install --upgrade pip`.)

## 4. Google Earth Engine
1. Go to <https://console.cloud.google.com>, create a project (or use an existing one) and note the **Project ID**.
2. Enable the **Earth Engine API** for the project, and register the project for Earth Engine at <https://code.earthengine.google.com/register> (non-commercial/research use is free).
3. Copy `.env.example` to `.env` and set `EE_PROJECT=<your project id>` and a random `SECRET_KEY`.
4. Choose **one** authentication method:
   - **Local user authentication (simplest, recommended for development):** run `earthengine authenticate` once and sign in. Credentials are stored by Earth Engine in your user profile, not in the project. Leave `EE_SERVICE_ACCOUNT` and `EE_PRIVATE_KEY_FILE` empty.
   - **Service account (for a server):** create a service account in the Cloud project, grant it the *Earth Engine Resource Viewer* (or Writer) role, register the account for Earth Engine, create a JSON key, store the file **outside the repo** (or anywhere git-ignored), and set `EE_SERVICE_ACCOUNT=name@project.iam.gserviceaccount.com` and `EE_PRIVATE_KEY_FILE=/path/to/key.json`.
5. Test: `python check_ee.py` — you should see "OK - Earth Engine is working."

Credentials are never in the source code.

## 5. Shapefiles
Place your administrative boundaries here (each folder: either the loose `.shp/.shx/.dbf/.prj` files **or** one `.zip` containing them):
```
data/districts/       <- district shapefile
data/subdistricts/    <- subdistrict shapefile
```
They are read once at start-up. The `.prj` is required (the app will not guess a CRS). The name column is auto-detected (e.g. `DISTRICT`, `NAME`, `TEHSIL`); if detection picks the wrong column, set `DISTRICT_NAME_FIELD`, `SUBDISTRICT_NAME_FIELD` (and optionally `SUBDISTRICT_PARENT_FIELD`) in `.env`. The start-up log prints which column was used.

Logo: put your logo in `static/images/` (the report looks for `ClimateReady_logo.png`, `logo.png` or `navbarLogo.png`, otherwise any file with "logo" in its name). The navbar also uses `navbarLogo.png` and `faviconLogo.png`.

## 6. Run
```
python app.py
```
Open <http://127.0.0.1:5000>.

## 7. Test procedure
1. Start Flask (check the log shows your shapefiles loaded).
2. Analysis page → type a district name in the search box.
3. Click the result, press **+ Add** (a chip appears).
4. **Start Assessment** and watch the progress steps (a first run on a district can take several minutes).
5. When the map appears, check the risk layer is drawn inside the boundary.
6. Switch between the four **Risk Maps** (only one is visible at a time).
7. Open an indicator group and switch indicators.
8. Change **Base Map** (None / Normal / Satellite) and move the opacity slider.
9. Click the map to inspect a location.
10. **Generate Recommendations**; check the popup, the pins, and **Locate on Map**.
11. Scroll to statistics and recommendations.
12. **Download Report** and open the PDF.
13. Try leaving the page: you should get the "assessment will be lost" warning.

## How it works
```
selection -> Flask -> local shapefile -> AOI -> Earth Engine
 UHI / Waterlogging / Air hazard indices  +  Socio-economic index
 Risk = Hazard x Socio / 5   (0.2-5)  ->  5 classes (1.16 / 2.12 / 3.08 / 4.04)
 -> statistics (area + population, from FINAL risk) -> priority areas -> recommendations -> PDF
```
| File | Purpose |
|---|---|
| `config.py` | all settings (limits, queue size, class breaks, dates) |
| `gee/uhi.py`, `waterlogging.py`, `air_pollution.py`, `socioeconomic.py` | the four research frameworks (ported from `ClimateReady_Master_GEE_FINAL.js`) |
| `gee/common.py` | shared Sentinel-2/Landsat inputs, normalisation, classification, palettes |
| `gee/pipeline.py` | combines hazards with socio-economic vulnerability, builds layers |
| `gee/statistics.py` | area / population per final risk class |
| `gee/recommendation_library.py` | **editable** indicator -> action text |
| `gee/recommendations.py` | priority-zone detection + library lookup |
| `jobs.py` | in-memory queue (`MAX_CONCURRENT_ASSESSMENTS`, `MAX_QUEUE_SIZE`, timeouts) |
| `locations.py` | shapefile loading, search, custom upload |
| `report.py` | ReportLab PDF |

### Changing settings
- Queue: `MAX_CONCURRENT_ASSESSMENTS` / `MAX_QUEUE_SIZE` in `.env` (defaults 2 and 5).
- Selection limits: `MAX_LOCATIONS` in `config.py`.
- Recommendation text: edit `gee/recommendation_library.py`.

## Differences from the GEE Code Editor script (please read)
The methodology (indicators, weights, datasets, dates, normalisation, formulas, class breaks) is unchanged. Unavoidable adaptations:
1. **2nd/98th percentile stretch values are computed once** (one `getInfo` per framework) and inserted as constants, instead of being re-computed inside every map tile. The numbers are the same as the script's.
2. **The AOI is simplified** (~33 m tolerance) before being sent to Earth Engine, to keep requests small.
3. **The 100 m projection** (`setDefaultProjection`) uses the UTM zone of the AOI centre automatically (script: fixed EPSG:32643). Override with `TARGET_CRS`.
4. **Area limit** `MAX_AOI_KM2` (default 15 000 km²) protects your quota.
5. Dominant indicator for a priority zone = largest mean (normalised score × AHP weight). Because LST/DEM/road density have the highest weights they will often be dominant; if you prefer another rule, edit `find_priority_areas` in `gee/recommendations.py`.
6. Priority zones are built from the highest class band present: High + Very High if any exist, otherwise Moderate. Zones smaller than `PRIORITY_MIN_ZONE_KM2` are ignored; `MAX_PINS_PER_HAZARD` is a safety cap only.
7. Pin positions are the zone centroid ("approximate").
8. Population totals follow the master script (WorldPop summed at 100 m).

## Limits of the in-memory design
Restarting Flask discards all assessments and queued jobs. A job that exceeds `PROCESSING_TIMEOUT_S` is marked failed and its slot freed, but an Earth Engine request already in flight cannot be force-killed; its result is discarded. Use one Flask process (the default) — the queue lives in that process.
Validation / sensitivity-analysis code from the research scripts is intentionally **not** included. (The public Methodology page still mentions validation text; edit `templates/methodology.html` if you want that removed.)

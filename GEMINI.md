# GEMINI.md - ClimateReady Project Context & Guide

## 1. Performance & File-Access Rules (Always Follow)
- **Strict Prohibition on Heavy Directories & Binary Files**:
  - Never run recursive file scans or broad greps across `.venv/`, `venv/`, `env/`, `node_modules/`, `__pycache__/`, `.git/`, or `.pytest_cache/`.
  - Never open or read raw binary or geospatial datasets (`*.shp`, `*.dbf`, `*.shx`, `*.prj`, `*.cpg`, `*.tif`, `*.tiff`, `*.pdf`, `*.png`, `*.jpg`, or raw binary dumps).
- **Targeted Operations**:
  - Use the **Module-to-File Map** below to inspect and edit *only* the specific application source files relevant to the active task.
  - All existing modules and tabs remain completely open for ongoing refinements, enhancements, and extensions whenever requested.

---

## 2. Tech Stack & Current State Summary
- **Backend**: Python 3.14 + Flask (`app.py`), Gunicorn, ThreadPoolExecutor for background Earth Engine calculations and report PDF compilation.
- **AI Agent Framework**: Modular LangGraph (`langgraph`, `langchain-google-genai`) with **`gemini-3.8-flash`** primary multimodal + agentic reasoning model, **`gemini-3.5-flash-lite`** routing model, structured Pydantic schemas, batched multimodal inference (1 single call for all layers), and Cloud SQL caching (<100ms response).
- **Geospatial & Remote Sensing Engine**: Google Earth Engine (`earthengine-api`), GeoPandas, Shapely (`locations.py`, `gee/pipeline.py`).
- **Database & Persistence**:
  - SQLAlchemy ORM (`database.py`, `projects.py`).
  - Google Cloud SQL (PostgreSQL via `psycopg2`) with automatic fallback to local SQLite (`data/climateready.db`) for offline development.
  - Disk-backed raster PNG caching under `data/projects/{project_id}/` (`risk_uhi.png`, `risk_waterlogging.png`).
- **Authentication**:
  - Google OAuth 2.0 OpenID Connect (`auth.py`, `/login`, `/auth/callback`).
  - One-click buildathon Evaluator sign-in (`/auth/evaluator`) generating isolated user sessions with full project persistence.
  - Protected assessment routes via `@auth.login_required` and `templates/auth_wall.html`.
- **Frontend**: Server-rendered Jinja2 templates, Vanilla JavaScript (ES6+ modular closures), Leaflet 1.9.4 for spatial mapping, Bootstrap 5.3 (custom theme), and ReportLab 4.x for PDF generation.
- **Module Status**:
  - `Landing Page` (`/`): Production-ready, centered 4-stage adaptation workflow overview, dynamic CTAs.
  - `About Us` (`/about`): Active, clean mission, methodology principles, and team overview.
  - `Assessment Workspace` (`/assessment` & `/assessment/<id>`):
    - **Stage 1 (Risk Profile)**: Interactive Leaflet map, layer panel (UHI, Waterlogging, individual indicator drivers, base maps, opacity), real-time point inspector, overview metrics, hazard stats (Area and Population breakdowns sorted High-to-Low), locked fixed 2024–2025 baseline timeline.
    - **Stage 2 (Intervention Discovery)**: Dual synchronised risk maps (UHI + Waterlogging), catalog-backed spatial recommendation clustering, progressive discovery status, actionable cards with GPS coords, indicators, simplified action names, concise short descriptions, and quantified impact. Hotspot polygons enriched with geodesic area (`pyproj.Geod`) and physical object area extraction (`GOOGLE/Research/open-buildings/v3/polygons` for `building_area_sqm`, `GOOGLE/DYNAMICWORLD/V1` 2024–2025 for `open_area_sqm` and `road_area_sqm`). Realistic implementation caps: Buildings (10–25%), Roads (10–20%), Open Area (20–40%) persisted as `allocated_intervention_area_sqm` and `target_surface_type`.
    - **Stage 3 (Decision Support)**: Deterministic costing (`allocated_intervention_area_sqm * cost_per_sqm`), 6 live KPI cards (Total Polygon Area, Total Est. Intervention Area, Total Population Across Zones, Selected CAPEX, Annual OPEX, People Impacted), clean Target Budget numeric input with centered dynamic slider (0.5x to 2.0x of entered budget), live budget exhaustion progress bar, 10-column sortable comparison table with black-bordered checkboxes (Select, Intervention & Target Surface with object area breakdown, People Impacted, Unit Setup Cost, Unit Maint. Cost, Total Implementation Cost, Total Annual Maint., Technical Complexity, Lifespan, Expected Impact), and Two Primary Action Buttons:
      1. `Lock Plan & Send to Tracking & Impact` (persists to Cloud SQL `DecisionPlanModel` and switches directly to Tab 4).
      2. `Generate Detailed Project Report` (5-section DPR modal: Assessment Overview sorted High-to-Low, Baseline Risk Maps 2024–2025, Intervention Plan Satellite Maps with polygons & numbered pins, Portfolio Overview with physical object breakdown, and Individual Intervention Specifications with `@media print` export).
    - **Stage 4 (Tracking & Impact)**: Operational post-implementation satellite observation and quantitative verification suite. Features locked plan guard, hazard view toggle (🔥 UHI vs. 💧 Waterlogging), side-by-side synchronized comparison maps (Left: Fixed 2024–2025 baseline risk overlay with locked intervention polygons and committed action % pins; Right: Live rolling 60-day Earth Engine Sentinel-2 / Landsat satellite surveillance with live timestamp and refresh button), "Calculate Post-Intervention Impact" button running zonal before-and-after calculations, 4 live impact KPI cards (Total Intervened Footprint, Beneficiaries Protected, Thermal/Cooling Delta, Runoff Attenuation), and zone-by-zone verification table persisted in Cloud SQL.
  - `Explore & Learn / Methodology` (`/methodology`, `/explore-and-learn`): Interactive technical documentation of the AHP risk modeling framework.
  - `Contact` (`/contact`): Contact form with JSONL persistence (`data/contact_messages.jsonl`) and email integration.

---

## 3. Exact Module-to-File Map

### A. Core Application & Server
- `app.py`: Flask application entry point, routing, API endpoints, job queueing, raster tile/overlay endpoints, and report endpoints.
- `wsgi.py`: Production WSGI entry point for Gunicorn and Google Cloud Run containers (`gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 180 wsgi:app`).
- `config.py`: Core configuration (hazards, breaks, scales, location limits, file upload thresholds, environment variables).
- `jobs.py`: In-memory and persisted assessment job state manager (`JobManager`, `Job`, status transitions).
- `mailer.py`: Contact form submission handler, JSONL logging, and optional SMTP notification.

### B. Authentication & Database Models
- `models/`: Modular database package (`models/__init__.py`) re-exporting all SQLAlchemy models and DB connection helpers.
- `database.py`: Core SQLAlchemy database configuration (`User`, `ProjectModel` with `is_demo` & `demo_badge_label`, `InterventionModel`, `DecisionPlanModel`), connection pooling, Google Cloud Run Unix socket parser (`/cloudsql/INSTANCE_CONNECTION_NAME`), and SQLite fallback.
- `projects.py`: High-level Project data layer (`ProjectStore`), CRUD operations, demo project pinning for all evaluators (`list_projects`), JSON serialization of assessments and recommendations, relational persistence of intervention items, and finalized adaptation plan locking (`save_decision_plan`, `get_locked_plan`).
- `auth.py`: Google OAuth 2.0 configuration, OpenID token exchange, session management, and `login_required` decorators.

### C. Geospatial & Earth Engine Risk Pipeline
- `locations.py`: Local shapefile indexing and spatial geometry lookup for Indian districts and subdistricts.
- `gee/pipeline.py`: Earth Engine hazard/risk calculation pipeline, multi-hazard aggregation, thumbnail raster overlay export.
- `gee/uhi.py`: Urban Heat Island hazard indicators (LST, NDBI, LULC, NDVI, Albedo).
- `gee/waterlogging.py`: Urban Waterlogging hazard indicators (DEM, Slope, DistWater, Rainfall, LULC, Imperviousness, DistDrain, Soil).
- `gee/socioeconomic.py`: Socio-economic vulnerability indicators (Population Density, Household Density, Vulnerable Demographics, Hospital Distance).
- `gee/statistics.py`: Spatial hazard/vulnerability statistics calculation across 5-level risk classes.
- `gee/common.py`: Shared Earth Engine utilities, headless Cloud Run container auth (`GEE_SERVICE_ACCOUNT_JSON`), reducers, AHP scoring algorithms (`Scorer`), color palettes.
- `report.py` & `services/report_builder.py`: ReportLab PDF generation engine, document layout, dynamic map thumbnails, statistical summaries, and action matrices.

### D. LangGraph AI Agent & Services Architecture
- `services/ai_agent/state.py`: Typed `AgentState` (`TypedDict`) and Pydantic schemas enforcing structured output generation with polygon coordinates, per-sqm costs, lifespan, complexity, impact, and provenance.
- `services/ai_agent/tools.py`: Deterministic spatial-indicator extractors (`extract_spatial_hotspots` extracting top 5 UHI + top 5 Waterlogging zones, simplified polygons, and zonal indicator signatures: NDBI, NDVI, LST, Albedo, DEM, Slope, Imperviousness), zero PNG/satellite transfers, and Cloud SQL caching helpers (`get_cached_interventions`, `save_cached_interventions`).
- `services/ai_agent/graph.py`: Compiled LangGraph `StateGraph` with **split focused requests** (1 for 5 UHI + 1 for 5 Waterlogging) reasoning on physical indicator signatures, structured Pydantic output, robust multi-model fallback (`gemini-3.8-flash` -> `gemini-2.5-flash-lite` -> zero-hallucination domain synthesizer), and `run_intervention_discovery` with cache-first lookup (<1ms response).
- `services/decision_planner.py`: Deterministic geodesic polygon area calculation (`pyproj.Geod`), single batched Earth Engine physical object area extraction (`GOOGLE/Research/open-buildings/v3/polygons` for `building_area_sqm`, `GOOGLE/DYNAMICWORLD/V1` for `open_area_sqm` and `road_area_sqm`) and demographic extraction (`WorldPop 2025` / `JRC GHSL`), deterministic financial & TCO models based on `allocated_intervention_area_sqm`, goal-driven portfolio budget optimization, and grounded 3-part AI executive decision brief synthesis (`generate_ai_decision_brief`).
- `services/gee_live_tracking.py`: Operational post-implementation satellite observation and impact verification service. Queries rolling recent 60-day Earth Engine Sentinel-2 / Landsat-8/9 surveillance window, computes multi-hazard live overlays, supports calibrated post-intervention simulation for Demo projects (`is_demo=True`), and deterministically calculates quantitative zonal before-and-after deltas (LST cooling, NDVI greening, runoff attenuation, risk drop).
- `scripts/seed_kalyan_demo.py`: Repeatable end-to-end demo seeding script populating all 4 modules for `Kalyan Resilience Project` (`proj_kalyan_demo`, `is_demo=True`) in Cloud SQL.
- `scripts/check_ee.py`: Utility script to test and verify Earth Engine credentials and elevation raster sampling.
- `scripts/simplify_shapefile.py`: Utility script for topological geometry simplification of administrative vector boundaries.
- `static/js/recommendations.js`: Frontend card renderer with unified recommendation grouping across similar locations, clean wrapped site context, multi-pin locating, and source citation footer.
- `static/js/map.js`: Leaflet wrapper (`CRMap`), raster overlay integration, base map switching, `setPolygonsAndPins` with bold black polygon boundaries (`#000000`), `focusMultiplePins` with multi-pin blinking animation, and constrained zoom normalization (`maxZoom: 13`).
- `static/js/planner.js`: Module 3 (Decision Support) interactive frontend controller for budget input with centered dynamic slider (0.5x to 2.0x), live budget exhaustion bar, 6 top KPI cards, 10-column sortable comparison table with black-bordered checkboxes, per-intervention action proportion sliders (`10%` to `100%`) dynamically scaling effective footprint and costs, plan locking transition to Tab 4 (`Lock Plan & Send to Tracking & Impact`), and 5-section Detailed Project Report (DPR) generation with satellite polygon maps, sticky header z-index isolation, and `@media print` export.
- `static/js/tracking.js`: Module 4 (Tracking & Impact) interactive frontend controller. Enforces locked adaptation plan guard, hazard switcher (🔥 UHI vs. 💧 Waterlogging), side-by-side synchronized comparison maps (Fixed 2024–2025 baseline risk overlay vs. Live rolling 60-day satellite monitoring with refresh button), "Calculate Post-Intervention Impact" zonal assessment, 4 live impact KPI cards, and zone-by-zone before-and-after verification table.

### E. Frontend Templates & Assets
- `templates/base.html`: Base layout, navigation header, auth status dropdown, footer.
- `templates/index.html`: Landing page, adaptation workflow overview, assessment CTA.
- `templates/about.html`: Platform overview and scientific methodology background.
- `templates/methodology.html`: Complete AHP scientific formula documentation and indicator references.
- `templates/contact.html`: Contact form and communication channel.
- `templates/auth_wall.html`: Auth gateway with Google Sign-In and Buildathon Evaluator quick-access.
- `templates/workspace_dashboard.html`: User project dashboard, project creation modal (Level, Location, Name), saved project cards.
- `templates/workspace_project.html`: Unified 4-stage project workspace (Risk Profile, Interventions, Decision Planner, Monitoring).
- `static/js/analysis.js`: Risk profile map controller, layer selection, live stats rendering, session rehydration.
- `static/js/map.js`: Leaflet wrapper (`CRMap`), raster overlay integration, base map switching, pin clustering.
- `static/css/style.css`: Core design system, typography, modern card components, layout variables.
- `static/css/home.css`: Landing page and adaptation workflow card styling.
- `static/css/analysis.css`: Interactive map, sidebar panels, legend, and assessment stats layout.

---

## 4. Coding & Architecture Conventions
- **Clean Separation of Concerns & Grounding Invariants**:
  - **Zero-Hallucination Policy**: Deterministic calculations (budgets, spatial statistics, index formulas, percentages) must be computed in Python (`gee/`, `report.py`, `projects.py`), never left to probabilistic LLM outputs.
  - **System-First Grounding**: All intervention GPS coordinates, baseline risk classes, and driving indicator labels must strictly match verified database assessment records.
  - **Scoped External Search & Mandatory Provenance**: External search is restricted to explicit, verified queries; every intervention parameter carries exact authoritative citations (NDMA, NIUA, CPWD, MoHUA, CEPT).
  - **Performance Optimization**: Multimodal satellite raster visual analysis is batched into 1 single call across all layers (~80% call reduction), and completed outputs are cached in Cloud SQL for <100ms subsequent reads.
  - Satellite raster overlays are cached to disk (`data/projects/{id}/risk_*.png`) for instant millisecond loads on reload or revisit.
- **Frontend Guidelines**:
  - Always guard DOM element lookups (`if ($(id)) ...`) to ensure scripts never crash on pages where specific buttons or modals are omitted.
  - When loading Leaflet maps in hidden tabs or upon dynamic tab-switching, always invoke `map.resize()` (`map.invalidateSize()`) and re-apply bounds (`map.showAOI(...)`).
- **Design System & Palette**:
  - Primary Brand Green: `#16A34A` / `#15803D`.
  - UHI Hazard Color: `#EA580C` (Warm Orange).
  - Waterlogging Hazard Color: `#1D4ED8` (Ocean Blue).
  - Risk Class Scale: 1 = Very Low (`#94A3B8`), 2 = Low (`#64748B`), 3 = Moderate (`#B7791F`), 4 = High (`#EA580C`), 5 = Very High (`#B91C1C`).
- **Terminology Invariant**:
  - Focus strictly on **Urban Heat Island (UHI)** and **Waterlogging** hazards alongside **Socio-Economic Vulnerability**.
  - Air pollution has been completely decoupled from the active pipeline and must not be referenced.

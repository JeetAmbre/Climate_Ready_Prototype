"""ClimateReady settings. Edit values here (or override with environment variables / .env)."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _num(name, default, cast=int):
    try:
        return cast(os.getenv(name, default))
    except ValueError:
        return default


# ---------------- Flask ----------------
SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-.env")

# ---------------- Earth Engine ----------------
EE_PROJECT = os.getenv("EE_PROJECT", "")
EE_SERVICE_ACCOUNT = os.getenv("EE_SERVICE_ACCOUNT", "")
EE_PRIVATE_KEY_FILE = os.getenv("EE_PRIVATE_KEY_FILE", "")
EE_PRIVATE_KEY_DATA = os.getenv("EE_PRIVATE_KEY_DATA", "")

# Assessment period (from the research scripts: fixed 2024–2025 baseline)
START_DATE = os.getenv("START_DATE", "2024-01-01")
END_DATE = os.getenv("END_DATE", "2025-12-31")

# Scale (metres) used for the 2nd/98th percentile normalisation of the hazard layers.
# 100m aligns with the analysis grid and is ~3x faster than 30m; override with STRETCH_SCALE=30 in .env if desired.
STRETCH_SCALE = _num("STRETCH_SCALE", 100)

# Common analysis grid for final risk / socio-economic products (master GEE script: 100 m)
ANALYSIS_SCALE = 100
# Projection for that grid. Leave empty to auto-pick the UTM zone of the AOI
# (the research scripts hard-code EPSG:32643 = UTM 43N, correct for Mumbai/Thane).
TARGET_CRS = os.getenv("TARGET_CRS", "")

# ---------------- Risk classes ----------------
# Final risk = hazard * socio / 5  (range 0.2 - 5). Equal-interval breaks from the master script.
RISK_BREAKS = [1.16, 2.12, 3.08, 4.04]
# Hazard and socio-economic indices (range 1 - 5), breaks from the research scripts.
INDEX_BREAKS = [1.8, 2.6, 3.4, 4.2]
LEVELS = ["Very Low", "Low", "Moderate", "High", "Very High"]

# ---------------- Location selection ----------------
MAX_LOCATIONS = {"district": 1, "subdistrict": 5}
DISTRICT_DIR = BASE_DIR / "data" / "districts"
SUBDISTRICT_DIR = BASE_DIR / "data" / "subdistricts"
# Attribute columns. Leave empty to auto-detect, or set the exact column name.
DISTRICT_NAME_FIELD = os.getenv("DISTRICT_NAME_FIELD", "")
SUBDISTRICT_NAME_FIELD = os.getenv("SUBDISTRICT_NAME_FIELD", "")
SUBDISTRICT_PARENT_FIELD = os.getenv("SUBDISTRICT_PARENT_FIELD", "")

MAX_UPLOAD_MB = _num("MAX_UPLOAD_MB", 10)
MAX_AOI_KM2 = _num("MAX_AOI_KM2", 15000, float)   # protects the Earth Engine quota
SIMPLIFY_TOLERANCE_DEG = 0.0003                    # ~33 m; keeps the AOI sent to GEE small

# ---------------- Queue / concurrency ----------------
MAX_CONCURRENT_ASSESSMENTS = _num("MAX_CONCURRENT_ASSESSMENTS", 2)
MAX_QUEUE_SIZE = _num("MAX_QUEUE_SIZE", 5)
QUEUED_TIMEOUT_S = _num("QUEUED_TIMEOUT_S", 900)
PROCESSING_TIMEOUT_S = _num("PROCESSING_TIMEOUT_S", 1800)
# A queued/running assessment whose page has not contacted the server for this long is abandoned and stopped
# (long enough for a phone screen to sleep for a while; the page checks in every ~2 seconds).
HEARTBEAT_TIMEOUT_S = _num("HEARTBEAT_TIMEOUT_S", 900)
JOB_TTL_S = 3600                                   # finished jobs are forgotten after 1 hour

# ---------------- Priority areas ----------------
PRIORITY_MIN_ZONE_KM2 = 0.25    # ignore tiny speckles
MAX_PINS_PER_HAZARD = 10        # safety cap only, not a target

# ---------------- Report ----------------
REPORT_DIR = BASE_DIR / "reports"
LOGO_CANDIDATES = ["ClimateReady_logo.png", "ClimateReadyLogo.png", "logo.png", "navbarLogo.png"]

# ---------------- Contact & Email ----------------
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = _num("MAIL_PORT", 587)
MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "t")
MAIL_USERNAME = os.getenv("MAIL_USERNAME", "")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", "")
MAIL_TO = os.getenv("MAIL_TO", "jeetambre090@gmail.com")

# ---------------- Gemini AI Agent ----------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_LITE_MODEL = os.getenv("GEMINI_LITE_MODEL", "gemini-3.5-flash-lite")
GOOGLE_MAPS_STATIC_API_KEY = os.getenv("GOOGLE_MAPS_STATIC_API_KEY", "")



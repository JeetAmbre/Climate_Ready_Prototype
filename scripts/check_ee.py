"""
scripts/check_ee.py - Verify Earth Engine configuration and credentials.
Run: `python scripts/check_ee.py`
"""
import sys
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

import ee
from gee.common import init_earth_engine

if __name__ == "__main__":
    init_earth_engine()
    print("Earth Engine initialized successfully.")
    elev = ee.Image("USGS/SRTMGL1_003").sample(ee.Geometry.Point([72.97, 19.2]), 30).first().get("elevation").getInfo()
    print(f"Test computation (SRTM elevation at Thane): {elev} m")
    print("OK - Earth Engine is working.")

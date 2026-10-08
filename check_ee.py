"""Run `python check_ee.py` to confirm Earth Engine is configured correctly."""
import ee
from gee.common import init_earth_engine

init_earth_engine()
print("Earth Engine initialised.")
print("Test computation (SRTM elevation at Thane):",
      ee.Image("USGS/SRTMGL1_003").sample(ee.Geometry.Point([72.97, 19.2]), 30).first().get("elevation").getInfo(), "m")
print("OK - Earth Engine is working.")

"""Local district / subdistrict shapefiles: loading, search, AOI building, custom upload."""
import tempfile
import uuid
import time
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely import make_valid
from shapely.geometry import mapping
from shapely.ops import unary_union

import config

NAME_CANDIDATES = {
    "district": ["district", "dtname", "dt_name", "distname", "dist_name", "district_n", "name_2", "name", "dname"],
    "subdistrict": ["subdistrict", "sub_dist", "sdtname", "sdt_name", "tehsil", "taluka", "taluk", "name_3", "name", "subdist"],
}
PARENT_CANDIDATES = ["district", "dtname", "dt_name", "distname", "dist_name", "name_2"]


def _pick(columns, candidates):
    low = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in low:
            return low[cand]
    return None


def _read_vector(folder: Path):
    """Read the first .shp (or .zip) found in a folder."""
    shp = sorted(folder.glob("*.shp")) or sorted(folder.glob("*.zip"))
    if not shp:
        return None, f"No .shp or .zip found in {folder}"
    path = shp[0]
    gdf = gpd.read_file(f"zip://{path}" if path.suffix == ".zip" else path)
    if gdf.crs is None:
        return None, f"{path.name} has no CRS (.prj missing); cannot use it."
    return gdf.to_crs(4326), None


class LocationStore:
    """Loaded once at start-up and kept in memory."""

    def __init__(self):
        self.levels = {}      # level -> {"gdf":..., "records":[...]}
        self.errors = {}
        self.uploads = {}     # upload_id -> {"geom","name","t"}

    def load(self):
        for level, folder, name_f, parent_f in [
            ("district", config.DISTRICT_DIR, config.DISTRICT_NAME_FIELD, ""),
            ("subdistrict", config.SUBDISTRICT_DIR, config.SUBDISTRICT_NAME_FIELD, config.SUBDISTRICT_PARENT_FIELD),
        ]:
            try:
                gdf, err = _read_vector(folder)
            except Exception as exc:                      # unreadable file etc.
                gdf, err = None, f"Could not read {level} shapefile: {exc}"
            if err:
                self.errors[level] = err
                print(f"[locations] {err}")
                continue
            cols = [c for c in gdf.columns if c != "geometry"]
            name_col = name_f or _pick(cols, NAME_CANDIDATES[level])
            if not name_col:
                name_col = next((c for c in cols if gdf[c].dtype == object), None)
            if not name_col:
                self.errors[level] = f"No name column found for {level}. Set {level.upper()}_NAME_FIELD in .env."
                continue
            parent_col = None
            if level == "subdistrict":
                parent_col = parent_f or _pick([c for c in cols if c != name_col], PARENT_CANDIDATES)
            gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].reset_index(drop=True)
            records = []
            for i, row in gdf.iterrows():
                records.append({
                    "id": f"{level}:{i}", "name": str(row[name_col]).strip(),
                    "parent": str(row[parent_col]).strip() if parent_col else "", "level": level,
                })
            self.levels[level] = {"gdf": gdf, "records": records, "by_id": {r["id"]: r for r in records}}
            print(f"[locations] loaded {len(records)} {level} features (name column: {name_col})")

    # ---------- search ----------
    def search(self, level, query, limit=12):
        data = self.levels.get(level)
        if not data:
            return []
        q = query.strip().lower()
        if not q:
            return []
        starts = [r for r in data["records"] if r["name"].lower().startswith(q)]
        contains = [r for r in data["records"] if q in r["name"].lower() and r not in starts]
        return (starts + contains)[:limit]

    def record(self, rec_id):
        level = rec_id.split(":")[0]
        return self.levels.get(level, {}).get("by_id", {}).get(rec_id)

    def geometry_for(self, ids):
        geoms = []
        for rid in ids:
            level, idx = rid.split(":")
            geoms.append(self.levels[level]["gdf"].geometry.iloc[int(idx)])
        return unary_union(geoms)

    def place_name_at(self, lon, lat):
        """Name of the admin unit containing a point (subdistrict preferred)."""
        from shapely.geometry import Point
        pt = Point(lon, lat)
        for level in ("subdistrict", "district"):
            data = self.levels.get(level)
            if not data:
                continue
            hit = data["gdf"][data["gdf"].geometry.contains(pt)]
            if len(hit):
                rec = data["records"][int(hit.index[0])]
                suffix = f", {rec['parent']}" if rec["parent"] else ""
                return rec["name"] + suffix
        return None

    # ---------- custom upload ----------
    def read_upload(self, file_storage):
        self._purge_uploads()
        if not file_storage.filename.lower().endswith(".zip"):
            raise ValueError("Please upload a .zip containing .shp, .shx, .dbf and .prj files.")
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / "up.zip"
            file_storage.save(zpath)
            with zipfile.ZipFile(zpath) as z:
                total = 0
                for m in z.infolist():
                    total += m.file_size
                    if m.filename.startswith(("/", "..")) or ".." in Path(m.filename).parts:
                        raise ValueError("The ZIP contains unsafe file paths.")
                if total > config.MAX_UPLOAD_MB * 1024 * 1024 * 8:
                    raise ValueError("The extracted files are too large.")
                z.extractall(tmp)
            shps = list(Path(tmp).rglob("*.shp"))
            if not shps:
                raise ValueError("No .shp file found inside the ZIP.")
            shp = shps[0]
            missing = [e for e in (".shx", ".dbf") if not shp.with_suffix(e).exists()]
            if missing:
                raise ValueError("Missing shapefile component(s): " + ", ".join(missing))
            if not shp.with_suffix(".prj").exists():
                raise ValueError("The shapefile has no .prj file, so its coordinate system is unknown. "
                                 "Add the .prj file and upload again.")
            try:
                gdf = gpd.read_file(shp)
            except Exception as exc:
                raise ValueError(f"The shapefile could not be read: {exc}")
            if gdf.crs is None:
                raise ValueError("The coordinate reference system (CRS) could not be interpreted.")
            try:
                gdf = gdf.to_crs(4326)
            except Exception:
                raise ValueError("The shapefile could not be transformed to WGS84 (EPSG:4326).")
            gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
            gdf = gdf[gdf.geom_type.isin(["Polygon", "MultiPolygon"])]
            if gdf.empty:
                raise ValueError("No valid polygon geometry found in the shapefile.")
            geom = make_valid(unary_union(list(gdf.geometry)))
        uid = uuid.uuid4().hex[:12]
        name = Path(file_storage.filename).stem
        self.uploads[uid] = {"geom": geom, "name": name, "t": time.time()}   # memory only
        return uid, name, geom

    def _purge_uploads(self):
        for k in [k for k, v in self.uploads.items() if time.time() - v["t"] > 3600]:
            self.uploads.pop(k, None)


def build_aoi(geom):
    """Shapely geometry -> dict used by the rest of the app."""
    geom = make_valid(geom)
    simple = geom.simplify(config.SIMPLIFY_TOLERANCE_DEG, preserve_topology=True)
    area_km2 = gpd.GeoSeries([geom], crs=4326).to_crs(6933).area.iloc[0] / 1e6
    c = geom.centroid
    minx, miny, maxx, maxy = geom.bounds
    return {
        "geom": simple, "geojson": mapping(simple), "area_km2": float(area_km2),
        "centroid": {"lat": c.y, "lng": c.x}, "bounds": [minx, miny, maxx, maxy],
    }


_DEFAULT_STORE = None


def get_default_location_store():
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = LocationStore()
    return _DEFAULT_STORE


def place_name_at(lon, lat):
    """Module-level reverse geocoding lookup for coordinates."""
    return get_default_location_store().place_name_at(lon, lat)

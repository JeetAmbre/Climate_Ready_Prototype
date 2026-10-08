"""Shrink an administrative shapefile for ClimateReady without changing how the app behaves.

Usage:
  python tools/simplify_shapefile.py INPUT.shp OUTPUT_FOLDER [--tolerance 0.0003] [--keep COL1,COL2] [--zip]

- Works in WGS84 degrees (0.0003 deg ~ 33 m). This is the same tolerance the app itself applies
  before sending an area to Earth Engine, so results are unaffected.
- Shared borders between neighbouring polygons stay shared (coverage simplification) when your
  shapely/GEOS version supports it; otherwise it falls back to per-polygon simplification.
- Prints a before/after check: feature count, invalid/empty geometries, and total area change.
"""
import argparse
import shutil
import zipfile
from pathlib import Path

import geopandas as gpd
import shapely
from shapely.ops import unary_union


def polygons_only(g):
    """Return only the polygon part of a geometry (shapefiles cannot mix polygons with lines/points)."""
    if g is None or g.is_empty:
        return None
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    if g.geom_type == "GeometryCollection":
        parts = [polygons_only(x) for x in g.geoms]
        parts = [p for p in parts if p is not None]
        return unary_union(parts) if parts else None
    return None


def area_km2(gdf):
    return gdf.to_crs(6933).area.sum() / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("outdir")
    ap.add_argument("--tolerance", type=float, default=0.0003, help="degrees (0.0003 ~ 33 m)")
    ap.add_argument("--keep", default="", help="comma-separated columns to keep (default: all)")
    ap.add_argument("--zip", action="store_true", help="also write one .zip (the app can read zips)")
    a = ap.parse_args()

    src = Path(a.input)
    gdf = gpd.read_file(src)
    if gdf.crs is None:
        raise SystemExit("The input has no CRS (.prj missing). Fix that first; the app will not guess one.")
    gdf = gdf.to_crs(4326)
    n0, area0 = len(gdf), area_km2(gdf)

    if a.keep:
        cols = [c.strip() for c in a.keep.split(",")]
        missing = [c for c in cols if c not in gdf.columns]
        if missing:
            raise SystemExit(f"Columns not found: {missing}. Available: {list(gdf.columns)}")
        gdf = gdf[cols + ["geometry"]]

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
    gdf["geometry"] = [polygons_only(g) for g in gdf.geometry.make_valid()]
    dropped = len(gdf) - int(gdf.geometry.notna().sum())     # zero-area shapes that are lines, not polygons
    gdf = gdf[gdf.geometry.notna()].copy()
    original = gdf.geometry.copy()

    try:      # keeps shared borders shared (needs shapely >= 2.1)
        simple = list(shapely.coverage_simplify(original.values, a.tolerance))
        method = "coverage simplification (shared borders preserved)"
    except Exception:
        simple = list(original.simplify(a.tolerance, preserve_topology=True))
        method = "per-polygon simplification (shapely < 2.1)"

    # Keep only polygon parts. If a feature collapsed (tiny sliver -> line/empty), keep its ORIGINAL shape.
    fixed, fallbacks = [], 0
    for new, old in zip(simple, original):
        g = polygons_only(shapely.make_valid(new)) if new is not None and not new.is_empty else None
        if g is None or g.is_empty:
            g, fallbacks = old, fallbacks + 1
        fixed.append(g)
    gdf["geometry"] = fixed

    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    stem = src.stem + "_simplified"
    shp = out / f"{stem}.shp"
    gdf.to_file(shp, driver="ESRI Shapefile")

    size = lambda files: sum(f.stat().st_size for f in files) / 1e6
    parts = sorted(out.glob(f"{stem}.*"))
    print(f"Method        : {method}")
    print(f"Features      : {n0} -> {len(gdf)}")
    print(f"Invalid geoms : {int((~gdf.geometry.is_valid).sum())}")
    print(f"Dropped       : {dropped} degenerate feature(s) with no polygon area")
    print(f"Kept original : {fallbacks} tiny feature(s) too small to simplify")
    print(f"Total area    : {area0:,.1f} -> {area_km2(gdf):,.1f} km2 ({100 * (area_km2(gdf) - area0) / area0:+.3f}%)")
    orig = sorted(src.parent.glob(f"{src.stem}.*"))
    print(f"Size          : {size(orig):.1f} MB -> {size(parts):.1f} MB")
    for f in parts:
        print(f"   {f.name}: {f.stat().st_size / 1e6:.1f} MB")
    if a.zip:
        z = out / f"{stem}.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in parts:
                zf.write(f, f.name)
        print(f"Zip           : {z.name} {z.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

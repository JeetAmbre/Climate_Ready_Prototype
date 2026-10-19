"""ClimateReady Flask app. Routes only; science lives in gee/, queue in jobs.py, PDF in report.py."""
import io
import re
import threading
import time
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from flask import Flask, jsonify, render_template, request, send_file, session

import config
import jobs as jobs_mod
from gee import common as C
from gee import pipeline
from gee.recommendations import build_recommendations
from locations import LocationStore, build_aoi
import mailer
import report

BUILD = "fast-v3"
BUILD_ID = str(int(time.time()))      # changes on every start/deploy: forces browsers to fetch fresh JS/CSS
app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
try:                                          # optional: gzip for HTML/JSON/JS/CSS (faster on mobile)
    from flask_compress import Compress  # type: ignore  # pyright: ignore[reportMissingImports]
    Compress(app)
except ImportError:
    pass
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = timedelta(days=7)   # safe: static URLs carry ?v=BUILD_ID


@app.context_processor
def _inject_build():
    return {"build_id": BUILD_ID}


app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

store = LocationStore()
store.load()
manager = jobs_mod.JobManager(lambda job: (_ensure_ee(), pipeline.run_assessment(job)))
_ee_ready = False


def _ensure_ee():
    global _ee_ready
    if not _ee_ready:
        C.init_earth_engine()
        _ee_ready = True


def err(msg, code=400):
    return jsonify(error=msg), code


def current_job():
    job = manager.get(session.get("job_id", ""))
    if job:
        job.last_seen = time.time()           # heartbeat: the user's page is still there
    return job


def completed_job():
    job = current_job()
    if not job or job.state != jobs_mod.COMPLETED:
        return None
    return job


# ---------------- pages ----------------
@app.route("/")
def index(): return render_template("index.html")
@app.route("/analysis")
def analysis():
    # Opening or refreshing the Analysis page always starts clean: cancel and forget any old assessment.
    old = current_job()
    if old:
        manager.cancel(old)
    session.pop("job_id", None)
    cfg = {"limits": config.MAX_LOCATIONS, "maxUploadMb": config.MAX_UPLOAD_MB, "levels": config.LEVELS,
           "loaded": {k: k in store.levels for k in ("district", "subdistrict")}, "errors": store.errors}
    return render_template("analysis.html", cfg=cfg)
@app.route("/methodology")
def methodology(): return render_template("methodology.html")
@app.route("/about")
def about(): return render_template("about.html")
@app.route("/contact")
def contact(): return render_template("contact.html")
@app.post("/api/contact")
def api_contact():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip()
    msg = (d.get("message") or "").strip()
    if not name or len(name) < 2:
        return err("Please enter your name.")
    if not email or "@" not in email or "." not in email:
        return err("Please enter a valid email address.")
    if not msg or len(msg) < 5:
        return err("Please write a short message.")
    client_ip = (
        request.headers.get("CF-Connecting-IP")
        or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or request.remote_addr
        or ""
    )
    mailer.handle_contact_submission(d, client_ip=client_ip)
    return jsonify(ok=True)


# ---------------- auto-deploy webhook ----------------
@app.post("/api/deploy-webhook")
def deploy_webhook():
    secret = getattr(config, "DEPLOY_SECRET", "cr-deploy-78f92a10b4c6e83d91f2")
    auth = request.headers.get("Authorization", "").strip()
    expected = f"Bearer {secret}"
    if not auth or auth != expected:
        return jsonify(error="Unauthorized"), 401

    def _execute_deploy():
        import subprocess
        import logging
        log = logging.getLogger("climateready.deploy")
        log.info("[DEPLOY] Webhook authenticated. Pulling latest commit...")
        time.sleep(1)
        cmd = (
            "set -e; "
            "cd /var/www/climateready; "
            "GIT_TERMINAL_PROMPT=0 git pull origin main; "
            "source venv/bin/activate; "
            "pip install -r requirements.txt; "
            "systemctl restart climateready"
        )
        res = subprocess.run(["/bin/bash", "-c", cmd], capture_output=True, text=True)
        if res.returncode == 0:
            log.info("[DEPLOY] Auto-deploy succeeded!")
        else:
            log.error(f"[DEPLOY] Auto-deploy failed (code {res.returncode}): {res.stderr}")

    threading.Thread(target=_execute_deploy, daemon=True).start()
    return jsonify(ok=True, message="Auto-deploy initiated"), 200



# ---------------- location ----------------
@app.post("/api/location/search")
def location_search():
    d = request.get_json(force=True)
    return jsonify(results=store.search(d.get("level", "district"), d.get("q", "")))


@app.post("/api/location/select")
def location_select():
    """Validates adding one location to the current selection (limits enforced here)."""
    d = request.get_json(force=True)
    level, rid, current = d.get("level"), d.get("id"), d.get("current", [])
    rec = store.record(rid or "")
    if not rec or rec["level"] != level:
        return err("Please choose a location from the list.")
    limit = config.MAX_LOCATIONS[level]
    if rid in current:
        return err(f"{rec['name']} is already selected.")
    if len(current) >= limit:
        return err(f"You can select a maximum of {limit} {level}{'s' if limit > 1 else ''} per assessment.")
    return jsonify(location=rec)


@app.post("/api/upload-aoi")
def upload_aoi():
    f = request.files.get("file")
    if not f:
        return err("No file received.")
    try:
        uid, name, geom = store.read_upload(f)
        aoi = build_aoi(geom)
    except ValueError as exc:
        return err(str(exc))
    except Exception as exc:
        return err(f"The upload could not be processed: {exc}")
    if aoi["area_km2"] > config.MAX_AOI_KM2:
        return err(f"The area ({aoi['area_km2']:,.0f} km²) exceeds the limit of {config.MAX_AOI_KM2:,.0f} km².")
    return jsonify(upload_id=uid, name=name, area_km2=aoi["area_km2"])


@app.errorhandler(413)
def too_big(_):
    return err(f"The file is larger than {config.MAX_UPLOAD_MB} MB.", 413)


# ---------------- assessment ----------------
@app.post("/api/assessment/start")
def assessment_start():
    old = current_job()
    if old and old.state in (jobs_mod.QUEUED, jobs_mod.PROCESSING):
        return jsonify(error="Assessment already in progress.", job_id=old.id), 409
    d = request.get_json(force=True)
    mode, ids = d.get("mode"), d.get("ids", [])
    try:
        if mode == "custom":
            up = store.uploads.get(d.get("upload_id", ""))
            if not up:
                return err("The uploaded area has expired. Please upload it again.")
            geom, label = up["geom"], f"Custom area: {up['name']}"
        elif mode in config.MAX_LOCATIONS:
            if not ids or len(ids) > config.MAX_LOCATIONS[mode]:
                return err(f"Select 1 to {config.MAX_LOCATIONS[mode]} {mode}(s).")
            recs = [store.record(i) for i in ids]
            if not all(recs):
                return err("Unknown location selected.")
            geom = store.geometry_for(ids)
            label = ", ".join(r["name"] for r in recs) + (" District" if mode == "district" else "")
        else:
            return err("Choose a location first.")
        aoi = build_aoi(geom)
    except Exception as exc:
        return err(f"Could not build the study area: {exc}")
    if aoi["area_km2"] > config.MAX_AOI_KM2:
        return err(f"The selected area ({aoi['area_km2']:,.0f} km²) exceeds the limit of {config.MAX_AOI_KM2:,.0f} km².")
    if old:                                   # finished assessment being replaced: free its memory
        manager.cancel(old)
    job = jobs_mod.Job(aoi, label, mode)
    ok, msg = manager.submit(job)
    if not ok:
        return err(msg, 503)
    session["job_id"] = job.id
    return jsonify(job_id=job.id, state=job.state), 202


@app.post("/api/assessment/cancel")
def assessment_cancel():
    """Called by the browser (sendBeacon) when the user leaves the page."""
    job = current_job()
    if job:
        manager.cancel(job)
    session.pop("job_id", None)
    return "", 204


@app.get("/api/assessment/status")
def assessment_status():
    job = current_job()
    if not job:
        return jsonify(state="NONE")
    return jsonify(job.public_status(manager.position(job) if job.state == jobs_mod.QUEUED else None))


# ---------------- layers / statistics ----------------
@app.get("/api/layers")
def layers():
    job = completed_job()
    if not job:
        return err("No completed assessment.", 404)
    out = [{"id": k, "label": v["label"], "group": v["group"], "hazard": v["hazard"], "legend": v["legend"],
            "available": v.get("available", True)} for k, v in job.layers.items()]
    return jsonify(layers=out, warnings=job.warnings, aoi=job.aoi["geojson"], bounds=job.aoi["bounds"], label=job.label,
                   date=date.today().isoformat(), has_recs=job.recs is not None)


@app.get("/api/layers/<layer_id>/tiles")
def layer_tiles(layer_id):
    job = completed_job()
    if not job or layer_id not in job.layers:
        return err("Unknown layer.", 404)
    if not job.layers[layer_id].get("available", True):
        return jsonify(unavailable=True, message="Data not available for this area.")
    lyr = job.layers[layer_id]
    if lyr["group"] in ("risk", "hazard"):
        # Class maps: one pre-rendered image (fast to pan/zoom) instead of thousands of heavy tiles.
        try:
            pipeline.overlay_png(job, layer_id)
            minx, miny, maxx, maxy = job.aoi["bounds"]
            return jsonify(overlay=f"/api/layers/{layer_id}/overlay.png?v={job.id}", bounds=[[miny, minx], [maxy, maxx]])
        except Exception as exc:
            print(f"[overlay] {layer_id} falling back to tiles: {exc}")
    try:
        return jsonify(url=pipeline.tile_url(job, layer_id))
    except Exception as exc:
        return err(f"Could not load this layer: {exc}", 500)


@app.get("/api/layers/<layer_id>/overlay.png")
def layer_overlay(layer_id):
    job = completed_job()
    if not job or layer_id not in job.layers:
        return err("Unknown layer.", 404)
    try:
        resp = send_file(io.BytesIO(pipeline.overlay_png(job, layer_id)), mimetype="image/png")
    except Exception as exc:
        return err(str(exc), 500)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/statistics")
def statistics():
    job = completed_job()
    return jsonify(job.stats) if job else err("No completed assessment.", 404)


@app.post("/api/map/point-info")
def point_info():
    job = completed_job()
    if not job:
        return err("No completed assessment.", 404)
    d = request.get_json(force=True)
    try:
        v = pipeline.point_info(job, float(d["lat"]), float(d["lng"]))
    except Exception as exc:
        return err(f"Could not read this location: {exc}", 500)
    if not v or all(x is None for x in v.values()):
        return jsonify(outside=True)
    lv = lambda c: config.LEVELS[int(c) - 1] if c else None
    out = {"risks": [], "indicators": []}
    for hz in pipeline.HAZARDS:
        out["risks"].append({"hazard": hz, "name": job.frameworks[hz].name, "level": lv(v.get(f"{hz}__riskcls")),
                             "value": v.get(f"{hz}__risk")})
    layer = job.layers.get(d.get("layer", ""))
    focus = layer["hazard"] if layer else None
    if focus in job.frameworks:
        for ind in job.frameworks[focus].indicators:
            out["indicators"].append({"label": ind.label, "unit": ind.unit, "value": v.get(f"{focus}__raw__{ind.key}")})
        out["focus"] = job.frameworks[focus].name
    return jsonify(out)


# ---------------- recommendations / report ----------------
def _compute_recs(job, tick=None):
    """Priority areas + recommendations. Runs once per assessment, only when asked for (button or report)."""
    with job.rec_lock:
        if job.recs is not None:
            return False
        st = job.rec_state = {"state": "running", "done": 0, "total": 4, "error": None, "notes": []}

        def bump():
            st["done"] += 1
            if tick:
                tick()
        try:
            job.priority, st["notes"] = pipeline.compute_priority(job, bump)
            job.recs = build_recommendations(job.priority, store.place_name_at)
            bump()
            st["state"] = "done"
        except Exception as exc:
            import traceback
            traceback.print_exc()
            st["state"], st["error"] = "failed", f"Recommendations could not be generated: {exc}"
            raise
        return True


def _recs_thread(job):
    try:
        _compute_recs(job)
    except Exception:
        pass                                   # error is stored in job.rec_state


@app.post("/api/recommendations")
def recommendations():
    """Starts generating recommendations (or says they are ready). Progress: /api/recommendations/status."""
    job = completed_job()
    if not job:
        return err("Complete an assessment first.", 409)
    if job.recs is not None:
        return jsonify(state="done")
    if job.rec_state and job.rec_state["state"] == "running":
        return jsonify(state="running")
    threading.Thread(target=_recs_thread, args=(job,), daemon=True).start()
    return jsonify(state="running")


@app.get("/api/recommendations/status")
def recommendations_status():
    job = completed_job()
    if not job:
        return err("No completed assessment.", 404)
    if job.recs is not None:
        return jsonify(state="done", progress=100)
    st = job.rec_state
    if not st:
        return jsonify(state="none", progress=0)
    return jsonify(state=st["state"], progress=min(97, int(100 * st["done"] / st["total"])), error=st["error"])


@app.get("/api/recommendations/result")
def recommendations_result():
    job = completed_job()
    if not job or job.recs is None:
        return err("Recommendations are not ready yet.", 409)
    return jsonify(recommendations=job.recs, notes=(job.rec_state or {}).get("notes", []))


def _build_report(job):
    """Runs in a background thread so the browser can show real progress. A map that fails to render
    becomes a 'could not be rendered' note in the PDF instead of stopping the whole report."""
    r = job.report
    try:
        framework_keys = list(pipeline.HAZARDS) + (["socio"] if "socio" in job.frameworks else [])
        ids = [f"risk_{h}" for h in pipeline.HAZARDS] + [f"ind_{h}_{i.key}" for h in framework_keys
                                                          for i in job.frameworks[h].indicators if i.available]
        r["total"] = len(ids) + 1 + 4

        def tick():
            r["done"] += 1

        try:                                             # recommendations are part of the report
            if not _compute_recs(job, tick):
                r["done"] += 4
        except Exception:
            if job.recs is None:
                job.recs = []
            r["warnings"].append("Recommendations could not be generated.")

        def fetch(layer_id):
            try:
                if layer_id.startswith("risk_"):
                    png = pipeline.overlay_png(job, layer_id)            # already rendered for the web map
                else:
                    png = pipeline.map_png(job, layer_id, 700, outline=False, crs=pipeline.OVERLAY_CRS)
            except Exception as exc:
                print(f"[report] map {layer_id} failed: {exc}")
                png = None
            r["done"] += 1
            return layer_id, png

        with ThreadPoolExecutor(max_workers=3) as ex:      # fewer at once = less memory on a small server
            pngs = dict(ex.map(fetch, ids))
        r["pdf"] = report.generate_report(job, pngs, {h: C.PALETTES[h] for h in pipeline.HAZARDS})
        r["done"], r["state"] = r["total"], "done"
    except Exception as exc:
        import traceback
        traceback.print_exc()
        r["state"], r["error"] = "failed", f"The report could not be generated: {exc}"


@app.post("/api/report/start")
def report_start():
    job = completed_job()
    if not job:
        return err("No completed assessment.", 404)
    if job.report and job.report["state"] == "running":
        return jsonify(state="running")
    if job.report and job.report["state"] == "done":
        return jsonify(state="done")
    job.report = {"state": "running", "done": 0, "total": 1, "pdf": None, "error": None, "warnings": []}
    threading.Thread(target=_build_report, args=(job,), daemon=True).start()
    return jsonify(state="running")


@app.get("/api/report/status")
def report_status():
    job = completed_job()
    r = job.report if job else None
    if not r:
        return jsonify(state="none", progress=0)
    pct = 100 if r["state"] == "done" else min(97, int(100 * r["done"] / max(r["total"], 1)))
    return jsonify(state=r["state"], progress=pct, error=r["error"])


@app.get("/api/report/download")
def report_download():
    job = completed_job()
    if not job or not job.report or job.report["state"] != "done":
        return err("The report is not ready yet.", 409)
    loc = re.sub(r'[\\/*?:"<>|]', '', str(job.label or '')).strip()
    download_name = f"ClimateReady Resilience Report - {loc}.pdf" if loc else "ClimateReady Resilience Report.pdf"
    resp = send_file(io.BytesIO(job.report["pdf"]), mimetype="application/pdf", as_attachment=True,
                     download_name=download_name)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/api/version")
def version():
    """Open http://127.0.0.1:5000/api/version to see exactly which code is running."""
    import gee.common as _c
    return jsonify(build=BUILD, app_file=__file__, common_file=_c.__file__,
                   has_scorer=hasattr(_c, "Scorer"))


if __name__ == "__main__":
    import gee.common as _c
    print(f"[ClimateReady] build={BUILD}\n[ClimateReady] app   : {__file__}\n[ClimateReady] common: {_c.__file__}"
          f"\n[ClimateReady] missing-data handling present: {hasattr(_c, 'Scorer')}")
    app.run(debug=False, threaded=True, use_reloader=False)

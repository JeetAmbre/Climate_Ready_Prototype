"""ClimateReady Flask app. Routes only; science lives in gee/, queue in jobs.py, PDF in report.py."""
import io
import re
import threading
import time
import uuid
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file, session, redirect, url_for
import requests

import config
import jobs as jobs_mod
from gee import common as C
from gee import pipeline
from services.ai_agent import run_intervention_discovery
from services.decision_planner import (
    enrich_intervention_polygons,
    calculate_financials,
    optimize_portfolio,
    summarize_portfolio,
    generate_ai_decision_brief,
)
from services.gee_live_tracking import tracking_service
from locations import LocationStore, build_aoi
from projects import ProjectStore
import auth
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
    return {
        "build_id": BUILD_ID,
        "current_user": session.get("user"),
        "is_google_auth_configured": auth.is_google_auth_configured()
    }


app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

store = LocationStore()
store.load()
project_store = ProjectStore()
_ee_ready = False


def _ensure_ee():
    global _ee_ready
    if not _ee_ready:
        C.init_earth_engine()
        _ee_ready = True


def _run_assessment_job(job):
    _ensure_ee()
    pipeline.run_assessment(job)
    pid = getattr(job, "project_id", None)
    if pid:
        try:
            proj_dir = Path("data") / "projects" / pid
            proj_dir.mkdir(parents=True, exist_ok=True)
            tile_urls = {}
            for hz in pipeline.HAZARDS:
                lid = f"risk_{hz}"
                try:
                    png = pipeline.overlay_png(job, lid)
                    (proj_dir / f"{lid}.png").write_bytes(png)
                    print(f"[app] Saved {lid}.png to {proj_dir}")
                except Exception as e:
                    print(f"[app] Error saving {lid}.png to disk: {e}")
                try:
                    tile_urls[lid] = pipeline.tile_url(job, lid)
                except Exception:
                    pass

            ass_data = {
                "label": job.label,
                "aoi": job.aoi["geojson"],
                "bounds": job.aoi["bounds"],
                "warnings": job.warnings,
                "stats": job.stats,
                "tile_urls": tile_urls,
                "layers": [{"id": k, "label": v["label"], "group": v["group"], "hazard": v["hazard"],
                            "legend": v["legend"], "available": v.get("available", True)}
                           for k, v in job.layers.items()]
            }
            project_store.save_project_assessment(pid, ass_data)
            print(f"[app] Successfully persisted assessment data for project {pid}")
        except Exception as e:
            print(f"[app] Error persisting assessment for project {pid}: {e}")


manager = jobs_mod.JobManager(_run_assessment_job)


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

@app.route("/explore")
@app.route("/analysis", endpoint="analysis")
def explore():
    # Live Risk Explorer is replaced by Assessment
    return redirect(url_for("assessment"))

@app.route("/assessment")
@app.route("/workspace")
def assessment():
    user = session.get("user")
    if not user:
        return render_template("auth_wall.html")
    user_id = user.get("id")
    projects = project_store.list_projects(user_id=user_id)
    cfg = {"limits": config.MAX_LOCATIONS, "maxUploadMb": config.MAX_UPLOAD_MB, "levels": config.LEVELS,
           "loaded": {k: k in store.levels for k in ("district", "subdistrict")}, "errors": store.errors}
    return render_template("workspace_dashboard.html", projects=projects, cfg=cfg)

@app.route("/assessment/<project_id>")
@app.route("/workspace/<project_id>")
def assessment_project(project_id):
    user = session.get("user")
    if not user:
        return redirect(url_for("assessment"))
    project = project_store.get_project(project_id)
    if not project:
        user_id = user.get("id")
        return render_template("workspace_dashboard.html", projects=project_store.list_projects(user_id=user_id),
                               error="Project not found.")
    
    # Check if this project already has completed assessment data stored in DB
    job_id = f"proj_job_{project_id}"
    session["job_id"] = job_id
    session["project_id"] = project_id
    
    ass = project.get("assessment_data")
    if ass:
        bounds = ass.get("bounds") or [0, 0, 0, 0]
        aoi_geojson = ass.get("aoi") or {}
        from shapely.geometry import shape
        try:
            geom_obj = shape(aoi_geojson) if aoi_geojson else None
        except Exception:
            geom_obj = None

        rehydrated = jobs_mod.Job(
            aoi={
                "geojson": aoi_geojson,
                "bounds": bounds,
                "centroid": {"lng": (bounds[0] + bounds[2]) / 2, "lat": (bounds[1] + bounds[3]) / 2},
                "area_km2": ass.get("stats", {}).get("overview", {}).get("area_km2", 0),
                "geom": geom_obj
            },
            label=ass.get("label", project["location_name"]),
            mode=project.get("level", "district")
        )
        rehydrated.id = job_id
        rehydrated.state = jobs_mod.COMPLETED
        rehydrated.stats = ass.get("stats")
        rehydrated.warnings = ass.get("warnings", [])
        rehydrated.layers = {l["id"]: l for l in ass.get("layers", [])} if isinstance(ass.get("layers"), list) else ass.get("layers", {})
        rehydrated.project_id = project_id
        rehydrated.recs = project.get("interventions_data") or []

        # Load cached overlay PNGs from disk into rehydrated.png_cache
        proj_dir = Path("data") / "projects" / project_id
        missing_pngs = []
        for hz in pipeline.HAZARDS:
            lid = f"risk_{hz}"
            p_file = proj_dir / f"{lid}.png"
            if p_file.exists():
                rehydrated.png_cache[("overlay", lid)] = p_file.read_bytes()
            else:
                missing_pngs.append(lid)

        # Backfill PNGs in background if missing
        if missing_pngs and aoi_geojson:
            def _backfill_pngs(job_to_run, pid_to_save):
                try:
                    _ensure_ee()
                    pipeline.run_assessment(job_to_run)
                    p_dir = Path("data") / "projects" / pid_to_save
                    p_dir.mkdir(parents=True, exist_ok=True)
                    for h in pipeline.HAZARDS:
                        l = f"risk_{h}"
                        p_bytes = pipeline.overlay_png(job_to_run, l)
                        (p_dir / f"{l}.png").write_bytes(p_bytes)
                        job_to_run.png_cache[("overlay", l)] = p_bytes
                    print(f"[app] Backfilled PNG overlays for project {pid_to_save}")
                except Exception as ex:
                    print(f"[app] Error backfilling PNG overlays: {ex}")
            threading.Thread(target=_backfill_pngs, args=(rehydrated, project_id), daemon=True).start()

        manager.jobs[job_id] = rehydrated

    cfg = {"limits": config.MAX_LOCATIONS, "maxUploadMb": config.MAX_UPLOAD_MB, "levels": config.LEVELS,
           "loaded": {k: k in store.levels for k in ("district", "subdistrict")}, "errors": store.errors}
    return render_template("workspace_project.html", project=project, cfg=cfg)

@app.post("/api/projects/create")
def api_project_create():
    user = session.get("user")
    if not user or not user.get("id"):
        return err("Authentication is required to create a project.", 401)
    d = request.get_json(force=True) or {}
    name = d.get("name", "").strip()
    level = d.get("level", "district")
    loc_id = d.get("location_id", "").strip()
    loc_name = d.get("location_name", "").strip()
    if not loc_id or not loc_name:
        return err("Location is required.")
    try:
        project = project_store.create_project(name, level, loc_id, loc_name, user_id=user.get("id"))
        return jsonify(ok=True, project=project)
    except Exception as e:
        return err(str(e), 400)

@app.post("/api/projects/<project_id>/assessment")
def api_project_save_assessment(project_id):
    user = session.get("user")
    if not user:
        return err("Authentication required.", 401)
    d = request.get_json(force=True) or {}
    ok = project_store.save_project_assessment(project_id, d)
    return jsonify(ok=ok)

@app.post("/api/projects/<project_id>/interventions")
def api_project_save_interventions(project_id):
    d = request.get_json(force=True) or {}
    interventions = d.get("interventions", [])
    ok = project_store.save_project_interventions(project_id, interventions)
    return jsonify(ok=ok)

@app.delete("/api/projects/<project_id>")
def api_project_delete(project_id):
    ok = project_store.delete_project(project_id)
    return jsonify(ok=ok)

# ---------------- Evaluator & Google Auth Routes ----------------
@app.route("/auth/evaluator")
def auth_evaluator():
    eval_id = uuid.uuid4().hex[:6]
    user_data = {
        "id": f"evaluator_{eval_id}",
        "name": f"Evaluator #{eval_id.upper()}",
        "email": f"evaluator_{eval_id}@buildathon.eval",
        "picture": ""
    }
    auth.save_user_profile(user_data)
    session["user"] = user_data
    return redirect(url_for("assessment"))

@app.route("/login")
def login():
    if not auth.is_google_auth_configured():
        return redirect(url_for("auth_evaluator"))

    provider_cfg = auth.get_google_provider_cfg()
    if not provider_cfg:
        return "Failed to contact Google OpenID service.", 500
    authorization_endpoint = provider_cfg["authorization_endpoint"]

    from urllib.parse import urlencode
    redirect_uri = url_for("auth_callback", _external=True)
    request_uri = authorization_endpoint + "?" + urlencode({
        "client_id": auth.GOOGLE_CLIENT_ID,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri,
        "access_type": "offline",
        "prompt": "select_account"
    })
    return redirect(request_uri)

@app.route("/auth/callback")
def auth_callback():
    code = request.args.get("code")
    if not code:
        return "Authorization code missing.", 400
    provider_cfg = auth.get_google_provider_cfg()
    token_endpoint = provider_cfg["token_endpoint"]
    redirect_uri = url_for("auth_callback", _external=True)

    token_res = requests.post(
        token_endpoint,
        data={
            "code": code,
            "client_id": auth.GOOGLE_CLIENT_ID,
            "client_secret": auth.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    tokens = token_res.json()
    userinfo_endpoint = provider_cfg["userinfo_endpoint"]
    user_res = requests.get(
        userinfo_endpoint,
        headers={"Authorization": f"Bearer {tokens.get('access_token')}"}
    )
    user_info = user_res.json()
    user_id = user_info.get("sub") or user_info.get("id") or user_info.get("email")
    session["user"] = {
        "id": user_id,
        "name": user_info.get("name", "User"),
        "email": user_info.get("email", ""),
        "picture": user_info.get("picture", "")
    }
    auth.save_user_profile(session["user"])
    return redirect(url_for("assessment"))

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))

@app.route("/methodology")
@app.route("/explore-and-learn")
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
    job.project_id = d.get("project_id")
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
def resolve_job_for_request():
    job = completed_job()
    if job:
        return job
    pid = request.args.get("project_id") or request.args.get("pid")
    if not pid and request.is_json:
        pid = (request.get_json(silent=True) or {}).get("project_id")
    if not pid:
        pid = session.get("project_id")
    if not pid and session.get("job_id", "").startswith("proj_job_"):
        pid = session["job_id"].replace("proj_job_", "")
    if pid:
        job_id = f"proj_job_{pid}"
        job = manager.get(job_id)
        if job:
            return job
        project = project_store.get_project(pid)
        if project and project.get("assessment_data"):
            ass = project["assessment_data"]
            bounds = ass.get("bounds") or [0, 0, 0, 0]
            aoi_geojson = ass.get("aoi") or {}
            from shapely.geometry import shape
            try:
                geom_obj = shape(aoi_geojson) if aoi_geojson else None
            except Exception:
                geom_obj = None
            rehydrated = jobs_mod.Job(
                aoi={
                    "geojson": aoi_geojson,
                    "bounds": bounds,
                    "centroid": {"lng": (bounds[0] + bounds[2]) / 2, "lat": (bounds[1] + bounds[3]) / 2},
                    "area_km2": ass.get("stats", {}).get("overview", {}).get("area_km2", 0),
                    "geom": geom_obj
                },
                label=ass.get("label", project["location_name"]),
                mode=project.get("level", "district")
            )
            rehydrated.id = job_id
            rehydrated.state = jobs_mod.COMPLETED
            rehydrated.stats = ass.get("stats")
            rehydrated.warnings = ass.get("warnings", [])
            rehydrated.layers = {l["id"]: l for l in ass.get("layers", [])} if isinstance(ass.get("layers"), list) else ass.get("layers", {})
            rehydrated.project_id = pid
            rehydrated.recs = project.get("interventions_data") or []

            proj_dir = Path("data") / "projects" / pid
            for hz in pipeline.HAZARDS:
                lid = f"risk_{hz}"
                p_file = proj_dir / f"{lid}.png"
                if p_file.exists():
                    rehydrated.png_cache[("overlay", lid)] = p_file.read_bytes()

            manager.jobs[job_id] = rehydrated
            session["job_id"] = job_id
            return rehydrated
    return None


@app.get("/api/layers")
def layers():
    job = resolve_job_for_request() or completed_job()
    if not job:
        return err("No completed assessment.", 404)
    out = [{"id": k, "label": v["label"], "group": v["group"], "hazard": v["hazard"], "legend": v["legend"],
            "available": v.get("available", True)} for k, v in job.layers.items()]
    return jsonify(layers=out, warnings=job.warnings, aoi=job.aoi["geojson"], bounds=job.aoi["bounds"], label=job.label,
                   date=date.today().isoformat(), has_recs=job.recs is not None)


@app.get("/api/layers/<layer_id>/tiles")
def layer_tiles(layer_id):
    job = resolve_job_for_request() or completed_job()
    pid = getattr(job, "project_id", None) or request.args.get("project_id") or request.args.get("pid") or session.get("project_id")
    if not pid and session.get("job_id", "").startswith("proj_job_"):
        pid = session["job_id"].replace("proj_job_", "")

    # 1. If overlay image exists on disk or in png_cache, return overlay immediately
    has_overlay = False
    if job and ("overlay", layer_id) in getattr(job, "png_cache", {}):
        has_overlay = True
    elif pid:
        disk_overlay = Path("data") / "projects" / pid / f"{layer_id}.png"
        if disk_overlay.exists():
            has_overlay = True

    if has_overlay and job and getattr(job, "aoi", None) and "bounds" in job.aoi:
        minx, miny, maxx, maxy = job.aoi["bounds"]
        return jsonify(overlay=f"/api/layers/{layer_id}/overlay.png?pid={pid or job.id}", bounds=[[miny, minx], [maxy, maxx]])

    # 2. Check if job has live EE images to generate overlay
    if not job or layer_id not in job.layers:
        return err("Unknown layer.", 404)
    if not job.layers[layer_id].get("available", True):
        return jsonify(unavailable=True, message="Data not available for this area.")
    lyr = job.layers[layer_id]

    # If job was rehydrated from database and lacks ee.Image objects, restore them on-demand
    if isinstance(lyr, dict) and "image" not in lyr and hasattr(job, "aoi") and job.aoi:
        try:
            _ensure_ee()
            pipeline.run_assessment(job)
            lyr = job.layers.get(layer_id, {})
        except Exception as exc:
            print(f"[layer_tiles] Could not restore EE images for {layer_id}: {exc}")

    if isinstance(lyr, dict) and lyr.get("group") in ("risk", "hazard") and "image" in lyr:
        try:
            png_bytes = pipeline.overlay_png(job, layer_id)
            if pid:
                p_dir = Path("data") / "projects" / pid
                p_dir.mkdir(parents=True, exist_ok=True)
                (p_dir / f"{layer_id}.png").write_bytes(png_bytes)
            minx, miny, maxx, maxy = job.aoi["bounds"]
            return jsonify(overlay=f"/api/layers/{layer_id}/overlay.png?pid={pid or job.id}", bounds=[[miny, minx], [maxy, maxx]])
        except Exception as exc:
            print(f"[overlay] {layer_id} falling back to tiles: {exc}")

    # 3. Check tile URL
    if isinstance(lyr, dict) and "image" in lyr:
        try:
            return jsonify(url=pipeline.tile_url(job, layer_id))
        except Exception as exc:
            return err(f"Could not load this layer: {exc}", 500)

    return err("Layer data currently unavailable.", 404)


@app.get("/api/layers/<layer_id>/overlay.png")
def layer_overlay(layer_id):
    pid = request.args.get("pid") or request.args.get("project_id")
    if not pid:
        job = resolve_job_for_request() or completed_job()
        pid = getattr(job, "project_id", None)
        if not pid and session.get("job_id", "").startswith("proj_job_"):
            pid = session["job_id"].replace("proj_job_", "")

    if pid:
        p_file = Path("data") / "projects" / pid / f"{layer_id}.png"
        if p_file.exists():
            resp = send_file(p_file, mimetype="image/png")
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp

    job = resolve_job_for_request() or completed_job()
    if job and ("overlay", layer_id) in getattr(job, "png_cache", {}):
        resp = send_file(io.BytesIO(job.png_cache[("overlay", layer_id)]), mimetype="image/png")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    if not job or layer_id not in job.layers:
        return err("Unknown layer.", 404)
    lyr = job.layers[layer_id]
    if isinstance(lyr, dict) and "image" in lyr:
        try:
            png_bytes = pipeline.overlay_png(job, layer_id)
            if pid:
                p_dir = Path("data") / "projects" / pid
                p_dir.mkdir(parents=True, exist_ok=True)
                (p_dir / f"{layer_id}.png").write_bytes(png_bytes)
            resp = send_file(io.BytesIO(png_bytes), mimetype="image/png")
            resp.headers["Cache-Control"] = "no-store"
            return resp
        except Exception as exc:
            return err(str(exc), 500)

    return err("Overlay not available.", 404)


@app.get("/api/statistics")
def statistics():
    job = resolve_job_for_request() or completed_job()
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
def _compute_recs(job, tick=None, force_refresh=False):
    """Priority areas + AI-grounded interventions via LangGraph Agent."""
    with job.rec_lock:
        if not force_refresh and job.recs is not None and len(job.recs) > 0:
            return False
        st = job.rec_state = {"state": "running", "done": 0, "total": 4, "error": None, "notes": []}

        def bump(*args, **kwargs):
            st["done"] += 1
            if tick:
                tick()
        try:
            pid = getattr(job, "project_id", None) or session.get("project_id") or (job.id.replace("proj_job_", "") if getattr(job, "id", "").startswith("proj_job_") else "")
            
            # Compute spatial priority clusters if live frameworks present
            if hasattr(job, "frameworks") and job.frameworks:
                try:
                    job.priority, st["notes"] = pipeline.compute_priority(job, bump)
                except Exception as ex:
                    print(f"[app] Note: live Earth Engine priority clusters skipped: {ex}")
            
            bump()
            # Run modular LangGraph AI Agent with spatial-visual analysis
            job.recs = run_intervention_discovery(pid, target_risk="both", force_refresh=force_refresh, on_progress=bump)
            if pid and job.recs:
                project_store.save_project_interventions(pid, job.recs)
            bump()
            st["state"] = "done"
        except Exception as exc:
            import traceback
            traceback.print_exc()
            st["state"], st["error"] = "failed", f"Recommendations could not be generated: {exc}"
            raise
        return True


def _recs_thread(job, force_refresh=False):
    try:
        _compute_recs(job, force_refresh=force_refresh)
    except Exception:
        pass                                   # error is stored in job.rec_state


@app.post("/api/recommendations")
def recommendations():
    """Starts generating recommendations (or says they are ready). Progress: /api/recommendations/status."""
    req_json = request.get_json(silent=True) or {}
    pid = request.args.get("project_id") or request.args.get("pid") or req_json.get("project_id")
    if not pid:
        pid = session.get("project_id")

    job = resolve_job_for_request() or completed_job()
    if not job:
        return err("Complete an assessment first.", 409)

    if pid:
        job.project_id = pid
        session["project_id"] = pid

    refresh = (request.args.get("refresh") in ("1", "true") or req_json.get("refresh", False))

    if refresh:
        job.recs = None
        job.rec_state = None

    if not refresh and job.recs is not None and len(job.recs) > 0:
        if pid:
            project_store.save_project_interventions(pid, job.recs)
        return jsonify(state="done")
    if job.rec_state and job.rec_state["state"] == "running":
        return jsonify(state="running")
    threading.Thread(target=_recs_thread, args=(job, refresh), daemon=True).start()
    return jsonify(state="running")


@app.get("/api/recommendations/status")
def recommendations_status():
    job = resolve_job_for_request() or completed_job()
    if not job:
        return err("No completed assessment.", 404)
    if job.recs is not None and len(job.recs) > 0:
        return jsonify(state="done", progress=100)
    st = job.rec_state
    if not st:
        return jsonify(state="none", progress=0)
    return jsonify(state=st["state"], progress=min(97, int(100 * st["done"] / st["total"])), error=st["error"])


@app.get("/api/recommendations/result")
def recommendations_result():
    job = resolve_job_for_request() or completed_job()
    if not job or job.recs is None:
        return err("Recommendations are not ready yet.", 409)

    pid = request.args.get("project_id") or getattr(job, "project_id", None) or session.get("project_id")
    if pid and job.recs:
        try:
            project_store.save_project_interventions(pid, job.recs)
        except Exception as e:
            print(f"[app] Note: auto-saving project interventions: {e}")

    return jsonify(recommendations=job.recs, notes=(job.rec_state or {}).get("notes", []))


# ---------------- Module 3: Decision Planner ----------------
@app.route("/api/decision_planner/enrich", methods=["GET", "POST"])
def api_decision_planner_enrich():
    """Deterministic polygon geodesic area + Earth Engine population enrichment."""
    req_json = request.get_json(silent=True) or {}
    pid = request.args.get("project_id") or req_json.get("project_id")
    job = resolve_job_for_request()
    if not pid:
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    # If incoming interventions provided in request body, save them to the project
    incoming_recs = req_json.get("interventions") or []
    if incoming_recs and isinstance(incoming_recs, list) and len(incoming_recs) > 0:
        project_store.save_project_interventions(pid, incoming_recs)

    # If project interventions are missing from store, check in-memory job
    proj = project_store.get_project(pid)
    if (not proj or not proj.get("interventions_data")) and job and getattr(job, "recs", None):
        project_store.save_project_interventions(pid, job.recs)

    force = request.args.get("force") == "1" or req_json.get("force") is True
    enriched = enrich_intervention_polygons(pid, force=force)
    if job and enriched:
        job.recs = enriched
    return jsonify(ok=True, interventions=enriched)


@app.post("/api/decision_planner/optimize")
def api_decision_planner_optimize():
    """Goal-driven budget optimizer across candidates."""
    d = request.get_json(force=True) or {}
    pid = d.get("project_id")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    budget = float(d.get("budget_inr", 2500000.0))
    coverage = float(d.get("coverage_pct", 30.0))
    goal = d.get("goal", "people_protected")
    hazard_filter = d.get("hazard_filter", "all")

    enriched = enrich_intervention_polygons(pid, force=False)
    result = optimize_portfolio(enriched, budget_inr=budget, coverage_pct=coverage, goal=goal, hazard_filter=hazard_filter)
    return jsonify(ok=True, **result)


@app.post("/api/decision_planner/summarize")
def api_decision_planner_summarize():
    """Recalculate portfolio metrics for custom manual selection."""
    d = request.get_json(force=True) or {}
    pid = d.get("project_id")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    selected_ids = d.get("selected_ids", [])
    budget = float(d.get("budget_inr", 2500000.0))
    coverage = float(d.get("coverage_pct", 30.0))

    enriched = enrich_intervention_polygons(pid, force=False)
    items_with_fin = []
    for r in enriched:
        it = dict(r)
        it.update(calculate_financials(r, coverage))
        items_with_fin.append(it)

    portfolio = summarize_portfolio(items_with_fin, selected_ids, budget)
    return jsonify(ok=True, portfolio=portfolio, items=items_with_fin)


@app.post("/api/decision_planner/ai_brief")
def api_decision_planner_ai_brief():
    """Generate 1 single grounded AI executive decision brief on selected interventions."""
    d = request.get_json(force=True) or {}
    pid = d.get("project_id")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    selected_ids = d.get("selected_ids", [])
    budget = float(d.get("budget_inr", 2500000.0))
    coverage = float(d.get("coverage_pct", 30.0))
    goal = d.get("goal", "people_protected")
    stakeholder = d.get("stakeholder_type", "municipal_dpr")

    brief = generate_ai_decision_brief(
        project_id=pid,
        selected_ids=selected_ids,
        budget_inr=budget,
        coverage_pct=coverage,
        goal=goal,
        stakeholder_type=stakeholder,
    )
    return jsonify(ok=True, brief=brief)


@app.post("/api/decision_planner/lock_plan")
def api_decision_planner_lock_plan():
    """Finalize and lock the adaptation plan in Cloud SQL (bridge to Module 4)."""
    d = request.get_json(force=True) or {}
    pid = d.get("project_id")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    plan = project_store.save_decision_plan(pid, d)
    if not plan:
        return err("Failed to lock decision plan.", 500)
    return jsonify(ok=True, plan=plan)


@app.get("/api/decision_planner/locked_plan")
def api_decision_planner_get_locked_plan():
    """Retrieve active locked plan for a project."""
    pid = request.args.get("project_id")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    plan = project_store.get_locked_plan(pid)
    return jsonify(ok=True, plan=plan)


# ---------------- Module 4: Tracking & Impact API Endpoints ----------------
@app.get("/api/tracking/status")
def api_tracking_status():
    """Retrieve Stage 4 tracking state, locked plan metadata, and existing impact calculation."""
    pid = request.args.get("project_id") or request.args.get("pid")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    plan = project_store.get_locked_plan(pid)
    if not plan:
        return jsonify(ok=True, has_locked_plan=False)

    return jsonify(
        ok=True,
        has_locked_plan=True,
        plan=plan,
        impact_summary=plan.get("impact_summary"),
    )


@app.get("/api/tracking/live_layer")
def api_tracking_live_layer():
    """Fetch live satellite observation overlay metadata (rolling 60-day Earth Engine window)."""
    pid = request.args.get("project_id") or request.args.get("pid")
    hazard = request.args.get("hazard", "uhi").lower()
    force_refresh = request.args.get("refresh", "0") in ("1", "true")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    res = tracking_service.get_live_monitoring_layer(pid, hazard=hazard, force_refresh=force_refresh)
    return jsonify(res)


@app.get("/api/tracking/live_overlay.png")
def api_tracking_live_overlay_png():
    """Serve cached live satellite PNG overlay for Leaflet."""
    pid = request.args.get("project_id") or request.args.get("pid")
    hazard = request.args.get("hazard", "uhi").lower()
    if not pid:
        return err("Project ID required.", 400)

    png_path = Path("data") / "projects" / pid / f"live_{hazard}.png"
    if not png_path.exists():
        # Fallback to baseline raster overlay
        png_path = Path("data") / "projects" / pid / f"risk_{hazard}.png"

    if png_path.exists():
        return send_file(png_path, mimetype="image/png")
    return err("Live overlay image not available.", 404)


@app.post("/api/tracking/calculate_impact")
def api_tracking_calculate_impact():
    """Calculate and persist post-intervention impact comparing 2024-2025 baseline vs. latest satellite observation."""
    d = request.get_json(force=True) or {}
    pid = d.get("project_id") or request.args.get("project_id")
    hazard = d.get("hazard")
    if not pid:
        job = resolve_job_for_request()
        pid = getattr(job, "project_id", None) if job else session.get("project_id")
    if not pid:
        return err("Project ID required.", 400)

    res = tracking_service.calculate_post_intervention_impact(pid, hazard=hazard)
    return jsonify(res)


def _build_report(job):
    """Runs in a background thread so the browser can show real progress. A map that fails to render
    becomes a 'could not be rendered' note in the PDF instead of stopping the whole report."""
    r = job.report
    try:
        pid = getattr(job, "project_id", None)
        framework_keys = [h for h in pipeline.HAZARDS if h in getattr(job, "frameworks", {})]
        if "socio" in getattr(job, "frameworks", {}):
            framework_keys.append("socio")

        ids = [f"risk_{h}" for h in pipeline.HAZARDS]
        for h in framework_keys:
            fw = job.frameworks.get(h)
            if fw and hasattr(fw, "indicators"):
                ids += [f"ind_{h}_{i.key}" for i in fw.indicators if getattr(i, "available", True)]

        r["total"] = len(ids) + 5

        def tick():
            r["done"] = min(r["total"] - 1, r["done"] + 1)

        # 1. Recommendations
        if not getattr(job, "recs", None):
            if pid:
                p = project_store.get_project(pid)
                if p and p.get("interventions_data"):
                    job.recs = p["interventions_data"]
            if not getattr(job, "recs", None) and hasattr(job, "frameworks") and job.frameworks:
                try:
                    _compute_recs(job, tick)
                except Exception:
                    job.recs = []
        r["done"] += 2

        # 2. Fetch PNGs
        def fetch(layer_id):
            png = None
            try:
                if ("overlay", layer_id) in getattr(job, "png_cache", {}):
                    png = job.png_cache[("overlay", layer_id)]
                if not png and pid:
                    p_disk = Path("data") / "projects" / pid / f"{layer_id}.png"
                    if p_disk.exists():
                        png = p_disk.read_bytes()
                if not png and layer_id in getattr(job, "layers", {}) and isinstance(job.layers[layer_id], dict) and "image" in job.layers[layer_id]:
                    if layer_id.startswith("risk_"):
                        png = pipeline.overlay_png(job, layer_id)
                    else:
                        png = pipeline.map_png(job, layer_id, 700, outline=False, crs=pipeline.OVERLAY_CRS)
            except Exception as exc:
                print(f"[report] map {layer_id} failed: {exc}")
                png = None
            r["done"] += 1
            return layer_id, png

        with ThreadPoolExecutor(max_workers=3) as ex:
            pngs = dict(ex.map(fetch, ids))

        r["pdf"] = report.generate_report(job, pngs, {h: C.PALETTES[h] for h in pipeline.HAZARDS})
        r["done"] = r["total"]
        r["state"] = "done"
    except Exception as exc:
        import traceback
        traceback.print_exc()
        r["state"], r["error"] = "failed", f"The report could not be generated: {exc}"


@app.post("/api/report/start")
def report_start():
    job = resolve_job_for_request()
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
    job = resolve_job_for_request()
    r = job.report if job else None
    if not r:
        return jsonify(state="none", progress=0)
    pct = 100 if r["state"] == "done" else min(97, int(100 * r["done"] / max(r["total"], 1)))
    return jsonify(state=r["state"], progress=pct, error=r["error"])


@app.get("/api/report/download")
def report_download():
    job = resolve_job_for_request()
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

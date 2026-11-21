"""In-memory assessment queue with a concurrency limit. No database, no Redis, no Celery."""
import threading
import time
import uuid
from collections import deque

import config

QUEUED, PROCESSING, COMPLETED, FAILED = "QUEUED", "PROCESSING", "COMPLETED", "FAILED"

class JobCancelled(Exception):
    """Raised inside a running assessment when the user has left the page."""


STEPS = [
    ("prepare", "Preparing selected area"),
    ("uhi", "Processing Urban Heat Island"),
    ("water", "Processing Waterlogging"),
    ("socio", "Processing Socio-economic vulnerability"),
    ("risk", "Combining hazards into final risk maps"),
    ("layers", "Preparing map layers"),
    ("stats", "Calculating area and population statistics"),
    ("render", "Rendering risk maps"),
]


class Job:
    def __init__(self, aoi, label, mode):
        self.id = uuid.uuid4().hex
        self.aoi, self.label, self.mode = aoi, label, mode
        self.state = QUEUED
        self.error = None
        self.created = time.time()
        self.last_seen = time.time()          # updated whenever the user's page contacts the server
        self.started = None
        self.finished = None
        self.steps = [{"key": k, "label": l, "status": "pending"} for k, l in STEPS]
        self.slot_released = False
        self.cancelled = False
        # results (filled by gee.pipeline)
        self.layers = {}          # layer id -> dict(label, group, hazard, image, vis, legend)
        self.tile_cache = {}
        self.png_cache = {}
        self.point_image = None
        self.stats = None
        self.priority = None      # hazard -> list of zones
        self.recs = None
        self.frameworks = {}
        self.crs = None
        self.risk, self.risk_cls = {}, {}      # final risk images (kept for recommendations)
        self.rec_state = None                  # recommendation progress
        self.rec_lock = threading.Lock()
        self.report = None        # PDF generation state
        self.warnings = []        # data that was unavailable, shown to the user

    def step(self, key, status):
        if self.cancelled:                      # stop at the next step boundary
            raise JobCancelled()
        for s in self.steps:
            if s["key"] == key:
                s["status"] = status

    def public_status(self, position=None):
        d = {"state": self.state, "steps": self.steps, "error": self.error, "job_id": self.id}
        if self.state == QUEUED:
            d["queue_position"] = position
        return d


class JobManager:
    def __init__(self, runner):
        self.runner = runner               # function(job) that does the Earth Engine work
        self.jobs = {}
        self.waiting = deque()
        self.active = 0
        self.lock = threading.Lock()
        threading.Thread(target=self._reaper, daemon=True).start()

    def get(self, job_id):
        return self.jobs.get(job_id)

    def submit(self, job):
        """Returns (ok, message). Fails if the queue is full."""
        with self.lock:
            if self.active >= config.MAX_CONCURRENT_ASSESSMENTS and len(self.waiting) >= config.MAX_QUEUE_SIZE:
                return False, "ClimateReady is currently at capacity. Please try again shortly."
            self.jobs[job.id] = job
            self.waiting.append(job.id)
            self._start_next()
        return True, ""

    def cancel(self, job):
        """User left the page: drop the job from the queue / free its slot / forget its results."""
        with self.lock:
            self._cancel_locked(job)

    def _cancel_locked(self, job):
        job.cancelled = True
        if job.state == QUEUED:
            try:
                self.waiting.remove(job.id)
            except ValueError:
                pass
        if job.state in (QUEUED, PROCESSING):
            job.state, job.error = FAILED, "Assessment cancelled."
        if job.started and not job.slot_released:     # was running: free its slot now
            job.slot_released = True
            self.active -= 1
        self.jobs.pop(job.id, None)
        self._start_next()

    def position(self, job):
        with self.lock:
            try:
                return list(self.waiting).index(job.id) + 1
            except ValueError:
                return None

    # ---- internals (call with lock held) ----
    def _start_next(self):
        while self.active < config.MAX_CONCURRENT_ASSESSMENTS and self.waiting:
            job = self.jobs.get(self.waiting.popleft())
            if not job or job.state != QUEUED:
                continue
            self.active += 1
            job.state, job.started = PROCESSING, time.time()
            threading.Thread(target=self._run, args=(job,), daemon=True).start()

    def _release(self, job):
        with self.lock:
            if not job.slot_released:
                job.slot_released = True
                self.active -= 1
            self._start_next()

    def _run(self, job):
        try:
            self.runner(job)
            if job.state == PROCESSING:           # not timed out meanwhile
                job.state = COMPLETED
        except JobCancelled:
            pass                                  # user left; slot was already released by cancel()
        except Exception as exc:                  # show a readable message, keep details in the log
            import traceback
            traceback.print_exc()
            if job.state == PROCESSING:
                job.state, job.error = FAILED, f"The assessment could not be completed: {exc}"
        finally:
            job.finished = time.time()
            self._release(job)

    def _reaper(self):
        """Every few seconds: time out stale jobs and forget old ones."""
        while True:
            time.sleep(10)
            now = time.time()
            with self.lock:
                for job in list(self.jobs.values()):
                    if job.state == QUEUED and now - job.created > config.QUEUED_TIMEOUT_S:
                        job.state = FAILED
                        job.error = "The assessment waited too long in the queue. Please try again."
                    elif job.state == PROCESSING and now - job.started > config.PROCESSING_TIMEOUT_S:
                        job.state = FAILED
                        job.error = "The assessment took longer than expected and was stopped. Please try again."
                        if not job.slot_released:
                            job.slot_released = True
                            self.active -= 1
                    elif job.state in (QUEUED, PROCESSING) and now - job.last_seen > config.HEARTBEAT_TIMEOUT_S:
                        self._cancel_locked(job)             # the user's page is gone: free the slot
                    elif job.finished and now - job.finished > config.JOB_TTL_S:
                        self.jobs.pop(job.id, None)
                self._start_next()

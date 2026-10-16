import os
from flask import Flask
from pagewatch.db import create_tables
from pagewatch.jobqueue import reset_stuck_jobs
from pagewatch.worker import Worker
from pagewatch.scheduler import start_scheduler, stop_scheduler
from pagewatch.web.routes import bp as web_bp

_worker = None


def init(start_worker=True, start_scheduler_thread=True):
    global _worker

    create_tables()
    # reset any jobs left running from an app crash
    reset_stuck_jobs(stuck_minutes=0)

    app = Flask(__name__, template_folder="web/templates")
    app.secret_key = os.environ.get("SECRET_KEY", "pagewatch-default-dev-secret-key")
    app.register_blueprint(web_bp)

    if start_worker and (_worker is None or not _worker._running):
        _worker = Worker()
        _worker.start()
        app.worker = _worker

    if start_scheduler_thread:
        app.scheduler = start_scheduler()
    else:
        app.scheduler = None

    # TODO: add clean shutdown hooks for worker thread
    return app


def stop_worker():
    global _worker
    if _worker is not None and _worker._running:
        _worker.stop()
    _worker = None

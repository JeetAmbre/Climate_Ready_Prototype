"""
wsgi.py - Production WSGI Entrypoint for Gunicorn & Google Cloud Run.
"""
from app import app

if __name__ == "__main__":
    app.run()

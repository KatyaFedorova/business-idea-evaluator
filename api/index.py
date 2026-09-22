"""Vercel entrypoint. FastAPI builds into a single Python function from here."""

from bie.api import create_app

app = create_app()

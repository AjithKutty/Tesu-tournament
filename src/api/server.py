"""FastAPI backend server for the Tournament Manager desktop app.

Usage:
    python -m uvicorn api.server:app --port 8741 --reload

Or from the project root:
    python -m uvicorn src.api.server:app --port 8741
"""

import sys
import os

# Ensure src/ is importable
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import (
    config_routes,
    import_routes,
    schedule_routes,
    results_routes,
    print_routes,
    export_routes,
)

app = FastAPI(
    title="Tournament Manager API",
    description="Backend API for the badminton tournament manager desktop app",
    version="0.1.0",
)

# CORS — allow Electron renderer on localhost
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Desktop app, localhost only
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include route modules
app.include_router(config_routes.router)
app.include_router(import_routes.router)
app.include_router(schedule_routes.router)
app.include_router(results_routes.router)
app.include_router(print_routes.router)
app.include_router(export_routes.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

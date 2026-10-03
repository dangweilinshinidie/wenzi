from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes import router
from app.services.asr import load_model
from app.services.storage import init_db

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
INDEX_FILE = STATIC_DIR / "index.html"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Path(settings.TEMP_DIR).mkdir(parents=True, exist_ok=True)
    init_db()
    load_model()
    logger.info("Service startup complete.")
    yield


app = FastAPI(
    title="Wenzi ASR API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def read_root() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "wenzi-asr",
    }


@app.get("/test", include_in_schema=False)
async def test_page() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.get("/ui", include_in_schema=False)
async def ui_page() -> FileResponse:
    return FileResponse(INDEX_FILE)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")

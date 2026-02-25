from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes import router
from app.services.asr import load_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Path(settings.TEMP_DIR).mkdir(parents=True, exist_ok=True)
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


@app.get("/")
async def read_root() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "wenzi-asr",
    }

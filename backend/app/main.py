"""MathModelAgent 应用入口，配置 FastAPI 应用和中间件。"""

from fastapi import FastAPI
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import os
from app.routers import (
    modeling_reference_router,
    openalex_test_router,
    modeling_router,
    ws_router,
    common_router,
    files_router,
    paper_repair_router,
    artifact_edit_router,
)
from app.utils.log_util import logger
from fastapi.staticfiles import StaticFiles
from app.utils.cli import get_ascii_banner, center_cli_str


@asynccontextmanager
async def lifespan(app: FastAPI):
    print(get_ascii_banner())
    print(center_cli_str("GitHub:https://github.com/jihe520/MathModelAgent"))
    logger.info("Starting MathModelAgent")

    PROJECT_FOLDER = "./project"
    os.makedirs(PROJECT_FOLDER, exist_ok=True)

    yield
    logger.info("Stopping MathModelAgent")


app = FastAPI(
    title="MathModelAgent",
    description="Agents for MathModel",
    version="0.1.0",
    lifespan=lifespan,
)

# Enhanced routes must be registered before the legacy modeling router because
# FastAPI resolves duplicate path+method routes in registration order.
app.include_router(openalex_test_router.router)
app.include_router(modeling_reference_router.router)
app.include_router(modeling_router.router)
app.include_router(ws_router.router)
app.include_router(common_router.router)
app.include_router(paper_repair_router.router)
app.include_router(artifact_edit_router.router)
app.include_router(files_router.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.mount(
    "/static",
    StaticFiles(directory="project/work_dir"),
    name="static",
)

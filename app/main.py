from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.alerts import router as alerts_router
from app.api.analysis import router as analysis_router
from app.api.evidence import router as evidence_router
from app.api.incidents import router as incidents_router
from app.api.reports import router as reports_router
from app.repositories.database import init_database


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    yield


app = FastAPI(
    title="KubeMedic",
    version="0.6.2",
    description="Kubernetes incident investigation service",
    lifespan=lifespan,
)

app.include_router(alerts_router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(
    incidents_router,
    prefix="/api/v1/incidents",
    tags=["incidents"],
)
app.include_router(evidence_router, prefix="/api/v1", tags=["evidence"])
app.include_router(analysis_router, prefix="/api/v1", tags=["analysis"])
app.include_router(reports_router, prefix="/api/v1", tags=["reports"])


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

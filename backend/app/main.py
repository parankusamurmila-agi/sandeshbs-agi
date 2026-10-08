from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from app.config import ALLOWED_ORIGINS
from app.api.routes import router

app = FastAPI(title="HA Request & Response Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


_asgi_handler = Mangum(app)


def handler(event, context):
    # Async self-invoke from ingest.trigger_extract carries {"task": "extract"}
    # (not an HTTP event) -- run the extraction worker directly, bypassing the
    # ASGI adapter. Everything else is a normal HTTP request for FastAPI.
    if isinstance(event, dict) and event.get("task") == "extract":
        from app.services import ingest

        ingest.run_extract(event["correspondence_id"])
        return {"ok": True}
    return _asgi_handler(event, context)

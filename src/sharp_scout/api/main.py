"""FastAPI signal server for Sharp Scout dashboard."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sharp_scout.config import ARTIFACTS_DIR, ROOT, get_settings
from sharp_scout.pipeline.run import load_latest_artifacts, run_pipeline

app = FastAPI(title="Sharp Scout", version="0.1.0", description="NFL hybrid model signal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/signals")
def get_signals() -> dict[str, Any]:
    data = load_latest_artifacts()
    if not data:
        raise HTTPException(404, "No signals yet — POST /api/run or run scripts/run_pipeline.py")
    return data


@app.get("/api/plays")
def get_plays() -> list[dict[str, Any]]:
    data = load_latest_artifacts()
    return data.get("plays") or []


@app.get("/api/ratings")
def get_ratings() -> list[dict[str, Any]]:
    data = load_latest_artifacts()
    return data.get("ratings") or []


@app.post("/api/run")
def trigger_run(
    demo: bool = Query(False, description="Use mock odds/splits"),
    skip_pbp: bool = Query(False, description="Skip nflverse download; neutral/demo ratings"),
    build_site: bool = Query(False, description="Rebuild docs/ GitHub Pages site"),
) -> dict[str, Any]:
    settings = get_settings()
    use_demo = demo or not settings.odds_api_key
    payload = run_pipeline(
        demo=use_demo,
        skip_pbp=skip_pbp or use_demo,
        build_pages=build_site,
    )
    return {
        "ok": True,
        "n_games": payload["n_games"],
        "n_validated": payload["n_validated"],
        "generated_at": payload["generated_at"],
        "demo": payload["demo"],
        "record": payload.get("record"),
    }


@app.get("/api/record")
def get_record() -> dict[str, Any]:
    from sharp_scout.ledger.tracker import compute_record

    return compute_record()


@app.get("/api/splits")
def get_splits() -> dict[str, Any]:
    data = load_latest_artifacts()
    return {
        "split_boards": data.get("split_boards") or [],
        "n_splits_games": data.get("n_splits_games"),
        "splits_date": data.get("splits_date"),
        "manual_slate": data.get("manual_slate"),
    }


@app.get("/api/stages")
def get_stages() -> dict[str, Any]:
    data = load_latest_artifacts()
    return {
        "stage_picks": data.get("stage_picks") or [],
        "stage_summary": data.get("stage_summary") or {},
        "record": (data.get("record") or {}).get("stage_records"),
    }


@app.get("/api/props")
def get_props() -> dict[str, Any]:
    from sharp_scout.config import ARTIFACTS_DIR
    import json

    path = ARTIFACTS_DIR / "latest_props.json"
    if not path.exists():
        raise HTTPException(404, "No props yet")
    return json.loads(path.read_text())


@app.post("/api/run-props")
def trigger_props(
    demo: bool = Query(False),
    skip_pbp: bool = Query(False),
    build_site: bool = Query(True),
) -> dict[str, Any]:
    from sharp_scout.props.pipeline import run_props_pipeline

    settings = get_settings()
    use_demo = demo or not settings.odds_api_key
    payload = run_props_pipeline(
        demo=use_demo,
        skip_pbp=skip_pbp or use_demo,
        build_pages=build_site,
    )
    return {
        "ok": True,
        "n_validated": payload["n_validated"],
        "generated_at": payload["generated_at"],
        "demo": payload["demo"],
    }


@app.post("/api/run-pregame")
def trigger_pregame(
    demo: bool = Query(False),
    force_all: bool = Query(False),
) -> dict[str, Any]:
    from sharp_scout.scheduler.pregame import run_due_pregame

    settings = get_settings()
    return run_due_pregame(
        demo=demo or not settings.odds_api_key,
        force_all_upcoming=force_all,
        build_pages=True,
        skip_pbp=demo or not settings.odds_api_key,
    )


# Serve existing Sharp Scout UI from repo root
INDEX = ROOT / "index.html"
if INDEX.exists():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(INDEX)


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "sharp_scout.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
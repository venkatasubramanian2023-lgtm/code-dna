"""REST API over the query engine and the unified data access layer.

Run:  uvicorn codedna.api.app:create_app --factory --port 8000     (docs at /docs)
"""
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel

from codedna import __version__, pipeline
from codedna.dna.classifier import mapping
from codedna.query import QueryEngine, UnknownRepository
from codedna.query.engine import COMPLEXITY_METRICS
from codedna.storage import HybridStore

REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class IngestRequest(BaseModel):
    repo: str      # owner/name on GitHub, for example "pallets/flask"


def create_app(store: HybridStore = None) -> FastAPI:
    """Build the app. Pass a store in tests; otherwise it connects to the real databases."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or HybridStore()
        app.state.engine = QueryEngine(app.state.store)
        yield

    app = FastAPI(title="Code DNA", version=__version__, lifespan=lifespan,
                  description="Hybrid NoSQL repository analysis and similarity detection")

    def engine(request: Request) -> QueryEngine:
        return request.app.state.engine

    @app.exception_handler(UnknownRepository)
    async def unknown_repo(_, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=404, content={"detail": f"unknown repository: {exc.args[0]}"})

    @app.exception_handler(ValueError)
    async def bad_value(_, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/health")
    def health(request: Request):
        s = request.app.state.store
        return {"status": "ok", "version": __version__, "backends": s.backends,
                "repositories": len(s.repo_ids())}

    @app.get("/mapping")
    def storage_mapping():
        """Which database each feature group is stored in (the data-aware mapping)."""
        return mapping()

    @app.get("/repos")
    def list_repos(request: Request):
        return request.app.state.store.repo_ids()

    @app.get("/repos/{owner}/{name}")
    def get_repo(owner: str, name: str, request: Request):
        record = request.app.state.store.get_repo(f"{owner}/{name}")
        if not record:
            raise UnknownRepository(f"{owner}/{name}")
        return record

    @app.get("/repos/{owner}/{name}/similar")
    def similar(owner: str, name: str, request: Request, k: int = Query(5, ge=1, le=50)):
        return engine(request).similar_to(f"{owner}/{name}", k)

    @app.get("/repos/{owner}/{name}/dependencies/similar")
    def similar_dependencies(owner: str, name: str, request: Request, k: int = Query(5, ge=1, le=50)):
        return engine(request).similar_dependencies(f"{owner}/{name}", k)

    @app.get("/repos/{owner}/{name}/contributors")
    def contributors(owner: str, name: str, request: Request, limit: int = Query(10, ge=1, le=100)):
        return engine(request).contributors_of(f"{owner}/{name}", limit)

    @app.get("/compare")
    def compare(request: Request, a: str, b: str):
        s = request.app.state.store
        for repo in (a, b):
            if s.lookup(repo) is None:
                raise UnknownRepository(repo)
        return s.compare(a, b)

    @app.get("/query/technology")
    def technology(request: Request, name: str):
        return engine(request).using_technology(name)

    @app.get("/query/complexity")
    def complexity(request: Request, threshold: float = 5.0, metric: str = "avg_cyclomatic",
                   top: int = Query(10, ge=1, le=100)):
        return engine(request).high_complexity(threshold, metric, top)

    @app.get("/query/metrics")
    def metrics_list():
        return list(COMPLEXITY_METRICS)

    @app.get("/query/language")
    def language(request: Request, name: str):
        return engine(request).by_language(name)

    @app.get("/search")
    def search(request: Request, text: str, limit: int = Query(10, ge=1, le=100)):
        return engine(request).search_readme(text, limit)

    @app.post("/ingest", status_code=201)
    def ingest(body: IngestRequest, request: Request):
        """Clone a GitHub repository, build its Code DNA and store it."""
        if not REPO_NAME.match(body.repo):
            raise HTTPException(422, "repo must look like owner/name")
        try:
            r = pipeline.ingest_repo(body.repo, request.app.state.store)
        except Exception as exc:
            raise HTTPException(502, f"could not ingest {body.repo}: {exc}")
        return {"repo": body.repo, "collect_s": r["collect_s"], "dna_s": r["dna_s"],
                "store_s": r["store_s"], "store_by_db_s": r["store_by_db_s"]}

    return app

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .discuss.engine import DiscussEngine
from .errors import NotFoundError, StateError
from .interview.engine import InterviewEngine
from .interview.seed import SeedBank
from .learn.catalog import TopicCatalog
from .learn.refresh import RefreshService, build_runner
from .llm import LLM, LLMError
from .routers import discuss, interview, learn, notes
from .store import Store, build_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app(settings: Settings | None = None, llm: LLM | None = None, store: Store | None = None) -> FastAPI:
    settings = settings or get_settings()
    llm = llm or LLM(settings)
    store = store if store is not None else build_store(settings)

    # All API routes live under /api so a CDN (Firebase Hosting) can serve the pages
    # and forward only /api/** to Cloud Run.
    app = FastAPI(title="PrepVerse AI", version="0.1.0", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    app.state.settings = settings
    app.state.store = store
    app.state.llm = llm
    app.state.catalog = TopicCatalog.load()
    app.state.engine = InterviewEngine(llm, store, SeedBank.load())
    app.state.discuss = DiscussEngine(llm, store, app.state.catalog)
    app.state.refresh = RefreshService(store, build_runner(settings, llm, store, app.state.catalog))

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    api = APIRouter(prefix="/api")
    for module in (interview, learn, discuss, notes):
        api.include_router(module.router)

    @app.exception_handler(LLMError)
    async def llm_error(_: Request, exc: LLMError):
        log.exception("LLM failure", exc_info=exc)
        return JSONResponse({"detail": "AI service error, please retry"}, status_code=status.HTTP_502_BAD_GATEWAY)

    @app.exception_handler(StateError)
    async def state_error(_: Request, exc: StateError):
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_409_CONFLICT)

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, exc: NotFoundError):
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)

    @api.get("/healthz")
    def healthz():
        return {"ok": True}

    @api.get("/config/public")
    def public_config():
        """Public Firebase web config so the UI can sign users in (these values aren't secrets)."""
        return {
            "auth_disabled": settings.auth_disabled,
            "firebase": {
                "apiKey": settings.firebase_web_api_key,
                "authDomain": settings.firebase_auth_domain or f"{settings.firebase_project_id}.firebaseapp.com",
                "projectId": settings.firebase_project_id,
                "appId": settings.firebase_app_id,
            } if settings.firebase_web_api_key else None,
        }

    app.include_router(api)

    # The UI. Mounted last so API routes (and /docs) take precedence.
    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app


app = create_app()

from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, Request, status

from .config import Settings
from .discuss.engine import DiscussEngine
from .interview.engine import InterviewEngine
from .learn.catalog import TopicCatalog
from .llm import LLM
from .store import Store


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_engine(request: Request) -> InterviewEngine:
    return request.app.state.engine


def get_discuss(request: Request) -> DiscussEngine:
    return request.app.state.discuss


def get_llm(request: Request) -> LLM:
    return request.app.state.llm


def get_catalog(request: Request) -> TopicCatalog:
    return request.app.state.catalog


def get_refresh(request: Request):
    return request.app.state.refresh


def _verify_firebase_token(token: str, project_id: str) -> str:
    import firebase_admin
    from firebase_admin import auth

    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": project_id} if project_id else None)
    return auth.verify_id_token(token)["uid"]


def current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings_dep),
) -> str:
    """Firebase ID token from `Authorization: Bearer <token>` -> uid."""
    if settings.auth_disabled:
        return "dev-user"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        return _verify_firebase_token(authorization.removeprefix("Bearer "), settings.firebase_project_id)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


class UsageLimiter:
    """Per-user daily cap on LLM calls (UTC day)."""

    def __init__(self, store: Store, limit: int, user_id: str):
        self.store, self.limit, self.user_id = store, limit, user_id

    def charge(self, calls: int) -> None:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        total = self.store.add_usage(self.user_id, day, calls)
        if total > self.limit:
            # Refund: a rejected request shouldn't count against the budget.
            self.store.add_usage(self.user_id, day, -calls)
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "daily AI usage limit reached")


def get_usage(
    user: str = Depends(current_user),
    store: Store = Depends(get_store),
    settings: Settings = Depends(get_settings_dep),
) -> UsageLimiter:
    return UsageLimiter(store, settings.max_daily_llm_calls_per_user, user)

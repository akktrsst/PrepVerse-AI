"""GitHub search API: popular, recently maintained repos per topic."""

from datetime import datetime, timedelta, timezone

import httpx

from app.learn.models import Topic

from ..models import RawItem
from .common import parse_dt, strip_html

API = "https://api.github.com/search/repositories"
MIN_STARS = 100


def parse(payload: dict, topic_id: str) -> list[RawItem]:
    items = []
    for repo in payload.get("items", []):
        if repo.get("archived") or repo.get("fork") or repo.get("stargazers_count", 0) < MIN_STARS:
            continue
        topics = ", ".join(repo.get("topics", [])[:8])
        items.append(RawItem(
            type="repo",
            title=repo["full_name"],
            url=repo["html_url"],
            source="GitHub",
            author=repo.get("owner", {}).get("login", ""),
            published_at=parse_dt(repo.get("pushed_at")),
            thumbnail=repo.get("owner", {}).get("avatar_url"),
            metrics={"stars": int(repo.get("stargazers_count", 0)), "forks": int(repo.get("forks_count", 0))},
            text=strip_html(f"{repo.get('description') or ''} Language: {repo.get('language') or 'n/a'}. Topics: {topics}", 800),
            candidate_topics=[topic_id],
        ))
    return items


def fetch(client: httpx.Client, token: str, topic: Topic, per_page: int = 8) -> list[RawItem]:
    since = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = client.get(API, headers=headers, params={
        "q": f"{topic.github_query} pushed:>{since}", "sort": "stars", "order": "desc", "per_page": per_page,
    })
    r.raise_for_status()
    return parse(r.json(), topic.id)

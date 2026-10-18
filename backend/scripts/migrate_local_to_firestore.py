"""Copy Learn Hub resources from the local file store into Firestore.

Saves re-running (and re-paying for) ingestion after a local `python -m ingest.run`.
Only resources are copied; local sessions/notes belong to the dev user.

    cd backend && python -m scripts.migrate_local_to_firestore --project <gcp-project>
"""

import argparse

from app.store import BACKEND_DIR, FileStore, FirestoreStore


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--project", required=True)
    p.add_argument("--source", default=str(BACKEND_DIR / ".data" / "store.json"))
    args = p.parse_args()

    local = FileStore(__import__("pathlib").Path(args.source))
    resources = list(local._resources.values())
    missing = sum(1 for r in resources if not r.embedding)
    print(f"local resources: {len(resources)} ({missing} without embeddings)")

    remote = FirestoreStore(args.project)
    existing = remote.existing_resource_ids([r.id for r in resources])
    todo = [r for r in resources if r.id not in existing]
    print(f"already in Firestore: {len(existing)}; copying {len(todo)}")
    remote.upsert_resources(todo)
    remote.refresh_topic_counts()
    counts = remote.topic_counts()
    print(f"done: {len(counts)} topics, {sum(sum(c.values()) for c in counts.values())} resource-topic links")


if __name__ == "__main__":
    main()

#!/usr/bin/env bash
# One-time setup + deploy: API on Cloud Run (scale-to-zero), the daily ingestion
# job for the Learn Hub, and the website on Firebase Hosting (forwards /api/** to Cloud Run).
# Prerequisite: Firebase added to this GCP project (Firebase console -> Add project ->
# pick the existing project), and the Firebase CLI (`npm i -g firebase-tools`, or use Cloud Shell).
#
# Usage:
#   PROJECT=my-project \
#   FIREBASE_WEB_API_KEY=... FIREBASE_APP_ID=... \
#   YOUTUBE_API_KEY=... GITHUB_TOKEN=... \
#   ./infra/deploy.sh
# The API keys are stored in Secret Manager on first run; later runs can omit them.
set -euo pipefail

PROJECT="${PROJECT:?set PROJECT=<gcp-project-id>}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-prepverse-api}"
SA_NAME="prepverse-api"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
JOB="${JOB:-prepverse-ingest}"

export CLOUDSDK_CORE_PROJECT="$PROJECT"  # scoped to this script; leaves your gcloud default alone

echo "==> Enabling APIs"
gcloud services enable \
  aiplatform.googleapis.com run.googleapis.com firestore.googleapis.com \
  cloudbuild.googleapis.com artifactregistry.googleapis.com \
  secretmanager.googleapis.com cloudscheduler.googleapis.com

echo "==> Firestore (native mode) — no-op if it already exists"
gcloud firestore databases create --location="$REGION" --type=firestore-native 2>/dev/null || true

echo "==> Service account with least-privilege roles"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 || \
  gcloud iam service-accounts create "$SA_NAME" --display-name="PrepVerse API"
# run.developer: lets the API start the ingest job for one topic ("Find resources now").
for role in roles/aiplatform.user roles/datastore.user roles/secretmanager.secretAccessor roles/run.invoker roles/run.developer; do
  # Retry: policy edits right after creating the service account can hit "concurrent policy change".
  for attempt in 1 2 3 4 5; do
    gcloud projects add-iam-policy-binding "$PROJECT" \
      --member="serviceAccount:${SA}" --role="$role" --condition=None >/dev/null 2>&1 && break
    [ "$attempt" = 5 ] && { echo "failed to grant $role" >&2; exit 1; }
    sleep $((attempt * 3))
  done
done

echo "==> Firestore vector indexes for Learn Hub search (768-dim, cosine) — no-op if they exist"
gcloud firestore indexes composite create --collection-group=resources --query-scope=COLLECTION \
  --field-config='field-path=embedding,vector-config={"dimension":"768","flat":"{}"}' 2>/dev/null || true
gcloud firestore indexes composite create --collection-group=resources --query-scope=COLLECTION \
  --field-config=field-path=topic_ids,array-config=contains \
  --field-config='field-path=embedding,vector-config={"dimension":"768","flat":"{}"}' 2>/dev/null || true

echo "==> Secrets for ingestion"
put_secret() {  # name, value (skips when value is empty)
  [ -z "$2" ] && return 0
  gcloud secrets describe "$1" >/dev/null 2>&1 || gcloud secrets create "$1" --replication-policy=automatic
  printf '%s' "$2" | gcloud secrets versions add "$1" --data-file=- >/dev/null
}
put_secret youtube-api-key "${YOUTUBE_API_KEY:-}"
put_secret github-token "${GITHUB_TOKEN:-}"

FIREBASE_ENV=""
if [ -n "${FIREBASE_WEB_API_KEY:-}" ]; then
  FIREBASE_ENV=",FIREBASE_WEB_API_KEY=${FIREBASE_WEB_API_KEY},FIREBASE_APP_ID=${FIREBASE_APP_ID:-}"
fi

echo "==> Deploying ${SERVICE} to Cloud Run (${REGION})"
gcloud run deploy "$SERVICE" \
  --source backend \
  --region "$REGION" \
  --service-account "$SA" \
  --allow-unauthenticated \
  --min-instances 0 --max-instances 3 \
  --memory 512Mi --cpu 1 --timeout 120 \
  --set-env-vars "GCP_PROJECT=${PROJECT},GCP_LOCATION=global,FIREBASE_PROJECT_ID=${PROJECT},STORE_BACKEND=firestore,AUTH_DISABLED=false,INGEST_JOB_NAME=${JOB},INGEST_JOB_REGION=${REGION}${FIREBASE_ENV}"

echo "==> Ingestion job ${JOB} (Cloud Run Job, same image)"
SECRETS=""
gcloud secrets describe youtube-api-key >/dev/null 2>&1 && SECRETS="YOUTUBE_API_KEY=youtube-api-key:latest"
gcloud secrets describe github-token >/dev/null 2>&1 && SECRETS="${SECRETS:+$SECRETS,}GITHUB_TOKEN=github-token:latest"
IMAGE="$(gcloud run services describe "$SERVICE" --region "$REGION" --format='value(spec.template.spec.containers[0].image)')"
gcloud run jobs deploy "$JOB" \
  --image "$IMAGE" \
  --region "$REGION" \
  --service-account "$SA" \
  --command python --args=-m,ingest.run \
  --task-timeout 3600 --max-retries 1 --memory 1Gi --cpu 1 \
  --set-env-vars "GCP_PROJECT=${PROJECT},GCP_LOCATION=global,STORE_BACKEND=firestore" \
  ${SECRETS:+--set-secrets "$SECRETS"}

echo "==> Daily trigger at 02:00 IST (20:30 UTC)"
gcloud scheduler jobs describe "${JOB}-daily" --location "$REGION" >/dev/null 2>&1 || \
  gcloud scheduler jobs create http "${JOB}-daily" \
    --location "$REGION" --schedule "30 20 * * *" --time-zone "UTC" \
    --uri "https://run.googleapis.com/v2/projects/${PROJECT}/locations/${REGION}/jobs/${JOB}:run" \
    --http-method POST --oauth-service-account-email "$SA"

echo "==> Website on Firebase Hosting"
if command -v firebase >/dev/null 2>&1; then
  (cd "$(dirname "$0")/.." && firebase deploy --only hosting --project "$PROJECT")
else
  echo "   Firebase CLI not found: skipped. Install it (npm i -g firebase-tools) and run:"
  echo "   firebase deploy --only hosting --project $PROJECT"
fi

cat <<EOF

Done. Site: https://${PROJECT}.web.app  (API docs: /api/docs)
Remaining manual steps:
  1. Billing -> Budgets & alerts: add alerts at \$50 / \$150 / \$250.
  2. Billing -> Credits: note when your trial credit expires.
  3. Firebase console (this project): Authentication -> enable Google sign-in;
     Project settings -> add a Web app (gives FIREBASE_WEB_API_KEY / FIREBASE_APP_ID),
     then re-run this script with those set. *.web.app / *.firebaseapp.com are
     authorized for sign-in automatically; add a custom domain there if you use one.
  4. Fill the Learn Hub now instead of waiting for 02:00 IST:
     gcloud run jobs execute ${JOB} --region ${REGION}
  5. Discuss answers should stream word by word. If they arrive all at once through
     Hosting, the CDN is buffering the stream; tell us and we'll route that call to
     Cloud Run directly.
EOF

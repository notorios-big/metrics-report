# Deployment (GCP Cloud Run Job + Cloud Scheduler + GitHub Actions)

Este proyecto corre como **Cloud Run Job** y se ejecuta **1 vez al día** vía **Cloud Scheduler**.
El deploy es automático desde **GitHub Actions** usando **Workload Identity Federation (OIDC)** (sin llaves).

> Proyecto GCP usado: `notorios`  
> Región Cloud Run / Scheduler: `us-central1`  
> Horario: `0 9 * * *` en `America/Santiago`

## Recursos en GCP

- Cloud Run Job: `metrics-report` (imagen en `gcr.io/notorios/metrics-report`)
- Cloud Scheduler job: `metrics-report-daily` (HTTP → `.../jobs/metrics-report:run`)
- Service Accounts:
  - Runtime del job: `metrics-report-job@notorios.iam.gserviceaccount.com`
  - Deployer (GitHub): `metrics-report-deployer@notorios.iam.gserviceaccount.com`
  - Scheduler caller: `metrics-report-scheduler@notorios.iam.gserviceaccount.com`
- Workload Identity Federation:
  - Pool: `github-pool`
  - Provider: `github-provider`
  - Condición: `assertion.repository == 'notorios-big/metrics-report'`
- Secret Manager (secret names):
  - `LEJUSTE_SHOPIFY_ACCESS_TOKEN`
  - `LEJUSTE_META_ACCESS_TOKEN`
  - `LEJUSTE_KLAVIYO_PRIVATE_KEY`
  - `LEJUSTE_GOOGLE_ADS_DEVELOPER_TOKEN`
  - `LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_ID`
  - `LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_SECRET`
  - `LEJUSTE_GOOGLE_ADS_OAUTH_REFRESH_TOKEN`

## Variables / prefijo `LEJUSTE_`

El runtime lee variables como `LEJUSTE_<NOMBRE>` y también sin prefijo por compatibilidad.
En producción usamos `LEJUSTE_` para diferenciar.

- Ejemplos no-secret:
  - `LEJUSTE_REPORT_TIMEZONE=America/Santiago`
  - `LEJUSTE_GOOGLE_SHEETS_SPREADSHEET_ID=...`

## Prerrequisitos (1 vez)

APIs:

```bash
gcloud config set project notorios
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  sheets.googleapis.com
```

Google Sheets:

- Compartir el spreadsheet con `metrics-report-job@notorios.iam.gserviceaccount.com` (permiso de edición).

## GitHub Actions (OIDC)

Workflow: `.github/workflows/deploy-cloud-run-job.yml`

Secrets (repository secrets en GitHub):

- `GCP_PROJECT_ID` = `notorios`
- `GCP_WORKLOAD_IDENTITY_PROVIDER` = `projects/495979799441/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `GCP_SERVICE_ACCOUNT_EMAIL` = `metrics-report-deployer@notorios.iam.gserviceaccount.com`
- `CLOUD_RUN_JOB_SERVICE_ACCOUNT_EMAIL` = `metrics-report-job@notorios.iam.gserviceaccount.com`

Notas:

- El workflow usa `gcloud builds submit` y **no streamea logs** (por VPC-SC); hace polling de estado.

## Permisos (resumen)

Deployer SA (`metrics-report-deployer@...`):

- `roles/run.admin`
- `roles/cloudbuild.builds.editor`
- `roles/serviceusage.serviceUsageConsumer`
- `roles/storage.admin` (Cloud Build buckets)
- `roles/artifactregistry.reader` (validación de imagen `gcr.io`)
- `roles/iam.serviceAccountUser` sobre:
  - `metrics-report-job@notorios.iam.gserviceaccount.com`
  - Cloud Build SA que use el proyecto (si aplica)

Runtime SA (`metrics-report-job@...`):

- `roles/secretmanager.secretAccessor` (leer secretos)
- `roles/artifactregistry.reader` (bajar imagen)

Cloud Run service agent (`service-495979799441@serverless-robot-prod.iam.gserviceaccount.com`):

- `roles/artifactregistry.reader` (bajar imagen desde `gcr.io` / Artifact Registry)

Scheduler SA (`metrics-report-scheduler@...`):

- `roles/run.invoker` a nivel del Job `metrics-report` (Cloud Run IAM)

## Subir secretos desde `.env` (local → Secret Manager)

Script helper:

```bash
PROJECT_ID=notorios ./scripts/gcp/sync_secrets_from_env.sh .env
```

Luego mapear a Cloud Run Job:

```bash
gcloud run jobs update metrics-report --region us-central1 \
  --set-secrets \
LEJUSTE_SHOPIFY_ACCESS_TOKEN=LEJUSTE_SHOPIFY_ACCESS_TOKEN:latest,\
LEJUSTE_META_ACCESS_TOKEN=LEJUSTE_META_ACCESS_TOKEN:latest,\
LEJUSTE_KLAVIYO_PRIVATE_KEY=LEJUSTE_KLAVIYO_PRIVATE_KEY:latest,\
LEJUSTE_GOOGLE_ADS_DEVELOPER_TOKEN=LEJUSTE_GOOGLE_ADS_DEVELOPER_TOKEN:latest,\
LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_ID=LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_ID:latest,\
LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_SECRET=LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_SECRET:latest,\
LEJUSTE_GOOGLE_ADS_OAUTH_REFRESH_TOKEN=LEJUSTE_GOOGLE_ADS_OAUTH_REFRESH_TOKEN:latest
```

## Cloud Scheduler (1 vez al día)

Crear SA + permisos y el scheduler:

```bash
gcloud iam service-accounts create metrics-report-scheduler \
  --display-name "metrics-report scheduler" || true

gcloud run jobs add-iam-policy-binding metrics-report \
  --region us-central1 \
  --member="serviceAccount:metrics-report-scheduler@notorios.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

gcloud scheduler jobs create http metrics-report-daily \
  --location "us-central1" \
  --schedule "0 9 * * *" \
  --time-zone "America/Santiago" \
  --uri "https://run.googleapis.com/v2/projects/notorios/locations/us-central1/jobs/metrics-report:run" \
  --http-method POST \
  --oauth-service-account-email "metrics-report-scheduler@notorios.iam.gserviceaccount.com" \
  --oauth-token-scope "https://www.googleapis.com/auth/cloud-platform" \
  --message-body "{}"
```

Probar trigger:

```bash
gcloud scheduler jobs run metrics-report-daily --location us-central1
```

## Operación / troubleshooting

Ejecutar manual:

```bash
gcloud run jobs execute metrics-report --region us-central1 --wait
```

Ver últimas ejecuciones:

```bash
gcloud run jobs executions list --job metrics-report --region us-central1 --limit 10
```

Ver logs de una ejecución (Cloud Logging):

```bash
EXECUTION="metrics-report-XXXX"
gcloud logging read \
'resource.type="cloud_run_job"
 resource.labels.job_name="metrics-report"
 resource.labels.location="us-central1"
 labels."run.googleapis.com/execution_name"="'${EXECUTION}'"' \
--project=notorios --limit=200 --format="value(textPayload)"
```


# metrics-report

Reemplazo en Python de los flujos n8n:

- `Metrics - Shopify Info (9).json`
- `Metrics - Google, META, Klaviyo.json`

Corre una vez al día y escribe métricas en Google Sheets (tabs: `PURCHASE`, `META`, `GADS`, `KLAVIYO`).

- `META` y `GADS` se guardan como totales diarios (no se repite la fecha).

## Requisitos

- Python 3.11+
- Acceso a Google Sheets API desde Cloud Run (recomendado: Service Account + compartir el spreadsheet con ese mail)

## Variables de entorno

Google Sheets:

- `GOOGLE_SHEETS_SPREADSHEET_ID` (default: `1h1_rGZEncDj8WRLnf4m9Kqr-78JGqoxq0CH_WnIzdH8`)
- `GOOGLE_SHEETS_PURCHASE_SHEET` (default: `PURCHASE`)
- `GOOGLE_SHEETS_META_SHEET` (default: `META`)
- `GOOGLE_SHEETS_GADS_SHEET` (default: `GADS`)
- `GOOGLE_SHEETS_KLAVIYO_SHEET` (default: `KLAVIYO`)

Shopify:

- `SHOPIFY_ACCESS_TOKEN` (requerida)
- `SHOPIFY_SHOP_DOMAIN` (default: `le-juste-s.myshopify.com`)
- `SHOPIFY_API_VERSION` (default: `2024-10`)

Meta:

- `META_ACCESS_TOKEN` (requerida)
- `META_AD_ACCOUNT_ID` (default: `act_1219778112947622`)
- `META_API_VERSION` (default: `v23.0`)

Google Ads:

- `GOOGLE_ADS_DEVELOPER_TOKEN` (requerida)
- `GOOGLE_ADS_CUSTOMER_ID` (default: `3261990482`)
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (default: `8058839890`)
- `GOOGLE_ADS_API_VERSION` (default: `21`)
- `GOOGLE_ADS_OAUTH_CLIENT_ID` (requerida si NO usás ADC)
- `GOOGLE_ADS_OAUTH_CLIENT_SECRET` (requerida si NO usás ADC)
- `GOOGLE_ADS_OAUTH_REFRESH_TOKEN` (requerida si NO usás ADC)

Nota: se consulta y guarda el total diario (no por campaña).
Local (opcional): si no querés guardar `refresh_token` en `.env`, podés usar ADC.
Para Google Ads (scope fuera de GCP) necesitás un OAuth Client propio (tipo "Desktop app") y correr:
`gcloud auth application-default login --client-id-file=./client_secret.json --scopes=https://www.googleapis.com/auth/adwords`
(no recomendado para Cloud Run).

Alternativa (local): generar `GOOGLE_ADS_OAUTH_REFRESH_TOKEN` con el helper:
`python -m metrics_report oauth google-ads --client-secret /ruta/client_secret.json`

Si te aparece `Error 400: redirect_uri_mismatch`, asegurate de usar un OAuth Client tipo **Desktop app**.
Si tu client es tipo **Web application**, agregá `http://localhost:8080/` como Authorized redirect URI (o corré el comando con `--port` y agregá ese puerto).

Klaviyo:

- `KLAVIYO_PRIVATE_KEY` (requerida)
- `KLAVIYO_METRIC_ID` (default: `XvmGgm`)
- `KLAVIYO_BY` (opcional, CSV: `flow_id,campaign_id`, default vacío; igual se guarda el total diario)
- `KLAVIYO_REVISION` (default: `2025-07-15`)

Otros:

- `LEJUSTE_REPORT_TIMEZONE` (o `REPORT_TIMEZONE`, default: `America/Santiago`)

Prefijo:
- La app soporta variables con prefijo `LEJUSTE_` (recomendado) y también sin prefijo por compatibilidad.

## Ejecutar local

1) Instalar deps: `pip install -r requirements.txt`
2) Crear `.env` desde `.env.example` y completar valores (se carga automáticamente al ejecutar)
3) Autenticación Google (Sheets API), elegir una:
   - **ADC (usuario, recomendado local)**: `gcloud auth application-default login --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets` (opcional: `gcloud auth application-default set-quota-project PROJECT_ID`)
   - **Service Account**: exportar `GOOGLE_APPLICATION_CREDENTIALS=/ruta/service-account.json` (ej: `./gs_cred.json`)
   - Nota: `gcloud auth login` (solo) no alcanza; la app usa ADC o `GOOGLE_APPLICATION_CREDENTIALS`.
   - Asegurate de tener habilitada la Google Sheets API en el proyecto "consumer" y de compartir el spreadsheet con el `client_email` del Service Account (si aplica).
4) Ejecutar: `python -m metrics_report`

Opcional:

- `python -m metrics_report --check-sheets`
- `python -m metrics_report --dry-run`
- `python -m metrics_report --only shopify meta`

## Cloud Run (Job) + Cloud Scheduler (1 vez al día)

En Cloud Run, usa Secret Manager y mapea secretos a variables de entorno (no uses `.env` en producción).

Helpers (opcionales) para deploy/scheduler:
- `scripts/gcp/deploy_job.sh` (build + create/update Job)
- `scripts/gcp/create_scheduler.sh` (create/update Scheduler)

0) Prerrequisitos (1 sola vez):

- Setear proyecto/region:
  - `gcloud config set project PROJECT_ID`
  - `gcloud config set run/region REGION`
- Habilitar APIs:
  - `gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com cloudscheduler.googleapis.com sheets.googleapis.com`
- Crear Service Account para el Job:
  - `gcloud iam service-accounts create metrics-report --display-name "metrics-report job"`
  - Email queda como: `metrics-report@PROJECT_ID.iam.gserviceaccount.com`
- Compartir el Google Sheet con ese email (desde Google Sheets → Share).

1) Build/push (ejemplo):

`gcloud builds submit --tag gcr.io/PROJECT_ID/metrics-report`

2) Crear Cloud Run Job (ejemplo, usando Secret Manager para credenciales):

`gcloud run jobs create metrics-report --image gcr.io/PROJECT_ID/metrics-report --region REGION --service-account SERVICE_ACCOUNT_EMAIL --set-env-vars GOOGLE_SHEETS_SPREADSHEET_ID=... --set-secrets SHOPIFY_ACCESS_TOKEN=SHOPIFY_ACCESS_TOKEN:latest,META_ACCESS_TOKEN=META_ACCESS_TOKEN:latest,KLAVIYO_PRIVATE_KEY=KLAVIYO_PRIVATE_KEY:latest,GOOGLE_ADS_DEVELOPER_TOKEN=GOOGLE_ADS_DEVELOPER_TOKEN:latest,GOOGLE_ADS_OAUTH_CLIENT_ID=GOOGLE_ADS_OAUTH_CLIENT_ID:latest,GOOGLE_ADS_OAUTH_CLIENT_SECRET=GOOGLE_ADS_OAUTH_CLIENT_SECRET:latest,GOOGLE_ADS_OAUTH_REFRESH_TOKEN=GOOGLE_ADS_OAUTH_REFRESH_TOKEN:latest`

Recomendado (nombres de secretos con prefijo `LEJUSTE_`):
`gcloud run jobs update metrics-report --region REGION --set-secrets LEJUSTE_SHOPIFY_ACCESS_TOKEN=LEJUSTE_SHOPIFY_ACCESS_TOKEN:latest,LEJUSTE_META_ACCESS_TOKEN=LEJUSTE_META_ACCESS_TOKEN:latest,LEJUSTE_KLAVIYO_PRIVATE_KEY=LEJUSTE_KLAVIYO_PRIVATE_KEY:latest,LEJUSTE_GOOGLE_ADS_DEVELOPER_TOKEN=LEJUSTE_GOOGLE_ADS_DEVELOPER_TOKEN:latest,LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_ID=LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_ID:latest,LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_SECRET=LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_SECRET:latest,LEJUSTE_GOOGLE_ADS_OAUTH_REFRESH_TOKEN=LEJUSTE_GOOGLE_ADS_OAUTH_REFRESH_TOKEN:latest`

3) Crear Cloud Scheduler para ejecutar el Job 1 vez al día (ejemplo 09:00 SCL):

`gcloud scheduler jobs create http metrics-report-daily --schedule \"0 9 * * *\" --time-zone \"America/Santiago\" --uri \"https://run.googleapis.com/v2/projects/PROJECT_ID/locations/REGION/jobs/metrics-report:run\" --http-method POST --oauth-service-account-email SCHEDULER_SA_EMAIL --oauth-token-scope \"https://www.googleapis.com/auth/cloud-platform\" --message-body \"{}\"`

4) Probar ejecución manual:

`gcloud run jobs execute metrics-report --region REGION --wait`

## CI/CD (opcional) con GitHub Actions

No es obligatorio pasar por GitHub: podés desplegar desde tu máquina con `gcloud` y listo.
Pero GitHub te sirve para versionar y para que un push a `main` actualice el Job automáticamente.

Workflow incluido: `.github/workflows/deploy-cloud-run-job.yml`.

Recomendado: autenticación sin keys con Workload Identity Federation (OIDC).
Secrets requeridos en GitHub:

- `GCP_PROJECT_ID`
- `GCP_WORKLOAD_IDENTITY_PROVIDER` (resource name del provider)
- `GCP_SERVICE_ACCOUNT_EMAIL` (SA que GitHub impersona para deploy)
- `CLOUD_RUN_JOB_SERVICE_ACCOUNT_EMAIL` (SA con la que corre el Job)

Notas:
- El workflow solo build/deploya el Job. Las variables/secretos del runtime se manejan con Secret Manager (`gcloud run jobs update ... --set-secrets ...`).
- Ajustá `REGION` en el workflow si no usás `us-central1`.

Permisos mínimos típicos:
- SA que GitHub impersona: `roles/run.admin`, `roles/cloudbuild.builds.editor`, `roles/iam.serviceAccountUser` (sobre `CLOUD_RUN_JOB_SERVICE_ACCOUNT_EMAIL`).
- SA del Scheduler (si usás Scheduler → Run Job via HTTP): `roles/run.jobRunner` (y OAuth scope `cloud-platform`).

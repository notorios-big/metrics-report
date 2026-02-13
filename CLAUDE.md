# Metrics Report — Contexto del proyecto

## Qué es

Pipeline de métricas diario para Le Juste. Agrega datos de Shopify, Meta Ads, Google Ads, Klaviyo y los escribe en Google Sheets. Corre en una VM GCP (`langgraph`, `35.239.11.160`) vía cron a las 9 AM hora Chile.

## Arquitectura

### Pipeline batch (cron 9 AM)

```
GCP Secret Manager → run.sh → python -m metrics_report → Google Sheets
```

Tasks: `shopify`, `shopify_funnel`, `customers`, `meta`, `meta_ads`, `google_ads`, `klaviyo`

### Webhook receiver (24/7)

```
Shopify ──webhook──▶ Cloudflare ──▶ nginx:443 ──▶ FastAPI:6972 ──▶ SQLite
```

- Servicio systemd: `metrics-webhook.service` (uvicorn en puerto 6972)
- DB: `/opt/metrics-report/webhooks.db`
- SSL: Let's Encrypt (auto-renewal vía certbot)
- Nginx config: `/etc/nginx/sites-enabled/metrics.notorios.cl`

### Webhooks de Shopify registrados

| Evento | URL | Registrado vía |
|---|---|---|
| `carts/create` | `https://metrics.notorios.cl/carts_created` | UI Shopify |
| `carts/update` | `https://metrics.notorios.cl/carts_created` | UI Shopify |
| `checkouts/create` | `https://metrics.notorios.cl/checkout_created` | API GraphQL |

- **Add to cart**: se deduplica por cart token (1 ATC = 1 sesión de carrito, sin importar cuántos productos)
- **Begin checkout**: `checkouts/create` no está disponible en la UI de Shopify para planes no-Plus; se registra vía API con `python -m metrics_report register-webhooks`
- **Purchase**: NO usa webhooks. Se obtiene de la Shopify Orders API (más confiable). Se consulta en el task `shopify_funnel` del pipeline.

### Flujo de datos SHOPI (funnel)

1. Webhooks guardan `add_to_cart` y `begin_checkout` en SQLite (`daily_counts`)
2. Cron 9 AM ejecuta task `shopify_funnel`:
   - Lee ATC y begin_checkout de SQLite (`webhook_db.get_counts`)
   - Lee purchases de Shopify Orders API (`fetch_orders` con filtro `financial_status:paid`)
   - Escribe fila por día en hoja SHOPI: `Día | Add to cart | Begin Checkout | Purchase`

## VM (`langgraph` / `35.239.11.160`)

- Ubuntu, Python 3.12, Docker
- Código en `/opt/metrics-report` (git clone)
- Venv en `/opt/metrics-report/.venv`
- Cron: `0 9 * * * /opt/metrics-report/run.sh >> /var/log/metrics-report.log 2>&1`
- SSH: `gcloud compute ssh sam@langgraph --zone=us-central1-c --project=notorios`

## Secrets (GCP Secret Manager, proyecto `notorios`)

Requeridos: `LEJUSTE_SHOPIFY_ACCESS_TOKEN`, `LEJUSTE_META_ACCESS_TOKEN`, `LEJUSTE_KLAVIYO_PRIVATE_KEY`, `LEJUSTE_GOOGLE_ADS_DEVELOPER_TOKEN`, `LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_ID`, `LEJUSTE_GOOGLE_ADS_OAUTH_CLIENT_SECRET`, `LEJUSTE_GOOGLE_ADS_OAUTH_REFRESH_TOKEN`

Opcionales: `LEJUSTE_SHOPIFY_WEBHOOK_SECRET` (para HMAC validation de webhooks; si no existe, el webhook receiver acepta todo con warning)

## Pendientes

- [ ] Crear `LEJUSTE_SHOPIFY_WEBHOOK_SECRET` en Secret Manager (API secret key de la app Shopify) y configurar en systemd service
- [ ] Limpiar webhooks duplicados si se re-registran vía API (los de carrito ya están en la UI)

## Notas de desarrollo

- Todos los env vars soportan prefijo `LEJUSTE_` o sin prefijo
- Timezone por defecto: `America/Santiago`
- El pipeline continúa si un task falla; reporta todos los errores al final
- `--dry-run` muestra qué haría sin escribir en Sheets
- `--only shopify_funnel` para correr un solo task
- Deploy: `git push` + `git pull` en la VM + `pip install -r requirements.txt` si hay deps nuevas

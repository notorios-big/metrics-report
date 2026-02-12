from __future__ import annotations

import logging

from metrics_report.http import request_json

_LOG = logging.getLogger(__name__)

WEBHOOK_CREATE_MUTATION = """
mutation webhookSubscriptionCreate($topic: WebhookSubscriptionTopic!, $webhookSubscription: WebhookSubscriptionInput!) {
  webhookSubscriptionCreate(topic: $topic, webhookSubscription: $webhookSubscription) {
    webhookSubscription { id }
    userErrors { field message }
  }
}
"""

WEBHOOK_TOPICS = [
    ("CARTS_CREATE", "https://metrics.notorios.cl/carts_created"),
    ("CARTS_UPDATE", "https://metrics.notorios.cl/carts_created"),
    ("CHECKOUTS_CREATE", "https://metrics.notorios.cl/checkout_created"),
]


def register_webhooks(
    *,
    shop_domain: str,
    api_version: str,
    access_token: str,
) -> None:
    url = f"https://{shop_domain}/admin/api/{api_version}/graphql.json"
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": access_token}

    for topic, callback_url in WEBHOOK_TOPICS:
        body = {
            "query": WEBHOOK_CREATE_MUTATION,
            "variables": {
                "topic": topic,
                "webhookSubscription": {
                    "callbackUrl": callback_url,
                    "format": "JSON",
                },
            },
        }
        resp = request_json("POST", url, headers=headers, json_body=body)
        if resp.get("errors"):
            _LOG.error("GraphQL errors for %s: %s", topic, resp["errors"])
            continue

        result = (resp.get("data") or {}).get("webhookSubscriptionCreate") or {}
        user_errors = result.get("userErrors") or []
        if user_errors:
            _LOG.error("User errors for %s: %s", topic, user_errors)
        else:
            sub_id = (result.get("webhookSubscription") or {}).get("id", "?")
            _LOG.info("Registered %s -> %s (id=%s)", topic, callback_url, sub_id)

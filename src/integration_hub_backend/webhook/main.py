"""Webhook service FastAPI app."""

from fastapi import FastAPI
from smart_llm.observability import install_observability

from integration_hub_backend.webhook.api.routes.send import router as send_router

app = FastAPI(title="Webhook Service", version="1.0.0", docs_url="/docs")
# Observability — Prometheus /metrics + Sentry + OTEL. Opt-in via env.
install_observability(app, service_name="webhook-service")
app.include_router(send_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "webhook-service"}

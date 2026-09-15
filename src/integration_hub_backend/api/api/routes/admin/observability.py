"""Platform Admin routes for managing global observability integrations."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from integration_hub_backend.api.api.deps import PlatformAdminDep, SessionDep
from integration_hub_backend.api.models.system_integration import (
    NotificationSystemIntegration,
    SystemIntegrationPublic,
)
from integration_hub_backend.api.services.observability_service import ObservabilityService

router = APIRouter(prefix="/admin/observability", tags=["admin"])


class SystemIntegrationUpdateLocal(BaseModel):
    is_enabled: bool | None = None
    config: dict[str, Any] | None = None


@router.get("/", response_model=list[SystemIntegrationPublic])
async def get_all_system_integrations(
    db: SessionDep, admin: PlatformAdminDep
) -> list[NotificationSystemIntegration]:
    """List all global observability integrations and their status."""
    service = ObservabilityService(db)
    return await service.list_global_configs()


@router.get("/{name}", response_model=SystemIntegrationPublic)
async def get_one_system_integration(
    name: str, db: SessionDep, admin: PlatformAdminDep
) -> NotificationSystemIntegration:
    """Get status of a specific global integration."""
    service = ObservabilityService(db)
    from integration_hub_backend.api.crud.system_integrations import get_system_integration

    integration = await get_system_integration(db, name)
    if not integration:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")
    return integration


@router.put("/{name}", response_model=SystemIntegrationPublic)
async def update_global_integration(
    name: str, body: SystemIntegrationUpdateLocal, db: SessionDep, admin: PlatformAdminDep
) -> NotificationSystemIntegration:
    """Update global integration settings (admin only)."""
    # Validation: enforce allowed platforms
    if name not in ("datadog", "splunk", "grafana", "elasticsearch", "kibana"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid platform name")

    service = ObservabilityService(db)
    return await service.update_global_config(name, is_enabled=body.is_enabled, config=body.config)


@router.get("/{name}/config")
async def get_global_integration_config(
    name: str, db: SessionDep, admin: PlatformAdminDep
) -> dict[str, Any]:
    """Retrieve the decrypted configuration (admin only)."""
    service = ObservabilityService(db)
    config = await service.get_decrypted_config(name)
    if not config and name not in ("datadog", "splunk", "grafana", "elasticsearch", "kibana"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Integration not found")

    return config

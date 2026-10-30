"""Notify platform for EPD E-Paper Wireless Gateway (unifies HA notify with iPhone Shortcuts /api/push)."""

from __future__ import annotations

from typing import Any

try:
    from homeassistant.components.notify import NotifyEntity, NotifyEntityFeature
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class NotifyEntity:  # type: ignore[no-redef]
        _attr_has_entity_name = False
        _attr_name = ""
        _attr_unique_id = ""
        _attr_icon = ""
        _attr_supported_features = 0

    class NotifyEntityFeature:  # type: ignore[no-redef]
        TITLE = 1

    ConfigEntry = Any  # type: ignore[assignment,misc]
    HomeAssistant = Any  # type: ignore[assignment,misc]
    DeviceInfo = dict  # type: ignore[assignment,misc]
    AddEntitiesCallback = Any  # type: ignore[assignment,misc]

from .const import DOMAIN
from .coordinator import EpdGatewayCoordinator
from .core.models import MemoRequest


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EPD Gateway NotifyEntity from a config entry."""
    coordinator: EpdGatewayCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([EpdGatewayNotifyEntity(coordinator, entry)])


class EpdGatewayNotifyEntity(NotifyEntity):
    """Home Assistant native NotifyEntity that pushes instant memos to the e-ink screen."""

    _attr_has_entity_name = True
    _attr_name = "墨水屏通知推送 (Memo Notify)"
    _attr_unique_id = f"{DOMAIN}_memo_notify"
    _attr_icon = "mdi:message-badge-outline"
    _attr_supported_features = NotifyEntityFeature.TITLE

    def __init__(self, coordinator: EpdGatewayCoordinator, entry: ConfigEntry) -> None:
        self.coordinator = coordinator
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, "epd_gateway_device")},
            name="EPD 4.2寸三色墨水屏网关",
            manufacturer="EastwoodNet",
            model="ESP32-C3 / S3 + nRF52810 (400x300 BWR)",
            configuration_url=self.coordinator.settings_mgr.settings.gateway_url,
        )

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a notification message directly to the e-ink screen via the unified MemoManager."""
        clean_msg = (message or "").strip()
        if not clean_msg:
            return
        clean_title = (title or "").strip() or "📌 HA 智能家居通知"
        duration = self.coordinator.settings_mgr.settings.default_memo_duration_min
        req = MemoRequest(
            text=clean_msg,
            title=clean_title,
            duration_min=duration,
            sender="HA通知系统",
        )
        await self.coordinator._run_in_executor(self.coordinator.activate_memo, req)

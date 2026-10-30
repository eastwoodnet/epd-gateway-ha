"""Image platform for EPD E-Paper Wireless Gateway (live 400x300 screen preview in Lovelace)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Optional

try:
    from homeassistant.components.image import ImageEntity
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    HAS_HA_IMAGE = True
except ImportError:
    HAS_HA_IMAGE = False

    class ImageEntity:  # type: ignore[no-redef]
        def __init__(self, hass: Any = None) -> None:
            self.hass = hass

        def async_write_ha_state(self) -> None:
            pass

        def async_on_remove(self, func: Callable[[], None]) -> None:
            pass

    ConfigEntry = Any  # type: ignore[assignment,misc]
    HomeAssistant = Any  # type: ignore[assignment,misc]
    DeviceInfo = dict  # type: ignore[assignment,misc]
    AddEntitiesCallback = Callable  # type: ignore[assignment,misc]

from .const import DOMAIN
from .coordinator import EpdGatewayCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EPD Gateway image preview entity."""
    coordinator: EpdGatewayCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([EpdScreenPreviewImage(hass, coordinator)])


class EpdScreenPreviewImage(ImageEntity):
    """Live 400x300 BWR e-ink screen preview image entity for Home Assistant dashboards."""

    _attr_has_entity_name = True
    _attr_unique_id = f"{DOMAIN}_screen_preview"
    _attr_name = "墨水屏实时画面预览 (Screen Preview)"
    _attr_content_type = "image/png"
    _attr_icon = "mdi:image-frame"

    def __init__(self, hass: HomeAssistant, coordinator: EpdGatewayCoordinator) -> None:
        super().__init__(hass)
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "epd_gateway_device")},
            name="EPD 4.2寸三色墨水屏网关",
            manufacturer="EastwoodNet",
            model="ESP32-C3 / S3 + nRF52810 (400x300 BWR)",
            configuration_url=coordinator.settings_mgr.get_settings().get("gateway_url"),
        )

    async def async_added_to_hass(self) -> None:
        def _on_update() -> None:
            self._attr_image_last_updated = self.coordinator.last_updated_dt or datetime.now()
            self.async_write_ha_state()

        self.async_on_remove(self.coordinator.add_listener(_on_update))

    @property
    def image_last_updated(self) -> Optional[datetime]:
        return self.coordinator.last_updated_dt

    async def async_image(self) -> Optional[bytes]:
        return await self.coordinator.async_get_preview_png()

"""Sensor platform for EPD E-Paper Wireless Gateway."""

from __future__ import annotations

from typing import Any, Callable, Dict

try:
    from homeassistant.components.sensor import SensorEntity
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class SensorEntity:  # type: ignore[no-redef]
        def async_write_ha_state(self) -> None:
            pass

        def async_on_remove(self, func: Callable[[], None]) -> None:
            pass

    ConfigEntry = Any  # type: ignore[assignment,misc]
    HomeAssistant = Any  # type: ignore[assignment,misc]
    DeviceInfo = dict  # type: ignore[assignment,misc]
    AddEntitiesCallback = Callable  # type: ignore[assignment,misc]

from .const import DISPLAY_MODE_LABELS, DOMAIN
from .coordinator import EpdGatewayCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EPD Gateway sensor entities."""
    coordinator: EpdGatewayCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([EpdActiveModeSensor(coordinator)])


class EpdActiveModeSensor(SensorEntity):
    """Sensor reporting the currently effective display mode and gateway metadata."""

    _attr_has_entity_name = True
    _attr_unique_id = f"{DOMAIN}_active_mode"
    _attr_name = "当前生效画面模式 (Active Mode)"
    _attr_icon = "mdi:Monitor-dashboard"

    def __init__(self, coordinator: EpdGatewayCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "epd_gateway_device")},
            name="EPD 4.2寸三色墨水屏网关",
            manufacturer="EastwoodNet",
            model="ESP32-C3 / S3 + nRF52810 (400x300 BWR)",
            configuration_url=coordinator.settings_mgr.get_settings().get("gateway_url"),
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.coordinator.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        info = self.coordinator.get_effective_mode_info()
        mode = info["effective_mode"]
        if mode == "memo":
            return "📌 即时便签插播 (Memo)"
        return DISPLAY_MODE_LABELS.get(mode, mode)

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        info = self.coordinator.get_effective_mode_info()
        memo = info.get("active_memo")
        return {
            "effective_mode_code": info["effective_mode"],
            "schedule_mode_code": info["schedule_mode"],
            "fallback_mode": info["fallback_mode"],
            "next_pull_sec": info["next_pull_sec"],
            "gateway_url": info["gateway_url"],
            "filled_photo_slots": info["filled_slots"],
            "weather_entity": info["weather_entity"],
            "calendar_entity": info["calendar_entity"],
            "weather_city": info["weather_city"],
            "memo_active": memo is not None,
            "memo_title": memo.get("title") if memo else None,
            "memo_text": memo.get("text") if memo else None,
        }

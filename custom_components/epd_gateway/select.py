"""Select platform for EPD E-Paper Wireless Gateway."""

from __future__ import annotations

from typing import Any, Callable, Optional

try:
    from homeassistant.components.select import SelectEntity
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class SelectEntity:  # type: ignore[no-redef]
        def async_write_ha_state(self) -> None:
            pass

        def async_on_remove(self, func: Callable[[], None]) -> None:
            pass

    ConfigEntry = Any  # type: ignore[assignment,misc]
    HomeAssistant = Any  # type: ignore[assignment,misc]
    DeviceInfo = dict  # type: ignore[assignment,misc]
    AddEntitiesCallback = Callable  # type: ignore[assignment,misc]

from .const import DISPLAY_MODES, DOMAIN
from .coordinator import EpdGatewayCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up EPD Gateway select entities."""
    coordinator: EpdGatewayCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([EpdFallbackModeSelect(coordinator)])


class EpdFallbackModeSelect(SelectEntity):
    """Select entity to control the fallback display mode of the e-ink screen."""

    _attr_has_entity_name = True
    _attr_unique_id = f"{DOMAIN}_fallback_mode"
    _attr_name = "闲时兜底模式 (Fallback Mode)"
    _attr_icon = "mdi:television-guide"
    _attr_options = DISPLAY_MODES

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
    def current_option(self) -> Optional[str]:
        return self.coordinator.scheduler.config.fallback_mode

    async def async_select_option(self, option: str) -> None:
        if option not in DISPLAY_MODES:
            raise ValueError(f"Invalid option: {option}")
        sched = self.coordinator.scheduler.get_schedule()
        sched["fallback_mode"] = option
        await self.coordinator._run_in_executor(self.coordinator.scheduler.save_schedule, sched)
        self.coordinator.notify_listeners()
        self.coordinator.notify_gateway_for_current_state()

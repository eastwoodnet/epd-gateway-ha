"""Button platform for EPD E-Paper Wireless Gateway."""

from __future__ import annotations

from typing import Any, Callable

try:
    from homeassistant.components.button import ButtonEntity
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
except ImportError:
    class ButtonEntity:  # type: ignore[no-redef]
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
    """Set up EPD Gateway button entities."""
    coordinator: EpdGatewayCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities(
        [
            EpdSyncNowButton(coordinator),
            EpdNativeCalendarButton(coordinator),
            EpdClearMemoButton(coordinator),
        ]
    )


class _BaseEpdButton(ButtonEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EpdGatewayCoordinator) -> None:
        self.coordinator = coordinator
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "epd_gateway_device")},
            name="EPD 4.2寸三色墨水屏网关",
            manufacturer="EastwoodNet",
            model="ESP32-C3 / S3 + nRF52810 (400x300 BWR)",
            configuration_url=coordinator.settings_mgr.get_settings().get("gateway_url"),
        )


class EpdSyncNowButton(_BaseEpdButton):
    """Button to immediately trigger ESP32 gateway to pull and refresh the current screen."""

    _attr_unique_id = f"{DOMAIN}_trigger_sync"
    _attr_name = "立即触发网关同步 (Sync Now)"
    _attr_icon = "mdi:sync"

    async def async_press(self) -> None:
        await self.coordinator.notifier.trigger_sync()


class EpdNativeCalendarButton(_BaseEpdButton):
    """Button to switch the e-ink screen to nRF hardware native perpetual calendar (0x20)."""

    _attr_unique_id = f"{DOMAIN}_native_calendar"
    _attr_name = "切换硬件原生万年历 (0x20 Calendar)"
    _attr_icon = "mdi:calendar-clock"

    async def async_press(self) -> None:
        await self.coordinator.notifier.trigger_calendar_mode()


class EpdClearMemoButton(_BaseEpdButton):
    """Button to clear active instant memo and resume normal 24H schedule."""

    _attr_unique_id = f"{DOMAIN}_clear_memo"
    _attr_name = "撤回即时便签 (Clear Memo)"
    _attr_icon = "mdi:note-remove-outline"

    async def async_press(self) -> None:
        await self.coordinator._run_in_executor(self.coordinator.memo_mgr.clear_memo)
        self.coordinator.notify_listeners()
        self.coordinator.notify_gateway_for_current_state()

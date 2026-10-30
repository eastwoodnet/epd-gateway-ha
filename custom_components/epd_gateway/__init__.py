"""The EPD E-Paper Wireless Gateway (epd_gateway) integration for Home Assistant."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

try:
    import voluptuous as vol
except ImportError:
    vol = None  # type: ignore[assignment]

try:
    from homeassistant.components import frontend
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.const import Platform
    from homeassistant.core import HomeAssistant, ServiceCall
    HAS_HOMEASSISTANT = True
    PLATFORMS: list[Platform] = [
        Platform.SELECT,
        Platform.BUTTON,
        Platform.SENSOR,
        Platform.IMAGE,
        Platform.NOTIFY,
    ]
except ImportError:
    HAS_HOMEASSISTANT = False
    frontend = None  # type: ignore[assignment]
    ConfigEntry = Any  # type: ignore[assignment,misc]
    HomeAssistant = Any  # type: ignore[assignment,misc]
    ServiceCall = Any  # type: ignore[assignment,misc]
    PLATFORMS = ["select", "button", "sensor", "image", "notify"]  # type: ignore[assignment]

from .const import (
    API_BASE_PATH,
    CONF_REGISTER_PANEL,
    DEFAULT_REGISTER_PANEL,
    DISPLAY_MODES,
    DOMAIN,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    SERVICE_CLEAR_MEMO,
    SERVICE_PUSH_MEMO,
    SERVICE_SET_FALLBACK_MODE,
    SERVICE_TRIGGER_NATIVE_CALENDAR,
    SERVICE_TRIGGER_SYNC,
)
from .coordinator import EpdGatewayCoordinator
from .http_views import register_http_views

_LOGGER = logging.getLogger(__name__)


def _register_sidebar_panel(hass: HomeAssistant, enable: bool) -> None:
    """Register or remove the EPD Gateway Web Workbench sidebar panel in Home Assistant."""
    if not HAS_HOMEASSISTANT or frontend is None:
        return
    try:
        if enable:
            frontend.async_register_built_in_panel(
                hass,
                component_name="iframe",
                sidebar_title=PANEL_TITLE,
                sidebar_icon=PANEL_ICON,
                frontend_url_path=PANEL_URL_PATH,
                config={"url": f"{API_BASE_PATH}/panel"},
                require_admin=False,
                update=True,
            )
        else:
            frontend.async_remove_panel(hass, PANEL_URL_PATH)
    except Exception as exc:
        _LOGGER.debug("Sidebar panel registration skipped/failed: %s", exc)


def _register_services(hass: HomeAssistant, coordinator: EpdGatewayCoordinator) -> None:
    """Register native Home Assistant services for automations and scripts."""
    if not hasattr(hass, "services"):
        return

    async def handle_push_memo(call: ServiceCall) -> None:
        text = str(call.data.get("text", "")).strip()
        title = str(call.data.get("title", "📌 桌面备忘提醒")).strip()
        duration_min = int(call.data.get("duration_min", 120))
        sender = str(call.data.get("sender", "HA自动化")).strip()
        await coordinator._run_in_executor(
            coordinator.memo_mgr.push_memo,
            text,
            title,
            duration_min,
            sender,
        )
        coordinator.notify_listeners()
        coordinator.notifier.trigger_sync_background()

    async def handle_clear_memo(call: ServiceCall) -> None:
        await coordinator._run_in_executor(coordinator.memo_mgr.clear_memo)
        coordinator.notify_listeners()
        coordinator.notify_gateway_for_current_state()

    async def handle_trigger_sync(call: ServiceCall) -> None:
        await coordinator.notifier.trigger_sync()

    async def handle_trigger_native_calendar(call: ServiceCall) -> None:
        await coordinator.notifier.trigger_calendar_mode()

    async def handle_set_fallback_mode(call: ServiceCall) -> None:
        mode = str(call.data.get("mode", "photo_album")).strip()
        if mode not in DISPLAY_MODES:
            raise ValueError(f"Unsupported mode: {mode}")
        sched = coordinator.scheduler.get_schedule()
        sched["fallback_mode"] = mode
        await coordinator._run_in_executor(coordinator.scheduler.save_schedule, sched)
        coordinator.notify_listeners()
        coordinator.notify_gateway_for_current_state()

    hass.services.async_register(
        DOMAIN,
        SERVICE_PUSH_MEMO,
        handle_push_memo,
        schema=vol.Schema(
            {
                vol.Required("text"): str,
                vol.Optional("title", default="📌 桌面备忘提醒"): str,
                vol.Optional("duration_min", default=120): vol.All(vol.Coerce(int), vol.Range(min=5, max=1440)),
                vol.Optional("sender", default="HA自动化"): str,
            }
        ) if vol is not None else None,
    )
    hass.services.async_register(DOMAIN, SERVICE_CLEAR_MEMO, handle_clear_memo)
    hass.services.async_register(DOMAIN, SERVICE_TRIGGER_SYNC, handle_trigger_sync)
    hass.services.async_register(DOMAIN, SERVICE_TRIGGER_NATIVE_CALENDAR, handle_trigger_native_calendar)
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_FALLBACK_MODE,
        handle_set_fallback_mode,
        schema=vol.Schema({vol.Required("mode"): vol.In(DISPLAY_MODES)}) if vol is not None else None,
    )


async def async_setup(hass: HomeAssistant, config: Dict[str, Any]) -> bool:
    """Set up the EPD Gateway component (supports auto-import if settings.json or yaml exists)."""
    hass.data.setdefault(DOMAIN, {})
    if hasattr(hass, "config_entries") and not hass.config_entries.async_entries(DOMAIN):
        yaml_cfg = config.get(DOMAIN) if isinstance(config.get(DOMAIN), dict) else {}
        settings_path = hass.config.path("epd_gateway_data", "settings.json")
        if DOMAIN in config or os.path.exists(settings_path):
            import_data: Dict[str, Any] = dict(yaml_cfg)
            if os.path.exists(settings_path):
                try:
                    def _read_settings() -> Dict[str, Any]:
                        with open(settings_path, "r", encoding="utf-8") as handle:
                            return json.load(handle)

                    disk_settings = await hass.async_add_executor_job(_read_settings)
                    if isinstance(disk_settings, dict):
                        for k in (
                            "gateway_url",
                            "weather_city",
                            "calendar_ical_url",
                            "weather_entity",
                            "calendar_entity",
                            "indoor_temp_entity",
                            "indoor_humidity_entity",
                        ):
                            if disk_settings.get(k) and not import_data.get(k):
                                import_data[k] = disk_settings[k]
                except Exception as exc:
                    _LOGGER.debug("Auto-import settings read skipped: %s", exc)

            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": "import"},
                    data=import_data,
                )
            )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up EPD Gateway from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    merged_config = {**(entry.data or {}), **(entry.options or {})}

    data_dir = hass.config.path("epd_gateway_data")
    coordinator = await hass.async_add_executor_job(
        EpdGatewayCoordinator,
        hass,
        data_dir,
        merged_config,
    )

    hass.data[DOMAIN]["coordinator"] = coordinator
    hass.data[DOMAIN]["entry"] = entry

    register_http_views(hass)
    _register_sidebar_panel(hass, merged_config.get(CONF_REGISTER_PANEL, DEFAULT_REGISTER_PANEL))
    _register_services(hass, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    merged_config = {**(entry.data or {}), **(entry.options or {})}
    coordinator: EpdGatewayCoordinator | None = hass.data.get(DOMAIN, {}).get("coordinator")
    if coordinator is not None:
        coordinator.update_from_config_entry(merged_config)
    _register_sidebar_panel(hass, merged_config.get(CONF_REGISTER_PANEL, DEFAULT_REGISTER_PANEL))


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        _register_sidebar_panel(hass, False)
        for srv in (
            SERVICE_PUSH_MEMO,
            SERVICE_CLEAR_MEMO,
            SERVICE_TRIGGER_SYNC,
            SERVICE_TRIGGER_NATIVE_CALENDAR,
            SERVICE_SET_FALLBACK_MODE,
        ):
            if hasattr(hass, "services") and hass.services.has_service(DOMAIN, srv):
                hass.services.async_remove(DOMAIN, srv)
        hass.data[DOMAIN].pop("coordinator", None)
        hass.data[DOMAIN].pop("entry", None)
    return unload_ok

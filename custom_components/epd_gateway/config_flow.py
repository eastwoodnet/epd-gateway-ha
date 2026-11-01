"""Config flow and Options flow for EPD E-Paper Wireless Gateway integration."""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    import voluptuous as vol
except ImportError:
    class _VolStub:
        @staticmethod
        def Schema(d):
            return d

        @staticmethod
        def Required(k, default=None):
            return k

        @staticmethod
        def Optional(k, default=None):
            return k

        @staticmethod
        def Any(*args):
            return args

    vol = _VolStub()  # type: ignore[assignment]

try:
    from homeassistant import config_entries
    from homeassistant.core import callback
    from homeassistant.helpers import selector
    HAS_HA_SELECTOR = True
except ImportError:
    # Lightweight stubs for running standalone unit tests outside Home Assistant
    HAS_HA_SELECTOR = False

    def callback(func):  # type: ignore[no-redef]
        return func

    class _StubConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

        async def async_set_unique_id(self, unique_id: str) -> None:
            self._unique_id = unique_id

        def _abort_if_unique_id_configured(self) -> None:
            pass

        def async_create_entry(self, *, title: str, data: Dict[str, Any]) -> Dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any,
            errors: Optional[Dict[str, str]] = None,
        ) -> Dict[str, Any]:
            return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}

    class _StubOptionsFlow:
        def async_create_entry(self, *, title: str, data: Dict[str, Any]) -> Dict[str, Any]:
            return {"type": "create_entry", "title": title, "data": data}

        def async_show_form(
            self,
            *,
            step_id: str,
            data_schema: Any,
            errors: Optional[Dict[str, str]] = None,
        ) -> Dict[str, Any]:
            return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {}}

    class config_entries:  # type: ignore[no-redef]
        ConfigFlow = _StubConfigFlow
        OptionsFlow = _StubOptionsFlow
        ConfigEntry = Any

from .const import (
    CONF_CALENDAR_ENTITY,
    CONF_CALENDAR_ICAL_URL,
    CONF_GATEWAY_URL,
    CONF_INDOOR_HUMIDITY_ENTITY,
    CONF_INDOOR_TEMP_ENTITY,
    CONF_REGISTER_PANEL,
    CONF_WEATHER_CITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_CALENDAR_ICAL_URL,
    DEFAULT_GATEWAY_URL,
    DEFAULT_REGISTER_PANEL,
    DEFAULT_WEATHER_CITY,
    DOMAIN,
)
from .core.models import ServerSettingsUpdate, validate_gateway_url


def validate_user_input(user_input: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, str]]:
    """Validate and normalize config/options input, returning (cleaned_data, errors)."""
    errors: Dict[str, str] = {}
    cleaned: Dict[str, Any] = dict(user_input)

    raw_gateway = str(user_input.get(CONF_GATEWAY_URL, "")).strip()
    try:
        cleaned[CONF_GATEWAY_URL] = validate_gateway_url(raw_gateway)
    except ValueError:
        errors[CONF_GATEWAY_URL] = "invalid_gateway_url"

    raw_city = str(user_input.get(CONF_WEATHER_CITY, "") or "").strip()
    raw_ical = str(user_input.get(CONF_CALENDAR_ICAL_URL, "") or "").strip()

    try:
        ServerSettingsUpdate.model_validate({"weather_city": raw_city})
        cleaned[CONF_WEATHER_CITY] = raw_city
    except Exception:
        errors[CONF_WEATHER_CITY] = "invalid_weather_city"

    if raw_ical and not (
        raw_ical.startswith("http://")
        or raw_ical.startswith("https://")
        or raw_ical.startswith("webcal://")
    ):
        errors[CONF_CALENDAR_ICAL_URL] = "invalid_ical_url"
    else:
        try:
            ServerSettingsUpdate.model_validate({"calendar_ical_url": raw_ical})
            cleaned[CONF_CALENDAR_ICAL_URL] = raw_ical
        except Exception:
            errors[CONF_CALENDAR_ICAL_URL] = "invalid_ical_url"

    cleaned[CONF_WEATHER_ENTITY] = str(user_input.get(CONF_WEATHER_ENTITY, "") or "").strip()
    cleaned[CONF_CALENDAR_ENTITY] = str(user_input.get(CONF_CALENDAR_ENTITY, "") or "").strip()
    cleaned[CONF_INDOOR_TEMP_ENTITY] = str(user_input.get(CONF_INDOOR_TEMP_ENTITY, "") or "").strip()
    cleaned[CONF_INDOOR_HUMIDITY_ENTITY] = str(user_input.get(CONF_INDOOR_HUMIDITY_ENTITY, "") or "").strip()
    cleaned[CONF_REGISTER_PANEL] = bool(user_input.get(CONF_REGISTER_PANEL, DEFAULT_REGISTER_PANEL))
    return cleaned, errors


def _opt_suggested(key: str, val: Any) -> vol.Optional:
    """Helper to attach suggested_value only when a non-empty default is present."""
    if val not in (None, "", getattr(vol, "UNDEFINED", object())):
        return vol.Optional(key, description={"suggested_value": val})
    return vol.Optional(key)


def _build_schema(defaults: Dict[str, Any]) -> vol.Schema:
    gw_default = defaults.get(CONF_GATEWAY_URL, DEFAULT_GATEWAY_URL)
    weather_ent_default = defaults.get(CONF_WEATHER_ENTITY, "")
    cal_ent_default = defaults.get(CONF_CALENDAR_ENTITY, "")
    indoor_t_default = defaults.get(CONF_INDOOR_TEMP_ENTITY, "")
    indoor_h_default = defaults.get(CONF_INDOOR_HUMIDITY_ENTITY, "")
    city_default = defaults.get(CONF_WEATHER_CITY, DEFAULT_WEATHER_CITY)
    ical_default = defaults.get(CONF_CALENDAR_ICAL_URL, DEFAULT_CALENDAR_ICAL_URL)
    panel_default = defaults.get(CONF_REGISTER_PANEL, DEFAULT_REGISTER_PANEL)

    if HAS_HA_SELECTOR:
        schema_dict: Dict[Any, Any] = {
            vol.Required(
                CONF_GATEWAY_URL,
                description={"suggested_value": gw_default},
            ): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.URL)),
            _opt_suggested(CONF_WEATHER_ENTITY, weather_ent_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="weather")
            ),
            _opt_suggested(CONF_INDOOR_TEMP_ENTITY, indoor_t_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            _opt_suggested(CONF_INDOOR_HUMIDITY_ENTITY, indoor_h_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor")
            ),
            _opt_suggested(CONF_CALENDAR_ENTITY, cal_ent_default): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="calendar")
            ),
            _opt_suggested(CONF_WEATHER_CITY, city_default): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            ),
            _opt_suggested(CONF_CALENDAR_ICAL_URL, ical_default): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
            ),
            _opt_suggested(CONF_REGISTER_PANEL, panel_default): selector.BooleanSelector(),
        }
        return vol.Schema(schema_dict)

    return vol.Schema(
        {
            vol.Required(CONF_GATEWAY_URL, default=gw_default): str,
            vol.Optional(CONF_WEATHER_ENTITY, default=weather_ent_default): str,
            vol.Optional(CONF_INDOOR_TEMP_ENTITY, default=indoor_t_default): str,
            vol.Optional(CONF_INDOOR_HUMIDITY_ENTITY, default=indoor_h_default): str,
            vol.Optional(CONF_CALENDAR_ENTITY, default=cal_ent_default): str,
            vol.Optional(CONF_WEATHER_CITY, default=city_default): str,
            vol.Optional(CONF_CALENDAR_ICAL_URL, default=ical_default): str,
            vol.Optional(CONF_REGISTER_PANEL, default=panel_default): bool,
        }
    )


class EpdGatewayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for EPD E-Paper Wireless Gateway."""

    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle the initial step configured by the user."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            cleaned, errors = validate_user_input(user_input)
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"EPD 墨水屏网关 ({cleaned[CONF_GATEWAY_URL]})",
                    data=cleaned,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_import(
        self, import_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle automatic import from configuration.yaml or migrated epd_gateway_data."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        raw = dict(import_data or {})
        if not raw.get(CONF_GATEWAY_URL):
            raw[CONF_GATEWAY_URL] = DEFAULT_GATEWAY_URL
        cleaned, errors = validate_user_input(raw)
        if errors:
            cleaned[CONF_GATEWAY_URL] = DEFAULT_GATEWAY_URL
        return self.async_create_entry(
            title=f"EPD 墨水屏网关 ({cleaned[CONF_GATEWAY_URL]})",
            data=cleaned,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> EpdGatewayOptionsFlowHandler:
        """Create the options flow."""
        return EpdGatewayOptionsFlowHandler(config_entry)


class EpdGatewayOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for EPD Gateway (change ESP32 IP, HA entities, city, iCal URL anytime)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Manage the EPD Gateway options."""
        errors: Dict[str, str] = {}
        current = {**(self._config_entry.data or {}), **(self._config_entry.options or {})}

        if user_input is not None:
            cleaned, errors = validate_user_input(user_input)
            if not errors:
                return self.async_create_entry(title="", data=cleaned)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(user_input or current),
            errors=errors,
        )

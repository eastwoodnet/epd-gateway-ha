"""Core coordinator and state manager for EPD E-Paper Wireless Gateway."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
import hashlib
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from .const import (
    API_BASE_PATH,
    CONF_CALENDAR_ENTITY,
    CONF_CALENDAR_ICAL_URL,
    CONF_GATEWAY_URL,
    CONF_INDOOR_HUMIDITY_ENTITY,
    CONF_INDOOR_TEMP_ENTITY,
    CONF_WEATHER_CITY,
    CONF_WEATHER_ENTITY,
    DEFAULT_GATEWAY_URL,
    HA_WEATHER_CONDITION_MAP,
)
from .core.album_manager import AlbumManager, FRAME_BYTES
from .core.calendar_manager import CalendarManager, get_local_tz
from .core.gateway_notifier import GatewayNotifier
from .core.memo_manager import MemoManager
from .core.models import MemoRequest
from .core.renderer import (
    ensure_fonts_available,
    epd_bytes_to_preview_png,
    render_calendar_image,
    render_clock_image,
    render_weather_image,
)
from .core.scheduler import Scheduler
from .core.settings_manager import SettingsManager
from .core.weather_manager import WeatherManager

_LOGGER = logging.getLogger(__name__)


def etag_matches(header_value: Optional[str], etag: str) -> bool:
    if not header_value:
        return False
    target = etag.strip('"')
    for candidate in header_value.split(","):
        candidate = candidate.strip()
        if candidate == "*":
            return True
        if candidate.startswith("W/"):
            candidate = candidate[2:].strip()
        if candidate == etag or candidate.strip('"') == target:
            return True
    return False


@dataclass
class ScreenRenderResult:
    """Result of rendering /screen.bin for the ESP32 gateway."""

    status_code: int
    body: bytes
    headers: Dict[str, str]
    effective_mode: str
    next_pull_sec: int


class EpdGatewayCoordinator:
    """Manages independent state, rendering, HA entity adapters, and gateway notifications."""

    def __init__(
        self,
        hass: Any,
        data_dir: str,
        config_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.hass = hass
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "photos"), exist_ok=True)

        # Synchronize process timezone with Home Assistant's configured time_zone (e.g. Asia/Shanghai)
        # so that 24H schedules, weather dates, and iCal today-filtering match local wall-clock time
        # even when running in Docker/K3s containers where /etc/localtime is missing or UTC.
        ha_tz = getattr(getattr(hass, "config", None), "time_zone", None)
        tz_name = str(ha_tz).strip() if ha_tz else (os.environ.get("TZ") or "Asia/Shanghai")
        if tz_name:
            os.environ["TZ"] = tz_name
            if hasattr(time, "tzset"):
                try:
                    time.tzset()
                except Exception:
                    pass

        # Ensure fonts are available in data_dir/fonts
        self.fonts_dir = os.path.join(self.data_dir, "fonts")
        ensure_fonts_available(self.fonts_dir)

        cfg = config_data or {}
        initial_gateway_url = cfg.get(CONF_GATEWAY_URL) or DEFAULT_GATEWAY_URL

        settings_existed = os.path.exists(os.path.join(self.data_dir, "settings.json"))
        self.settings_mgr = SettingsManager(self.data_dir, default_gateway_url=initial_gateway_url)

        # Apply initial ConfigEntry values when settings.json is newly created or when explicit HA entities are passed
        init_changes: Dict[str, Any] = {}
        if not settings_existed:
            if cfg.get(CONF_GATEWAY_URL):
                init_changes["gateway_url"] = cfg[CONF_GATEWAY_URL]
            if cfg.get(CONF_WEATHER_CITY):
                init_changes["weather_city"] = cfg[CONF_WEATHER_CITY]
            if cfg.get(CONF_CALENDAR_ICAL_URL):
                init_changes["calendar_ical_url"] = cfg[CONF_CALENDAR_ICAL_URL]
        for ent_key in (
            CONF_WEATHER_ENTITY,
            CONF_CALENDAR_ENTITY,
            CONF_INDOOR_TEMP_ENTITY,
            CONF_INDOOR_HUMIDITY_ENTITY,
        ):
            if cfg.get(ent_key):
                init_changes[ent_key] = str(cfg[ent_key]).strip()
        if init_changes:
            self.settings_mgr.update(init_changes)

        self.weather_entity: str = (
            cfg.get(CONF_WEATHER_ENTITY) or self.settings_mgr.settings.weather_entity or ""
        ).strip()
        self.calendar_entity: str = (
            cfg.get(CONF_CALENDAR_ENTITY) or self.settings_mgr.settings.calendar_entity or ""
        ).strip()
        self.indoor_temp_entity: str = (
            cfg.get(CONF_INDOOR_TEMP_ENTITY) or self.settings_mgr.settings.indoor_temp_entity or ""
        ).strip()
        self.indoor_humidity_entity: str = (
            cfg.get(CONF_INDOOR_HUMIDITY_ENTITY) or self.settings_mgr.settings.indoor_humidity_entity or ""
        ).strip()

        self.scheduler = Scheduler(self.data_dir)
        self.schedule_engine = self.scheduler  # alias
        self.album_mgr = AlbumManager(self.data_dir, api_prefix=API_BASE_PATH)
        self.memo_mgr = MemoManager(self.data_dir)
        self.weather_mgr = WeatherManager(
            self.data_dir,
            default_city=self.settings_mgr.settings.weather_city,
        )
        self.calendar_mgr = CalendarManager(
            self.data_dir,
            default_ical_url=self.settings_mgr.settings.calendar_ical_url,
        )
        self.notifier = GatewayNotifier(self.settings_mgr.settings.gateway_url)

        self._last_dispatched_mode: Optional[str] = None
        self._last_calendar_sync_date: Optional[str] = None
        self._listeners: List[Callable[[], None]] = []
        self.last_rendered_bin: Optional[bytes] = None
        self.last_rendered_png: Optional[bytes] = None
        self.last_updated_dt: Optional[datetime] = None
        self.last_effective_mode: str = "photo_album"

    async def _run_in_executor(self, func: Callable[..., Any], *args: Any) -> Any:
        if self.hass is not None and hasattr(self.hass, "async_add_executor_job"):
            return await self.hass.async_add_executor_job(func, *args)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    def notify_listeners(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception as exc:
                _LOGGER.debug("Listener error: %s", exc)

    def notify_gateway_for_current_state(self) -> None:
        """Notify ESP32 gateway according to current effective mode (identical to server/main.py)."""
        now_ts = time.time()
        if self.memo_mgr.is_active(now_ts):
            self.notifier.trigger_sync_background()
            return

        _, active_mode, _ = self.scheduler.get_current_rule(
            fallback_rotate_min=self.settings_mgr.settings.rotate_interval_min
        )
        if active_mode == "sleep_dnd":
            self._last_dispatched_mode = "sleep_dnd"
            return
        if active_mode == "clock":
            self._last_dispatched_mode = "clock"
            self._last_calendar_sync_date = time.strftime("%Y-%m-%d", time.localtime(now_ts))
            self.notifier.trigger_calendar_mode_background(timestamp=int(now_ts), timezone=8)
            return

        self.notifier.trigger_sync_background()

    def activate_memo(self, req: MemoRequest):
        state = self.memo_mgr.set_memo(
            text=req.text,
            title=req.title,
            duration_min=req.duration_min,
            sender=req.sender,
            theme=req.theme,
        )
        self.notify_listeners()
        self.notifier.trigger_sync_background()
        return state

    def update_from_config_entry(self, merged_config: Dict[str, Any]) -> None:
        """Apply updated HA ConfigEntry / OptionsFlow values."""
        self.weather_entity = (merged_config.get(CONF_WEATHER_ENTITY) or "").strip()
        self.calendar_entity = (merged_config.get(CONF_CALENDAR_ENTITY) or "").strip()
        self.indoor_temp_entity = (merged_config.get(CONF_INDOOR_TEMP_ENTITY) or "").strip()
        self.indoor_humidity_entity = (merged_config.get(CONF_INDOOR_HUMIDITY_ENTITY) or "").strip()

        changes: Dict[str, Any] = {
            "weather_entity": self.weather_entity,
            "calendar_entity": self.calendar_entity,
            "indoor_temp_entity": self.indoor_temp_entity,
            "indoor_humidity_entity": self.indoor_humidity_entity,
        }
        if merged_config.get(CONF_GATEWAY_URL):
            changes["gateway_url"] = merged_config[CONF_GATEWAY_URL]
        if merged_config.get(CONF_WEATHER_CITY) is not None:
            changes["weather_city"] = merged_config[CONF_WEATHER_CITY]
        if merged_config.get(CONF_CALENDAR_ICAL_URL) is not None:
            changes["calendar_ical_url"] = merged_config[CONF_CALENDAR_ICAL_URL]

        updated = self.settings_mgr.update(changes)
        self.notifier.set_gateway_url(updated.gateway_url)
        self.weather_mgr.default_city = updated.weather_city
        self.calendar_mgr.set_ical_url(updated.calendar_ical_url)

        self.notify_listeners()

    def get_effective_mode_info(self) -> Dict[str, Any]:
        """Return current effective mode, next_pull_sec, and active memo status."""
        now_ts = time.time()
        active_memo = self.memo_mgr.get_active_memo()
        active_rule, sched_mode, next_pull_sec = self.scheduler.get_current_rule(
            fallback_rotate_min=self.settings_mgr.settings.rotate_interval_min
        )
        effective_mode = "memo" if active_memo else sched_mode
        if active_memo:
            remain_sec = max(30, int(active_memo.get("expire_at", now_ts) - now_ts))
            next_pull_sec = min(remain_sec, 3600)

        slots = self.album_mgr.list_slots()
        filled_slots = sum(1 for s in slots if s.get("exists"))
        settings = self.settings_mgr.settings

        return {
            "effective_mode": effective_mode,
            "schedule_mode": sched_mode,
            "active_rule": active_rule.model_dump() if active_rule else None,
            "fallback_mode": self.scheduler.config.fallback_mode,
            "next_pull_sec": next_pull_sec,
            "active_memo": active_memo,
            "filled_slots": filled_slots,
            "gateway_url": settings.gateway_url,
            "weather_entity": self.weather_entity,
            "calendar_entity": self.calendar_entity,
            "indoor_temp_entity": self.indoor_temp_entity,
            "indoor_humidity_entity": self.indoor_humidity_entity,
            "weather_city": settings.weather_city,
            "calendar_ical_url": settings.calendar_ical_url,
        }

    def _read_ha_sensor_numeric(self, entity_id: str) -> Optional[str]:
        """Read a numeric sensor state from Home Assistant and format it cleanly."""
        if not entity_id or self.hass is None or not hasattr(self.hass, "states"):
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", None, ""):
            return None
        try:
            val = float(state.state)
            if abs(val - round(val)) < 0.05:
                return str(int(round(val)))
            return f"{val:.1f}"
        except Exception:
            return None

    def _enrich_with_indoor_sensors(self, weather_data: Dict[str, Any]) -> Dict[str, Any]:
        """Attach indoor_temp and indoor_humidity from HA sensor entities if configured."""
        enriched = dict(weather_data)
        indoor_t = self._read_ha_sensor_numeric(self.indoor_temp_entity)
        indoor_h = self._read_ha_sensor_numeric(self.indoor_humidity_entity)
        if indoor_t is not None:
            enriched["indoor_temp"] = indoor_t
            enriched["indoor_temp_entity"] = self.indoor_temp_entity
        if indoor_h is not None:
            enriched["indoor_humidity"] = indoor_h
            enriched["indoor_humidity_entity"] = self.indoor_humidity_entity
        return enriched

    async def async_get_weather_data(
        self,
        city_override: Optional[str] = None,
        force_refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Get weather data in the exact dictionary format required by render_weather_image().
        Priority:
        1. If a Home Assistant weather.* entity is bound and valid in hass.states (and no explicit city_override), use it.
        2. Otherwise use WeatherManager (wttr.in).
        3. If Home Assistant indoor temperature/humidity sensors are bound, attach indoor_temp / indoor_humidity.
        """
        target_city = (
            city_override
            if city_override is not None
            else self.settings_mgr.settings.weather_city
        )

        if city_override is None and self.weather_entity and self.hass is not None:
            ha_weather = await self._async_adapt_ha_weather_entity(self.weather_entity, target_city)
            if ha_weather is not None:
                return self._enrich_with_indoor_sensors(ha_weather)

        base_weather = await self._run_in_executor(self.weather_mgr.get_weather, target_city, force_refresh)
        return self._enrich_with_indoor_sensors(base_weather)

    async def _async_adapt_ha_weather_entity(
        self,
        entity_id: str,
        city_override: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Convert a Home Assistant weather.* entity state into render_weather_image's dict."""
        if not hasattr(self.hass, "states"):
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", None):
            return None

        attrs = state.attributes or {}
        raw_cond = str(state.state).lower().strip()
        desc = HA_WEATHER_CONDITION_MAP.get(raw_cond, raw_cond or "晴")

        temp_val = attrs.get("temperature", 24)
        try:
            temp_c = str(int(round(float(temp_val))))
        except Exception:
            temp_c = "--"

        feels_val = attrs.get("apparent_temperature", temp_val)
        try:
            feels_like = str(int(round(float(feels_val))))
        except Exception:
            feels_like = temp_c

        humidity_val = attrs.get("humidity", 50)
        try:
            humidity = str(int(round(float(humidity_val))))
        except Exception:
            humidity = "--"

        wind_bearing = attrs.get("wind_bearing", "")
        if isinstance(wind_bearing, (int, float)) or (
            isinstance(wind_bearing, str) and wind_bearing.replace(".", "", 1).isdigit()
        ):
            wind_dir = WeatherManager.deg_to_wind_dir(wind_bearing)
        elif isinstance(wind_bearing, str) and wind_bearing.strip():
            wind_dir = wind_bearing.strip()
        else:
            wind_dir = "微风"

        wind_speed = attrs.get("wind_speed", "")
        try:
            ws_int = int(round(float(wind_speed)))
            wind_str = f"{wind_dir} {ws_int}km/h"
        except Exception:
            wind_str = f"{wind_dir} {wind_speed}".strip() or "--"

        city_name = city_override.strip()
        if not city_name:
            friendly = str(attrs.get("friendly_name", "")).strip()
            for suffix in (" Weather", "天气", " Forecast", "预报"):
                if friendly.endswith(suffix) and len(friendly) > len(suffix):
                    friendly = friendly[: -len(suffix)].strip()
            city_name = friendly or "本地"

        raw_forecasts: List[Dict[str, Any]] = []
        if hasattr(self.hass, "services") and self.hass.services.has_service("weather", "get_forecasts"):
            try:
                resp = await self.hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {"entity_id": entity_id, "type": "daily"},
                    blocking=True,
                    return_response=True,
                )
                if isinstance(resp, dict) and entity_id in resp:
                    raw_forecasts = resp[entity_id].get("forecast", []) or []
            except Exception as exc:
                _LOGGER.debug("weather.get_forecasts failed for %s: %s", entity_id, exc)

        if not raw_forecasts and isinstance(attrs.get("forecast"), list):
            raw_forecasts = attrs.get("forecast")

        weekdays_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        forecast_list: List[Dict[str, str]] = []
        today_max = temp_c
        today_min = temp_c

        for idx, fc in enumerate(raw_forecasts[:3]):
            if not isinstance(fc, dict):
                continue
            fc_cond = str(fc.get("condition", raw_cond)).lower().strip()
            fc_desc = HA_WEATHER_CONDITION_MAP.get(fc_cond, desc)

            fc_max_raw = fc.get("temperature", temp_c)
            fc_min_raw = fc.get("templow", fc_max_raw)
            try:
                max_s = str(int(round(float(fc_max_raw))))
            except Exception:
                max_s = str(fc_max_raw)
            try:
                min_s = str(int(round(float(fc_min_raw))))
            except Exception:
                min_s = str(fc_min_raw)

            if idx == 0:
                today_max = max_s
                today_min = min_s

            dt_str = str(fc.get("datetime", ""))
            target_dt = date.today() + timedelta(days=idx)
            label = weekdays_cn[target_dt.weekday()]
            short_date = target_dt.isoformat()
            if dt_str:
                try:
                    dt_parsed = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    short_date = dt_parsed.strftime("%Y-%m-%d")
                    label = weekdays_cn[dt_parsed.weekday()]
                except Exception:
                    pass

            forecast_list.append({
                "label": label,
                "date": short_date,
                "desc": fc_desc,
                "temp_min": min_s,
                "temp_max": max_s,
            })

        return {
            "city": city_name,
            "temp_c": temp_c,
            "feels_like_c": feels_like,
            "humidity": humidity,
            "weather_desc": desc,
            "wind": wind_str,
            "temp_min": today_min,
            "temp_max": today_max,
            "forecast": forecast_list,
            "update_time": datetime.now().strftime("%H:%M"),
            "stale": False,
            "source": entity_id,
        }

    async def async_get_calendar_data(
        self,
        force_refresh: bool = False,
        custom_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get calendar events in the exact dictionary format required by render_calendar_image().
        Priority:
        1. If custom_url is passed or calendar_ical_url is configured in settings, use CalendarManager (iCal).
        2. If a Home Assistant calendar.* entity is configured and valid in hass.states, read today's events from HA.
        3. Fallback to CalendarManager (mock/default).
        """
        configured_url = self.settings_mgr.settings.calendar_ical_url.strip()
        self.calendar_mgr.set_ical_url(configured_url)

        if custom_url is not None or configured_url:
            return await self._run_in_executor(
                self.calendar_mgr.fetch_calendar_data,
                force_refresh,
                custom_url,
            )

        if self.calendar_entity and self.hass is not None:
            ha_cal = await self._async_adapt_ha_calendar_entity(self.calendar_entity)
            if ha_cal is not None:
                return ha_cal

        return await self._run_in_executor(
            self.calendar_mgr.fetch_calendar_data,
            force_refresh,
            custom_url,
        )

    async def _async_adapt_ha_calendar_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Read today's events from a Home Assistant calendar.* entity."""
        if not hasattr(self.hass, "states"):
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unavailable", "unknown", None):
            return None

        local_tz = get_local_tz()
        today = date.today()
        now_dt = datetime.now(local_tz)
        start_dt = datetime.combine(today, dtime.min).replace(tzinfo=local_tz)
        end_dt = datetime.combine(today, dtime.max).replace(tzinfo=local_tz)

        raw_events: List[Dict[str, Any]] = []
        if hasattr(self.hass, "services") and self.hass.services.has_service("calendar", "get_events"):
            try:
                resp = await self.hass.services.async_call(
                    "calendar",
                    "get_events",
                    {
                        "entity_id": entity_id,
                        "start_date_time": start_dt.isoformat(),
                        "end_date_time": end_dt.isoformat(),
                    },
                    blocking=True,
                    return_response=True,
                )
                if isinstance(resp, dict) and entity_id in resp:
                    raw_events = resp[entity_id].get("events", []) or []
            except Exception as exc:
                _LOGGER.warning("calendar.get_events failed for %s: %s", entity_id, exc)
                return {
                    "fetched_at": now_dt.timestamp(),
                    "today_date": today.isoformat(),
                    "ical_url": f"ha://{entity_id}",
                    "is_mock": False,
                    "stale": True,
                    "status": "error",
                    "message": f"HA 日历实体读取失败: {exc}",
                    "error_detail": str(exc),
                    "events": [],
                    "update_time": now_dt.strftime("%H:%M"),
                }

        events: List[Dict[str, Any]] = []
        for item in raw_events:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary", "未命名日程")).strip()
            location = str(item.get("location", "")).strip()
            description = str(item.get("description", "")).strip()
            raw_start = str(item.get("start", "")).strip()
            raw_end = str(item.get("end", "")).strip()

            if len(raw_start) == 10 and "T" not in raw_start:
                events.append({
                    "title": summary,
                    "start_time": "全天",
                    "end_time": "",
                    "location": location,
                    "description": description,
                    "is_all_day": True,
                    "is_ongoing": True,
                    "_sort_key": (0, 0),
                })
                continue

            try:
                ev_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00"))
                if ev_start.tzinfo is None:
                    ev_start = ev_start.replace(tzinfo=local_tz)
                else:
                    ev_start = ev_start.astimezone(local_tz)

                if raw_end:
                    ev_end = datetime.fromisoformat(raw_end.replace("Z", "+00:00"))
                    if ev_end.tzinfo is None:
                        ev_end = ev_end.replace(tzinfo=local_tz)
                    else:
                        ev_end = ev_end.astimezone(local_tz)
                else:
                    ev_end = ev_start + timedelta(hours=1)

                is_ongoing = ev_start <= now_dt <= ev_end
                events.append({
                    "title": summary,
                    "start_time": ev_start.strftime("%H:%M"),
                    "end_time": ev_end.strftime("%H:%M"),
                    "location": location,
                    "description": description,
                    "is_all_day": False,
                    "is_ongoing": is_ongoing,
                    "_sort_key": (1, ev_start.hour * 60 + ev_start.minute),
                })
            except Exception:
                continue

        events.sort(key=lambda x: x.get("_sort_key", (1, 0)))
        for ev in events:
            ev.pop("_sort_key", None)

        friendly_name = (state.attributes or {}).get("friendly_name", entity_id)
        return {
            "fetched_at": now_dt.timestamp(),
            "today_date": today.isoformat(),
            "ical_url": f"ha://{entity_id}",
            "is_mock": False,
            "status": "ok",
            "message": f"从 HA 日历 ({friendly_name}) 同步 {len(events)} 项今日日程",
            "source_label": f"数据源: Home Assistant 日历 ({friendly_name})",
            "events": events,
            "update_time": now_dt.strftime("%H:%M"),
        }

    async def async_render_screen(self, client_etag: Optional[str] = None) -> ScreenRenderResult:
        """
        Execute the exact priority pipeline & headers as server/main.py:
        1. Active Memo (Priority Override)
        2. 24H Schedule Rule (sleep_dnd -> 304, clock -> 0x20 BLE + 304, photo_album, weather_date, calendar_todo)
        """
        next_pull_sec = 1800
        bin_data: Optional[bytes] = None
        now_ts = time.time()
        effective_mode = "photo_album"

        # 1. First priority: Instant Memo override
        if self.memo_mgr.is_active(now_ts):
            self._last_dispatched_mode = "memo"
            effective_mode = "memo"
            bin_data = await self._run_in_executor(self.memo_mgr.get_bin_data)
            memo_state = self.memo_mgr.get_state()
            remain_sec = max(30, int(memo_state.expire_at - now_ts))
            next_pull_sec = min(remain_sec, 3600)

        # 2. Second priority: 24-hour schedule
        if bin_data is None:
            active_rule, active_mode, sched_next_pull = self.scheduler.get_current_rule(
                fallback_rotate_min=self.settings_mgr.settings.rotate_interval_min
            )
            effective_mode = active_mode
            next_pull_sec = sched_next_pull

            if active_mode == "sleep_dnd":
                self._last_dispatched_mode = "sleep_dnd"
                self.last_effective_mode = "sleep_dnd"
                return ScreenRenderResult(
                    status_code=304,
                    body=b"",
                    headers={
                        "ETag": client_etag if client_etag else '"dnd-keep"',
                        "X-Next-Pull": str(next_pull_sec),
                        "X-Sleep-Seconds": str(next_pull_sec),
                        "Cache-Control": "no-cache",
                    },
                    effective_mode="sleep_dnd",
                    next_pull_sec=next_pull_sec,
                )

            if active_mode == "clock":
                today_str = time.strftime("%Y-%m-%d", time.localtime(now_ts))
                cal_etag = f'"native-calendar-{today_str}"'
                if self._last_dispatched_mode != "clock" or self._last_calendar_sync_date != today_str:
                    self._last_dispatched_mode = "clock"
                    self._last_calendar_sync_date = today_str
                    self.notifier.trigger_calendar_mode_background(
                        timestamp=int(now_ts), timezone=8, delay_sec=1.2
                    )
                self.last_effective_mode = "clock"
                return ScreenRenderResult(
                    status_code=304,
                    body=b"",
                    headers={
                        "ETag": cal_etag,
                        "X-Next-Pull": str(next_pull_sec),
                        "X-Sleep-Seconds": str(next_pull_sec),
                        "Cache-Control": "no-cache",
                    },
                    effective_mode="clock",
                    next_pull_sec=next_pull_sec,
                )

            self._last_dispatched_mode = active_mode

            if active_mode == "photo_album":
                rotate_interval = (
                    active_rule.config.get("rotate_interval_min", 60)
                    if active_rule
                    else self.settings_mgr.settings.rotate_interval_min
                )
                _, photo_bytes = await self._run_in_executor(
                    self.album_mgr.get_active_photo_info,
                    rotate_interval,
                    now_ts,
                )
                if photo_bytes and len(photo_bytes) == FRAME_BYTES:
                    bin_data = photo_bytes
                else:
                    bin_data = await self._run_in_executor(
                        render_clock_image,
                        self.settings_mgr.settings.screen_width,
                        self.settings_mgr.settings.screen_height,
                        "相册卡槽未配置，请在 Web 后台上传照片",
                    )

            elif active_mode == "weather_date":
                rule_city = active_rule.config.get("city") if active_rule else None
                w_data = await self.async_get_weather_data(city_override=rule_city)
                bin_data = await self._run_in_executor(
                    render_weather_image,
                    w_data,
                    self.settings_mgr.settings.screen_width,
                    self.settings_mgr.settings.screen_height,
                )

            elif active_mode == "calendar_todo":
                cal_data = await self.async_get_calendar_data()
                bin_data = await self._run_in_executor(
                    render_calendar_image,
                    cal_data,
                    self.settings_mgr.settings.screen_width,
                    self.settings_mgr.settings.screen_height,
                )

            else:
                bin_data = await self._run_in_executor(
                    render_clock_image,
                    self.settings_mgr.settings.screen_width,
                    self.settings_mgr.settings.screen_height,
                    f"模式: {active_mode}",
                )

        if not bin_data:
            bin_data = await self._run_in_executor(render_clock_image)

        content_hash = hashlib.md5(bin_data).hexdigest()
        etag = f'"{content_hash}"'
        headers = {
            "ETag": etag,
            "X-Next-Pull": str(next_pull_sec),
            "X-Sleep-Seconds": str(next_pull_sec),
            "Cache-Control": "no-cache",
        }

        if self.last_rendered_bin != bin_data:
            self.last_rendered_bin = bin_data
            self.last_rendered_png = await self._run_in_executor(epd_bytes_to_preview_png, bin_data)
            self.last_updated_dt = datetime.now()
            self.last_effective_mode = effective_mode
            self.notify_listeners()
        else:
            self.last_effective_mode = effective_mode

        if etag_matches(client_etag, etag):
            return ScreenRenderResult(
                status_code=304,
                body=b"",
                headers=headers,
                effective_mode=effective_mode,
                next_pull_sec=next_pull_sec,
            )

        return ScreenRenderResult(
            status_code=200,
            body=bin_data,
            headers=headers,
            effective_mode=effective_mode,
            next_pull_sec=next_pull_sec,
        )

    async def async_get_preview_png(self) -> bytes:
        """Return a 400x300 PNG preview of the currently active screen for HA ImageEntity."""
        if self.last_rendered_png is not None:
            return self.last_rendered_png

        result = await self.async_render_screen(client_etag=None)
        if result.body:
            self.last_rendered_png = await self._run_in_executor(epd_bytes_to_preview_png, result.body)
            return self.last_rendered_png

        w_data = await self.async_get_weather_data()
        bin_data = await self._run_in_executor(render_weather_image, w_data)
        self.last_rendered_bin = bin_data
        self.last_rendered_png = await self._run_in_executor(epd_bytes_to_preview_png, bin_data)
        self.last_updated_dt = datetime.now()
        return self.last_rendered_png

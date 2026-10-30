"""HTTP API and Web Workbench Views for EPD E-Paper Wireless Gateway in Home Assistant."""

from __future__ import annotations

import io
import json
import mimetypes
import os
import time
from typing import Any, Optional

try:
    from aiohttp import web
except ImportError:
    class _WebStub:
        Request = Any
        Response = Any

    web = _WebStub()  # type: ignore[assignment]

from pydantic import ValidationError

try:
    from homeassistant.components.http import HomeAssistantView
except ImportError:
    class HomeAssistantView:  # type: ignore[no-redef]
        """Fallback base class when running unit tests outside Home Assistant."""

        url: str = ""
        extra_urls: list[str] = []
        name: str = ""
        requires_auth: bool = False

from .const import (
    API_BASE_PATH,
    CONF_CALENDAR_ENTITY,
    CONF_CALENDAR_ICAL_URL,
    CONF_GATEWAY_URL,
    CONF_INDOOR_HUMIDITY_ENTITY,
    CONF_INDOOR_TEMP_ENTITY,
    CONF_WEATHER_CITY,
    CONF_WEATHER_ENTITY,
    DOMAIN,
)
from .coordinator import EpdGatewayCoordinator
from .core.album_manager import FRAME_BYTES, TOTAL_SLOTS
from .core.models import MemoRequest, ScheduleConfig, ServerSettingsUpdate
from .core.renderer import (
    raw_to_image,
    render_calendar_image,
    render_weather_image,
)

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATIC_DIR = os.path.join(WEB_DIR, "static")
INDEX_HTML_PATH = os.path.join(WEB_DIR, "templates", "index.html")


def _get_coordinator(request: web.Request) -> Optional[EpdGatewayCoordinator]:
    hass = request.app.get("hass")
    if hass is None:
        return request.app.get(DOMAIN)
    domain_data = hass.data.get(DOMAIN, {})
    return domain_data.get("coordinator")


def _json_response(payload: Any, status: int = 200) -> web.Response:
    return web.Response(
        body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        status=status,
        content_type="application/json",
        charset="utf-8",
    )


def _format_validation_error(exc: ValidationError) -> str:
    errors = exc.errors()
    if errors:
        return "; ".join(str(err.get("msg", "参数校验失败")) for err in errors)
    return str(exc)


class EpdScreenBinView(HomeAssistantView):
    """Serves the 30,000-byte BWR screen payload to the ESP32 Gateway (100% identical to server/main.py)."""

    url = f"{API_BASE_PATH}/screen.bin"
    extra_urls = ["/screen.bin"]
    name = "api:epd_gateway:screen_bin"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        client_etag = request.headers.get("if-none-match")
        result = await coord.async_render_screen(client_etag=client_etag)
        return web.Response(
            body=result.body,
            status=result.status_code,
            headers=result.headers,
            content_type="application/octet-stream",
        )


class EpdPanelView(HomeAssistantView):
    """Serves the full Web Workbench (24H Schedule + 3-Slot Photo Studio + Memo + Settings)."""

    url = f"{API_BASE_PATH}/panel"
    extra_urls = [f"{API_BASE_PATH}/panel/"]
    name = "api:epd_gateway:panel"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        if not os.path.exists(INDEX_HTML_PATH):
            return web.Response(text="Workbench template not found", status=404)
        hass = request.app.get("hass")
        if hass is not None and hasattr(hass, "async_add_executor_job"):
            def _read_html() -> str:
                with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
                    return handle.read()
            html_content = await hass.async_add_executor_job(_read_html)
        else:
            with open(INDEX_HTML_PATH, "r", encoding="utf-8") as handle:
                html_content = handle.read()
        return web.Response(
            text=html_content,
            status=200,
            content_type="text/html",
            charset="utf-8",
        )


class EpdStaticAssetView(HomeAssistantView):
    """Serves static CSS and JS files for the EPD Gateway Web Workbench."""

    url = f"{API_BASE_PATH}/static/{{filepath:.*}}"
    name = "api:epd_gateway:static"
    requires_auth = False

    async def get(self, request: web.Request, filepath: str) -> web.Response:
        safe_root = os.path.realpath(STATIC_DIR)
        target_path = os.path.realpath(os.path.join(safe_root, filepath))
        if not target_path.startswith(safe_root + os.sep) or not os.path.isfile(target_path):
            return web.Response(text="Not Found", status=404)

        mime_type, _ = mimetypes.guess_type(target_path)
        if target_path.endswith(".css"):
            mime_type = "text/css"
        elif target_path.endswith(".js"):
            mime_type = "application/javascript"

        hass = request.app.get("hass")
        if hass is not None and hasattr(hass, "async_add_executor_job"):
            def _read_bytes() -> bytes:
                with open(target_path, "rb") as handle:
                    return handle.read()
            content = await hass.async_add_executor_job(_read_bytes)
        else:
            with open(target_path, "rb") as handle:
                content = handle.read()
        return web.Response(
            body=content,
            status=200,
            content_type=mime_type or "application/octet-stream",
        )


class EpdScheduleView(HomeAssistantView):
    """GET and POST 24-hour schedule rules and fallback mode (100% identical to server/main.py)."""

    url = f"{API_BASE_PATH}/schedule"
    name = "api:epd_gateway:schedule"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        active_rule, active_mode, next_pull = coord.scheduler.get_current_rule(
            fallback_rotate_min=coord.settings_mgr.settings.rotate_interval_min
        )
        return _json_response({
            "config": coord.scheduler.config.model_dump(),
            "active_rule": active_rule.model_dump() if active_rule else None,
            "active_mode": active_mode,
            "next_pull_sec": next_pull,
        })

    async def post(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        try:
            raw_body = await request.json()
            config = ScheduleConfig.model_validate(raw_body)
        except ValidationError as exc:
            return _json_response({"detail": _format_validation_error(exc)}, status=422)
        except Exception as exc:
            return _json_response({"detail": str(exc)}, status=400)

        await coord._run_in_executor(coord.scheduler.save_config, config)
        coord.notify_listeners()
        coord.notify_gateway_for_current_state()
        return _json_response({"status": "ok", "message": "排程配置已保存"})


class EpdAlbumSlotsView(HomeAssistantView):
    """GET list of all 3 photo album slots."""

    url = f"{API_BASE_PATH}/album/slots"
    name = "api:epd_gateway:album_slots"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)
        return _json_response({"slots": coord.album_mgr.list_slots()})


class EpdAlbumSlotDetailView(HomeAssistantView):
    """POST (upload 30,000-byte binary) and DELETE for a specific photo album slot (1..3)."""

    url = f"{API_BASE_PATH}/album/slot/{{slot_id}}"
    name = "api:epd_gateway:album_slot_detail"
    requires_auth = False

    async def post(self, request: web.Request, slot_id: str) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        try:
            slot_num = int(slot_id)
        except ValueError:
            return _json_response({"detail": f"卡槽 ID 必须在 1~{TOTAL_SLOTS} 之间"}, status=422)

        if not 1 <= slot_num <= TOTAL_SLOTS:
            return _json_response({"detail": f"卡槽 ID 必须在 1~{TOTAL_SLOTS} 之间"}, status=422)

        body = await request.read()
        if len(body) != FRAME_BYTES:
            return _json_response(
                {"detail": f"点阵大小必须恰好为 {FRAME_BYTES} 字节，当前为 {len(body)} 字节"},
                status=400,
            )

        await coord._run_in_executor(coord.album_mgr.save_slot, slot_num, body)
        coord.notify_listeners()
        coord.notifier.trigger_sync_background()
        return _json_response({"status": "ok", "message": f"卡槽 {slot_num} 保存成功"})

    async def delete(self, request: web.Request, slot_id: str) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        try:
            slot_num = int(slot_id)
        except ValueError:
            return _json_response({"detail": f"卡槽 ID 必须在 1~{TOTAL_SLOTS} 之间"}, status=422)

        if not 1 <= slot_num <= TOTAL_SLOTS:
            return _json_response({"detail": f"卡槽 ID 必须在 1~{TOTAL_SLOTS} 之间"}, status=422)

        success = await coord._run_in_executor(coord.album_mgr.delete_slot, slot_num)
        if not success:
            return _json_response({"detail": "卡槽不存在或未上传"}, status=404)
        coord.notify_listeners()
        coord.notifier.trigger_sync_background()
        return _json_response({"status": "ok", "message": f"卡槽 {slot_num} 已删除"})


class EpdAlbumPreviewView(HomeAssistantView):
    """GET 400x300 PNG preview of a specific photo album slot."""

    url = f"{API_BASE_PATH}/album/preview/{{slot_id}}.png"
    name = "api:epd_gateway:album_preview"
    requires_auth = False

    async def get(self, request: web.Request, slot_id: str) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        try:
            slot_num = int(slot_id)
        except ValueError:
            return _json_response({"detail": f"卡槽 ID 必须在 1~{TOTAL_SLOTS} 之间"}, status=422)

        if not 1 <= slot_num <= TOTAL_SLOTS:
            return _json_response({"detail": f"卡槽 ID 必须在 1~{TOTAL_SLOTS} 之间"}, status=422)

        png_bytes = await coord._run_in_executor(coord.album_mgr.get_slot_png, slot_num)
        if png_bytes is None:
            return _json_response({"detail": "预览图不存在"}, status=404)
        return web.Response(
            body=png_bytes,
            status=200,
            headers={"Cache-Control": "no-store"},
            content_type="image/png",
        )


class EpdMemoPushView(HomeAssistantView):
    """POST/GET to push an instant memo and DELETE to clear active memo (100% identical to server/main.py)."""

    url = f"{API_BASE_PATH}/push"
    extra_urls = ["/api/push"]
    name = "api:epd_gateway:push"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        try:
            raw_body = await request.json()
            req = MemoRequest.model_validate(raw_body)
        except ValidationError as exc:
            return _json_response({"detail": _format_validation_error(exc)}, status=422)
        except Exception as exc:
            return _json_response({"detail": str(exc)}, status=400)

        if "duration_min" not in req.model_fields_set:
            req = MemoRequest(
                **req.model_dump(exclude={"duration_min"}),
                duration_min=coord.settings_mgr.settings.default_memo_duration_min,
            )
        state = await coord._run_in_executor(coord.activate_memo, req)
        return _json_response({
            "status": "ok",
            "message": "便签已激活，并已通知网关立即同步",
            "memo": state.model_dump(),
        })

    async def get(self, request: web.Request) -> web.Response:
        """GET push endpoint for iPhone Shortcuts / Bark style triggers."""
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        text = request.query.get("text", "")
        title = request.query.get("title", "📌 桌面备忘提醒")
        duration_raw = request.query.get("duration_min")
        sender = request.query.get("sender", "快捷指令")

        try:
            duration_min = (
                int(duration_raw)
                if duration_raw is not None
                else coord.settings_mgr.settings.default_memo_duration_min
            )
            req = MemoRequest(
                text=text,
                title=title,
                duration_min=duration_min,
                sender=sender,
            )
        except ValidationError as exc:
            return _json_response({"detail": _format_validation_error(exc)}, status=422)
        except Exception as exc:
            return _json_response({"detail": str(exc)}, status=400)

        state = await coord._run_in_executor(coord.activate_memo, req)
        return _json_response({"status": "ok", "message": "便签已推送", "memo": state.model_dump()})

    async def delete(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        await coord._run_in_executor(coord.memo_mgr.clear_memo)
        coord.notify_listeners()
        coord.notify_gateway_for_current_state()
        return _json_response({"status": "ok", "message": "便签已清除，已通知网关恢复常规排程"})


class EpdMemoStatusView(HomeAssistantView):
    """GET current active memo status."""

    url = f"{API_BASE_PATH}/memo/status"
    name = "api:epd_gateway:memo_status"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        state = coord.memo_mgr.get_state()
        data = state.model_dump()
        data["remaining_sec"] = max(0, int(state.expire_at - time.time())) if state.active else 0
        return _json_response(data)


class EpdSettingsView(HomeAssistantView):
    """GET and POST system settings (100% identical to server/main.py)."""

    url = f"{API_BASE_PATH}/settings"
    name = "api:epd_gateway:settings"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        return _json_response(coord.settings_mgr.settings.model_dump())

    async def post(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        try:
            raw_body = await request.json()
            settings = ServerSettingsUpdate.model_validate(raw_body)
        except ValidationError as exc:
            return _json_response({"detail": _format_validation_error(exc)}, status=422)
        except Exception as exc:
            return _json_response({"detail": str(exc)}, status=400)

        changes = settings.model_dump(exclude_unset=True)
        updated = await coord._run_in_executor(coord.settings_mgr.update, changes)
        coord.notifier.set_gateway_url(updated.gateway_url)
        coord.weather_mgr.default_city = updated.weather_city
        coord.weather_entity = updated.weather_entity
        coord.calendar_entity = updated.calendar_entity
        coord.indoor_temp_entity = updated.indoor_temp_entity
        coord.indoor_humidity_entity = updated.indoor_humidity_entity
        if "calendar_ical_url" in changes:
            coord.calendar_mgr.set_ical_url(updated.calendar_ical_url)
        if any(
            k in changes
            for k in (
                "weather_city",
                "rotate_interval_min",
                "calendar_ical_url",
                "weather_entity",
                "calendar_entity",
                "indoor_temp_entity",
                "indoor_humidity_entity",
            )
        ):
            coord.notify_gateway_for_current_state()

        # Sync updated settings back to Home Assistant ConfigEntry if running in HA
        hass = request.app.get("hass")
        if hass is not None and DOMAIN in hass.data:
            entry = hass.data[DOMAIN].get("entry")
            if entry is not None and hasattr(hass, "config_entries"):
                new_data = {
                    **entry.data,
                    CONF_GATEWAY_URL: updated.gateway_url,
                    CONF_WEATHER_CITY: updated.weather_city,
                    CONF_CALENDAR_ICAL_URL: updated.calendar_ical_url,
                    CONF_WEATHER_ENTITY: updated.weather_entity,
                    CONF_CALENDAR_ENTITY: updated.calendar_entity,
                    CONF_INDOOR_TEMP_ENTITY: updated.indoor_temp_entity,
                    CONF_INDOOR_HUMIDITY_ENTITY: updated.indoor_humidity_entity,
                }
                hass.config_entries.async_update_entry(entry, data=new_data)

        coord.notify_listeners()
        return _json_response({"status": "ok", "message": "系统设置已更新"})


class EpdWeatherView(HomeAssistantView):
    """GET current weather data."""

    url = f"{API_BASE_PATH}/weather"
    name = "api:epd_gateway:weather"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        city = request.query.get("city")
        data = await coord.async_get_weather_data(city_override=city, force_refresh=False)
        return _json_response(data)


class EpdWeatherRefreshView(HomeAssistantView):
    """POST to force refresh weather data."""

    url = f"{API_BASE_PATH}/weather/refresh"
    name = "api:epd_gateway:weather_refresh"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        city = request.query.get("city")
        data = await coord.async_get_weather_data(city_override=city, force_refresh=True)
        coord.notifier.trigger_sync_background()
        return _json_response({"status": "ok", "message": "天气数据已强制更新并触发网关同步", "data": data})


class EpdWeatherPreviewView(HomeAssistantView):
    """GET 400x300 PNG preview of the rendered weather screen."""

    url = f"{API_BASE_PATH}/weather/preview.png"
    name = "api:epd_gateway:weather_preview"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        city = request.query.get("city")
        w_data = await coord.async_get_weather_data(city_override=city)
        raw_bin = await coord._run_in_executor(
            render_weather_image,
            w_data,
            coord.settings_mgr.settings.screen_width,
            coord.settings_mgr.settings.screen_height,
        )
        img = await coord._run_in_executor(
            raw_to_image,
            raw_bin,
            coord.settings_mgr.settings.screen_width,
            coord.settings_mgr.settings.screen_height,
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return web.Response(
            body=buf.getvalue(),
            status=200,
            headers={"Cache-Control": "no-cache"},
            content_type="image/png",
        )


class EpdCalendarView(HomeAssistantView):
    """GET current calendar data."""

    url = f"{API_BASE_PATH}/calendar"
    name = "api:epd_gateway:calendar"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        url_param = request.query.get("url")
        data = await coord.async_get_calendar_data(force_refresh=False, custom_url=url_param)
        return _json_response(data)


class EpdCalendarRefreshView(HomeAssistantView):
    """POST to force refresh calendar data."""

    url = f"{API_BASE_PATH}/calendar/refresh"
    name = "api:epd_gateway:calendar_refresh"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        url_param = request.query.get("url")
        data = await coord.async_get_calendar_data(force_refresh=True, custom_url=url_param)
        coord.notifier.trigger_sync_background()
        return _json_response({
            "status": "ok",
            "message": data.get("message", "日历数据已刷新"),
            "data": data,
        })


class EpdCalendarPreviewView(HomeAssistantView):
    """GET 400x300 PNG preview of the rendered calendar screen."""

    url = f"{API_BASE_PATH}/calendar/preview.png"
    name = "api:epd_gateway:calendar_preview"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        url_param = request.query.get("url")
        cal_data = await coord.async_get_calendar_data(custom_url=url_param)
        raw_bin = await coord._run_in_executor(
            render_calendar_image,
            cal_data,
            coord.settings_mgr.settings.screen_width,
            coord.settings_mgr.settings.screen_height,
        )
        img = await coord._run_in_executor(
            raw_to_image,
            raw_bin,
            coord.settings_mgr.settings.screen_width,
            coord.settings_mgr.settings.screen_height,
        )
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return web.Response(
            body=buf.getvalue(),
            status=200,
            headers={"Cache-Control": "no-cache"},
            content_type="image/png",
        )


class EpdTriggerView(HomeAssistantView):
    """POST to immediately trigger ESP32 gateway sync."""

    url = f"{API_BASE_PATH}/trigger"
    name = "api:epd_gateway:trigger"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        success = await coord.notifier.trigger_sync()
        return _json_response({
            "status": "ok" if success else "failed",
            "message": "已成功向网关发送触发指令" if success else "网关连接超时或未响应",
        })


class EpdDeviceCalendarView(HomeAssistantView):
    """POST to switch the e-ink screen to nRF hardware native perpetual calendar (0x20)."""

    url = f"{API_BASE_PATH}/device/calendar"
    name = "api:epd_gateway:device_calendar"
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        coord = _get_coordinator(request)
        if coord is None:
            return _json_response({"detail": "EPD Gateway 尚未初始化"}, status=503)

        now_ts = int(time.time())
        success = await coord.notifier.trigger_calendar_mode(timestamp=now_ts, timezone=8)
        if success:
            coord._last_dispatched_mode = "clock"
            coord._last_calendar_sync_date = time.strftime("%Y-%m-%d", time.localtime(now_ts))
        return _json_response({
            "status": "ok" if success else "failed",
            "message": "已切换墨水屏至硬件原生万年历并完成时间校准" if success else "网关连接超时或墨水屏切换失败",
        })


ALL_VIEWS = [
    EpdScreenBinView,
    EpdPanelView,
    EpdStaticAssetView,
    EpdScheduleView,
    EpdAlbumSlotsView,
    EpdAlbumSlotDetailView,
    EpdAlbumPreviewView,
    EpdMemoPushView,
    EpdMemoStatusView,
    EpdSettingsView,
    EpdWeatherView,
    EpdWeatherRefreshView,
    EpdWeatherPreviewView,
    EpdCalendarView,
    EpdCalendarRefreshView,
    EpdCalendarPreviewView,
    EpdTriggerView,
    EpdDeviceCalendarView,
]


def register_http_views(hass: Any) -> None:
    """Register all HTTP views once per Home Assistant instance."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("views_registered"):
        return
    for view_cls in ALL_VIEWS:
        hass.http.register_view(view_cls())
    domain_data["views_registered"] = True

"""Constants for the EPD E-Paper Wireless Gateway integration."""

DOMAIN = "epd_gateway"

CONF_GATEWAY_URL = "gateway_url"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_CALENDAR_ENTITY = "calendar_entity"
CONF_INDOOR_TEMP_ENTITY = "indoor_temp_entity"
CONF_INDOOR_HUMIDITY_ENTITY = "indoor_humidity_entity"
CONF_WEATHER_CITY = "weather_city"
CONF_CALENDAR_ICAL_URL = "calendar_ical_url"
CONF_REGISTER_PANEL = "register_panel"

DEFAULT_GATEWAY_URL = "http://192.168.1.100"
DEFAULT_WEATHER_CITY = ""
DEFAULT_CALENDAR_ICAL_URL = ""
DEFAULT_REGISTER_PANEL = True

PANEL_URL_PATH = "epd-gateway"
PANEL_TITLE = "EPD 墨水屏"
PANEL_ICON = "mdi:tablet-dashboard"
API_BASE_PATH = "/api/epd_gateway"

DISPLAY_MODES = [
    "photo_album",
    "weather_date",
    "calendar_todo",
    "clock",
    "sleep_dnd",
]

DISPLAY_MODE_LABELS = {
    "photo_album": "🖼️ 相册轮播 (Photo Album)",
    "weather_date": "⛅ 天气与日期 (Weather & Date)",
    "calendar_todo": "📅 今日日程看板 (Calendar & Todo)",
    "clock": "📆 硬件原生万年历 (Native Perpetual Calendar)",
    "sleep_dnd": "🌙 免打扰休眠 (Sleep / DND)",
}

# Mapping from Home Assistant standard weather conditions to Chinese descriptions
# that match renderer.py's get_weather_icon_type(desc) keyword expectations.
HA_WEATHER_CONDITION_MAP = {
    "clear-night": "晴",
    "cloudy": "阴",
    "exceptional": "极端天气",
    "fog": "雾",
    "hail": "冰雹",
    "lightning": "雷电",
    "lightning-rainy": "雷阵雨",
    "partlycloudy": "多云",
    "pouring": "暴雨",
    "rainy": "小雨",
    "snowy": "雪",
    "snowy-rainy": "雨夹雪",
    "sunny": "晴",
    "windy": "大风",
    "windy-variant": "多云大风",
}

SERVICE_PUSH_MEMO = "push_memo"
SERVICE_CLEAR_MEMO = "clear_memo"
SERVICE_TRIGGER_SYNC = "trigger_sync"
SERVICE_TRIGGER_NATIVE_CALENDAR = "trigger_native_calendar"
SERVICE_SET_FALLBACK_MODE = "set_fallback_mode"

import json
import os

from .models import ServerSettings
from .persistence import atomic_write_json


class SettingsManager:
    def __init__(self, data_dir: str, default_gateway_url: str = "http://192.168.1.100"):
        os.makedirs(data_dir, exist_ok=True)
        self.settings_file = os.path.join(data_dir, "settings.json")
        self.default_gateway_url = default_gateway_url
        self.settings = self._load()

    def _load(self) -> ServerSettings:
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, "r", encoding="utf-8") as handle:
                    return ServerSettings(**json.load(handle))
            except Exception as exc:
                raise RuntimeError(f"读取 settings.json 失败: {exc}") from exc
        settings = ServerSettings(gateway_url=self.default_gateway_url)
        atomic_write_json(self.settings_file, settings.model_dump())
        return settings

    def save(self, settings: ServerSettings) -> None:
        atomic_write_json(self.settings_file, settings.model_dump())
        self.settings = settings

    def update(self, changes: dict) -> ServerSettings:
        data = self.settings.model_dump()
        data.update({k: v for k, v in changes.items() if v is not None})
        settings = ServerSettings(**data)
        self.save(settings)
        return settings

    def get_settings(self) -> dict:
        return self.settings.model_dump()

    def save_settings(self, changes: dict) -> dict:
        return self.update(changes).model_dump()

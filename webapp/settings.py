"""Configuration for both the headless server and the SDK adapter."""
from dataclasses import dataclass, fields
import json
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 4050
    custom_port: int = 4051
    custom_token: str = ""
    sdk_host: str = "127.0.0.1"
    sdk_port: int = 0
    sdk_timeout: float = 10.0
    font_name: str = ""
    log_dir: str = "./logs"
    log_level: str = "info"
    helper_executable: str = ""
    helper_lib_dir: str = ""

    def __post_init__(self):
        for key in ("port", "custom_port", "sdk_port"):
            value = getattr(self, key)
            if type(value) is not int or not 0 <= value <= 65535:
                raise ValueError(f"Invalid {key}")
        if not self.port or self.custom_port == self.port:
            raise ValueError("Main port must be nonzero and ports must differ")
        if not 0 < self.sdk_timeout <= 60:
            raise ValueError("sdk_timeout must be between 0 and 60 seconds")


def load_settings(path: str | None) -> Settings:
    if not path:
        return Settings()
    config_path = Path(path).expanduser().resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    unknown = set(data) - {item.name for item in fields(Settings)}
    if unknown:
        raise ValueError(f"Unknown configuration fields: {', '.join(sorted(unknown))}")
    for key in ("log_dir", "helper_executable", "helper_lib_dir"):
        if data.get(key):
            data[key] = str((config_path.parent / Path(data[key]).expanduser()).resolve())
    return Settings(**data)

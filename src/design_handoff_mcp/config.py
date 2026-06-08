from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    lanhu_cookie: str
    dds_cookie: str
    data_dir: Path
    http_timeout: float
    server_host: str
    server_port: int
    transport: str
    default_image_scale: str
    max_nodes_per_response: int
    debug: bool
    lanhu_base_url: str = "https://lanhuapp.com"
    dds_base_url: str = "https://dds.lanhuapp.com"

    @classmethod
    def from_env(cls) -> "Settings":
        if load_dotenv:
            load_dotenv(override=False)
        data_dir = Path(os.getenv("DATA_DIR", "./data")).expanduser()
        cookie = os.getenv("LANHU_COOKIE", "")
        return cls(
            lanhu_cookie=cookie,
            dds_cookie=os.getenv("DDS_COOKIE", cookie),
            data_dir=data_dir,
            http_timeout=float(os.getenv("HTTP_TIMEOUT", "30")),
            server_host=os.getenv("SERVER_HOST", "127.0.0.1"),
            server_port=int(os.getenv("SERVER_PORT", "8125")),
            transport=os.getenv("MCP_TRANSPORT", "http").strip().lower(),
            default_image_scale=os.getenv("DEFAULT_IMAGE_SCALE", "2x"),
            max_nodes_per_response=int(os.getenv("MAX_NODES_PER_RESPONSE", "200")),
            debug=_bool_env("DEBUG"),
        )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "packets").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "assets").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "raw").mkdir(parents=True, exist_ok=True)

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
from .lanhu_client import LanhuClient


def sanitize_filename(value: str, fallback: str = "asset") -> str:
    name = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE).strip("_")
    return name or fallback


def guess_extension(url: str, default: str = ".png") -> str:
    last = Path(urlparse(url).path).name
    if "." not in last:
        return default
    ext = "." + last.rsplit(".", 1)[-1].lower()
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        return ext
    return default


class AssetStore:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def download_packet_assets(
        self,
        packet: dict,
        client: LanhuClient,
        asset_output_dir: str | None = None,
    ) -> dict:
        base = Path(asset_output_dir).expanduser() if asset_output_dir else self._default_dir(packet)
        base.mkdir(parents=True, exist_ok=True)
        results = []

        for asset in packet.get("assets", []):
            remote_url = asset.get("remote_url")
            if not remote_url:
                asset["download_status"] = "skipped"
                continue

            ext = guess_extension(remote_url, ".png")
            filename = sanitize_filename(asset.get("file_name") or asset.get("name") or asset["id"], asset["id"])
            if not filename.endswith(ext):
                filename = f"{filename}{ext}"
            target = base / filename

            try:
                if not target.exists():
                    target.write_bytes(await client.download_bytes(remote_url))
                asset["local_path"] = str(target)
                detected_size = _image_size(target)
                if detected_size:
                    asset["size"] = detected_size
                asset["download_status"] = "downloaded"
                results.append({"id": asset["id"], "path": str(target), "status": "downloaded"})
            except Exception as exc:
                asset["download_status"] = "failed"
                asset["download_error"] = str(exc)
                packet.setdefault("warnings", []).append(
                    {
                        "node_id": None,
                        "code": "missing_asset",
                        "severity": "high",
                        "message": f"Asset download failed for {asset['id']}: {exc}",
                    }
                )
                results.append({"id": asset["id"], "status": "failed", "error": str(exc)})

        return {"asset_dir": str(base), "results": results}

    def _default_dir(self, packet: dict) -> Path:
        source = packet.get("source") or {}
        design = packet.get("design") or {}
        project = sanitize_filename(source.get("project_id") or "project")
        name = sanitize_filename(design.get("name") or source.get("design_id") or "design")
        version = sanitize_filename(source.get("version_id") or "version")
        return self.settings.data_dir / "assets" / project / name / version


def _image_size(path: Path) -> dict[str, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return {"width": int.from_bytes(data[16:20], "big"), "height": int.from_bytes(data[20:24], "big")}
    if len(data) >= 4 and data[:2] == b"\xff\xd8":
        idx = 2
        while idx + 9 < len(data):
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            idx += 2
            if marker in {0xD8, 0xD9}:
                continue
            if idx + 2 > len(data):
                break
            length = int.from_bytes(data[idx:idx + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF} and idx + 7 < len(data):
                return {
                    "height": int.from_bytes(data[idx + 3:idx + 5], "big"),
                    "width": int.from_bytes(data[idx + 5:idx + 7], "big"),
                }
            idx += length
    return None

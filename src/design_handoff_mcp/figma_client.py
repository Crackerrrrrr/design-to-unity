from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import Settings


class FigmaClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class FigmaUrl:
    raw_url: str
    file_key: str
    node_id: str | None = None
    file_type: str | None = None
    file_name: str | None = None
    version: str | None = None


def parse_figma_url(value: str) -> FigmaUrl:
    raw = value.strip()
    if not raw:
        raise ValueError("Figma URL or file key is empty")

    if "://" not in raw and "/" not in raw and "?" not in raw:
        return FigmaUrl(raw_url=raw, file_key=raw)

    parsed = urlparse(raw)
    parts = [part for part in parsed.path.split("/") if part]
    file_type = parts[0] if parts else None
    file_key = parts[1] if len(parts) >= 2 and file_type in {"file", "design", "proto", "board", "slides"} else None
    if not file_key:
        raise ValueError("Figma URL must contain a file key, for example https://www.figma.com/design/<file_key>/...")

    params = parse_qs(parsed.query, keep_blank_values=True)
    node_id = _normalize_node_id(_last_param(params, "node-id") or _last_param(params, "node_id"))
    version = _last_param(params, "version-id") or _last_param(params, "version_id") or _last_param(params, "version")
    file_name = unquote(parts[2]) if len(parts) >= 3 else None
    return FigmaUrl(
        raw_url=raw,
        file_key=file_key,
        node_id=node_id,
        file_type=file_type,
        file_name=file_name,
        version=version,
    )


def _last_param(params: dict[str, list[str]], key: str) -> str | None:
    values = params.get(key)
    return values[-1] if values else None


def _normalize_node_id(value: str | None) -> str | None:
    if not value:
        return None
    text = unquote(str(value)).strip()
    if not text:
        return None
    if ":" in text:
        return text
    if "-" in text:
        head, tail = text.split("-", 1)
        if head.isdigit() and tail:
            return f"{head}:{tail}"
    return text


class FigmaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        headers = {
            "User-Agent": "DesignToUnity/0.1",
            "Accept": "application/json",
        }
        if settings.figma_oauth_token:
            headers["Authorization"] = f"Bearer {settings.figma_oauth_token}"
        elif settings.figma_token:
            headers["X-Figma-Token"] = settings.figma_token
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=settings.http_timeout,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = path_or_url if path_or_url.startswith("http://") or path_or_url.startswith("https://") else f"{self.settings.figma_base_url}{path_or_url}"
        response = await self.client.get(url, params=params)
        if response.status_code == 403 and not (self.settings.figma_token or self.settings.figma_oauth_token):
            raise FigmaClientError("Figma API requires FIGMA_TOKEN or FIGMA_OAUTH_TOKEN.")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("err"):
            raise FigmaClientError(str(payload.get("err")))
        return payload

    async def get_file(
        self,
        file_key: str,
        version: str | None = None,
        ids: list[str] | None = None,
        depth: int | None = None,
        geometry: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if version:
            params["version"] = version
        if ids:
            params["ids"] = ",".join(ids)
        if depth:
            params["depth"] = int(depth)
        if geometry:
            params["geometry"] = geometry
        return await self._get_json(f"/v1/files/{file_key}", params)

    async def get_file_nodes(
        self,
        file_key: str,
        ids: list[str],
        version: str | None = None,
        depth: int | None = None,
        geometry: str | None = None,
    ) -> dict[str, Any]:
        if not ids:
            raise ValueError("Figma node ids are required")
        params: dict[str, Any] = {"ids": ",".join(ids)}
        if version:
            params["version"] = version
        if depth:
            params["depth"] = int(depth)
        if geometry:
            params["geometry"] = geometry
        return await self._get_json(f"/v1/files/{file_key}/nodes", params)

    async def get_image_urls(
        self,
        file_key: str,
        ids: list[str],
        scale: float = 1.0,
        fmt: str = "png",
        version: str | None = None,
        use_absolute_bounds: bool = False,
    ) -> dict[str, str | None]:
        if not ids:
            return {}
        params: dict[str, Any] = {
            "ids": ",".join(ids),
            "scale": scale,
            "format": fmt,
        }
        if version:
            params["version"] = version
        if use_absolute_bounds:
            params["use_absolute_bounds"] = "true"
        payload = await self._get_json(f"/v1/images/{file_key}", params)
        images = payload.get("images") or {}
        return {str(node_id): url for node_id, url in images.items()}

    async def get_image_fills(self, file_key: str) -> dict[str, str]:
        payload = await self._get_json(f"/v1/files/{file_key}/images")
        return {str(key): str(value) for key, value in (payload.get("images") or {}).items() if value}

    async def get_file_components(self, file_key: str) -> dict[str, Any]:
        return await self._get_json(f"/v1/files/{file_key}/components")

    async def get_file_styles(self, file_key: str) -> dict[str, Any]:
        return await self._get_json(f"/v1/files/{file_key}/styles")

    async def get_local_variables(self, file_key: str) -> dict[str, Any]:
        return await self._get_json(f"/v1/files/{file_key}/variables/local")

    async def get_published_variables(self, file_key: str) -> dict[str, Any]:
        return await self._get_json(f"/v1/files/{file_key}/variables/published")

    async def download_bytes(self, url: str) -> bytes:
        response = await self.client.get(url)
        response.raise_for_status()
        return response.content


def figma_node_id_to_asset_id(node_id: str) -> str:
    return _normalize_node_id(node_id) or node_id

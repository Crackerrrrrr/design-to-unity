from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from .config import Settings


class LanhuClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class LanhuUrl:
    raw_url: str
    team_id: str | None
    project_id: str
    image_id: str | None = None
    doc_id: str | None = None
    version_id: str | None = None


def parse_lanhu_url(value: str) -> LanhuUrl:
    raw = value.strip()
    if not raw:
        raise ValueError("Lanhu URL is empty")

    query_source = raw
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        query_source = parsed.fragment or parsed.query
        if "?" in query_source:
            query_source = query_source.split("?", 1)[1]
    elif raw.startswith("?"):
        query_source = raw[1:]

    params = {k: v[-1] for k, v in parse_qs(query_source, keep_blank_values=True).items()}
    project_id = params.get("pid") or params.get("project_id")
    if not project_id:
        raise ValueError("Lanhu URL must contain pid/project_id")

    image_id = params.get("image_id")
    doc_id = params.get("docId") or params.get("doc_id")
    return LanhuUrl(
        raw_url=raw,
        team_id=params.get("tid") or params.get("team_id"),
        project_id=project_id,
        image_id=image_id,
        doc_id=doc_id,
        version_id=params.get("versionId") or params.get("version_id"),
    )


def _ok_code(payload: dict[str, Any]) -> bool:
    return str(payload.get("code")) in {"0", "00000"}


class LanhuClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/142.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": f"{settings.lanhu_base_url}/web/",
            "Origin": settings.lanhu_base_url,
            "request-from": "web",
            "real-path": "/item/project/stage",
            "sec-ch-ua": '"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        if settings.lanhu_cookie:
            headers["Cookie"] = settings.lanhu_cookie
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=settings.http_timeout,
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def list_designs(self, url: str) -> dict[str, Any]:
        parsed = parse_lanhu_url(url)
        designs_url = f"{self.settings.lanhu_base_url}/api/project/images"
        params: dict[str, Any] = {
            "project_id": parsed.project_id,
            "dds_status": 1,
            "position": 1,
            "show_cb_src": 1,
            "comment": 1,
        }
        if parsed.team_id:
            params["team_id"] = parsed.team_id

        payload = await self._get_json(designs_url, params)
        if not _ok_code(payload):
            raise LanhuClientError(payload.get("msg") or "Failed to list Lanhu designs")

        project = payload.get("data") or payload.get("result") or {}
        sector_map = await self._load_sector_map(parsed.project_id)
        designs = []
        for index, item in enumerate(project.get("images") or [], start=1):
            design_id = item.get("id")
            sectors = sector_map.get(design_id, [])
            designs.append(
                {
                    "index": index,
                    "id": design_id,
                    "name": item.get("name") or f"Design {index}",
                    "width": item.get("width"),
                    "height": item.get("height"),
                    "url": item.get("url"),
                    "latest_version": item.get("latest_version"),
                    "updated_at": item.get("update_time"),
                    "sectors": sectors,
                }
            )

        return {
            "source": {
                "provider": "lanhu",
                "team_id": parsed.team_id,
                "project_id": parsed.project_id,
                "url": parsed.raw_url,
            },
            "project_name": project.get("name"),
            "total": len(designs),
            "designs": designs,
        }

    async def _load_sector_map(self, project_id: str) -> dict[str, list[str]]:
        url = f"{self.settings.lanhu_base_url}/api/project/project_sectors"
        try:
            payload = await self._get_json(url, {"project_id": project_id})
        except Exception:
            return {}
        if not _ok_code(payload):
            return {}
        sectors = ((payload.get("data") or {}).get("sectors")) or []
        by_image: dict[str, list[str]] = {}
        sector_names = {s.get("id"): s.get("name") for s in sectors if s.get("id")}
        for sector in sectors:
            name = sector.get("name") or sector_names.get(sector.get("id"))
            for image_id in sector.get("images") or []:
                if image_id and name:
                    by_image.setdefault(image_id, []).append(name)
        return by_image

    async def choose_design(self, url: str, design_name_or_index: str | int | None) -> tuple[LanhuUrl, dict[str, Any]]:
        parsed = parse_lanhu_url(url)
        listing = await self.list_designs(url)
        designs = listing["designs"]
        target: dict[str, Any] | None = None

        if design_name_or_index is None and parsed.image_id:
            target = next((d for d in designs if d.get("id") == parsed.image_id), None)
        elif design_name_or_index is not None:
            key = str(design_name_or_index).strip()
            if key.isdigit():
                index = int(key)
                target = next((d for d in designs if d.get("index") == index), None)
            if target is None:
                target = next((d for d in designs if d.get("name") == key), None)
            if target is None:
                matches = [d for d in designs if key and key in str(d.get("name"))]
                if len(matches) == 1:
                    target = matches[0]

        if target is None:
            available = [f"{d['index']}. {d['name']}" for d in designs[:80]]
            raise LanhuClientError("Design not found. Available designs: " + "; ".join(available))

        return parsed, target

    async def fetch_design_sources(self, parsed: LanhuUrl, design: dict[str, Any]) -> dict[str, Any]:
        version_id = design.get("latest_version") or parsed.version_id
        if not version_id:
            version_id = await self._resolve_latest_version(parsed.project_id, parsed.team_id, design["id"])

        dds_schema = None
        dds_error = None
        try:
            dds_schema = await self._fetch_dds_schema(version_id)
        except Exception as exc:
            dds_error = str(exc)

        sketch_json = None
        sketch_error = None
        try:
            sketch_json = await self._fetch_sketch_json(parsed.project_id, parsed.team_id, design["id"])
        except Exception as exc:
            sketch_error = str(exc)

        if dds_schema is None and sketch_json is None:
            raise LanhuClientError(f"Cannot fetch design schema. dds={dds_error}; sketch={sketch_error}")

        return {
            "version_id": version_id,
            "dds_schema": dds_schema,
            "dds_error": dds_error,
            "sketch_json": sketch_json,
            "sketch_error": sketch_error,
        }

    async def _resolve_latest_version(self, project_id: str, team_id: str | None, design_id: str) -> str:
        url = f"{self.settings.lanhu_base_url}/api/project/multi_info"
        params: dict[str, Any] = {"project_id": project_id, "img_limit": 500, "detach": 1}
        if team_id:
            params["team_id"] = team_id
        payload = await self._get_json(url, params)
        if not _ok_code(payload):
            raise LanhuClientError(payload.get("msg") or "Cannot resolve latest design version")
        for item in ((payload.get("result") or {}).get("images")) or []:
            if item.get("id") == design_id and item.get("latest_version"):
                return item["latest_version"]
        raise LanhuClientError(f"Cannot find latest version for design {design_id}")

    async def _fetch_dds_schema(self, version_id: str) -> dict[str, Any]:
        headers = {
            "User-Agent": "Mozilla/5.0 DesignHandoffMCP/0.1",
            "Accept": "application/json, text/plain, */*",
            "Referer": f"{self.settings.dds_base_url}/",
        }
        if self.settings.dds_cookie:
            headers["Cookie"] = self.settings.dds_cookie
        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.settings.http_timeout,
            follow_redirects=True,
        ) as client:
            endpoint = f"{self.settings.dds_base_url}/api/dds/image/store_schema_revise"
            response = await client.get(endpoint, params={"version_id": version_id})
            response.raise_for_status()
            payload = response.json()
            if not _ok_code(payload):
                raise LanhuClientError(payload.get("msg") or "DDS schema request failed")
            schema_url = ((payload.get("data") or {}).get("data_resource_url"))
            if not schema_url:
                raise LanhuClientError("DDS schema response has no data_resource_url")
            schema_response = await client.get(schema_url)
            schema_response.raise_for_status()
            return schema_response.json()

    async def _fetch_sketch_json(self, project_id: str, team_id: str | None, design_id: str) -> dict[str, Any]:
        url = f"{self.settings.lanhu_base_url}/api/project/image"
        params: dict[str, Any] = {"dds_status": 1, "project_id": project_id, "image_id": design_id}
        if team_id:
            params["team_id"] = team_id
        payload = await self._get_json(url, params)
        if not _ok_code(payload):
            raise LanhuClientError(payload.get("msg") or "Design detail request failed")
        detail = payload.get("result") or payload.get("data") or {}
        versions = detail.get("versions") or []
        json_url = versions[0].get("json_url") if versions else None
        if not json_url:
            raise LanhuClientError("Design detail has no version json_url")
        response = await self.client.get(json_url)
        response.raise_for_status()
        return response.json()

    async def download_bytes(self, url: str) -> bytes:
        headers = {"Referer": f"{self.settings.lanhu_base_url}/", "Origin": self.settings.lanhu_base_url}
        response = await self.client.get(url, headers=headers)
        response.raise_for_status()
        return response.content


def stable_hash(value: Any) -> str:
    payload = repr(value).encode("utf-8", "ignore")
    return hashlib.sha1(payload).hexdigest()

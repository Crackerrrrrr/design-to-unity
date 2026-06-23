from __future__ import annotations

import hashlib
import json
import base64
import re
from pathlib import Path
from typing import Any

from .asset_store import _image_size, sanitize_filename
from .figma_client import FigmaUrl, parse_figma_url
from .normalizer import (
    _add_semantic,
    _apply_semantics,
    _enrich_assets,
    _hash,
    _semantic_summary,
    _unity_rect,
    attach_reusable_prefab_registry,
    enrich_delivery_metadata,
)
from .profiles import build_handoff_profiles
from .psd_adapter import (
    _attach_dropdown_hints,
    _attach_input_hints,
    _attach_layout_hints,
    _attach_radio_hints,
    _attach_scroll_hints,
    _attach_slider_hints,
    _attach_tab_hints,
    _attach_text_button_hints,
    _attach_text_hints,
)


def make_figma_packet(
    payload: dict[str, Any],
    figma_url: FigmaUrl | str | None = None,
    node_name_or_index: str | int | None = None,
    rendered_image_urls: dict[str, str | None] | None = None,
    target: str = "unity",
    scale: float = 1.0,
    image_format: str = "png",
) -> dict[str, Any]:
    parsed_url = parse_figma_url(figma_url) if isinstance(figma_url, str) else figma_url
    source_node = select_figma_root(payload, parsed_url.node_id if parsed_url else None, node_name_or_index)
    file_key = (parsed_url.file_key if parsed_url else None) or str(payload.get("key") or payload.get("file_key") or "snapshot")
    file_name = str(payload.get("name") or (parsed_url.file_name if parsed_url else None) or source_node.get("name") or "FigmaDesign")
    image_urls = rendered_image_urls or {}
    warnings: list[dict[str, Any]] = []
    assets: dict[str, dict[str, Any]] = {}

    design_info = _figma_design_info(file_key, file_name, source_node, scale)
    reference_asset_ref = _register_figma_asset(
        assets=assets,
        file_key=file_key,
        node=source_node,
        name=f"{design_info['name']}_design_reference",
        rect={"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]},
        usage="design_reference",
        scale=scale,
        image_format=image_format,
        rendered_image_urls=image_urls,
    )
    design_info["reference_asset_ref"] = reference_asset_ref

    root_node = _normalize_figma_node(
        node=source_node,
        parent_id=None,
        parent_path="",
        parent_global={"x": _num((_figma_rect(source_node) or {}).get("x")), "y": _num((_figma_rect(source_node) or {}).get("y"))},
        assets=assets,
        warnings=warnings,
        design_info=design_info,
        file_key=file_key,
        rendered_image_urls=image_urls,
        scale=scale,
        image_format=image_format,
        z_counter=[1],
        parent_layout_mode=None,
        force_root=True,
    )
    root_node["id"] = "root"
    root_node["parent_id"] = None
    root_node["semantic_type"] = "screen_root"
    root_node["semantic_confidence"] = 1.0
    root_node["semantic_reasons"] = ["selected Figma frame is the packet root"]
    root_node["global_rect"] = {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]}
    root_node["local_rect"] = {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]}
    root_node["unity_rect_hint"] = _unity_rect(root_node["local_rect"])

    _attach_figma_hints(root_node, warnings)
    _enrich_assets(assets, root_node, design_info)
    enrich_delivery_metadata(root_node, design_info, assets, provider="figma")
    packet = {
        "packet_id": _packet_id(file_key, _figma_node_id(source_node), target, scale),
        "source": {
            "provider": "figma",
            "file_key": file_key,
            "file_name": file_name,
            "node_id": _figma_node_id(source_node),
            "node_name": source_node.get("name"),
            "url": parsed_url.raw_url if parsed_url else None,
            "version": parsed_url.version if parsed_url else payload.get("version"),
            "schema_source": "figma-rest-api" if parsed_url else "figma-json-snapshot",
            "image_scale": scale,
            "image_format": image_format,
        },
        "design": design_info,
        "nodes": [root_node],
        "assets": list(assets.values()),
        "semantic_map": _semantic_summary(root_node),
        "handoff_profiles": build_handoff_profiles(design_info),
        "target": target,
        "warnings": warnings,
        "asset_export": {
            "requested_node_ids": figma_asset_node_ids_from_assets(assets.values()),
            "image_scale": scale,
            "image_format": image_format,
        },
    }
    attach_figma_tokens(packet, _figma_variables_payload(payload))
    packet["asset_download"] = packet["asset_export"]
    attach_reusable_prefab_registry(packet)
    return packet


def make_figma_snapshot_packet(
    snapshot_path: str | Path,
    target: str = "unity",
    node_name_or_index: str | int | None = None,
    scale: float = 1.0,
    image_format: str = "png",
) -> dict[str, Any]:
    path = Path(snapshot_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    figma_url = parse_figma_url(str(payload.get("url"))) if payload.get("url") else None
    packet = make_figma_packet(
        payload=payload,
        figma_url=figma_url,
        node_name_or_index=node_name_or_index,
        rendered_image_urls=_snapshot_image_urls(payload),
        target=target,
        scale=scale,
        image_format=image_format,
    )
    packet["source"]["schema_source"] = "figma-json-snapshot"
    packet["source"]["snapshot_path"] = str(path)
    packet["source"]["snapshot_hash"] = _file_sha1(path)
    return packet


def make_figma_snapshot_batch_packets(
    snapshot_path: str | Path,
    target: str = "unity",
    page_name_or_index: str | int | None = None,
    target_types: list[str] | str | None = None,
    max_items: int = 50,
    scale: float = 1.0,
    image_format: str = "png",
) -> dict[str, Any]:
    path = Path(snapshot_path).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    targets = figma_import_target_listing(
        payload,
        page_name_or_index=page_name_or_index,
        target_types=target_types,
        max_items=max_items,
    )
    packets = []
    for item in targets["targets"]:
        packet = make_figma_snapshot_packet(
            path,
            target=target,
            node_name_or_index=item["index"],
            scale=scale,
            image_format=image_format,
        )
        packet["source"]["batch"] = {
            "mode": "snapshot",
            "target_index": item["index"],
            "target_id": item.get("id"),
            "target_name": item.get("name"),
            "target_type": item.get("type"),
            "page_id": item.get("page_id"),
            "page_name": item.get("page_name"),
        }
        packets.append(packet)
    return {
        "status": "success",
        "snapshot_path": str(path),
        "target_count": len(targets["targets"]),
        "targets": targets["targets"],
        "packets": packets,
    }


def make_figma_export_packet(
    export_path: str | Path,
    target: str = "unity",
    node_name_or_index: str | int | None = None,
    scale: float | None = None,
    image_format: str | None = None,
) -> dict[str, Any]:
    manifest_path = _figma_export_manifest_path(export_path)
    export_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    materialized = _materialize_embedded_export_files(manifest, export_dir)
    payload = _payload_from_export_manifest(manifest)
    figma_url = parse_figma_url(str(manifest.get("url"))) if manifest.get("url") else None
    packet = make_figma_packet(
        payload=payload,
        figma_url=figma_url,
        node_name_or_index=node_name_or_index,
        rendered_image_urls=_snapshot_image_urls(payload),
        target=target,
        scale=scale if scale is not None else _num(manifest.get("scale"), manifest.get("image_scale"), 1),
        image_format=(image_format or manifest.get("image_format") or "png").strip().lower(),
    )
    packet["source"]["schema_source"] = "figma-plugin-export"
    packet["source"]["export_path"] = str(manifest_path)
    packet["source"]["export_dir"] = str(export_dir)
    packet["source"]["manifest_hash"] = _file_sha1(manifest_path)
    packet["source"]["plugin_version"] = manifest.get("plugin_version") or manifest.get("version")
    _attach_exported_reference(packet, manifest, export_dir, materialized)
    _attach_exported_assets(packet, manifest, export_dir, materialized)
    asset_map = {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}
    _enrich_assets(asset_map, packet["nodes"][0], packet["design"])
    packet["assets"] = list(asset_map.values())
    enrich_delivery_metadata(packet["nodes"][0], packet["design"], asset_map, provider="figma")
    packet["asset_export"] = {
        "asset_dir": str(export_dir),
        "manifest_path": str(manifest_path),
        "result_count": len(packet.get("assets") or []),
        "results": [
            {"id": asset.get("id"), "path": asset.get("local_path"), "status": asset.get("download_status")}
            for asset in packet.get("assets") or []
        ],
    }
    packet["asset_download"] = packet["asset_export"]
    attach_reusable_prefab_registry(packet)
    return packet


def figma_export_schema() -> dict[str, Any]:
    return {
        "schema": "design-to-unity.figma-export",
        "schema_version": 1,
        "required": ["root or document"],
        "optional": {
            "file_key": "Figma file key.",
            "file_name": "Figma file name.",
            "url": "Original Figma URL.",
            "root": "Selected Figma node JSON from plugin export.",
            "document": "Figma REST-like document JSON.",
            "preview": "Preview file path or embedded file object.",
            "assets": "List of exported node assets. Each item needs node_id plus path or data.",
        },
        "asset_item": {
            "node_id": "Figma node id, for example 12:34.",
            "path": "Relative path under the export directory, for example assets/figma_12_34.png.",
            "file_name": "Optional file name.",
            "usage": "image, shape, text, design_reference, etc.",
            "data": "Optional base64 or data URL for single JSON exports.",
            "mime_type": "Optional MIME type, for example image/png.",
        },
        "node_fields": [
            "absoluteBoundingBox",
            "absoluteRenderBounds",
            "constraints",
            "layoutMode",
            "itemSpacing",
            "paddingLeft",
            "paddingRight",
            "paddingTop",
            "paddingBottom",
            "primaryAxisAlignItems",
            "counterAxisAlignItems",
            "primaryAxisSizingMode",
            "counterAxisSizingMode",
            "layoutGrow",
            "layoutAlign",
            "layoutPositioning",
            "layoutSizingHorizontal",
            "layoutSizingVertical",
            "fills",
            "strokes",
            "effects",
            "blendMode",
            "isMask",
            "maskType",
            "componentProperties",
            "componentPropertyDefinitions",
            "reactions",
            "styleOverrideTable",
            "characterStyleOverrides",
        ],
        "folder_shape": [
            "figma-export/design.json",
            "figma-export/preview.png",
            "figma-export/assets/<node>.png",
        ],
    }


def validate_figma_export(export_path: str | Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        manifest_path = _figma_export_manifest_path(export_path)
    except Exception as exc:
        return {"status": "error", "errors": [{"code": "manifest_missing", "message": str(exc)}], "warnings": []}
    export_dir = manifest_path.parent
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "error", "errors": [{"code": "manifest_invalid_json", "message": str(exc)}], "warnings": []}

    if not isinstance(manifest, dict):
        errors.append({"code": "manifest_not_object", "message": "Figma export manifest must be a JSON object."})
    if not (manifest.get("root") or manifest.get("document") or manifest.get("nodes")):
        errors.append({"code": "missing_figma_tree", "message": "Manifest must include root, document, or nodes."})

    preview = _export_file_entry(manifest.get("preview") or {"path": "preview.png"}, "preview.png")
    if preview and not preview.get("data"):
        preview_path = _resolve_export_file(export_dir, preview)
        if not preview_path.exists():
            warnings.append({"code": "preview_missing", "path": str(preview_path), "message": "Preview image is missing; visual diff will be unavailable until provided."})

    for index, item in enumerate(manifest.get("assets") or []):
        if not isinstance(item, dict):
            errors.append({"code": "asset_not_object", "index": index, "message": "Asset entries must be objects."})
            continue
        if not item.get("node_id"):
            errors.append({"code": "asset_missing_node_id", "index": index, "message": "Asset entry is missing node_id."})
        if not (item.get("path") or item.get("data")):
            errors.append({"code": "asset_missing_file", "index": index, "node_id": item.get("node_id"), "message": "Asset entry must include path or embedded data."})
            continue
        if item.get("path") and not _resolve_export_file(export_dir, item).exists():
            errors.append({"code": "asset_file_missing", "index": index, "node_id": item.get("node_id"), "path": str(_resolve_export_file(export_dir, item)), "message": "Exported asset file is missing."})

    return {
        "status": "error" if errors else "success",
        "schema": "design-to-unity.figma-export",
        "manifest_path": str(manifest_path),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }


def figma_frame_listing(payload: dict[str, Any]) -> dict[str, Any]:
    document = payload.get("document") or payload.get("file", {}).get("document") or payload
    pages = []
    frames = []
    for page_index, page in enumerate(document.get("children") or [], start=1):
        if page.get("type") != "CANVAS":
            continue
        page_entry = {
            "index": page_index,
            "id": page.get("id"),
            "name": page.get("name"),
            "frame_count": 0,
        }
        pages.append(page_entry)
        for frame in page.get("children") or []:
            if frame.get("type") not in {"FRAME", "COMPONENT", "COMPONENT_SET", "INSTANCE", "GROUP", "SECTION"}:
                continue
            rect = _figma_rect(frame)
            item = {
                "index": len(frames) + 1,
                "page_index": page_index,
                "page_id": page.get("id"),
                "page_name": page.get("name"),
                "id": frame.get("id"),
                "name": frame.get("name"),
                "type": frame.get("type"),
                "width": rect.get("width"),
                "height": rect.get("height"),
                "child_count": len(frame.get("children") or []),
            }
            frames.append(item)
            page_entry["frame_count"] += 1
    return {"pages": pages, "frames": frames, "total_frames": len(frames)}


def figma_page_listing(payload: dict[str, Any]) -> dict[str, Any]:
    listing = figma_frame_listing(payload)
    pages = []
    for page in listing.get("pages") or []:
        pages.append(
            {
                "index": page.get("index"),
                "id": page.get("id"),
                "name": page.get("name"),
                "frame_count": page.get("frame_count", 0),
            }
        )
    return {
        "pages": pages,
        "total_pages": len(pages),
        "total_frames": listing.get("total_frames", 0),
    }


def figma_import_target_listing(
    payload: dict[str, Any],
    page_name_or_index: str | int | None = None,
    target_types: list[str] | str | None = None,
    max_items: int = 50,
) -> dict[str, Any]:
    listing = figma_frame_listing(payload)
    target_type_set = _normalize_figma_target_types(target_types)
    page_filter = str(page_name_or_index).strip() if page_name_or_index is not None else ""
    selected = []
    for frame in listing.get("frames") or []:
        if target_type_set and str(frame.get("type") or "").upper() not in target_type_set:
            continue
        if page_filter:
            page_match = False
            if page_filter.isdigit() and int(page_filter) == int(frame.get("page_index") or -1):
                page_match = True
            if page_filter == str(frame.get("page_id") or "") or page_filter.lower() == str(frame.get("page_name") or "").lower():
                page_match = True
            if page_filter.lower() and page_filter.lower() in str(frame.get("page_name") or "").lower():
                page_match = True
            if not page_match:
                continue
        selected.append(frame)
        if len(selected) >= max(1, int(max_items)):
            break
    return {
        "pages": listing.get("pages") or [],
        "total_frames": listing.get("total_frames", 0),
        "target_types": sorted(target_type_set) if target_type_set else [],
        "page_filter": page_name_or_index,
        "target_count": len(selected),
        "targets": selected,
    }


def select_figma_root(
    payload: dict[str, Any],
    node_id: str | None = None,
    node_name_or_index: str | int | None = None,
) -> dict[str, Any]:
    if payload.get("nodes"):
        nodes_payload = payload.get("nodes") or {}
        if node_id:
            node_payload = nodes_payload.get(node_id) or nodes_payload.get(node_id.replace(":", "-"))
            if node_payload and node_payload.get("document"):
                return node_payload["document"]
        first = next(iter(nodes_payload.values()), None)
        if first and first.get("document"):
            return first["document"]

    document = payload.get("document") or payload.get("file", {}).get("document") or payload.get("root") or payload
    if node_id:
        found = _find_figma_node(document, node_id)
        if found:
            return found

    listing = figma_frame_listing({"document": document})
    frames = listing["frames"]
    if node_name_or_index is not None and frames:
        key = str(node_name_or_index).strip()
        target_id = None
        if key.isdigit():
            index = int(key)
            target_id = next((frame["id"] for frame in frames if frame["index"] == index), None)
        if target_id is None:
            exact = next((frame for frame in frames if frame["name"] == key), None)
            partial = [frame for frame in frames if key and key.lower() in str(frame["name"]).lower()]
            target_id = (exact or (partial[0] if len(partial) == 1 else None) or {}).get("id")
        if target_id:
            found = _find_figma_node(document, target_id)
            if found:
                return found

    if frames:
        found = _find_figma_node(document, frames[0]["id"])
        if found:
            return found
    if document.get("type") == "DOCUMENT" and document.get("children"):
        return document["children"][0]
    return document


def figma_asset_node_ids(packet: dict[str, Any]) -> list[str]:
    return figma_asset_node_ids_from_assets(packet.get("assets") or [])


def figma_asset_node_ids_from_assets(assets: Any) -> list[str]:
    node_ids = []
    for asset in assets:
        node_id = asset.get("source_node_id") or asset.get("figma_node_id")
        if node_id and node_id not in node_ids:
            node_ids.append(str(node_id))
    return node_ids


def figma_image_fill_refs(packet: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for asset in packet.get("assets") or []:
        image_ref = asset.get("source_image_ref")
        if image_ref and image_ref not in refs:
            refs.append(str(image_ref))
    for node in _walk_packet_nodes(packet):
        metadata = node.get("source_metadata") or {}
        for image_ref in metadata.get("image_fill_refs") or []:
            if image_ref and image_ref not in refs:
                refs.append(str(image_ref))
    return refs


def _walk_packet_nodes(packet: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    for root in packet.get("nodes") or []:
        walk(root)
    return nodes


def attach_figma_image_urls(packet: dict[str, Any], image_urls: dict[str, str | None]) -> None:
    for asset in packet.get("assets") or []:
        node_id = str(asset.get("source_node_id") or asset.get("figma_node_id") or "")
        if not node_id:
            continue
        url = image_urls.get(node_id) or image_urls.get(node_id.replace(":", "-"))
        if url:
            asset["remote_url"] = url
            asset["download_status"] = "pending"
        elif not asset.get("local_path"):
            asset["download_status"] = "missing"
    packet.setdefault("asset_export", {})["image_url_count"] = sum(1 for value in image_urls.values() if value)


def attach_figma_image_fill_urls(packet: dict[str, Any], image_fill_urls: dict[str, str | None]) -> None:
    matched = 0
    for asset in packet.get("assets") or []:
        image_ref = str(asset.get("source_image_ref") or "")
        if not image_ref:
            continue
        url = image_fill_urls.get(image_ref)
        if not url:
            continue
        matched += 1
        asset["source_image_fill_url"] = url
        asset["source_image_fill_status"] = "available"
        if not asset.get("remote_url"):
            asset["remote_url"] = url
            asset["download_status"] = "pending"
            asset["remote_url_source"] = "figma_image_fill"
    packet.setdefault("asset_export", {})["image_fill_url_count"] = sum(1 for value in image_fill_urls.values() if value)
    packet.setdefault("asset_export", {})["image_fill_url_matched_asset_count"] = matched


def attach_figma_tokens(packet: dict[str, Any], variables_payload: dict[str, Any] | None) -> None:
    token_registry = figma_token_registry(variables_payload)
    if not token_registry.get("tokens"):
        packet.setdefault("design_tokens", {"provider": "figma", "tokens": [], "collections": [], "modes": []})
        packet.setdefault(
            "token_summary",
            {
                "provider": "figma",
                "token_count": 0,
                "collection_count": 0,
                "mode_count": 0,
                "by_type": {},
            },
        )
        return
    packet["design_tokens"] = token_registry
    packet["token_summary"] = {
        "provider": "figma",
        "token_count": len(token_registry.get("tokens") or []),
        "collection_count": len(token_registry.get("collections") or []),
        "mode_count": len(token_registry.get("modes") or []),
        "by_type": token_registry.get("by_type") or {},
    }


def figma_token_registry(variables_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = variables_payload if isinstance(variables_payload, dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else payload
    variables = meta.get("variables") if isinstance(meta.get("variables"), dict) else {}
    collections = meta.get("variableCollections") if isinstance(meta.get("variableCollections"), dict) else meta.get("collections") if isinstance(meta.get("collections"), dict) else {}
    if not variables and isinstance(payload.get("variables"), dict):
        variables = payload["variables"]
    if not collections and isinstance(payload.get("variableCollections"), dict):
        collections = payload["variableCollections"]

    collection_entries = []
    mode_entries = []
    modes_by_id: dict[str, dict[str, Any]] = {}
    for collection_id, collection in collections.items():
        if not isinstance(collection, dict):
            continue
        collection_name = collection.get("name") or collection_id
        modes = collection.get("modes") if isinstance(collection.get("modes"), list) else []
        collection_entries.append(
            {
                "id": collection.get("id") or collection_id,
                "key": collection.get("key"),
                "name": collection_name,
                "default_mode_id": collection.get("defaultModeId"),
                "mode_count": len(modes),
            }
        )
        for mode in modes:
            if not isinstance(mode, dict):
                continue
            mode_entry = {
                "id": mode.get("modeId") or mode.get("id"),
                "name": mode.get("name"),
                "collection_id": collection.get("id") or collection_id,
                "collection_name": collection_name,
                "is_default": (mode.get("modeId") or mode.get("id")) == collection.get("defaultModeId"),
            }
            mode_entries.append(mode_entry)
            if mode_entry["id"]:
                modes_by_id[str(mode_entry["id"])] = mode_entry

    tokens = []
    by_type: dict[str, int] = {}
    for variable_id, variable in variables.items():
        if not isinstance(variable, dict):
            continue
        resolved_type = _figma_variable_type(variable)
        by_type[resolved_type] = by_type.get(resolved_type, 0) + 1
        values_by_mode = variable.get("valuesByMode") if isinstance(variable.get("valuesByMode"), dict) else {}
        token_modes = []
        for mode_id, raw_value in values_by_mode.items():
            token_modes.append(
                {
                    "mode_id": mode_id,
                    "mode_name": (modes_by_id.get(str(mode_id)) or {}).get("name"),
                    "value": _figma_token_value(raw_value, resolved_type),
                    "raw_value": raw_value,
                }
            )
        tokens.append(
            {
                "id": variable.get("id") or variable_id,
                "key": variable.get("key"),
                "name": variable.get("name"),
                "path": str(variable.get("name") or "").split("/"),
                "type": resolved_type,
                "resolved_type": resolved_type,
                "collection_id": variable.get("variableCollectionId"),
                "scopes": variable.get("scopes") or [],
                "remote": variable.get("remote"),
                "description": variable.get("description"),
                "values_by_mode": token_modes,
                "unity_token_hint": _unity_token_hint(variable, resolved_type),
            }
        )

    tokens.sort(key=lambda item: (str(item.get("type")), str(item.get("name"))))
    return {
        "provider": "figma",
        "schema": "design-to-unity.figma-tokens",
        "tokens": tokens,
        "collections": collection_entries,
        "modes": mode_entries,
        "by_type": by_type,
    }


def _figma_variables_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("variables", "figma_variables", "local_variables", "variable_payload"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if isinstance(meta.get("variables"), dict) or isinstance(meta.get("variableCollections"), dict):
        return {"meta": meta}
    return None


def _figma_variable_type(variable: dict[str, Any]) -> str:
    raw_type = str(variable.get("resolvedType") or variable.get("type") or "UNKNOWN").upper()
    return {
        "COLOR": "color",
        "FLOAT": "number",
        "NUMBER": "number",
        "STRING": "string",
        "BOOLEAN": "boolean",
    }.get(raw_type, raw_type.lower())


def _figma_token_value(value: Any, token_type: str) -> Any:
    if token_type == "color" and isinstance(value, dict):
        return _paint_color({"type": "SOLID", "color": value})
    if isinstance(value, dict) and value.get("type") == "VARIABLE_ALIAS":
        return {"alias": value.get("id")}
    return value


def _unity_token_hint(variable: dict[str, Any], token_type: str) -> dict[str, Any]:
    name = str(variable.get("name") or "")
    path = [part for part in name.split("/") if part]
    category = path[0].lower() if path else token_type
    hint = {
        "category": category,
        "recommended_binding": "theme_token",
        "unity_name": sanitize_filename(name.replace("/", "_") or str(variable.get("id") or "token"), "token"),
    }
    if token_type == "color":
        hint["recommended_targets"] = ["Graphic.color", "TextMeshProUGUI.color", "Selectable.colors"]
    elif token_type == "number":
        hint["recommended_targets"] = ["RectTransform.sizeDelta", "LayoutGroup.spacing", "LayoutGroup.padding", "TMP.fontSize"]
    elif token_type == "string":
        hint["recommended_targets"] = ["TextMeshProUGUI.text", "localization_key"]
    return hint


def _figma_export_manifest_path(export_path: str | Path) -> Path:
    path = Path(export_path).expanduser().resolve()
    if path.is_dir():
        for name in ("design.json", "figma-export.json", "export.json"):
            candidate = path / name
            if candidate.is_file():
                return candidate
        raise FileNotFoundError(f"Figma export directory has no design.json: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Figma export manifest not found: {path}")
    return path


def _payload_from_export_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "name": manifest.get("file_name") or manifest.get("name") or "FigmaExport",
        "key": manifest.get("file_key") or manifest.get("key") or "plugin-export",
        "url": manifest.get("url"),
        "version": manifest.get("figma_version") or manifest.get("version"),
    }
    for key in ("document", "root", "nodes", "images", "rendered_image_urls"):
        if key in manifest:
            payload[key] = manifest[key]
    if "root" not in payload and isinstance(manifest.get("selection"), dict):
        payload["root"] = manifest["selection"]
    return payload


def _materialize_embedded_export_files(manifest: dict[str, Any], export_dir: Path) -> dict[str, Path]:
    materialized: dict[str, Path] = {}
    embedded_dir = export_dir / "embedded-assets"
    preview = _export_file_entry(manifest.get("preview"), "preview.png")
    if preview and preview.get("data"):
        target = embedded_dir / (preview.get("file_name") or preview.get("path") or "preview.png")
        _write_base64_file(target, str(preview["data"]))
        materialized["preview"] = target

    for item in manifest.get("assets") or []:
        if not isinstance(item, dict) or not item.get("data"):
            continue
        node_id = str(item.get("node_id") or item.get("id") or len(materialized))
        file_name = item.get("file_name") or item.get("path") or f"{_node_id(node_id)}.png"
        target = embedded_dir / "assets" / Path(str(file_name)).name
        _write_base64_file(target, str(item["data"]))
        materialized[f"asset:{node_id}"] = target
    return materialized


def _write_base64_file(target: Path, data: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = data.split(",", 1)[1] if data.startswith("data:") and "," in data else data
    target.write_bytes(base64.b64decode(payload))


def _attach_exported_reference(
    packet: dict[str, Any],
    manifest: dict[str, Any],
    export_dir: Path,
    materialized: dict[str, Path],
) -> None:
    design = packet.get("design") or {}
    reference_ref = design.get("reference_asset_ref")
    if not reference_ref:
        return
    preview_entry = _export_file_entry(manifest.get("preview") or {"path": "preview.png"}, "preview.png")
    preview_path = materialized.get("preview") or (_resolve_export_file(export_dir, preview_entry) if preview_entry else None)
    if not preview_path or not preview_path.exists():
        return
    for asset in packet.get("assets") or []:
        if asset.get("id") != reference_ref:
            continue
        _apply_local_asset_file(asset, preview_path)
        asset["usage"] = "design_reference"
        asset["asset_role"] = "design_reference"
        break


def _attach_exported_assets(
    packet: dict[str, Any],
    manifest: dict[str, Any],
    export_dir: Path,
    materialized: dict[str, Path],
) -> None:
    nodes_by_source = {
        str((node.get("source_metadata") or {}).get("figma_node_id") or (node.get("source_metadata") or {}).get("source_node_id")): node
        for node in _walk_nodes((packet.get("nodes") or [{}])[0])
    }
    assets_by_source = {
        str(asset.get("source_node_id") or asset.get("figma_node_id")): asset
        for asset in packet.get("assets") or []
        if asset.get("source_node_id") or asset.get("figma_node_id")
    }
    for item in manifest.get("assets") or []:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("node_id") or item.get("id") or "")
        if not node_id:
            continue
        path = materialized.get(f"asset:{node_id}") or _resolve_export_file(export_dir, item)
        if not path.exists():
            continue
        asset = assets_by_source.get(node_id)
        if not asset:
            node = nodes_by_source.get(node_id)
            if not node:
                continue
            asset = _create_local_export_asset(node, item, path)
            packet.setdefault("assets", []).append(asset)
            assets_by_source[node_id] = asset
            node["asset_ref"] = asset["id"]
            if node.get("type") == "unknown":
                node["type"] = "image"
        _apply_local_asset_file(asset, path)
        asset["usage"] = item.get("usage") or asset.get("usage") or "image"
        asset["asset_role"] = asset["usage"]


def _create_local_export_asset(node: dict[str, Any], item: dict[str, Any], path: Path) -> dict[str, Any]:
    node_id = str((node.get("source_metadata") or {}).get("figma_node_id") or node.get("id"))
    raw = f"figma-export:{node_id}:{path.name}"
    asset_id = "asset_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    rect = node.get("global_rect") or {}
    return {
        "id": asset_id,
        "name": sanitize_filename(str(node.get("name") or path.stem), asset_id),
        "file_name": path.name,
        "type": "image",
        "remote_url": None,
        "local_path": str(path),
        "suggested_unity_path": f"Assets/DesignToUnity/Sprites/{path.name}",
        "format": path.suffix.lstrip(".").lower() or "png",
        "logical_size": {"width": rect.get("width"), "height": rect.get("height")},
        "scale": item.get("scale") or 1,
        "has_alpha": path.suffix.lower() in {".png", ".webp", ".svg"},
        "usage": item.get("usage") or "image",
        "asset_role": item.get("usage") or "image",
        "source_provider": "figma",
        "source_node_id": node_id,
        "figma_node_id": node_id,
        "download_status": "exported",
        "unity_import_hints": {
            "textureType": "Sprite",
            "spriteMode": "Single",
            "alphaIsTransparency": True,
            "sRGBTexture": True,
            "mipmapEnabled": False,
            "wrapMode": "Clamp",
            "filterMode": "Bilinear",
            "compression": "None",
            "pixelsPerUnit": 100,
        },
    }


def _apply_local_asset_file(asset: dict[str, Any], path: Path) -> None:
    resolved = path.expanduser().resolve()
    content_hash = _file_sha1(resolved)
    asset["local_path"] = str(resolved)
    asset["file_name"] = resolved.name
    asset["format"] = resolved.suffix.lstrip(".").lower() or asset.get("format") or "png"
    asset["download_status"] = "exported"
    asset["content_hash"] = content_hash
    asset["file_hash"] = content_hash
    size = _image_size(resolved)
    if size:
        asset["size"] = size


def _export_file_entry(value: Any, default_path: str | None = None) -> dict[str, Any] | None:
    if value is None and default_path is None:
        return None
    if isinstance(value, str):
        return {"path": value, "file_name": Path(value).name}
    if isinstance(value, dict):
        result = dict(value)
        if default_path and not (result.get("path") or result.get("file_name")):
            result["path"] = default_path
        return result
    if default_path:
        return {"path": default_path, "file_name": Path(default_path).name}
    return None


def _resolve_export_file(export_dir: Path, item: dict[str, Any] | None) -> Path:
    if not item:
        return export_dir / "__missing__"
    raw = str(item.get("path") or item.get("file_name") or "")
    path = Path(raw)
    if path.is_absolute():
        return path
    return (export_dir / path).resolve()


def _normalize_figma_node(
    node: dict[str, Any],
    parent_id: str | None,
    parent_path: str,
    parent_global: dict[str, float],
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
    design_info: dict[str, Any],
    file_key: str,
    rendered_image_urls: dict[str, str | None],
    scale: float,
    image_format: str,
    z_counter: list[int],
    parent_layout_mode: str | None = None,
    force_root: bool = False,
) -> dict[str, Any]:
    figma_id = _figma_node_id(node)
    raw_name = str(node.get("name") or node.get("type") or "node")
    node_id = "root" if force_root else _node_id(figma_id)
    path = raw_name if not parent_path else f"{parent_path}/{raw_name}"
    global_rect = _figma_rect(node)
    if force_root:
        global_rect = {"x": parent_global.get("x", 0), "y": parent_global.get("y", 0), "width": global_rect["width"], "height": global_rect["height"]}
    local_rect = {
        "x": round(global_rect["x"] - parent_global.get("x", 0), 1),
        "y": round(global_rect["y"] - parent_global.get("y", 0), 1),
        "width": global_rect["width"],
        "height": global_rect["height"],
    }
    node_type = _node_type(node)
    text = _text_info(node)
    if text:
        node_type = "text"
    z_index = z_counter[0]
    z_counter[0] += 1

    asset_ref = None
    if _should_export_node(node, node_type):
        asset_ref = _register_figma_asset(
            assets=assets,
            file_key=file_key,
            node=node,
            name=raw_name,
            rect=global_rect,
            usage=node_type if node_type in {"image", "shape", "text"} else "image",
            scale=scale,
            image_format=image_format,
            rendered_image_urls=rendered_image_urls,
        )
        if node_type == "unknown":
            node_type = "image"

    result = {
        "id": node_id,
        "parent_id": parent_id,
        "name": raw_name,
        "unity_name_hint": _unity_name(z_index, raw_name),
        "path": path,
        "type": node_type,
        "semantic_type": None,
        "semantic_confidence": None,
        "semantic_reasons": [],
        "visible": node.get("visible") is not False,
        "z_index": z_index,
        "global_rect": global_rect,
        "local_rect": local_rect,
        "unity_rect_hint": _unity_rect(local_rect),
        "style": _style_info(node),
        "text": text,
        "asset_ref": asset_ref,
        "children": [],
        "source_metadata": _source_metadata(node, file_key),
    }
    _attach_figma_feature_warnings(result, warnings)
    _apply_semantics(result, design_info)
    _apply_figma_semantics(result, node, design_info)
    _apply_figma_manual_semantics(result, node)
    _attach_figma_component_variant_hints(result, node)
    _attach_figma_prototype_hints(result, node)
    _attach_auto_layout_hint(result, node)
    _attach_layout_element_hint(result, node, parent_layout_mode)
    _attach_anchor_hint(result, node, parent_global)

    child_parent_global = global_rect
    child_parent_layout_mode = str(node.get("layoutMode") or "").upper() or None
    for child in node.get("children") or []:
        child_node = _normalize_figma_node(
            node=child,
            parent_id=result["id"],
            parent_path=path,
            parent_global=child_parent_global,
            assets=assets,
            warnings=warnings,
            design_info=design_info,
            file_key=file_key,
            rendered_image_urls=rendered_image_urls,
            scale=scale,
            image_format=image_format,
            z_counter=z_counter,
            parent_layout_mode=child_parent_layout_mode,
        )
        result["children"].append(child_node)

    if result["type"] == "unknown" and result["children"]:
        result["type"] = "group"
    result["content_hash"] = _hash(
        {
            "rect": global_rect,
            "style": result["style"],
            "text": text,
            "asset_ref": asset_ref,
            "figma_type": node.get("type"),
            "component_id": node.get("componentId"),
            "component_properties": node.get("componentProperties"),
            "children": [child.get("content_hash") for child in result["children"]],
        }
    )
    return result


def _attach_figma_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    _attach_text_hints(root, warnings)
    _attach_text_button_hints(root, warnings)
    _attach_slider_hints(root, warnings)
    _attach_scroll_hints(root, warnings)
    _attach_input_hints(root, warnings)
    _attach_dropdown_hints(root, warnings)
    _attach_tab_hints(root, warnings)
    _attach_radio_hints(root, warnings)
    for node in _walk_nodes(root):
        metadata = node.get("source_metadata") or {}
        if metadata.get("clips_content") and node.get("semantic_type") in {"mask_candidate", "scroll_viewport_candidate"}:
            node["unity_mask_hint"] = {
                "can_add_rect_mask_2d": True,
                "recommended_unity_component": "RectMask2D",
                "requires_review": False,
                "source": "figma_clips_content",
            }
        if node.get("figma_interaction_hint"):
            interaction = node.setdefault("unity_interaction_hint", {})
            interaction.setdefault("raycast_target_if_interactive", True)
            interaction["has_figma_prototype"] = True
            interaction["prototype_actions"] = (node.get("figma_interaction_hint") or {}).get("actions") or []
            interaction["navigation_event"] = node.get("unity_navigation_hint")
            if node.get("semantic_type") == "button_candidate":
                interaction.setdefault("can_add_button", True)
                interaction.setdefault("default_add_button", True)
            interaction.setdefault(
                "notes",
                [
                    "Figma prototype interaction is preserved as a navigation/event hint.",
                    "Bind project-specific scene/page routing or callbacks in Unity after import.",
                ],
            )


def _apply_figma_semantics(result: dict[str, Any], node: dict[str, Any], design_info: dict[str, Any]) -> None:
    name = " ".join(str(part or "") for part in (node.get("name"), node.get("type"), _component_property_text(node))).lower()
    figma_type = str(node.get("type") or "").upper()
    layout_mode = str(node.get("layoutMode") or "").upper()
    clips_content = bool(node.get("clipsContent"))
    is_text_node = result.get("type") == "text" or figma_type == "TEXT"
    is_component_shell = bool(result.get("children")) or figma_type in {"INSTANCE", "COMPONENT", "COMPONENT_SET"}
    is_named_part = _has_any(
        name,
        (
            "label",
            "text",
            "caption",
            "title",
            "track",
            "fill",
            "filled",
            "handle",
            "thumb",
            "knob",
            "background",
            "bg",
            "icon",
            "mark",
            "checkmark",
            "勾",
            "文本",
            "标签",
            "图标",
            "背景",
        ),
    ) and not is_component_shell
    can_infer_control = not is_text_node and not is_named_part
    rect = result.get("global_rect") or {}
    width = _num(rect.get("width"))
    height = _num(rect.get("height"))
    area = width * height
    screen_area = max(1.0, _num(design_info.get("width")) * _num(design_info.get("height")))
    area_ratio = area / screen_area

    if figma_type == "INSTANCE":
        _add_semantic_to_node(result, "component_instance_candidate", 0.8, ["Figma node is an INSTANCE"])
    if figma_type == "COMPONENT":
        _add_semantic_to_node(result, "component_definition_candidate", 0.84, ["Figma node is a COMPONENT"])
    if can_infer_control and _has_any(name, ("button", "btn", "按钮")):
        _add_semantic_to_node(result, "button_candidate", 0.94, ["Figma name/component indicates button"])
    if can_infer_control and _has_any(name, ("slider", "progress", "进度", "滑块")):
        _add_semantic_to_node(result, "slider_candidate" if "slider" in name or "滑块" in name else "progress_candidate", 0.9, ["Figma name/component indicates slider/progress"])
    if can_infer_control and _has_any(name, ("toggle", "switch", "checkbox", "check", "开关", "复选")):
        _add_semantic_to_node(result, "toggle_candidate", 0.88, ["Figma name/component indicates toggle"])
    if can_infer_control and _has_any(name, ("tab", "nav", "页签", "标签")) and result.get("children"):
        _add_semantic_to_node(result, "tab_group_candidate", 0.82, ["Figma name/component indicates tab group"])
    elif can_infer_control and _has_any(name, ("tab", "nav", "页签", "标签")):
        _add_semantic_to_node(result, "tab_candidate", 0.82, ["Figma name/component indicates tab item"])
    if can_infer_control and _has_any(name, ("radio", "choice", "option", "单选")) and result.get("children"):
        _add_semantic_to_node(result, "radio_group_candidate", 0.82, ["Figma name/component indicates radio group"])
    elif can_infer_control and _has_any(name, ("radio", "choice", "option", "单选")):
        _add_semantic_to_node(result, "radio_candidate", 0.82, ["Figma name/component indicates radio item"])
    if can_infer_control and _has_any(name, ("input", "textfield", "text field", "field", "输入")):
        _add_semantic_to_node(result, "input_candidate", 0.88, ["Figma name/component indicates input field"])
    if can_infer_control and _has_any(name, ("dropdown", "select", "picker", "下拉", "选择器")):
        _add_semantic_to_node(result, "dropdown_candidate", 0.88, ["Figma name/component indicates dropdown"])
    if clips_content and (_has_any(name, ("scroll", "list", "viewport", "滚动", "列表")) or result.get("children")):
        _add_semantic_to_node(result, "scroll_area_candidate", 0.82, ["Figma node clips content and looks scrollable"])
    elif clips_content:
        _add_semantic_to_node(result, "mask_candidate", 0.76, ["Figma node clips content"])
    if layout_mode in {"VERTICAL", "HORIZONTAL"} and _has_any(name, ("list", "item", "cell", "列表")):
        _add_semantic_to_node(result, "list_item_candidate", 0.74, ["Figma auto layout/name indicates list item"])
    if area_ratio >= 0.72 and result.get("parent_id") == "root":
        _add_semantic_to_node(result, "background_candidate", 0.65, ["large top-level Figma node may be a background"])


def _apply_figma_manual_semantics(result: dict[str, Any], node: dict[str, Any]) -> None:
    tags = _figma_manual_tags(node)
    if not tags:
        return
    metadata = result.setdefault("source_metadata", {})
    metadata["manual_tags"] = tags
    manual_map = {
        "button": "button_candidate",
        "btn": "button_candidate",
        "slider": "slider_candidate",
        "progress": "progress_candidate",
        "toggle": "toggle_candidate",
        "switch": "toggle_candidate",
        "tab": "tab_candidate",
        "radio": "radio_candidate",
        "input": "input_candidate",
        "textfield": "input_candidate",
        "dropdown": "dropdown_candidate",
        "select": "dropdown_candidate",
        "scroll": "scroll_area_candidate",
        "scrollview": "scroll_area_candidate",
        "scrollbar": "scrollbar_candidate",
        "mask": "mask_candidate",
        "listitem": "list_item_candidate",
        "list-item": "list_item_candidate",
        "prefab": "manual_prefab_candidate",
    }
    normalized = [tag.lower() for tag in tags]
    if "ignore" in normalized:
        result["semantic_type"] = "ignored_by_designer"
        result["semantic_confidence"] = 1.0
        result["semantic_reasons"] = ["Explicit Figma manual tag @ignore"]
        result["requires_semantic_review"] = False
        result["unity_ignore"] = {
            "enabled": True,
            "source": "figma_manual_tag",
            "tags": tags,
        }
        result["semantic_candidates"] = [
            {
                "semantic_type": "ignored_by_designer",
                "confidence": 1.0,
                "reasons": ["Explicit Figma manual tag @ignore"],
            }
        ]
        return

    for tag in normalized:
        semantic_type = manual_map.get(tag)
        if semantic_type:
            result["semantic_type"] = semantic_type
            result["semantic_confidence"] = 1.0
            result["semantic_reasons"] = [f"Explicit Figma manual tag @{tag}"]
            result["requires_semantic_review"] = False
            result["semantic_candidates"] = [
                {
                    "semantic_type": semantic_type,
                    "confidence": 1.0,
                    "reasons": [f"Explicit Figma manual tag @{tag}"],
                }
            ]
            return


def _attach_figma_component_variant_hints(result: dict[str, Any], node: dict[str, Any]) -> None:
    figma_type = str(node.get("type") or "").upper()
    variant_properties = _figma_variant_properties(node)
    component_id = node.get("componentId")
    component_property_definitions = node.get("componentPropertyDefinitions")

    metadata = result.setdefault("source_metadata", {})
    if variant_properties:
        metadata["variant_properties"] = variant_properties
    if component_property_definitions:
        metadata["component_property_definitions"] = component_property_definitions

    if figma_type == "COMPONENT_SET":
        axes = _figma_variant_axes_from_definitions(component_property_definitions)
        result["variant_group_hint"] = {
            "provider": "figma",
            "component_set_id": _figma_node_id(node),
            "component_set_name": node.get("name"),
            "variant_axes": axes,
            "unity_strategy": "prefab_variants_or_state_overrides",
            "requires_editor_importer": True,
            "source": "figma_component_set",
        }
        metadata["component_set_id"] = _figma_node_id(node)
        metadata["variant_axes"] = axes

    if figma_type in {"COMPONENT", "INSTANCE"} or variant_properties:
        result["component_variant_hint"] = {
            "provider": "figma",
            "node_role": "instance" if figma_type == "INSTANCE" else "definition" if figma_type == "COMPONENT" else "unknown",
            "component_id": component_id,
            "component_name": node.get("name"),
            "variant_properties": variant_properties,
            "variant_override_fields": [f"figma.variant.{key}" for key in sorted(variant_properties)],
            "unity_strategy": "instance_overrides",
            "requires_editor_importer": bool(variant_properties),
            "source": "figma_component_properties",
        }


def _attach_figma_prototype_hints(result: dict[str, Any], node: dict[str, Any]) -> None:
    reactions = _figma_reactions(node)
    if not reactions:
        return
    source_actions = []
    unity_actions = []
    for index, reaction in enumerate(reactions):
        trigger = reaction.get("trigger") if isinstance(reaction.get("trigger"), dict) else {}
        actions = reaction.get("actions")
        if not isinstance(actions, list):
            single_action = reaction.get("action")
            actions = [single_action] if isinstance(single_action, dict) else []
        if not actions:
            actions = [{}]
        for action in actions:
            if not isinstance(action, dict):
                continue
            normalized = _figma_reaction_action(index, trigger, action)
            source_actions.append(normalized)
            unity_actions.append(_unity_navigation_action(normalized))
    if not source_actions:
        return

    result["figma_interaction_hint"] = {
        "provider": "figma",
        "reaction_count": len(reactions),
        "action_count": len(source_actions),
        "default_trigger": source_actions[0].get("trigger_type"),
        "actions": source_actions,
        "requires_review": any(action.get("requires_review") for action in source_actions),
        "source": "figma_reactions",
    }
    result["unity_navigation_hint"] = {
        "can_bind_navigation_event": True,
        "recommended_event": _unity_event_for_semantic(result.get("semantic_type")),
        "actions": unity_actions,
        "requires_business_binding": True,
        "requires_review": any(action.get("requires_review") for action in unity_actions),
        "source": "figma_reactions",
    }


def _attach_auto_layout_hint(result: dict[str, Any], node: dict[str, Any]) -> None:
    layout_mode = str(node.get("layoutMode") or "").upper()
    if layout_mode not in {"VERTICAL", "HORIZONTAL"}:
        return
    spacing = _num(node.get("itemSpacing"))
    primary_align = str(node.get("primaryAxisAlignItems") or "").upper()
    counter_align = str(node.get("counterAxisAlignItems") or "").upper()
    child_alignment = _unity_child_alignment(layout_mode, primary_align, counter_align)
    result["unity_layout_hint"] = {
        "can_add_layout_group": True,
        "default_add_layout_group": True,
        "component": "VerticalLayoutGroup" if layout_mode == "VERTICAL" else "HorizontalLayoutGroup",
        "direction": layout_mode.lower(),
        "child_alignment": child_alignment["name"],
        "child_alignment_enum": child_alignment["enum"],
        "spacing": {
            "x": spacing if layout_mode == "HORIZONTAL" else 0,
            "y": spacing if layout_mode == "VERTICAL" else 0,
        },
        "padding": {
            "left": _num(node.get("paddingLeft")),
            "right": _num(node.get("paddingRight")),
            "top": _num(node.get("paddingTop")),
            "bottom": _num(node.get("paddingBottom")),
        },
        "child_control_width": True,
        "child_control_height": True,
        "child_force_expand_width": str(node.get("primaryAxisSizingMode") or "").upper() == "AUTO" and layout_mode == "HORIZONTAL",
        "child_force_expand_height": str(node.get("primaryAxisSizingMode") or "").upper() == "AUTO" and layout_mode == "VERTICAL",
        "requires_review": False,
        "source": "figma_auto_layout",
        "figma": {
            "layoutMode": layout_mode,
            "primaryAxisAlignItems": node.get("primaryAxisAlignItems"),
            "counterAxisAlignItems": node.get("counterAxisAlignItems"),
            "primaryAxisSizingMode": node.get("primaryAxisSizingMode"),
            "counterAxisSizingMode": node.get("counterAxisSizingMode"),
        },
    }


def _unity_child_alignment(layout_mode: str, primary: str, counter: str) -> dict[str, Any]:
    vertical_part = _unity_vertical_alignment(primary if layout_mode == "VERTICAL" else counter)
    horizontal_part = _unity_horizontal_alignment(counter if layout_mode == "VERTICAL" else primary)
    name = f"{vertical_part}{horizontal_part}"
    enum_map = {
        "UpperLeft": 0,
        "UpperCenter": 1,
        "UpperRight": 2,
        "MiddleLeft": 3,
        "MiddleCenter": 4,
        "MiddleRight": 5,
        "LowerLeft": 6,
        "LowerCenter": 7,
        "LowerRight": 8,
    }
    return {"name": name, "enum": enum_map.get(name, 0)}


def _unity_horizontal_alignment(value: str) -> str:
    if value in {"MAX", "END"}:
        return "Right"
    if value in {"CENTER", "SPACE_BETWEEN"}:
        return "Center"
    return "Left"


def _unity_vertical_alignment(value: str) -> str:
    if value in {"MAX", "END"}:
        return "Lower"
    if value in {"CENTER", "SPACE_BETWEEN"}:
        return "Middle"
    return "Upper"


def _attach_layout_element_hint(result: dict[str, Any], node: dict[str, Any], parent_layout_mode: str | None) -> None:
    layout_align = str(node.get("layoutAlign") or "").upper()
    layout_positioning = str(node.get("layoutPositioning") or "").upper()
    horizontal_sizing = str(node.get("layoutSizingHorizontal") or node.get("layoutSizingX") or "").upper()
    vertical_sizing = str(node.get("layoutSizingVertical") or node.get("layoutSizingY") or "").upper()
    layout_grow = _num(node.get("layoutGrow"))
    has_explicit_field = any(
        value not in {"", "INHERIT", "AUTO", "0"}
        for value in (
            layout_align,
            layout_positioning,
            horizontal_sizing,
            vertical_sizing,
            str(node.get("layoutGrow") if node.get("layoutGrow") is not None else ""),
        )
    )
    if not parent_layout_mode and not has_explicit_field:
        return
    if not any((layout_align, layout_positioning, horizontal_sizing, vertical_sizing, layout_grow)):
        return

    rect = result.get("local_rect") or {}
    preferred_width = max(0.0, _num(rect.get("width")))
    preferred_height = max(0.0, _num(rect.get("height")))
    ignore_layout = layout_positioning == "ABSOLUTE"
    flexible_width = -1.0
    flexible_height = -1.0

    if not ignore_layout:
        if parent_layout_mode == "HORIZONTAL":
            if layout_grow > 0 or horizontal_sizing == "FILL":
                flexible_width = max(1.0, layout_grow)
            if layout_align == "STRETCH" or vertical_sizing == "FILL":
                flexible_height = 1.0
        elif parent_layout_mode == "VERTICAL":
            if layout_grow > 0 or vertical_sizing == "FILL":
                flexible_height = max(1.0, layout_grow)
            if layout_align == "STRETCH" or horizontal_sizing == "FILL":
                flexible_width = 1.0
        else:
            if horizontal_sizing == "FILL":
                flexible_width = max(1.0, layout_grow)
            if vertical_sizing == "FILL":
                flexible_height = max(1.0, layout_grow)

    if not ignore_layout and flexible_width < 0 and flexible_height < 0 and layout_align not in {"STRETCH"}:
        return

    hint = {
        "can_add_layout_element": True,
        "default_add_layout_element": True,
        "ignore_layout": ignore_layout,
        "min_width": -1,
        "min_height": -1,
        "preferred_width": preferred_width,
        "preferred_height": preferred_height,
        "flexible_width": flexible_width,
        "flexible_height": flexible_height,
        "layout_priority": 1,
        "layout_align": layout_align or None,
        "layout_grow": layout_grow,
        "layout_positioning": layout_positioning or None,
        "layout_sizing_horizontal": horizontal_sizing or None,
        "layout_sizing_vertical": vertical_sizing or None,
        "parent_layout_mode": parent_layout_mode,
        "source": "figma_auto_layout_child",
        "requires_review": False,
    }
    result["unity_layout_element_hint"] = {key: value for key, value in hint.items() if value is not None}


def _attach_anchor_hint(result: dict[str, Any], node: dict[str, Any], parent_rect: dict[str, Any]) -> None:
    constraints = node.get("constraints")
    if not isinstance(constraints, dict):
        return
    horizontal = str(constraints.get("horizontal") or "").upper()
    vertical = str(constraints.get("vertical") or "").upper()
    anchor_hint = _unity_anchor_from_figma_constraints(result.get("local_rect") or {}, parent_rect, horizontal, vertical)
    result["unity_anchor_hint"] = {
        "horizontal": horizontal,
        "vertical": vertical,
        "anchor_mode": _anchor_mode(horizontal, vertical),
        "requires_review": horizontal == "SCALE" or vertical == "SCALE",
        "source": "figma_constraints",
        **anchor_hint,
    }


def _anchor_mode(horizontal: str, vertical: str) -> str:
    h = {
        "LEFT": "left",
        "RIGHT": "right",
        "LEFT_RIGHT": "horizontal_stretch",
        "CENTER": "center_x",
        "SCALE": "scale_x",
    }.get(horizontal, "left")
    v = {
        "TOP": "top",
        "BOTTOM": "bottom",
        "TOP_BOTTOM": "vertical_stretch",
        "CENTER": "center_y",
        "SCALE": "scale_y",
    }.get(vertical, "top")
    return f"{h}_{v}"


def _unity_anchor_from_figma_constraints(
    local_rect: dict[str, Any],
    parent_rect: dict[str, Any],
    horizontal: str,
    vertical: str,
) -> dict[str, Any]:
    x = _num(local_rect.get("x"))
    y = _num(local_rect.get("y"))
    width = max(0.0, _num(local_rect.get("width")))
    height = max(0.0, _num(local_rect.get("height")))
    parent_width = _num(parent_rect.get("width"))
    parent_height = _num(parent_rect.get("height"))
    if parent_width <= 0 or parent_height <= 0:
        return {
            "anchorMin": [0, 1],
            "anchorMax": [0, 1],
            "pivot": [0, 1],
            "anchoredPosition": [x, -y],
            "sizeDelta": [width, height],
            "parent_size": {"width": parent_width, "height": parent_height},
            "fallback": "top_left_no_parent_size",
        }

    left = x
    right = parent_width - x - width
    top = y
    bottom = parent_height - y - height

    if horizontal == "RIGHT":
        anchor_min_x = anchor_max_x = 1.0
        pivot_x = 1.0
        anchored_x = -right
        size_x = width
    elif horizontal == "CENTER":
        anchor_min_x = anchor_max_x = 0.5
        pivot_x = 0.5
        anchored_x = (x + width / 2.0) - parent_width / 2.0
        size_x = width
    elif horizontal == "LEFT_RIGHT":
        anchor_min_x = 0.0
        anchor_max_x = 1.0
        pivot_x = 0.5
        anchored_x = (left - right) / 2.0
        size_x = -(left + right)
    elif horizontal == "SCALE":
        anchor_min_x = _ratio(left, parent_width)
        anchor_max_x = _ratio(left + width, parent_width)
        pivot_x = 0.5
        anchored_x = 0.0
        size_x = 0.0
    else:
        anchor_min_x = anchor_max_x = 0.0
        pivot_x = 0.0
        anchored_x = left
        size_x = width

    if vertical == "BOTTOM":
        anchor_min_y = anchor_max_y = 0.0
        pivot_y = 0.0
        anchored_y = bottom
        size_y = height
    elif vertical == "CENTER":
        anchor_min_y = anchor_max_y = 0.5
        pivot_y = 0.5
        anchored_y = parent_height / 2.0 - (y + height / 2.0)
        size_y = height
    elif vertical == "TOP_BOTTOM":
        anchor_min_y = 0.0
        anchor_max_y = 1.0
        pivot_y = 0.5
        anchored_y = (bottom - top) / 2.0
        size_y = -(top + bottom)
    elif vertical == "SCALE":
        anchor_min_y = _ratio(bottom, parent_height)
        anchor_max_y = _ratio(parent_height - top, parent_height)
        pivot_y = 0.5
        anchored_y = 0.0
        size_y = 0.0
    else:
        anchor_min_y = anchor_max_y = 1.0
        pivot_y = 1.0
        anchored_y = -top
        size_y = height

    return {
        "anchorMin": [_round_anchor(anchor_min_x), _round_anchor(anchor_min_y)],
        "anchorMax": [_round_anchor(anchor_max_x), _round_anchor(anchor_max_y)],
        "pivot": [_round_anchor(pivot_x), _round_anchor(pivot_y)],
        "anchoredPosition": [round(anchored_x, 3), round(anchored_y, 3)],
        "sizeDelta": [round(size_x, 3), round(size_y, 3)],
        "insets": {
            "left": round(left, 3),
            "right": round(right, 3),
            "top": round(top, 3),
            "bottom": round(bottom, 3),
        },
        "parent_size": {"width": round(parent_width, 3), "height": round(parent_height, 3)},
    }


def _ratio(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(1.0, value / total))


def _round_anchor(value: float) -> float:
    rounded = round(value, 6)
    if abs(rounded) < 0.000001:
        return 0.0
    if abs(rounded - 1.0) < 0.000001:
        return 1.0
    return rounded


def _figma_design_info(file_key: str, file_name: str, node: dict[str, Any], scale: float) -> dict[str, Any]:
    rect = _figma_rect(node)
    return {
        "name": node.get("name") or file_name or "FigmaDesign",
        "width": rect["width"],
        "height": rect["height"],
        "scale": scale,
        "unit": "px",
        "coordinate_system": "top-left",
        "figma_file_key": file_key,
        "figma_node_id": _figma_node_id(node),
        "source_image_url": None,
    }


def _register_figma_asset(
    assets: dict[str, dict[str, Any]],
    file_key: str,
    node: dict[str, Any],
    name: str,
    rect: dict[str, float],
    usage: str,
    scale: float,
    image_format: str,
    rendered_image_urls: dict[str, str | None],
) -> str:
    figma_id = _figma_node_id(node)
    image_fill = _first_image_fill(node)
    image_ref = _figma_image_ref(image_fill)
    raw = f"figma:{file_key}:{figma_id}:{usage}:{scale}:{image_format}"
    asset_id = "asset_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    if asset_id not in assets:
        safe = sanitize_filename(name, asset_id)
        file_stem = f"{safe}_{asset_id.removeprefix('asset_')[:8]}"
        remote_url = rendered_image_urls.get(figma_id) or rendered_image_urls.get(figma_id.replace(":", "-"))
        assets[asset_id] = {
            "id": asset_id,
            "name": safe,
            "file_name": f"{file_stem}.{image_format}",
            "type": "image",
            "remote_url": remote_url,
            "local_path": None,
            "suggested_unity_path": f"Assets/DesignToUnity/Sprites/{file_stem}.{image_format}",
            "format": image_format,
            "size": None,
            "logical_size": {"width": rect["width"], "height": rect["height"]},
            "scale": scale,
            "has_alpha": image_format.lower() in {"png", "webp", "svg"},
            "usage": usage,
            "asset_role": usage,
            "download_status": "pending" if remote_url else "missing",
            "source_provider": "figma",
            "source_node_id": figma_id,
            "figma_node_id": figma_id,
            "source_image_ref": image_ref,
            "image_fill": _figma_image_fill_info(image_fill),
            "asset_key": f"figma:image_ref:{image_ref}" if image_ref else f"figma:node:{figma_id}:{usage}",
            "unity_import_hints": {
                "textureType": "Sprite",
                "spriteMode": "Single",
                "alphaIsTransparency": True,
                "sRGBTexture": True,
                "mipmapEnabled": False,
                "wrapMode": "Clamp",
                "filterMode": "Bilinear",
                "compression": "None",
                "pixelsPerUnit": 100,
            },
        }
    return asset_id


def _should_export_node(node: dict[str, Any], node_type: str) -> bool:
    figma_type = str(node.get("type") or "").upper()
    if node.get("visible") is False:
        return False
    if node_type == "text":
        return False
    if _has_image_fill(node):
        return True
    if figma_type in {"VECTOR", "BOOLEAN_OPERATION", "STAR", "POLYGON", "LINE"}:
        return True
    if _has_complex_effects(node):
        return figma_type not in {"FRAME", "GROUP", "COMPONENT", "INSTANCE"}
    if figma_type == "INSTANCE" and not node.get("children"):
        return True
    return False


def _node_type(node: dict[str, Any]) -> str:
    figma_type = str(node.get("type") or "").upper()
    if figma_type == "TEXT":
        return "text"
    if figma_type in {"FRAME", "GROUP", "COMPONENT", "INSTANCE", "COMPONENT_SET", "SECTION", "CANVAS", "DOCUMENT"}:
        return "group"
    if figma_type in {"RECTANGLE", "ELLIPSE", "LINE", "POLYGON", "STAR"}:
        return "shape"
    if figma_type in {"VECTOR", "BOOLEAN_OPERATION"}:
        return "image"
    if node.get("children"):
        return "group"
    return "unknown"


def _figma_rect(node: dict[str, Any]) -> dict[str, float]:
    rect = node.get("absoluteBoundingBox") or node.get("absoluteRenderBounds") or node.get("bounds") or {}
    if not rect and node.get("children"):
        child_rects = [_figma_rect(child) for child in node.get("children") or []]
        return _union_rect(child_rects)
    return {
        "x": round(_num(rect.get("x")), 1),
        "y": round(_num(rect.get("y")), 1),
        "width": round(max(0, _num(rect.get("width"))), 1),
        "height": round(max(0, _num(rect.get("height"))), 1),
    }


def _union_rect(rects: list[dict[str, float]]) -> dict[str, float]:
    valid = [rect for rect in rects if rect.get("width", 0) > 0 and rect.get("height", 0) > 0]
    if not valid:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    left = min(rect["x"] for rect in valid)
    top = min(rect["y"] for rect in valid)
    right = max(rect["x"] + rect["width"] for rect in valid)
    bottom = max(rect["y"] + rect["height"] for rect in valid)
    return {"x": round(left, 1), "y": round(top, 1), "width": round(right - left, 1), "height": round(bottom - top, 1)}


def _style_info(node: dict[str, Any]) -> dict[str, Any]:
    fill = _first_visible_fill(node)
    image_fill = _first_image_fill(node)
    stroke = _first_visible_stroke(node)
    result = {
        "opacity": _num(node.get("opacity"), 1),
        "fill_color": _paint_color(fill) if fill else None,
        "fill_type": fill.get("type") if isinstance(fill, dict) else None,
        "image_fill": _figma_image_fill_info(image_fill),
        "corner_radius": _corner_radius(node),
        "border": _border_info(node, stroke),
        "shadow": _shadow_info(node),
        "blur": _blur_info(node),
        "effects": _figma_effect_summary(node),
        "blend_mode": node.get("blendMode"),
        "clips_content": node.get("clipsContent"),
    }
    return {key: value for key, value in result.items() if value is not None and value != {}}


def _text_info(node: dict[str, Any]) -> dict[str, Any] | None:
    if str(node.get("type") or "").upper() != "TEXT":
        return None
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    fills = node.get("fills") if isinstance(node.get("fills"), list) else []
    fill = next((item for item in fills if item.get("visible", True) and item.get("type") == "SOLID"), None)
    effects = _text_effects(node)
    text = {
        "content": node.get("characters") or "",
        "font_family": style.get("fontFamily"),
        "font_postscript_name": style.get("fontPostScriptName"),
        "font_size": _num(style.get("fontSize")),
        "font_weight": style.get("fontWeight"),
        "font_style": "italic" if style.get("italic") else None,
        "color": _paint_color(fill) if fill else None,
        "align": str(style.get("textAlignHorizontal") or "").lower() or None,
        "vertical_align": str(style.get("textAlignVertical") or "").lower() or None,
        "line_height": _num(style.get("lineHeightPx") or style.get("lineHeightPercentFontSize")),
        "letter_spacing": _num(style.get("letterSpacing")),
        "effects": effects,
        "figma_style": style,
        "style_override_table": node.get("styleOverrideTable"),
        "character_style_overrides": node.get("characterStyleOverrides"),
    }
    if node.get("styleOverrideTable") or node.get("characterStyleOverrides"):
        text["style_quality"] = "multi_style"
        text["unsupported_text_features"] = ["figma_style_overrides"]
    return {key: value for key, value in text.items() if value not in (None, {}, [])}


def _figma_variant_properties(node: dict[str, Any]) -> dict[str, Any]:
    properties = node.get("componentProperties")
    if not isinstance(properties, dict):
        return {}
    result: dict[str, Any] = {}
    for key, value in properties.items():
        clean_key = str(key).strip()
        if not clean_key:
            continue
        if isinstance(value, dict):
            if "value" in value:
                result[clean_key] = value.get("value")
            elif "preferredValues" in value:
                result[clean_key] = value.get("preferredValues")
            elif "defaultValue" in value:
                result[clean_key] = value.get("defaultValue")
            else:
                result[clean_key] = {
                    item_key: item_value
                    for item_key, item_value in value.items()
                    if item_key in {"type", "variantOptions", "boundVariables"}
                } or str(value)
        else:
            result[clean_key] = value
    return {key: value for key, value in result.items() if value not in (None, "", [], {})}


def _figma_variant_axes_from_definitions(definitions: Any) -> list[dict[str, Any]]:
    if not isinstance(definitions, dict):
        return []
    axes = []
    for key, value in definitions.items():
        item = value if isinstance(value, dict) else {}
        axes.append(
            {
                "name": str(key),
                "type": item.get("type"),
                "default_value": item.get("defaultValue"),
                "variant_options": item.get("variantOptions") or item.get("preferredValues") or [],
            }
        )
    return axes


def _figma_reactions(node: dict[str, Any]) -> list[dict[str, Any]]:
    raw = node.get("reactions")
    if raw is None:
        raw = node.get("interactions")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _figma_reaction_action(index: int, trigger: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    action_type = str(action.get("type") or action.get("actionType") or "").upper() or "UNKNOWN"
    navigation = str(action.get("navigation") or action.get("navigationType") or "").upper() or None
    destination_id = action.get("destinationId") or action.get("destination_id") or action.get("nodeId") or action.get("node_id")
    transition = action.get("transition") if isinstance(action.get("transition"), dict) else {}
    url = action.get("url") or action.get("href")
    return {
        "index": index,
        "trigger_type": str(trigger.get("type") or trigger.get("triggerType") or "ON_CLICK").upper(),
        "trigger": trigger,
        "action_type": action_type,
        "navigation": navigation,
        "destination_source_node_id": destination_id,
        "destination_node_id": _node_id(str(destination_id)) if destination_id else None,
        "url": url,
        "transition": transition,
        "preserve_scroll_position": action.get("preserveScrollPosition"),
        "overlay_relative_position": action.get("overlayRelativePosition"),
        "requires_review": action_type not in {"NODE", "URL", "BACK", "CLOSE", "SWAP", "OVERLAY"} and not destination_id and not url,
    }


def _unity_navigation_action(action: dict[str, Any]) -> dict[str, Any]:
    action_type = str(action.get("action_type") or "").upper()
    navigation = str(action.get("navigation") or "").upper()
    if action.get("url") or action_type == "URL":
        unity_action_type = "open_url"
    elif navigation in {"NAVIGATE", "SWAP", "OVERLAY"} or action_type in {"NODE", "SWAP", "OVERLAY"}:
        unity_action_type = "navigate_to_node"
    elif action_type == "BACK" or navigation == "BACK":
        unity_action_type = "navigate_back"
    elif action_type == "CLOSE" or navigation == "CLOSE":
        unity_action_type = "close_overlay"
    else:
        unity_action_type = "custom_callback"
    return {
        "unity_action_type": unity_action_type,
        "event": _unity_event_from_trigger(action.get("trigger_type")),
        "target_node_id": action.get("destination_node_id"),
        "target_source_node_id": action.get("destination_source_node_id"),
        "url": action.get("url"),
        "figma_action_type": action_type,
        "figma_navigation": action.get("navigation"),
        "transition": action.get("transition") or {},
        "requires_review": bool(action.get("requires_review") or unity_action_type == "custom_callback"),
    }


def _unity_event_from_trigger(trigger_type: Any) -> str:
    trigger = str(trigger_type or "").upper()
    if trigger in {"ON_DRAG", "ON_HOVER"}:
        return "Pointer event"
    if trigger in {"AFTER_TIMEOUT", "MOUSE_ENTER", "MOUSE_LEAVE"}:
        return "Lifecycle or pointer event"
    return "Button.onClick"


def _unity_event_for_semantic(semantic_type: Any) -> str:
    if semantic_type in {"toggle_candidate", "tab_candidate", "radio_candidate"}:
        return "Toggle.onValueChanged"
    if semantic_type in {"slider_candidate", "progress_candidate"}:
        return "Slider.onValueChanged"
    if semantic_type == "dropdown_candidate":
        return "TMP_Dropdown.onValueChanged"
    if semantic_type == "input_candidate":
        return "TMP_InputField.onSubmit"
    return "Button.onClick"


def _source_metadata(node: dict[str, Any], file_key: str) -> dict[str, Any]:
    variant_properties = _figma_variant_properties(node)
    manual_tags = _figma_manual_tags(node)
    image_fill_refs = _figma_image_fill_refs(node)
    effect_summary = _figma_effect_summary(node)
    unsupported_features = _unsupported_figma_features(node)
    return {
        "source_provider": "figma",
        "source_node_id": _figma_node_id(node),
        "source_path": node.get("name"),
        "figma_file_key": file_key,
        "figma_node_id": _figma_node_id(node),
        "figma_type": node.get("type"),
        "component_id": node.get("componentId"),
        "component_properties": node.get("componentProperties"),
        "variant_properties": variant_properties or None,
        "manual_tags": manual_tags or None,
        "prototype_reactions": node.get("reactions") or node.get("interactions"),
        "styles": node.get("styles"),
        "constraints": node.get("constraints"),
        "layout_mode": node.get("layoutMode"),
        "layout_align": node.get("layoutAlign"),
        "layout_grow": node.get("layoutGrow"),
        "layout_positioning": node.get("layoutPositioning"),
        "layout_sizing_horizontal": node.get("layoutSizingHorizontal") or node.get("layoutSizingX"),
        "layout_sizing_vertical": node.get("layoutSizingVertical") or node.get("layoutSizingY"),
        "clips_content": node.get("clipsContent"),
        "absolute_bounding_box": node.get("absoluteBoundingBox"),
        "absolute_render_bounds": node.get("absoluteRenderBounds"),
        "blend_mode": node.get("blendMode"),
        "figma_effects": effect_summary or None,
        "unsupported_figma_features": unsupported_features or None,
        "recommended_fidelity_mode": "rasterized_export_or_visual_diff" if unsupported_features else None,
        "has_image_fill": _has_image_fill(node),
        "has_mask": _has_figma_mask(node),
        "image_fill_refs": image_fill_refs or None,
        "first_image_ref": image_fill_refs[0] if image_fill_refs else None,
        "has_complex_effects": _has_complex_effects(node),
    }


def _figma_manual_tags(node: dict[str, Any]) -> list[str]:
    tags = []
    values = [node.get("manualTags"), node.get("manual_tags")]
    plugin_data = node.get("pluginData") if isinstance(node.get("pluginData"), dict) else {}
    shared_plugin_data = node.get("sharedPluginData") if isinstance(node.get("sharedPluginData"), dict) else {}
    for key in ("manualTags", "manual_tags", "tags", "designToUnityTags"):
        values.append(plugin_data.get(key))
        values.append(shared_plugin_data.get(key))
    for namespace_values in shared_plugin_data.values():
        if isinstance(namespace_values, dict):
            for key in ("manualTags", "manual_tags", "tags", "designToUnityTags"):
                values.append(namespace_values.get(key))

    for value in values:
        if isinstance(value, list):
            tags.extend(str(item).strip().lstrip("@#") for item in value)
        elif isinstance(value, str):
            tags.extend(str(item).strip().lstrip("@#") for item in re.split(r"[,\s]+", value) if item.strip())
    tags.extend(re.findall(r"[@#]([a-zA-Z][\w-]*)", str(node.get("name") or "")))
    return sorted({tag.lower() for tag in tags if tag})


def _first_visible_fill(node: dict[str, Any]) -> dict[str, Any] | None:
    fills = node.get("fills") if isinstance(node.get("fills"), list) else []
    return next((fill for fill in fills if fill.get("visible", True)), None)


def _first_image_fill(node: dict[str, Any]) -> dict[str, Any] | None:
    fills = node.get("fills") if isinstance(node.get("fills"), list) else []
    return next((fill for fill in fills if fill.get("visible", True) and fill.get("type") == "IMAGE"), None)


def _figma_image_fill_refs(node: dict[str, Any]) -> list[str]:
    fills = node.get("fills") if isinstance(node.get("fills"), list) else []
    refs = []
    for fill in fills:
        if not isinstance(fill, dict) or not fill.get("visible", True) or fill.get("type") != "IMAGE":
            continue
        image_ref = _figma_image_ref(fill)
        if image_ref and image_ref not in refs:
            refs.append(image_ref)
    return refs


def _figma_image_ref(fill: dict[str, Any] | None) -> str | None:
    if not isinstance(fill, dict):
        return None
    return str(fill.get("imageRef") or fill.get("image_ref") or fill.get("imageHash") or fill.get("image_hash") or "").strip() or None


def _figma_image_fill_info(fill: dict[str, Any] | None) -> dict[str, Any] | None:
    image_ref = _figma_image_ref(fill)
    if not isinstance(fill, dict) or not image_ref:
        return None
    return {
        "image_ref": image_ref,
        "scale_mode": fill.get("scaleMode"),
        "scaling_factor": fill.get("scalingFactor"),
        "rotation": fill.get("rotation"),
        "image_transform": fill.get("imageTransform"),
        "filters": fill.get("filters"),
    }


def _first_visible_stroke(node: dict[str, Any]) -> dict[str, Any] | None:
    strokes = node.get("strokes") if isinstance(node.get("strokes"), list) else []
    return next((stroke for stroke in strokes if stroke.get("visible", True)), None)


def _paint_color(paint: dict[str, Any] | None) -> str | None:
    if not paint or not isinstance(paint.get("color"), dict):
        return None
    color = paint["color"]
    alpha = _num(paint.get("opacity"), color.get("a"), 1)
    r = int(round(max(0, min(1, _num(color.get("r")))) * 255))
    g = int(round(max(0, min(1, _num(color.get("g")))) * 255))
    b = int(round(max(0, min(1, _num(color.get("b")))) * 255))
    return f"rgba({r},{g},{b},{round(alpha, 4)})"


def _corner_radius(node: dict[str, Any]) -> float | None:
    if node.get("cornerRadius") is not None:
        return _num(node.get("cornerRadius"))
    radii = node.get("rectangleCornerRadii")
    if isinstance(radii, list) and radii:
        values = [_num(value) for value in radii]
        if len(set(values)) == 1:
            return values[0]
    return None


def _border_info(node: dict[str, Any], stroke: dict[str, Any] | None) -> dict[str, Any] | None:
    if not stroke:
        return None
    return {
        "size": _num(node.get("strokeWeight"), 1),
        "color": _paint_color(stroke),
        "align": node.get("strokeAlign"),
    }


def _shadow_info(node: dict[str, Any]) -> dict[str, Any] | None:
    effects = node.get("effects") if isinstance(node.get("effects"), list) else []
    shadow = next((effect for effect in effects if effect.get("visible", True) and effect.get("type") in {"DROP_SHADOW", "INNER_SHADOW"}), None)
    if not shadow:
        return None
    offset = shadow.get("offset") if isinstance(shadow.get("offset"), dict) else {}
    return {
        "x": _num(offset.get("x")),
        "y": _num(offset.get("y")),
        "blur": _num(shadow.get("radius")),
        "spread": _num(shadow.get("spread")),
        "color": _paint_color({"type": "SOLID", "color": shadow.get("color")}) if shadow.get("color") else None,
        "type": shadow.get("type"),
    }


def _blur_info(node: dict[str, Any]) -> dict[str, Any] | None:
    effects = node.get("effects") if isinstance(node.get("effects"), list) else []
    blur = next((effect for effect in effects if effect.get("visible", True) and effect.get("type") in {"LAYER_BLUR", "BACKGROUND_BLUR"}), None)
    if not blur:
        return None
    blur_type = str(blur.get("type") or "")
    return {
        "type": blur_type,
        "radius": _num(blur.get("radius")),
        "affects_bounds": blur_type == "LAYER_BLUR",
        "requires_review": True,
    }


def _text_effects(node: dict[str, Any]) -> dict[str, Any]:
    shadow = _shadow_info(node)
    return {"shadow": shadow} if shadow else {}


def _has_image_fill(node: dict[str, Any]) -> bool:
    fills = node.get("fills") if isinstance(node.get("fills"), list) else []
    return any(fill.get("visible", True) and fill.get("type") == "IMAGE" for fill in fills)


def _has_complex_effects(node: dict[str, Any]) -> bool:
    if _unsupported_figma_features(node):
        return True
    return False


def _figma_effect_summary(node: dict[str, Any]) -> dict[str, Any]:
    effects = node.get("effects") if isinstance(node.get("effects"), list) else []
    visible_effects = []
    counts: dict[str, int] = {}
    for effect in effects:
        if not isinstance(effect, dict) or not effect.get("visible", True):
            continue
        effect_type = str(effect.get("type") or "UNKNOWN")
        counts[effect_type] = counts.get(effect_type, 0) + 1
        offset = effect.get("offset") if isinstance(effect.get("offset"), dict) else {}
        item = {
            "type": effect_type,
            "radius": _num(effect.get("radius")),
            "spread": _num(effect.get("spread")),
            "offset": {"x": _num(offset.get("x")), "y": _num(offset.get("y"))} if offset else None,
            "color": _paint_color({"type": "SOLID", "color": effect.get("color")}) if effect.get("color") else None,
        }
        visible_effects.append({key: value for key, value in item.items() if value not in (None, {}, [])})
    fills = [fill for fill in (node.get("fills") or []) if isinstance(fill, dict) and fill.get("visible", True)] if isinstance(node.get("fills"), list) else []
    blend_mode = str(node.get("blendMode") or "").upper()
    has_gradient_fill = any(str(fill.get("type") or "").startswith("GRADIENT") for fill in fills)
    has_multiple_fills = len(fills) > 1
    has_mask = _has_figma_mask(node)
    if (
        not visible_effects
        and not has_gradient_fill
        and not has_multiple_fills
        and blend_mode in {"", "NORMAL", "PASS_THROUGH"}
        and not has_mask
    ):
        return {}
    return {
        "visible_effect_count": len(visible_effects),
        "counts_by_type": counts,
        "effects": visible_effects,
        "visible_fill_count": len(fills),
        "has_gradient_fill": has_gradient_fill,
        "has_multiple_fills": has_multiple_fills,
        "blend_mode": node.get("blendMode"),
        "has_mask": has_mask,
    }


def _unsupported_figma_features(node: dict[str, Any]) -> list[str]:
    features = []
    effects = node.get("effects") if isinstance(node.get("effects"), list) else []
    visible_effect_types = {
        str(effect.get("type") or "").upper()
        for effect in effects
        if isinstance(effect, dict) and effect.get("visible", True)
    }
    if "LAYER_BLUR" in visible_effect_types:
        features.append("layer_blur")
    if "BACKGROUND_BLUR" in visible_effect_types:
        features.append("background_blur")
    fills = [fill for fill in (node.get("fills") or []) if isinstance(fill, dict) and fill.get("visible", True)] if isinstance(node.get("fills"), list) else []
    if len(fills) > 1:
        features.append("multiple_fills")
    if any(str(fill.get("type") or "").startswith("GRADIENT") for fill in fills):
        features.append("gradient_fill")
    blend_mode = str(node.get("blendMode") or "").upper()
    if blend_mode not in {"", "NORMAL", "PASS_THROUGH"}:
        features.append("blend_mode")
    if _has_figma_mask(node):
        features.append("mask")
    return sorted(set(features))


def _has_figma_mask(node: dict[str, Any]) -> bool:
    return bool(node.get("isMask") or node.get("maskType"))


def _attach_figma_feature_warnings(node: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    metadata = node.get("source_metadata") or {}
    features = set(metadata.get("unsupported_figma_features") or [])
    if not features and not (node.get("style") or {}).get("shadow"):
        return
    node_name = node.get("name") or node.get("id")
    node_id = node.get("id")
    if "layer_blur" in features or "background_blur" in features:
        warnings.append(
            {
                "node_id": node_id,
                "source_node_id": metadata.get("figma_node_id"),
                "code": "figma_blur_requires_review",
                "severity": "medium",
                "message": f"Figma node '{node_name}' uses blur; prefer rendered asset export and visual diff for exact fidelity.",
            }
        )
    if "blend_mode" in features:
        warnings.append(
            {
                "node_id": node_id,
                "source_node_id": metadata.get("figma_node_id"),
                "code": "figma_blend_mode_requires_review",
                "severity": "medium",
                "message": f"Figma node '{node_name}' uses blend mode '{metadata.get('blend_mode')}'; Unity Image blending may not match exactly.",
            }
        )
    if {"multiple_fills", "gradient_fill"} & features:
        warnings.append(
            {
                "node_id": node_id,
                "source_node_id": metadata.get("figma_node_id"),
                "code": "figma_fill_requires_review",
                "severity": "medium",
                "message": f"Figma node '{node_name}' uses multiple or gradient fills; rendered asset export is safer than editable Image color.",
            }
        )
    if "mask" in features:
        warnings.append(
            {
                "node_id": node_id,
                "source_node_id": metadata.get("figma_node_id"),
                "code": "figma_mask_requires_review",
                "severity": "medium",
                "message": f"Figma node '{node_name}' uses masking; verify clipping in Unity or export the affected group as an image.",
            }
        )
    if (node.get("style") or {}).get("shadow"):
        warnings.append(
            {
                "node_id": node_id,
                "source_node_id": metadata.get("figma_node_id"),
                "code": "figma_shadow_best_effort",
                "severity": "low",
                "message": f"Figma node '{node_name}' uses shadow; Unity UI Shadow is a best-effort approximation.",
            }
        )


def _add_semantic_to_node(node: dict[str, Any], semantic_type: str, confidence: float, reasons: list[str]) -> None:
    candidates = list(node.get("semantic_candidates") or [])
    _add_semantic(candidates, semantic_type, confidence, reasons)
    candidates.sort(key=lambda item: item.get("confidence") or 0, reverse=True)
    node["semantic_candidates"] = candidates
    primary = candidates[0] if candidates else None
    if primary:
        node["semantic_type"] = primary["semantic_type"]
        node["semantic_confidence"] = primary["confidence"]
        node["semantic_reasons"] = primary["reasons"]


def _walk_nodes(root: dict[str, Any]) -> list[dict[str, Any]]:
    result = []

    def walk(node: dict[str, Any]) -> None:
        result.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return result


def _find_figma_node(node: dict[str, Any], node_id: str) -> dict[str, Any] | None:
    wanted = {node_id, node_id.replace(":", "-")}
    current = str(node.get("id") or "")
    if current in wanted or current.replace(":", "-") in wanted:
        return node
    for child in node.get("children") or []:
        found = _find_figma_node(child, node_id)
        if found:
            return found
    return None


def _normalize_figma_target_types(value: list[str] | str | None) -> set[str]:
    if value is None or value == "":
        return {"FRAME", "COMPONENT", "COMPONENT_SET"}
    if isinstance(value, str):
        raw_items = re.split(r"[,\s]+", value)
    else:
        raw_items = [str(item) for item in value]
    return {item.strip().upper() for item in raw_items if item and item.strip()}


def _snapshot_image_urls(payload: dict[str, Any]) -> dict[str, str | None]:
    images = payload.get("images") or payload.get("rendered_image_urls") or {}
    if isinstance(images, dict):
        return {str(key): value for key, value in images.items()}
    return {}


def _figma_node_id(node: dict[str, Any]) -> str:
    return str(node.get("id") or _hash(node.get("name") or node.get("type") or "node")[:12])


def _node_id(figma_id: str) -> str:
    return "figma_" + re.sub(r"[^0-9A-Za-z_]+", "_", figma_id).strip("_")


def _unity_name(index: int, name: str) -> str:
    return f"node_{index:03d}_{sanitize_filename(name, 'node')}"


def _component_property_text(node: dict[str, Any]) -> str:
    properties = node.get("componentProperties")
    if not isinstance(properties, dict):
        return ""
    parts = []
    for key, value in properties.items():
        if isinstance(value, dict):
            parts.append(f"{key}={value.get('value')}")
        else:
            parts.append(f"{key}={value}")
    return " ".join(parts)


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in tokens)


def _num(*values: Any) -> float:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            if match:
                return float(match.group(0))
    return 0.0


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _packet_id(file_key: str, node_id: str, target: str, scale: float) -> str:
    raw = f"figma:{file_key}:{node_id}:{target}:{scale}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]

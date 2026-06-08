from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlparse

from .asset_store import sanitize_filename
from .lanhu_client import LanhuUrl
from .profiles import build_handoff_profiles


def make_packet(
    parsed_url: LanhuUrl,
    design: dict[str, Any],
    version_id: str,
    dds_schema: dict[str, Any] | None,
    sketch_json: dict[str, Any] | None,
    target: str = "unity",
) -> dict[str, Any]:
    source_payload = dds_schema or sketch_json or {}
    design_info = _design_info(design, source_payload)
    asset_registry: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []
    if design_info.get("source_image_url"):
        design_info["reference_asset_ref"] = _register_asset(
            asset_registry,
            f"{design_info['name']}_design_reference",
            design_info["source_image_url"],
            {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]},
            design_info["scale"],
            "design_reference",
        )

    roots = _extract_root_layers(source_payload)
    root_node = {
        "id": "root",
        "parent_id": None,
        "name": design_info["name"],
        "path": design_info["name"],
        "type": "group",
        "semantic_type": "screen_root",
        "visible": True,
        "z_index": 0,
        "global_rect": {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]},
        "local_rect": {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]},
        "unity_rect_hint": _unity_rect({"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]}),
        "style": {"opacity": 1},
        "children": [],
    }

    z_counter = [1]
    for layer in roots:
        node = _normalize_layer(
            layer=layer,
            parent_id="root",
            parent_path=design_info["name"],
            parent_global={"x": 0, "y": 0},
            assets=asset_registry,
            warnings=warnings,
            z_counter=z_counter,
            scale=design_info["scale"],
            design_info=design_info,
        )
        if node:
            root_node["children"].append(node)

    _enrich_assets(asset_registry, root_node, design_info)
    assets = list(asset_registry.values())
    packet_id = _packet_id(parsed_url.project_id, design.get("id"), version_id)
    packet = {
        "packet_id": packet_id,
        "source": {
            "provider": "lanhu",
            "team_id": parsed_url.team_id,
            "project_id": parsed_url.project_id,
            "design_id": design.get("id"),
            "version_id": version_id,
            "url": parsed_url.raw_url,
            "schema_source": "dds" if dds_schema is not None else "sketch",
        },
        "design": design_info,
        "nodes": [root_node],
        "assets": assets,
        "semantic_map": _semantic_summary(root_node),
        "handoff_profiles": build_handoff_profiles(design_info),
        "target": target,
        "warnings": warnings,
    }
    return packet


def _packet_id(project_id: str, design_id: str | None, version_id: str) -> str:
    raw = f"lanhu:{project_id}:{design_id}:{version_id}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _design_info(design: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    width = _num(design.get("width")) or _num(_lookup(payload, ["artboard.frame.width", "board.width", "props.style.width"]))
    height = _num(design.get("height")) or _num(_lookup(payload, ["artboard.frame.height", "board.height", "props.style.height"]))
    scale = _detect_scale(payload, width, height)
    if scale and scale > 1 and width and height and _looks_like_raw_canvas(payload, width, height):
        width = round(width / scale, 1)
        height = round(height / scale, 1)
    return {
        "name": design.get("name") or "LanhuDesign",
        "width": width or 0,
        "height": height or 0,
        "scale": scale,
        "unit": "px",
        "coordinate_system": "top-left",
        "source_image_url": (design.get("url") or "").split("?", 1)[0] or None,
    }


def _detect_scale(payload: dict[str, Any], width: float | None, height: float | None) -> float:
    raw_w = _num(_lookup(payload, ["artboard.frame.width", "board.width", "props.style.width"]))
    raw_h = _num(_lookup(payload, ["artboard.frame.height", "board.height", "props.style.height"]))
    if raw_w and width and raw_w > width:
        ratio = raw_w / width
        if 0.75 <= ratio <= 8:
            return round(ratio, 4)
    if raw_h and height and raw_h > height:
        ratio = raw_h / height
        if 0.75 <= ratio <= 8:
            return round(ratio, 4)

    text = " ".join(str(payload.get(k, "")) for k in ("device", "psdName", "name", "type"))
    if "@3x" in text:
        return 3.0
    if "@1x" in text:
        return 1.0
    return 2.0


def _looks_like_raw_canvas(payload: dict[str, Any], width: float | None, height: float | None) -> bool:
    board_w = _num(_lookup(payload, ["artboard.frame.width", "board.width"]))
    return bool(board_w and width and abs(board_w - width) < 1 and width >= 700)


def _extract_root_layers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("children"), list):
        return payload["children"]
    artboard = payload.get("artboard") or {}
    if isinstance(artboard.get("layers"), list):
        return artboard["layers"]
    board = payload.get("board") or {}
    if isinstance(board.get("layers"), list):
        return board["layers"]
    if isinstance(payload.get("layers"), list):
        return payload["layers"]
    if isinstance(payload.get("info"), list):
        return payload["info"]
    return [payload] if payload else []


def _normalize_layer(
    layer: dict[str, Any],
    parent_id: str,
    parent_path: str,
    parent_global: dict[str, float],
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
    z_counter: list[int],
    scale: float,
    design_info: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(layer, dict) or layer.get("visible") is False:
        return None

    raw_name = _layer_name(layer)
    node_id = str(layer.get("id") or layer.get("uid") or _hash({"name": raw_name, "z": z_counter[0]})[:12])
    path = f"{parent_path}/{raw_name}" if parent_path else raw_name
    global_rect = _scaled_rect(_rect_of(layer), scale)
    if global_rect["width"] <= 0 and global_rect["height"] <= 0 and _children_of(layer):
        global_rect = {"x": parent_global["x"], "y": parent_global["y"], "width": 0, "height": 0}

    local_rect = {
        "x": round(global_rect["x"] - parent_global["x"], 1),
        "y": round(global_rect["y"] - parent_global["y"], 1),
        "width": global_rect["width"],
        "height": global_rect["height"],
    }
    layer_type = _node_type(layer)
    text = _text_info(layer, scale)
    asset_ref = None
    image_url = _image_url(layer)
    if image_url:
        asset_ref = _register_asset(assets, raw_name, image_url, global_rect, scale, layer_type)
        if layer_type == "unknown":
            layer_type = "image"
    if text:
        layer_type = "text"

    z_index = z_counter[0]
    z_counter[0] += 1
    node = {
        "id": node_id,
        "parent_id": parent_id,
        "name": raw_name,
        "unity_name_hint": _unity_name(z_index, raw_name),
        "path": path,
        "type": layer_type,
        "semantic_type": None,
        "semantic_confidence": None,
        "semantic_reasons": [],
        "visible": True,
        "z_index": z_index,
        "global_rect": global_rect,
        "local_rect": local_rect,
        "unity_rect_hint": _unity_rect(local_rect),
        "style": _style_info(layer, scale, warnings, node_id),
        "text": text,
        "asset_ref": asset_ref,
        "children": [],
        "source_metadata": {
            "source_node_id": node_id,
            "source_path": path,
        },
    }
    node["content_hash"] = _hash(
        {
            "rect": global_rect,
            "style": node["style"],
            "text": text,
            "asset_ref": asset_ref,
        }
    )
    _apply_semantics(node, design_info)

    for child in _children_of(layer):
        child_node = _normalize_layer(
            child,
            node_id,
            path,
            {"x": global_rect["x"], "y": global_rect["y"]},
            assets,
            warnings,
            z_counter,
            scale,
            design_info,
        )
        if child_node:
            node["children"].append(child_node)

    if node["type"] == "unknown" and node["children"]:
        node["type"] = "group"
    return node


def _layer_name(layer: dict[str, Any]) -> str:
    props = layer.get("props") or {}
    return str(layer.get("name") or props.get("className") or props.get("name") or layer.get("type") or "node")


def _children_of(layer: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("children", "layers"):
        value = layer.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _node_type(layer: dict[str, Any]) -> str:
    kind = str(layer.get("type") or layer.get("layerType") or layer.get("ddsType") or "").lower()
    if kind in {"lanhutext", "textlayer", "text"} or layer.get("textInfo") or layer.get("text"):
        return "text"
    if kind in {"lanhuimage", "bitmaplayer", "image"} or _image_url(layer):
        return "image"
    if kind in {"grouplayer", "layersection", "symbolinstance", "symbolinstence", "artboard"}:
        return "group"
    if kind in {"shapelayer", "shape", "rectangle", "oval"}:
        return "shape"
    if _children_of(layer):
        return "group"
    if layer.get("fill") or _lookup(layer, ["style.fills", "layerEffects.solidFill"]):
        return "shape"
    return "unknown"


def _rect_of(layer: dict[str, Any]) -> dict[str, float]:
    frame = layer.get("frame") or layer.get("realFrame") or {}
    style = (layer.get("props") or {}).get("style") or {}
    return {
        "x": _num(frame.get("x"), frame.get("left"), layer.get("x"), layer.get("left"), style.get("left")) or 0,
        "y": _num(frame.get("y"), frame.get("top"), layer.get("y"), layer.get("top"), style.get("top")) or 0,
        "width": _num(frame.get("width"), layer.get("width"), style.get("width")) or 0,
        "height": _num(frame.get("height"), layer.get("height"), style.get("height")) or 0,
    }


def _scaled_rect(rect: dict[str, float], scale: float) -> dict[str, float]:
    if scale > 1:
        scaled = {key: round(value / scale, 1) for key, value in rect.items()}
    else:
        scaled = {key: round(value, 1) for key, value in rect.items()}
    if scaled["width"] < 0:
        scaled["x"] = round(scaled["x"] + scaled["width"], 1)
        scaled["width"] = abs(scaled["width"])
    if scaled["height"] < 0:
        scaled["y"] = round(scaled["y"] + scaled["height"], 1)
        scaled["height"] = abs(scaled["height"])
    return scaled


def _unity_rect(rect: dict[str, float]) -> dict[str, Any]:
    return {
        "anchorMin": [0, 1],
        "anchorMax": [0, 1],
        "pivot": [0, 1],
        "anchoredPosition": [rect["x"], -rect["y"]],
        "sizeDelta": [rect["width"], rect["height"]],
    }


def _style_info(layer: dict[str, Any], scale: float, warnings: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    style = (layer.get("props") or {}).get("style") or {}
    fill_color = _color_value(
        _lookup(layer, ["fill.color", "style.fills.0.color", "fills.0.color"]) or style.get("backgroundColor")
    )
    opacity = _opacity(layer)
    result = {
        "opacity": opacity,
        "fill_color": fill_color,
        "corner_radius": _scaled_num(_lookup(layer, ["radius", "cornerRadius", "props.style.borderRadius"]), scale),
        "border": _border(layer, scale),
        "shadow": _shadow(layer, scale),
    }
    if result["corner_radius"]:
        warnings.append(
            {
                "node_id": node_id,
                "code": "rounded_rect_requires_custom_solution",
                "severity": "low",
                "message": "Rounded corners need a project-specific Unity solution unless the node is exported as a sprite.",
            }
        )
    if result["shadow"]:
        warnings.append(
            {
                "node_id": node_id,
                "code": "unsupported_shadow",
                "severity": "medium",
                "message": "Unity UGUI Shadow may not fully match the design shadow.",
            }
        )
    return {key: value for key, value in result.items() if value is not None}


def _text_info(layer: dict[str, Any], scale: float) -> dict[str, Any] | None:
    text_info = layer.get("textInfo")
    art_text = layer.get("text")
    props = layer.get("props") or {}
    data = layer.get("data") or {}
    style = props.get("style") or {}

    content = None
    source_style: dict[str, Any] = {}
    if isinstance(text_info, dict):
        content = text_info.get("text")
        source_style = text_info
    elif isinstance(art_text, dict):
        content = art_text.get("value")
        source_style = ((art_text.get("style") or {}).get("font") or {}) | {"color": (art_text.get("style") or {}).get("color")}
    elif layer.get("type") == "lanhutext":
        content = data.get("value") or props.get("text")
        source_style = style

    if content is None:
        return None

    return {
        "content": str(content),
        "font_family": source_style.get("fontPostScriptName") or source_style.get("fontName") or source_style.get("name"),
        "font_size": _scaled_num(source_style.get("size") or style.get("fontSize"), scale),
        "font_weight": source_style.get("fontWeight") or _font_weight(source_style.get("fontStyleName") or source_style.get("type")),
        "color": _color_value(source_style.get("color") or style.get("color")),
        "align": source_style.get("justification") or source_style.get("align") or style.get("textAlign"),
        "line_height": _scaled_num(_lookup(source_style, ["lineHeight.value", "leading"]) or style.get("lineHeight"), scale),
        "letter_spacing": source_style.get("tracking") or style.get("letterSpacing") or 0,
        "overflow": "clip",
        "wrap": "\n" in str(content),
    }


def _image_url(layer: dict[str, Any]) -> str | None:
    image = layer.get("image") or {}
    dds_image = layer.get("ddsImage") or {}
    images = layer.get("images") or {}
    data = layer.get("data") or {}
    value = data.get("value")
    for candidate in (
        image.get("imageUrl"),
        image.get("svgUrl"),
        dds_image.get("imageUrl"),
        images.get("png_xxxhd"),
        images.get("svg"),
        value if isinstance(value, str) and value.startswith("http") else None,
    ):
        if candidate:
            return str(candidate)
    return None


def _register_asset(
    assets: dict[str, dict[str, Any]],
    name: str,
    remote_url: str,
    rect: dict[str, float],
    scale: float,
    usage: str,
) -> str:
    asset_id = "asset_" + _hash(remote_url)[:12]
    if asset_id not in assets:
        ext = _ext(remote_url)
        safe = sanitize_filename(name, asset_id)
        file_stem = f"{safe}_{asset_id.removeprefix('asset_')[:8]}"
        assets[asset_id] = {
            "id": asset_id,
            "name": safe,
            "file_name": f"{file_stem}{ext}",
            "type": "image",
            "remote_url": remote_url,
            "local_path": None,
            "suggested_unity_path": f"Assets/DesignHandoff/Sprites/{file_stem}{ext}",
            "format": ext.lstrip("."),
            "size": None,
            "logical_size": {"width": rect["width"], "height": rect["height"]},
            "scale": scale,
            "has_alpha": ext.lower() in {".png", ".webp", ".svg"},
            "usage": usage,
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


def _apply_semantics(node: dict[str, Any], design_info: dict[str, Any]) -> None:
    name = str(node.get("name") or "").lower()
    text = str((node.get("text") or {}).get("content") or "").lower()
    rect = node.get("global_rect") or {}
    width = _num(rect.get("width")) or 0
    height = _num(rect.get("height")) or 0
    x = _num(rect.get("x")) or 0
    y = _num(rect.get("y")) or 0
    screen_w = _num(design_info.get("width")) or 0
    screen_h = _num(design_info.get("height")) or 0
    screen_area = max(screen_w * screen_h, 1)
    area_ratio = (width * height) / screen_area if width and height else 0
    aspect = width / height if height else 0
    node_type = node.get("type")
    candidates: list[dict[str, Any]] = []

    strong_button_tokens = ("btn", "button", "按钮")
    action_button_tokens = ("confirm", "submit", "cancel", "取消", "ok", "play", "start")
    button_like_rect = 2.0 <= aspect <= 8.0 and 28 <= height <= 120 and width >= 80 and area_ratio <= 0.2
    if _has_token(name, strong_button_tokens) or (
        node_type in {"image", "shape", "group"} and button_like_rect and _has_token(name, action_button_tokens)
    ):
        reasons = []
        if _has_token(name, strong_button_tokens):
            reasons.append("name/action text suggests button")
        if button_like_rect:
            reasons.append("rect has button-like aspect and height")
        _add_semantic(candidates, "button_candidate", 0.86 if _has_token(name, strong_button_tokens) else 0.62, reasons)

    if _has_token(name, ("bg", "background", "背景", "backdrop", "底图")) or area_ratio >= 0.72:
        reasons = []
        if area_ratio >= 0.72:
            reasons.append("node covers most of the screen")
        if _has_token(name, ("bg", "background", "背景", "backdrop", "底图")):
            reasons.append("name suggests background")
        _add_semantic(candidates, "background_candidate", 0.84 if area_ratio >= 0.72 else 0.72, reasons)

    title_tokens = ("title", "标题", "headline", "name")
    if _has_token(name, title_tokens) or (node_type == "text" and (y <= screen_h * 0.28 or _has_token(text, title_tokens))):
        reasons = []
        if _has_token(name, title_tokens) or _has_token(text, title_tokens):
            reasons.append("name/text suggests title")
        if node_type == "text" and y <= screen_h * 0.28:
            reasons.append("text is in the upper screen area")
        _add_semantic(candidates, "title_candidate", 0.72 if _has_token(name, title_tokens) else 0.56, reasons)

    icon_tokens = ("icon", "ico", "flag", "wechat", "instagram", "facebook", "twitter", "close", "logo", "arrow", "返回", "关闭")
    if node_type in {"image", "shape"} and (
        _has_token(name, icon_tokens)
        or (width <= 96 and height <= 96 and area_ratio <= 0.03)
        or (0.65 <= aspect <= 1.55 and width <= 128 and height <= 128)
    ):
        reasons = []
        if _has_token(name, icon_tokens):
            reasons.append("name suggests icon")
        if width <= 96 and height <= 96:
            reasons.append("node is small")
        if 0.65 <= aspect <= 1.55:
            reasons.append("node is roughly square")
        _add_semantic(candidates, "icon_candidate", 0.78 if _has_token(name, icon_tokens) else 0.58, reasons)

    if node_type == "image" and _has_token(name, ("text", "文字", "label", "copy")):
        _add_semantic(candidates, "text_image_candidate", 0.76, ["image layer name suggests exported text"])

    centered_x = screen_w and abs((x + width / 2) - screen_w / 2) <= screen_w * 0.18
    centered_y = screen_h and abs((y + height / 2) - screen_h / 2) <= screen_h * 0.24
    if node_type in {"image", "group", "shape"} and 0.12 <= area_ratio <= 0.7 and (centered_x or _has_token(name, ("panel", "card", "面板", "框"))):
        reasons = []
        if centered_x:
            reasons.append("node is horizontally centered")
        if _has_token(name, ("panel", "card", "面板", "框")):
            reasons.append("name suggests panel/card")
        _add_semantic(candidates, "panel_candidate", 0.68 if centered_x else 0.62, reasons)

    if node_type in {"image", "group", "shape"} and 0.18 <= area_ratio <= 0.85 and centered_x and centered_y:
        _add_semantic(candidates, "dialog_candidate", 0.58, ["node is centered and large enough for a dialog"])

    if _has_token(name, ("item", "cell", "row", "list", "列表", "条目")):
        _add_semantic(candidates, "list_item_candidate", 0.66, ["name suggests list item"])

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    primary = candidates[0] if candidates else None
    node["semantic_candidates"] = candidates
    node["semantic_type"] = primary["semantic_type"] if primary else None
    node["semantic_confidence"] = primary["confidence"] if primary else None
    node["semantic_reasons"] = primary["reasons"] if primary else []
    if primary and primary["confidence"] < 0.7:
        node["requires_semantic_review"] = True
    if node.get("semantic_type") == "button_candidate":
        node["unity_interaction_hint"] = {
            "can_add_button": True,
            "default_add_button": False,
            "raycast_target_if_interactive": True,
        }


def _has_token(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _add_semantic(candidates: list[dict[str, Any]], semantic_type: str, confidence: float, reasons: list[str]) -> None:
    clean_reasons = [reason for reason in reasons if reason]
    for existing in candidates:
        if existing["semantic_type"] == semantic_type:
            if confidence > existing["confidence"]:
                existing["confidence"] = round(confidence, 2)
            existing["reasons"] = sorted(set(existing["reasons"] + clean_reasons))
            return
    candidates.append(
        {
            "semantic_type": semantic_type,
            "confidence": round(confidence, 2),
            "reasons": clean_reasons,
        }
    )


def _enrich_assets(assets: dict[str, dict[str, Any]], root_node: dict[str, Any], design_info: dict[str, Any]) -> None:
    screen_w = _num(design_info.get("width")) or 0
    screen_h = _num(design_info.get("height")) or 0
    screen_area = max(screen_w * screen_h, 1)
    usage: dict[str, list[dict[str, Any]]] = {}

    def walk(node: dict[str, Any]) -> None:
        asset_ref = node.get("asset_ref")
        if asset_ref:
            usage.setdefault(asset_ref, []).append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root_node)

    for asset in assets.values():
        nodes = usage.get(asset["id"], [])
        rect = asset.get("logical_size") or {}
        width = _num(rect.get("width")) or 0
        height = _num(rect.get("height")) or 0
        area_ratio = (width * height) / screen_area if width and height else 0
        aspect = width / height if height else 0
        name = str(asset.get("name") or "").lower()
        semantic_types = {node.get("semantic_type") for node in nodes if node.get("semantic_type")}
        used_by_text_node = any(node.get("type") == "text" for node in nodes)

        is_reference = asset.get("usage") == "design_reference"
        is_large_background = bool(is_reference or "background_candidate" in semantic_types or area_ratio >= 0.72)
        is_icon_like = bool("icon_candidate" in semantic_types or width <= 96 and height <= 96 and area_ratio <= 0.03)
        is_button_like = bool("button_candidate" in semantic_types or 2.0 <= aspect <= 8.0 and 28 <= height <= 120)
        is_text_like = bool(used_by_text_node or "text_image_candidate" in semantic_types or _has_token(name, ("text", "label", "文字")))
        is_panel_like = bool("panel_candidate" in semantic_types or "dialog_candidate" in semantic_types)
        if is_reference:
            role = "design_reference"
            folder = "References"
        elif is_large_background:
            role = "background"
            folder = "Backgrounds"
        elif is_button_like:
            role = "button_sprite"
            folder = "Buttons"
        elif is_text_like:
            role = "text_sprite"
            folder = "TextSprites"
        elif is_icon_like:
            role = "icon"
            folder = "Icons"
        elif is_panel_like:
            role = "panel"
            folder = "Panels"
        else:
            role = "sprite"
            folder = "Sprites"

        nine_slice_candidate = bool(is_button_like or is_panel_like)
        asset.update(
            {
                "safe_file_name": asset.get("file_name"),
                "suggested_unity_folder": f"Assets/DesignHandoff/{folder}",
                "asset_role": role,
                "used_by_node_ids": [node.get("id") for node in nodes],
                "used_by_node_paths": [node.get("path") for node in nodes],
                "is_large_background": is_large_background,
                "is_icon_like": is_icon_like,
                "is_button_like": is_button_like,
                "is_text_like": is_text_like,
                "is_panel_like": is_panel_like,
                "area_ratio": round(area_ratio, 4),
                "aspect_ratio": round(aspect, 4) if aspect else None,
                "duplicate_of": None,
                "nine_slice_hint": {
                    "candidate": nine_slice_candidate,
                    "reason": "button/panel-like sprite may benefit from a project-specific nine-slice rule"
                    if nine_slice_candidate
                    else "not a strong nine-slice candidate",
                    "requires_review": nine_slice_candidate,
                },
            }
        )


def _semantic_summary(root: dict[str, Any]) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {}

    def walk(node: dict[str, Any]) -> None:
        semantic = node.get("semantic_type")
        if semantic:
            summary.setdefault(semantic, []).append(node["id"])
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return summary


def _num(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            match = re.search(r"-?\d+(?:\.\d+)?", value)
            if match:
                return float(match.group(0))
    return None


def _scaled_num(value: Any, scale: float) -> float | None:
    number = _num(value)
    if number is None:
        return None
    if scale > 1:
        return round(number / scale, 1)
    return round(number, 1)


def _lookup(obj: dict[str, Any], paths: list[str]) -> Any:
    for path in paths:
        current: Any = obj
        for part in path.split("."):
            if isinstance(current, list) and part.isdigit():
                idx = int(part)
                current = current[idx] if idx < len(current) else None
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                current = None
            if current is None:
                break
        if current is not None:
            return current
    return None


def _color_value(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if value.get("value"):
            return str(value["value"])
        r = round(_num(value.get("red"), value.get("r")) or 0)
        g = round(_num(value.get("green"), value.get("g")) or 0)
        b = round(_num(value.get("blue"), value.get("b")) or 0)
        a = _num(value.get("alpha"), value.get("a"), value.get("opacity"))
        if a is not None and a > 1:
            a = a / 100
        if a is not None and a < 1:
            return f"rgba({r},{g},{b},{round(a, 3)})"
        return f"rgb({r},{g},{b})"
    return None


def _opacity(layer: dict[str, Any]) -> float:
    raw = _lookup(layer, ["blendOptions.opacity.value", "opacity", "props.style.opacity"])
    number = _num(raw)
    if number is None:
        return 1
    if number > 1:
        number = number / 100
    return round(number, 3)


def _border(layer: dict[str, Any], scale: float) -> dict[str, Any] | None:
    border = _lookup(layer, ["style.borders.0", "borders.0", "layerEffects.frameFX"])
    if not isinstance(border, dict):
        return None
    return {
        "size": _scaled_num(border.get("size"), scale),
        "color": _color_value(border.get("color")),
    }


def _shadow(layer: dict[str, Any], scale: float) -> dict[str, Any] | None:
    shadow = _lookup(layer, ["style.shadows.0", "shadows.0", "layerEffects.dropShadow"])
    if not isinstance(shadow, dict):
        return None
    return {
        "x": _scaled_num(shadow.get("x") or shadow.get("offsetX"), scale),
        "y": _scaled_num(shadow.get("y") or shadow.get("offsetY"), scale),
        "blur": _scaled_num(shadow.get("blur"), scale),
        "spread": _scaled_num(shadow.get("spread"), scale),
        "color": _color_value(shadow.get("color")),
    }


def _font_weight(value: Any) -> int | None:
    if not value:
        return None
    match = re.search(r"\d{3}", str(value))
    return int(match.group(0)) if match else None


def _unity_name(index: int, name: str) -> str:
    return f"node_{index:03d}_{sanitize_filename(name, 'node')}"


def _hash(value: Any) -> str:
    return hashlib.sha1(repr(value).encode("utf-8", "ignore")).hexdigest()


def _ext(url: str) -> str:
    suffix = "." + urlparse(url).path.rsplit(".", 1)[-1].lower() if "." in urlparse(url).path else ".png"
    return suffix if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"} else ".png"

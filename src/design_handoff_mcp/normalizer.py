from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .asset_store import sanitize_filename
from .lanhu_client import LanhuUrl
from .profiles import build_handoff_profiles


_REUSABLE_COMPONENT_SEMANTICS = {
    "button_candidate",
    "progress_candidate",
    "slider_candidate",
    "toggle_candidate",
    "tab_candidate",
    "radio_candidate",
    "input_candidate",
    "dropdown_candidate",
    "scroll_area_candidate",
    "scrollbar_candidate",
    "mask_candidate",
}
_REUSABLE_STRUCTURAL_SEMANTICS = {
    "icon_candidate",
    "text_image_candidate",
    "panel_candidate",
    "dialog_candidate",
    "list_item_candidate",
    "manual_prefab_candidate",
    "tab_group_candidate",
    "radio_group_candidate",
    "scroll_viewport_candidate",
    "scroll_content_candidate",
}
_NON_REUSABLE_SEMANTICS = {
    "screen_root",
    "background_candidate",
    "ignored_by_designer",
}


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
    design_info["provider"] = "lanhu"
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

    _merge_overlapping_lanhu_text_fragments(root_node, design_info)
    _attach_text_backed_button_hints(root_node, design_info)
    _apply_lanhu_scroll_viewport_hint(root_node, design_info, warnings)
    _enrich_assets(asset_registry, root_node, design_info)
    enrich_delivery_metadata(root_node, design_info, asset_registry, provider="lanhu")
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
    attach_reusable_prefab_registry(packet)
    return packet


def _apply_lanhu_scroll_viewport_hint(root_node: dict[str, Any], design_info: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    content_width = _num(design_info.get("width")) or 0
    content_height = _num(design_info.get("height")) or 0
    scale = _num(design_info.get("scale")) or 1
    physical_width = content_width * scale
    physical_height = content_height * scale
    viewport_physical_height = _infer_lanhu_viewport_physical_height(physical_width, physical_height)
    if not viewport_physical_height:
        return

    viewport_height = round(viewport_physical_height / scale, 2)
    if content_height <= viewport_height + 2:
        return

    bottom = _max_node_bottom(root_node)
    if bottom <= viewport_height + 2:
        return

    viewport_rect = {"x": 0, "y": 0, "width": round(content_width, 2), "height": viewport_height}
    content_rect = {"x": 0, "y": 0, "width": round(content_width, 2), "height": round(content_height, 2)}
    scroll_info = {
        "required": True,
        "direction": "vertical",
        "source": "lanhu_long_artboard",
        "preferred_unity_scope": "prefab_internal_scroll_area",
        "reason": "Lanhu DDS content height exceeds the inferred device viewport height.",
        "viewport_rect": viewport_rect,
        "content_rect": content_rect,
        "overflow": {"bottom": round(content_height - viewport_height, 2)},
        "viewport_physical_size": {
            "width": round(physical_width, 2),
            "height": round(viewport_physical_height, 2),
        },
        "content_physical_size": {
            "width": round(physical_width, 2),
            "height": round(physical_height, 2),
        },
    }
    design_info["viewport"] = {
        "x": 0,
        "y": 0,
        "width": round(content_width, 2),
        "height": viewport_height,
        "physical_width": round(physical_width, 2),
        "physical_height": round(viewport_physical_height, 2),
        "inferred": True,
        "source": "lanhu_common_device_viewport",
    }
    design_info["scroll"] = scroll_info
    root_node["unity_scroll_hint"] = {
        "can_add_scroll_rect": True,
        "default_add_scroll_rect": True,
        "direction": "vertical",
        "viewport_node_id": "viewport",
        "content_node_id": "content",
        "viewport_rect": viewport_rect,
        "content_rect": content_rect,
        "movement_type": "clamped",
        "requires_review": False,
        "source": "lanhu_long_artboard",
        "preferred_unity_scope": "prefab_internal_scroll_area",
        "notes": [
            "Create the ScrollRect inside the generated prefab rather than wrapping the prefab externally in the scene.",
            "Infer fixed header/footer regions from top-level layout, then place the overflowing content nodes under ScrollRect Content.",
            "Do not crop nodes below viewport_rect; they are scrollable content.",
        ],
    }
    warnings.append(
        {
            "node_id": "root",
            "code": "lanhu_long_artboard_scroll_candidate",
            "severity": "info",
            "message": (
                "Lanhu content is taller than the inferred device viewport; expose it as vertical scroll content "
                f"({round(physical_width)}x{round(physical_height)} content, {round(physical_width)}x{round(viewport_physical_height)} viewport)."
            ),
        }
    )


def _infer_lanhu_viewport_physical_height(physical_width: float, physical_height: float) -> float | None:
    if physical_width <= 0 or physical_height <= 0:
        return None
    if 700 <= physical_width <= 760 and physical_height > 1700:
        return 1559.0
    return None


def _max_node_bottom(root_node: dict[str, Any]) -> float:
    max_bottom = 0.0

    def walk(node: dict[str, Any]) -> None:
        nonlocal max_bottom
        rect = _rect_or_empty(node.get("global_rect"))
        max_bottom = max(max_bottom, rect["y"] + rect["height"])
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child)

    walk(root_node)
    return round(max_bottom, 2)


def apply_lanhu_reused_background_assets(packet: dict[str, Any]) -> dict[str, Any]:
    source = packet.get("source") or {}
    if str(source.get("provider") or "").lower() != "lanhu":
        return {"applied_count": 0, "items": []}
    roots = packet.get("nodes") or []
    if not roots:
        return {"applied_count": 0, "items": []}
    assets = {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}
    applied: list[dict[str, Any]] = []

    def walk(parent: dict[str, Any]) -> None:
        children = [child for child in parent.get("children") or [] if isinstance(child, dict)]
        row_nodes = [child for child in children if _is_lanhu_reusable_background_row(child)]
        source_rows = [_background_source_row(child, assets) for child in row_nodes if child.get("asset_ref")]
        source_rows = [item for item in source_rows if item]
        target_rows = [child for child in row_nodes if not child.get("asset_ref") and _style_rgb(child) is not None]
        for target in target_rows:
            target_rgb = _style_rgb(target)
            if target_rgb is None:
                continue
            compatible = [source_row for source_row in source_rows if _similar_size(target.get("global_rect"), source_row["node"].get("global_rect"))]
            if not compatible:
                continue
            best = min(compatible, key=lambda source_row: _rgb_distance(target_rgb, source_row["rgb"]))
            if _rgb_distance(target_rgb, best["rgb"]) > 90:
                continue
            previous_type = target.get("type")
            target["asset_ref"] = best["node"].get("asset_ref")
            target["type"] = "image"
            target["source_metadata"] = dict(target.get("source_metadata") or {})
            target["source_metadata"].update(
                {
                    "inferred_reused_background_asset": True,
                    "reused_background_source_node_id": best["node"].get("id"),
                    "reused_background_source_asset_ref": best["node"].get("asset_ref"),
                    "reused_background_match": {
                        "target_rgb": list(target_rgb),
                        "source_rgb": list(best["rgb"]),
                        "distance": round(_rgb_distance(target_rgb, best["rgb"]), 2),
                    },
                    "original_type_before_background_reuse": previous_type,
                }
            )
            target.setdefault("semantic_reasons", [])
            target["semantic_reasons"] = sorted(set([*target["semantic_reasons"], "reused a same-size Lanhu row background sprite inferred from style color"]))
            target["content_hash"] = _hash({"rect": target.get("global_rect"), "style": target.get("style"), "asset_ref": target.get("asset_ref")})
            applied.append(
                {
                    "node_id": target.get("id"),
                    "source_node_id": best["node"].get("id"),
                    "asset_ref": target.get("asset_ref"),
                    "target_rgb": list(target_rgb),
                    "source_rgb": list(best["rgb"]),
                }
            )
        for child in children:
            walk(child)

    for root in roots:
        walk(root)

    if applied:
        packet.setdefault("warnings", []).append(
            {
                "node_id": None,
                "code": "lanhu_reused_background_assets_inferred",
                "severity": "info",
                "message": f"Inferred {len(applied)} Lanhu style-only background nodes that reuse downloaded same-size background sprites.",
            }
        )
        asset_lookup = {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}
        _enrich_assets(asset_lookup, roots[0], packet.get("design") or {})
        enrich_delivery_metadata(roots[0], packet.get("design") or {}, asset_lookup, provider="lanhu")
    packet["lanhu_reused_background_assets"] = {"applied_count": len(applied), "items": applied}
    return packet["lanhu_reused_background_assets"]


def _packet_id(project_id: str, design_id: str | None, version_id: str) -> str:
    raw = f"lanhu:{project_id}:{design_id}:{version_id}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _design_info(design: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    width = _num(design.get("width")) or _num(_lookup(payload, ["artboard.frame.width", "board.width", "style.width", "props.style.width"]))
    height = _num(design.get("height")) or _num(_lookup(payload, ["artboard.frame.height", "board.height", "style.height", "props.style.height"]))
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
    raw_w = _num(_lookup(payload, ["artboard.frame.width", "board.width", "style.width", "props.style.width"]))
    raw_h = _num(_lookup(payload, ["artboard.frame.height", "board.height", "style.height", "props.style.height"]))
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
    board_w = _num(_lookup(payload, ["artboard.frame.width", "board.width", "style.width", "props.style.width"]))
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
    row_dims = layer.get("rowDims") or {}
    style = layer.get("style") or {}
    props_style = (layer.get("props") or {}).get("style") or {}
    return {
        "x": _num(frame.get("x"), frame.get("left"), row_dims.get("x"), row_dims.get("left"), layer.get("x"), layer.get("left"), style.get("left"), props_style.get("left")) or 0,
        "y": _num(frame.get("y"), frame.get("top"), row_dims.get("y"), row_dims.get("top"), layer.get("y"), layer.get("top"), style.get("top"), props_style.get("top")) or 0,
        "width": _num(frame.get("width"), row_dims.get("width"), layer.get("width"), style.get("width"), props_style.get("width")) or 0,
        "height": _num(frame.get("height"), row_dims.get("height"), layer.get("height"), style.get("height"), props_style.get("height")) or 0,
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
    style = layer.get("style") or {}
    props_style = (layer.get("props") or {}).get("style") or {}
    fill_color = _color_value(
        _lookup(layer, ["fill.color", "style.fills.0.color", "fills.0.color"]) or style.get("backgroundColor") or props_style.get("backgroundColor")
    )
    opacity = _opacity(layer)
    result = {
        "opacity": opacity,
        "fill_color": fill_color,
        "corner_radius": _scaled_num(_lookup(layer, ["radius", "cornerRadius", "style.borderRadius", "props.style.borderRadius"]), scale),
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
    style = {**(props.get("style") or {}), **(layer.get("style") or {})}

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
    normalized_content = _clean_text_content(str(content))

    return {
        "content": normalized_content,
        "font_family": source_style.get("fontPostScriptName") or source_style.get("fontName") or source_style.get("fontFamily") or source_style.get("name"),
        "font_size": _scaled_num(source_style.get("size") or style.get("fontSize"), scale),
        "font_weight": source_style.get("fontWeight") or _font_weight(source_style.get("fontStyleName") or source_style.get("type")),
        "color": _color_value(source_style.get("color") or style.get("color")),
        "align": source_style.get("justification") or source_style.get("align") or style.get("textAlign"),
        "line_height": _scaled_num(_lookup(source_style, ["lineHeight.value", "leading"]) or style.get("lineHeight"), scale),
        "letter_spacing": source_style.get("tracking") or style.get("letterSpacing") or 0,
        "overflow": "clip",
        "wrap": "\n" in normalized_content,
    }


def _clean_text_content(value: str) -> str:
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).replace("\xa0", " ")


def _image_url(layer: dict[str, Any]) -> str | None:
    image = layer.get("image") or {}
    dds_image = layer.get("ddsImage") or {}
    images = layer.get("images") or {}
    data = layer.get("data") or {}
    props = layer.get("props") or {}
    style = layer.get("style") or {}
    props_style = props.get("style") or {}
    value = data.get("value")
    for candidate in (
        image.get("imageUrl"),
        image.get("svgUrl"),
        dds_image.get("imageUrl"),
        images.get("png_xxxhd"),
        images.get("svg"),
        props.get("src"),
        value if isinstance(value, str) and value.startswith("http") else None,
        style.get("backgroundImage"),
        props_style.get("backgroundImage"),
        style.get("background"),
        props_style.get("background"),
    ):
        cleaned = _clean_image_url(candidate)
        if cleaned:
            return cleaned
    return None


def _clean_image_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("url("):
        raw = raw[4:].strip()
        if raw.endswith(")"):
            raw = raw[:-1].strip()
        raw = raw.strip("\"'")
    match = re.search(r"https?://[^\s)'\"<>]+", raw)
    return match.group(0) if match else None


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
            "suggested_unity_path": f"Assets/DesignToUnity/Sprites/{file_stem}{ext}",
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
    identity_text = " ".join(
        str(part or "")
        for part in (
            node.get("id"),
            node.get("path"),
            node.get("unity_name_hint"),
            name,
            text,
        )
    ).lower()
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

    is_lanhu_design = design_info.get("provider") == "lanhu"
    component_canvas = screen_w <= 512 and screen_h <= 256
    strong_button_tokens = ("btn", "button", "按钮")
    action_button_tokens = (
        "confirm",
        "submit",
        "cancel",
        "ok",
        "play",
        "start",
        "close",
        "open",
        "buy",
        "claim",
        "purchase",
        "开始",
        "确定",
        "确认",
        "取消",
        "关闭",
        "继续",
        "领取",
        "购买",
    )
    physical_button_like_rect = (
        2.0 <= aspect <= 8.0
        and 28 <= height <= 120
        and width >= 80
        and (area_ratio <= 0.2 or component_canvas)
    )
    logical_button_like_rect = (
        is_lanhu_design
        and
        screen_w <= 512
        and 1.6 <= aspect <= 8.0
        and 8 <= height <= 42
        and width >= 20
        and area_ratio <= 0.08
    )
    button_like_rect = physical_button_like_rect or logical_button_like_rect
    action_button = node_type in {"image", "shape", "group"} and button_like_rect and _has_token(identity_text, action_button_tokens)
    if _has_token(identity_text, strong_button_tokens) or action_button:
        reasons = []
        if _has_token(identity_text, strong_button_tokens):
            reasons.append("name/action text suggests button")
        if button_like_rect:
            reasons.append("rect has button-like aspect and height")
        confidence = 0.88 if action_button and (component_canvas or logical_button_like_rect) else 0.86 if _has_token(identity_text, strong_button_tokens) else 0.62
        _add_semantic(candidates, "button_candidate", confidence, reasons)

    scrollbar_tokens = ("scrollbar", "scroll_bar", "scroll bar", "滚动条")
    scrollbar_handle_tokens = ("handle", "thumb", "knob", "滑块", "滑柄")
    if node_type in {"image", "shape", "group"} and _has_token(name, scrollbar_tokens):
        if _has_token(name, scrollbar_handle_tokens):
            _add_semantic(candidates, "scrollbar_handle_candidate", 0.92, ["name suggests scrollbar handle"])
        else:
            _add_semantic(candidates, "scrollbar_candidate", 0.9, ["name suggests scrollbar"])

    slider_tokens = ("slider", "slide", "thumb", "handle", "滑块", "拖动")
    progress_tokens = ("progress", "progressbar", "progress_bar", "loading", "percent", "percentage", "bar", "hp", "health", "exp", "xp", "energy", "stamina", "进度", "进度条", "加载", "血条", "生命", "经验", "能量", "体力")
    bar_like_rect = aspect >= 3.0 and 6 <= height <= 80 and width >= 60 and area_ratio <= 0.12
    if node_type in {"image", "shape", "group"} and (_has_token(name, slider_tokens) or _has_token(text, slider_tokens)):
        reasons = ["name/text suggests slider"]
        if bar_like_rect:
            reasons.append("rect has horizontal control-like proportions")
        _add_semantic(candidates, "slider_candidate", 0.84 if bar_like_rect else 0.72, reasons)
    elif node_type in {"image", "shape", "group"} and (
        _has_token(name, progress_tokens) or _has_token(text, progress_tokens)
    ):
        reasons = ["name/text suggests progress bar"]
        if bar_like_rect:
            reasons.append("rect has progress-bar-like proportions")
        _add_semantic(candidates, "progress_candidate", 0.8 if bar_like_rect else 0.66, reasons)
    elif node_type in {"image", "shape"} and bar_like_rect and y >= screen_h * 0.08:
        _add_semantic(candidates, "progress_candidate", 0.54, ["rect is a wide thin bar"])

    toggle_tokens = (
        "toggle",
        "switch",
        "checkbox",
        "check_box",
        "勾选",
        "复选",
        "开关",
    )
    toggle_part_tokens = (
        "track",
        "bg",
        "background",
        "fill",
        "checkmark",
        "tick",
        "knob",
        "thumb",
        "handle",
        "状态",
        "圆点",
    )
    toggle_like_rect = node_type in {"image", "shape", "group"} and width <= max(180, screen_w * 0.22) and height <= max(96, screen_h * 0.16)
    toggle_part = node_type in {"image", "shape"} and _has_token(name, toggle_part_tokens)
    if node_type in {"image", "shape", "group"} and not toggle_part and (_has_token(name, toggle_tokens) or _has_token(text, toggle_tokens)):
        reasons = ["name/text suggests toggle"]
        if toggle_like_rect:
            reasons.append("rect has toggle/checkbox-like size")
        _add_semantic(candidates, "toggle_candidate", 0.86 if toggle_like_rect else 0.72, reasons)

    radio_group_tokens = (
        "radiogroup",
        "radio_group",
        "radio-group",
        "radio group",
        "radiooptions",
        "radio_options",
        "radio-options",
        "radio options",
        "choicegroup",
        "choice_group",
        "choice-group",
        "choice group",
        "单选组",
        "单选列表",
        "选项组",
    )
    radio_item_tokens = (
        "radio_",
        "_radio",
        "radio-",
        "-radio",
        "radio",
        "choice_",
        "_choice",
        "choice-",
        "-choice",
        "单选",
    )
    if node_type == "group" and _has_token(name, radio_group_tokens):
        _add_semantic(candidates, "radio_group_candidate", 0.88, ["name suggests radio group"])
    elif node_type in {"image", "shape", "group"} and _has_token(name, radio_item_tokens):
        _add_semantic(candidates, "radio_candidate", 0.78, ["name suggests radio option"])

    tab_group_tokens = ("tabs", "tabbar", "tab_bar", "tabgroup", "tab_group", "页签", "标签栏")
    tab_item_tokens = ("tab_", "_tab", "tab-", "-tab", "页签", "标签")
    if node_type == "group" and _has_token(name, tab_group_tokens):
        _add_semantic(candidates, "tab_group_candidate", 0.88, ["name suggests tab group"])
    elif node_type in {"image", "shape", "group"} and _has_token(name, tab_item_tokens):
        _add_semantic(candidates, "tab_candidate", 0.78, ["name suggests tab item"])

    scroll_tokens = (
        "scroll",
        "scrollview",
        "scroll_view",
        "list",
        "grid",
        "滚动",
        "滑动区域",
        "列表",
    )
    scroll_like_rect = node_type == "group" and area_ratio >= 0.08 and (height >= screen_h * 0.25 or width >= screen_w * 0.35)
    if node_type == "group" and (_has_token(name, scroll_tokens) or (_has_token(text, scroll_tokens) and scroll_like_rect)):
        reasons = ["name/text suggests scrollable area"]
        if scroll_like_rect:
            reasons.append("group has scroll/list-like size")
        _add_semantic(candidates, "scroll_area_candidate", 0.82 if _has_token(name, scroll_tokens) else 0.62, reasons)

    input_tokens = (
        "input",
        "inputfield",
        "textinput",
        "textfield",
        "text_field",
        "search",
        "username",
        "password",
        "email",
        "placeholder",
        "输入",
        "文本框",
        "搜索",
        "昵称",
        "账号",
        "密码",
        "邮箱",
    )
    input_like_rect = 2.5 <= aspect <= 12.0 and 24 <= height <= 96 and width >= 90 and area_ratio <= 0.18
    if node_type in {"image", "shape", "group"} and (_has_token(name, input_tokens) or (_has_token(text, input_tokens) and input_like_rect)):
        reasons = ["name/text suggests text input"]
        if input_like_rect:
            reasons.append("rect has input-field-like proportions")
        _add_semantic(candidates, "input_candidate", 0.86 if input_like_rect else 0.72, reasons)

    dropdown_tokens = (
        "dropdown",
        "drop_down",
        "selectbox",
        "select_box",
        "picker",
        "combo",
        "combobox",
        "下拉",
        "选择器",
        "选项框",
    )
    dropdown_like_rect = 2.0 <= aspect <= 10.0 and 24 <= height <= 96 and width >= 90 and area_ratio <= 0.2
    if node_type in {"image", "shape", "group"} and (_has_token(name, dropdown_tokens) or (_has_token(text, dropdown_tokens) and dropdown_like_rect)):
        reasons = ["name/text suggests dropdown"]
        if dropdown_like_rect:
            reasons.append("rect has dropdown-like proportions")
        _add_semantic(candidates, "dropdown_candidate", 0.86 if dropdown_like_rect else 0.72, reasons)

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

    mask_tokens = ("mask", "clip", "clipping", "clip_rect", "cliprect", "裁剪", "蒙版", "遮罩")
    if node_type in {"group", "image", "shape", "mask"} and _has_token(name, mask_tokens):
        _add_semantic(candidates, "mask_candidate", 0.84, ["name suggests rectangular clipping/mask container"])

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
            "default_add_button": True,
            "raycast_target_if_interactive": True,
        }
    if node.get("semantic_type") == "toggle_candidate":
        toggle_value = _toggle_value_from_text(" ".join(part for part in (name, text) if part))
        node["unity_interaction_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "raycast_target_if_interactive": True,
        }
        node["unity_toggle_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "value": toggle_value,
            "graphic_node_id": None,
            "requires_review": False,
            "notes": [
                "Toggle was inferred from source layer naming or text.",
                "If graphic_node_id is empty, the Toggle component uses the target graphic as its state graphic.",
            ],
        }
    if node.get("semantic_type") == "tab_group_candidate":
        node["unity_tab_group_hint"] = {
            "can_add_toggle_group": True,
            "default_add_toggle_group": True,
            "allow_switch_off": False,
            "tab_node_ids": [],
            "notes": [
                "Tab group was inferred from source layer naming.",
                "Child tab candidates should use Toggle.m_Group to reference this ToggleGroup.",
            ],
        }
    if node.get("semantic_type") == "tab_candidate":
        node["unity_interaction_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "raycast_target_if_interactive": True,
        }
        node["unity_tab_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "group_node_id": None,
            "label_node_id": None,
            "value": _toggle_value_from_text(" ".join(part for part in (name, text) if part)),
            "requires_review": True,
            "notes": [
                "Tab item was inferred from source layer naming.",
                "Bind a ToggleGroup when a parent tab group can be identified.",
            ],
        }
    if node.get("semantic_type") == "radio_group_candidate":
        node["unity_radio_group_hint"] = {
            "can_add_toggle_group": True,
            "default_add_toggle_group": True,
            "allow_switch_off": False,
            "radio_node_ids": [],
            "notes": [
                "Radio group was inferred from source layer naming.",
                "Child radio candidates should use Toggle.m_Group to reference this ToggleGroup.",
            ],
        }
    if node.get("semantic_type") == "radio_candidate":
        node["unity_interaction_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "raycast_target_if_interactive": True,
        }
        node["unity_radio_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "group_node_id": None,
            "label_node_id": None,
            "value": _toggle_value_from_text(" ".join(part for part in (name, text) if part)),
            "requires_review": True,
            "notes": [
                "Radio option was inferred from source layer naming.",
                "Bind a ToggleGroup when a parent radio group can be identified.",
            ],
        }
    if node.get("semantic_type") == "mask_candidate":
        node["unity_mask_hint"] = {
            "can_add_rect_mask_2d": True,
            "default_add_rect_mask_2d": True,
            "recommended_unity_component": "RectMask2D",
            "requires_review": False,
            "notes": [
                "Mask candidate was inferred from source layer naming.",
                "RectMask2D represents rectangular UI clipping only; Photoshop bitmap/vector masks still require visual QA or rasterized export.",
            ],
        }
    if node.get("semantic_type") == "input_candidate":
        text_child = _first_descendant_with_text(node)
        placeholder_child = _first_placeholder_descendant(node) or text_child
        node["unity_interaction_hint"] = {
            "can_add_tmp_input_field": True,
            "default_add_tmp_input_field": True,
            "raycast_target_if_interactive": True,
        }
        node["unity_input_hint"] = {
            "can_add_tmp_input_field": True,
            "default_add_tmp_input_field": True,
            "text_component_node_id": (text_child or {}).get("id"),
            "placeholder_node_id": (placeholder_child or {}).get("id"),
            "text": ((text_child or {}).get("text") or {}).get("content"),
            "line_type": "single_line",
            "requires_review": not bool(text_child),
            "notes": [
                "TMP_InputField was inferred from source layer naming or text.",
                "Bind business validation and submit callbacks in Unity after import.",
            ],
        }
    if node.get("semantic_type") == "dropdown_candidate":
        caption_child = _first_descendant_with_text(node)
        node["unity_interaction_hint"] = {
            "can_add_tmp_dropdown": True,
            "default_add_tmp_dropdown": True,
            "raycast_target_if_interactive": True,
        }
        node["unity_dropdown_hint"] = {
            "can_add_tmp_dropdown": True,
            "default_add_tmp_dropdown": True,
            "template_node_id": None,
            "caption_text_node_id": (caption_child or {}).get("id"),
            "item_text_node_id": None,
            "options": [((caption_child or {}).get("text") or {}).get("content")] if caption_child else [],
            "value": 0,
            "requires_review": True,
            "notes": [
                "TMP_Dropdown was inferred from source layer naming or text.",
                "Bind template/item references when an expanded menu or option list exists in the design.",
            ],
        }
    if node.get("semantic_type") in {"progress_candidate", "slider_candidate"}:
        node["unity_interaction_hint"] = {
            "can_add_slider": True,
            "default_add_slider": True,
            "interactable": node.get("semantic_type") == "slider_candidate",
            "requires_fill_handle_review": True,
        }
    if node.get("semantic_type") == "scroll_area_candidate":
        node["unity_interaction_hint"] = {
            "can_add_scroll_rect": True,
            "default_add_scroll_rect": True,
            "requires_content_viewport_review": True,
        }
    if node.get("semantic_type") == "scrollbar_candidate":
        node["unity_interaction_hint"] = {
            "can_add_scrollbar": True,
            "default_add_scrollbar": True,
            "requires_handle_review": True,
        }


def _has_token(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _merge_overlapping_lanhu_text_fragments(root: dict[str, Any], design_info: dict[str, Any]) -> None:
    def visit(parent: dict[str, Any]) -> None:
        for child in parent.get("children") or []:
            if isinstance(child, dict):
                visit(child)

        children = parent.get("children") or []
        groups: dict[tuple[float, float, float, float], list[dict[str, Any]]] = {}
        for child in children:
            if not isinstance(child, dict) or child.get("type") != "text" or not _text_content(child):
                continue
            rect = child.get("global_rect") or {}
            key = (
                round(_num(rect.get("x")) or 0, 1),
                round(_num(rect.get("y")) or 0, 1),
                round(_num(rect.get("width")) or 0, 1),
                round(_num(rect.get("height")) or 0, 1),
            )
            groups.setdefault(key, []).append(child)

        merge_by_id: dict[str, dict[str, Any]] = {}
        merged_ids: set[str] = set()
        for key, items in groups.items():
            if len(items) < 2:
                continue
            merged = _merged_lanhu_rich_text_node(parent, items, design_info)
            if not merged:
                continue
            first_id = str(items[0].get("id") or "")
            if first_id:
                merge_by_id[first_id] = merged
            merged_ids.update(str(item.get("id") or "") for item in items)

        if not merge_by_id:
            return
        new_children: list[dict[str, Any]] = []
        for child in children:
            child_id = str(child.get("id") or "")
            if child_id in merge_by_id:
                new_children.append(merge_by_id[child_id])
            elif child_id not in merged_ids:
                new_children.append(child)
        parent["children"] = new_children

    visit(root)


def _merged_lanhu_rich_text_node(parent: dict[str, Any], items: list[dict[str, Any]], design_info: dict[str, Any]) -> dict[str, Any] | None:
    ordered = sorted(items, key=lambda node: int(_num(node.get("z_index"), 0) or 0))
    first = ordered[0]
    parent_id = str(parent.get("id") or "root")
    rect = dict(first.get("global_rect") or {})
    local_rect = dict(first.get("local_rect") or {})
    content, spans = _join_lanhu_text_fragments(ordered)
    if not content.strip():
        return None

    text = dict(first.get("text") or {})
    text["content"] = content
    text["spans"] = spans
    text["wrap"] = bool("\n" in content or any((node.get("text") or {}).get("wrap") for node in ordered))
    text["rich_text_source"] = "lanhu_overlapping_fragments"

    merged_id = f"{parent_id}_rich_text_{_hash([node.get('id') for node in ordered])[:8]}"
    merged = {
        **first,
        "id": merged_id,
        "parent_id": parent_id,
        "name": str(parent.get("name") or first.get("name") or "rich_text"),
        "unity_name_hint": _unity_name(int(_num(first.get("z_index"), 0) or 0), f"{parent.get('name') or 'rich_text'}_rich_text"),
        "path": f"{parent.get('path') or parent.get('name') or parent_id}/rich_text",
        "type": "text",
        "semantic_type": None,
        "semantic_confidence": None,
        "semantic_reasons": [],
        "global_rect": rect,
        "local_rect": local_rect,
        "unity_rect_hint": _unity_rect(local_rect),
        "style": dict(first.get("style") or {}),
        "text": text,
        "asset_ref": None,
        "children": [],
        "source_metadata": {
            **(first.get("source_metadata") or {}),
            "merged_text_fragments": [node.get("id") for node in ordered],
            "source": "lanhu_overlapping_fragments",
        },
    }
    merged["content_hash"] = _hash(
        {
            "rect": rect,
            "style": merged["style"],
            "text": text,
            "asset_ref": None,
        }
    )
    _apply_semantics(merged, design_info)
    merged["source_metadata"]["merged_text_fragments"] = [node.get("id") for node in ordered]
    merged["source_metadata"]["source"] = "lanhu_overlapping_fragments"
    return merged


def _join_lanhu_text_fragments(items: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    content = ""
    spans: list[dict[str, Any]] = []
    for node in items:
        text = node.get("text") if isinstance(node.get("text"), dict) else {}
        fragment = str(text.get("content") or "")
        if not fragment:
            continue
        separator = _lanhu_text_fragment_separator(content, fragment)
        content += separator
        start = len(content)
        content += fragment
        span = {
            "start": start,
            "length": len(fragment),
            "color": text.get("color"),
            "font_size": text.get("font_size"),
            "font_weight": text.get("font_weight"),
            "font_style": text.get("font_style"),
        }
        spans.append({key: value for key, value in span.items() if value is not None})
    return content, spans


def _lanhu_text_fragment_separator(current: str, fragment: str) -> str:
    if not current or not fragment:
        return ""
    if current[-1].isspace() or fragment[0].isspace():
        return ""
    if fragment[0] in ",.;:!?，。；：！？)]}":
        return ""
    if current[-1] in "([{":
        return ""
    if current[-1] in ",，;；:":
        return " "
    if current[-1].isalnum() and fragment[0].isalnum():
        return " "
    return ""


def _text_content(node: dict[str, Any]) -> str:
    text = node.get("text") if isinstance(node.get("text"), dict) else {}
    return str(text.get("content") or "")


def _attach_text_backed_button_hints(root: dict[str, Any], design_info: dict[str, Any]) -> None:
    nodes: list[dict[str, Any]] = []
    parent_by_obj: dict[int, dict[str, Any]] = {}

    def walk(node: dict[str, Any], parent: dict[str, Any] | None = None) -> None:
        nodes.append(node)
        if parent is not None:
            parent_by_obj[id(node)] = parent
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, node)

    walk(root)
    for text_node in nodes:
        if text_node.get("type") != "text" or not _button_action_label(text_node):
            continue
        candidate = parent_by_obj.get(id(text_node))
        depth = 0
        while candidate is not None and depth < 6:
            if _is_text_button_backing(candidate, text_node, design_info):
                _promote_semantic(
                    candidate,
                    "button_candidate",
                    0.9,
                    ["action text is placed inside a button-like backing node"],
                )
                candidate["unity_button_hint"] = {
                    "can_add_button": True,
                    "default_add_button": True,
                    "target_graphic_node_id": candidate.get("id"),
                    "label_node_id": text_node.get("id"),
                    "raycast_target_if_interactive": True,
                    "source": "text_backed_button_inference",
                }
                break
            candidate = parent_by_obj.get(id(candidate))
            depth += 1


def _button_action_label(node: dict[str, Any]) -> str | None:
    text = node.get("text") if isinstance(node.get("text"), dict) else {}
    content = str(text.get("content") or "").strip()
    if not content:
        return None
    lowered = content.lower()
    action_tokens = (
        "open",
        "buy",
        "claim",
        "free",
        "unlock",
        "get now",
        "领取",
        "购买",
        "打开",
        "免费",
        "解锁",
    )
    return content if _has_token(lowered, action_tokens) else None


def _is_text_button_backing(candidate: dict[str, Any], text_node: dict[str, Any], design_info: dict[str, Any]) -> bool:
    if candidate.get("type") not in {"image", "shape", "group"}:
        return False
    if not (candidate.get("asset_ref") or candidate.get("type") == "shape"):
        return False
    if candidate.get("semantic_type") in {
        "screen_root",
        "background_candidate",
        "panel_candidate",
        "dialog_candidate",
        "scroll_area_candidate",
        "scroll_viewport_candidate",
        "scroll_content_candidate",
        "slider_candidate",
        "progress_candidate",
    }:
        return False

    rect = candidate.get("global_rect") or {}
    text_rect = text_node.get("global_rect") or {}
    width = _num(rect.get("width")) or 0
    height = _num(rect.get("height")) or 0
    aspect = width / height if height else 0
    screen_w = _num(design_info.get("width")) or 0
    screen_h = _num(design_info.get("height")) or 0
    area_ratio = (width * height) / max(screen_w * screen_h, 1) if width and height else 0
    if screen_w <= 512:
        button_like_rect = 1.6 <= aspect <= 8.0 and 8 <= height <= 42 and width >= 20 and area_ratio <= 0.08
    else:
        button_like_rect = 2.0 <= aspect <= 8.0 and 28 <= height <= 120 and width >= 80 and area_ratio <= 0.2
    if not button_like_rect:
        return False

    x = _num(rect.get("x")) or 0
    y = _num(rect.get("y")) or 0
    tx = _num(text_rect.get("x")) or 0
    ty = _num(text_rect.get("y")) or 0
    tw = _num(text_rect.get("width")) or 0
    th = _num(text_rect.get("height")) or 0
    return bool(
        tx >= x - 2
        and ty >= y - 2
        and tx + tw <= x + width + 2
        and ty + th <= y + height + 2
        and abs((tx + tw / 2) - (x + width / 2)) <= width * 0.35
    )


def _promote_semantic(node: dict[str, Any], semantic_type: str, confidence: float, reasons: list[str]) -> None:
    candidates = list(node.get("semantic_candidates") or [])
    _add_semantic(candidates, semantic_type, confidence, reasons)
    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    primary = candidates[0] if candidates else None
    node["semantic_candidates"] = candidates
    node["semantic_type"] = primary["semantic_type"] if primary else None
    node["semantic_confidence"] = primary["confidence"] if primary else None
    node["semantic_reasons"] = primary["reasons"] if primary else []
    if primary and primary["confidence"] < 0.7:
        node["requires_semantic_review"] = True
    else:
        node.pop("requires_semantic_review", None)
    if node.get("semantic_type") == "button_candidate":
        node["unity_interaction_hint"] = {
            "can_add_button": True,
            "default_add_button": True,
            "raycast_target_if_interactive": True,
        }


def _toggle_value_from_text(text: str) -> bool | None:
    lowered = str(text or "").lower()
    if _has_token(lowered, ("off", "unchecked", "uncheck", "disabled", "false", "关", "未选")):
        return False
    if _has_token(lowered, ("on", "checked", "check", "selected", "true", "开", "选中", "勾选")):
        return True
    return None


def _first_descendant_with_text(node: dict[str, Any]) -> dict[str, Any] | None:
    for child in node.get("children") or []:
        if (child.get("text") or {}).get("content"):
            return child
        nested = _first_descendant_with_text(child)
        if nested:
            return nested
    return None


def _first_placeholder_descendant(node: dict[str, Any]) -> dict[str, Any] | None:
    for child in node.get("children") or []:
        haystack = " ".join(
            str(part or "")
            for part in (
                child.get("name"),
                child.get("path"),
                (child.get("text") or {}).get("content"),
            )
        ).lower()
        if _has_token(haystack, ("placeholder", "hint", "请输入", "输入", "占位")):
            return child
        nested = _first_placeholder_descendant(child)
        if nested:
            return nested
    return None


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


def _is_lanhu_reusable_background_row(node: dict[str, Any]) -> bool:
    rect = _rect_or_empty(node.get("global_rect"))
    width = rect["width"]
    height = rect["height"]
    return bool(
        node.get("children")
        and width > 0
        and height > 0
        and width >= height * 3
        and 8 <= height <= 80
    )


def _background_source_row(node: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    asset = assets.get(str(node.get("asset_ref") or ""))
    if not asset:
        return None
    rgb = _asset_main_rgb(asset)
    if rgb is None:
        return None
    return {"node": node, "asset": asset, "rgb": rgb}


def _asset_main_rgb(asset: dict[str, Any]) -> tuple[int, int, int] | None:
    local_path = str(asset.get("local_path") or "")
    if not local_path:
        return None
    path = Path(local_path).expanduser()
    if not path.exists():
        return None
    try:
        from PIL import Image

        image = Image.open(path).convert("RGBA")
    except Exception:
        return None
    width, height = image.size
    if not width or not height:
        return None
    left = int(width * 0.28)
    right = max(left + 1, int(width * 0.95))
    top = int(height * 0.2)
    bottom = max(top + 1, int(height * 0.8))
    pixels = []
    for _, _, r, g, b, a in _iter_rgba_pixels(image.crop((left, top, right, bottom))):
        if a > 32:
            pixels.append((r, g, b))
    if not pixels:
        return None
    return tuple(round(sum(pixel[index] for pixel in pixels) / len(pixels)) for index in range(3))  # type: ignore[return-value]


def _iter_rgba_pixels(image: Any):
    width, height = image.size
    data = image.load()
    for y in range(height):
        for x in range(width):
            r, g, b, a = data[x, y]
            yield x, y, r, g, b, a


def _style_rgb(node: dict[str, Any]) -> tuple[int, int, int] | None:
    style = node.get("style") if isinstance(node.get("style"), dict) else {}
    return _parse_rgb(style.get("fill_color"))


def _parse_rgb(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    numbers = [float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", value)]
    if len(numbers) < 3:
        return None
    return tuple(max(0, min(255, round(numbers[index]))) for index in range(3))  # type: ignore[return-value]


def _rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((a[index] - b[index]) ** 2 for index in range(3)) ** 0.5


def _similar_size(a: Any, b: Any) -> bool:
    rect_a = _rect_or_empty(a)
    rect_b = _rect_or_empty(b)
    width_tolerance = max(1.0, rect_a["width"] * 0.03)
    height_tolerance = max(1.0, rect_a["height"] * 0.05)
    return abs(rect_a["width"] - rect_b["width"]) <= width_tolerance and abs(rect_a["height"] - rect_b["height"]) <= height_tolerance


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

        existing_nine_slice_hint = asset.get("nine_slice_hint") if isinstance(asset.get("nine_slice_hint"), dict) else {}
        existing_border = existing_nine_slice_hint.get("border")
        inferred_border = None if existing_border else _infer_figma_nine_slice_border(asset, nodes, width, height)
        nine_slice_candidate = bool(existing_nine_slice_hint.get("candidate") or existing_border or is_button_like or is_panel_like)
        if inferred_border:
            nine_slice_candidate = True
        nine_slice_hint = {
            "candidate": nine_slice_candidate,
            "reason": existing_nine_slice_hint.get("reason")
            or (
                "explicit nine-slice border supplied by source export"
                if existing_border
                else "inferred from Figma corner radius / stroke for a stretchable UI sprite"
                if inferred_border
                else "button/panel-like sprite may benefit from a project-specific nine-slice rule"
                if nine_slice_candidate
                else "not a strong nine-slice candidate"
            ),
            "requires_review": bool(existing_nine_slice_hint.get("requires_review", False if (existing_border or inferred_border) else nine_slice_candidate)),
        }
        if existing_border:
            nine_slice_hint["border"] = existing_border
        elif inferred_border:
            nine_slice_hint["border"] = inferred_border
            nine_slice_hint["source"] = "figma_style_inference"
        asset.update(
            {
                "safe_file_name": asset.get("file_name"),
                "suggested_unity_folder": f"Assets/DesignToUnity/{folder}",
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
                "nine_slice_hint": nine_slice_hint,
            }
        )


def _infer_figma_nine_slice_border(
    asset: dict[str, Any],
    nodes: list[dict[str, Any]],
    width: float,
    height: float,
) -> dict[str, float] | None:
    if asset.get("source_provider") != "figma" or not width or not height:
        return None
    if asset.get("usage") == "design_reference" or asset.get("is_large_background"):
        return None
    source_node = next((node for node in nodes if isinstance(node.get("style"), dict)), None)
    if not source_node:
        return None
    style = source_node.get("style") or {}
    semantic_type = source_node.get("semantic_type")
    is_stretchable = semantic_type in {
        "button_candidate",
        "progress_candidate",
        "slider_candidate",
        "toggle_candidate",
        "tab_candidate",
        "radio_candidate",
        "input_candidate",
        "dropdown_candidate",
        "manual_prefab_candidate",
        "panel_candidate",
        "dialog_candidate",
        "list_item_candidate",
    }
    name = " ".join(str(value or "").lower() for value in (asset.get("name"), source_node.get("name"), source_node.get("path")))
    if not is_stretchable and not _has_token(name, ("button", "btn", "panel", "card", "dialog", "modal", "window", "popup", "按钮", "面板", "卡片")):
        return None

    corner = _corner_radius_value(style.get("corner_radius"))
    border_size = _num((style.get("border") or {}).get("size")) if isinstance(style.get("border"), dict) else None
    if not corner and not border_size:
        return None
    logical_border = max(_num(corner, 0) or 0, (_num(border_size, 0) or 0) * 2)
    if logical_border <= 0:
        return None
    scale = max(0.1, _num(asset.get("scale"), 1) or 1)
    physical_width = max(width * scale, width)
    physical_height = max(height * scale, height)
    border = min(logical_border * scale, max(0, physical_width / 2 - 1), max(0, physical_height / 2 - 1))
    if border <= 0:
        return None
    value = round(border, 2)
    return {"left": value, "right": value, "top": value, "bottom": value}


def _corner_radius_value(value: Any) -> float | None:
    if isinstance(value, dict):
        candidates = [value.get(key) for key in ("top_left", "topRight", "top_left_radius", "x", "value")]
        numeric = [_num(item) for item in candidates]
        numeric = [item for item in numeric if item is not None]
        return max(numeric) if numeric else None
    if isinstance(value, (list, tuple)):
        numeric = [_num(item) for item in value]
        numeric = [item for item in numeric if item is not None]
        return max(numeric) if numeric else None
    return _num(value)


def enrich_delivery_metadata(
    root_node: dict[str, Any],
    design_info: dict[str, Any],
    assets: dict[str, dict[str, Any]] | None = None,
    provider: str | None = None,
) -> None:
    asset_lookup = assets or {}
    default_parent_global = {"x": 0, "y": 0}

    def walk(node: dict[str, Any], parent_global: dict[str, float]) -> dict[str, float]:
        node_global = _rect_or_empty(node.get("global_rect"))
        child_bounds = [walk(child, node_global) for child in node.get("children") or []]
        own_bounds = _own_visual_bounds(node)
        bounds = own_bounds
        if child_bounds and (node.get("type") == "group" or not node.get("asset_ref")):
            bounds = _union_visual_rect([own_bounds, *child_bounds])
        node["visual_bounds"] = bounds
        render_rect = {
            "x": round(bounds["x"] - (parent_global.get("x") or 0), 1),
            "y": round(bounds["y"] - (parent_global.get("y") or 0), 1),
            "width": bounds["width"],
            "height": bounds["height"],
        }
        node["render_rect"] = render_rect
        node["unity_render_rect_hint"] = _unity_rect(render_rect)
        node["render_strategy"] = _render_strategy_for_node(node, asset_lookup)
        node["source_semantics"] = _source_semantics_for_node(node, provider)
        return bounds

    walk(root_node, default_parent_global)


def _own_visual_bounds(node: dict[str, Any]) -> dict[str, float]:
    rect = _rect_or_empty(node.get("global_rect"))
    left = rect["x"]
    top = rect["y"]
    right = rect["x"] + rect["width"]
    bottom = rect["y"] + rect["height"]
    style = node.get("style") or {}
    reasons: list[str] = []

    border = style.get("border") if isinstance(style.get("border"), dict) else {}
    border_size = _num(border.get("size")) or 0
    if border_size > 0:
        expand = border_size / 2
        left -= expand
        top -= expand
        right += expand
        bottom += expand
        reasons.append("border expands visual bounds")

    shadow = style.get("shadow") if isinstance(style.get("shadow"), dict) else None
    if shadow:
        left, top, right, bottom = _expand_for_shadow(left, top, right, bottom, shadow)
        reasons.append("shadow expands visual bounds")

    blur = style.get("blur") if isinstance(style.get("blur"), dict) else None
    blur_radius = _num((blur or {}).get("radius")) or 0
    if blur and blur.get("affects_bounds") and blur_radius > 0:
        left -= blur_radius
        top -= blur_radius
        right += blur_radius
        bottom += blur_radius
        reasons.append("layer blur expands visual bounds")

    text_effects = ((node.get("text") or {}).get("effects") or {}) if isinstance(node.get("text"), dict) else {}
    outline = text_effects.get("outline") if isinstance(text_effects.get("outline"), dict) else {}
    outline_width = _num(outline.get("width")) or 0
    if outline_width > 0:
        left -= outline_width
        top -= outline_width
        right += outline_width
        bottom += outline_width
        reasons.append("text outline expands visual bounds")
    text_shadow = text_effects.get("shadow") if isinstance(text_effects.get("shadow"), dict) else None
    if text_shadow:
        shadow_payload = dict(text_shadow)
        offset = text_shadow.get("offset") if isinstance(text_shadow.get("offset"), dict) else {}
        shadow_payload.setdefault("x", offset.get("x"))
        shadow_payload.setdefault("y", offset.get("y"))
        left, top, right, bottom = _expand_for_shadow(left, top, right, bottom, shadow_payload)
        reasons.append("text shadow expands visual bounds")

    bounds = {
        "x": round(left, 1),
        "y": round(top, 1),
        "width": round(max(0, right - left), 1),
        "height": round(max(0, bottom - top), 1),
    }
    if bounds != rect:
        node["visual_bounds_reasons"] = reasons
    return bounds


def _render_strategy_for_node(node: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    semantic_type = node.get("semantic_type")
    node_type = node.get("type")
    asset = assets.get(str(node.get("asset_ref") or ""))
    text = node.get("text") or {}
    source_metadata = node.get("source_metadata") or {}
    unsupported_features = list(source_metadata.get("unsupported_psd_features") or [])
    unsupported_features.extend(source_metadata.get("unsupported_figma_features") or [])
    reasons: list[str] = []
    components: list[str] = []
    mode = "metadata_only"
    asset_required = False
    editable = False
    preserve_children = bool(node.get("children"))
    requires_review = bool(node.get("requires_semantic_review"))

    manual_tags = _node_manual_tags(node)
    if "ignore" in manual_tags or semantic_type == "ignored_by_designer" or (node.get("unity_ignore") or {}).get("enabled"):
        return {
            "mode": "metadata_only",
            "target": "unity",
            "recommended_components": [],
            "asset_required": False,
            "asset_ref": node.get("asset_ref"),
            "editable": False,
            "preserve_children": False,
            "requires_review": False,
            "reasons": ["explicit manual tag tells Unity writers to skip this node"],
        }

    component_map = {
        "button_candidate": ["Image", "Button"],
        "progress_candidate": ["Image", "Slider"],
        "slider_candidate": ["Image", "Slider"],
        "toggle_candidate": ["Image", "Toggle"],
        "tab_group_candidate": ["ToggleGroup"],
        "tab_candidate": ["Image", "Toggle"],
        "radio_group_candidate": ["ToggleGroup"],
        "radio_candidate": ["Image", "Toggle"],
        "input_candidate": ["Image", "TMP_InputField"],
        "dropdown_candidate": ["Image", "TMP_Dropdown"],
        "scroll_area_candidate": ["ScrollRect", "RectMask2D"],
        "scrollbar_candidate": ["Image", "Scrollbar"],
        "scroll_viewport_candidate": ["RectMask2D"],
        "mask_candidate": ["RectMask2D"],
    }
    if semantic_type in component_map:
        components.extend(component_map[semantic_type])
        reasons.append(f"semantic_type {semantic_type} maps to Unity UI components")

    if node.get("unity_layout_hint"):
        component = (node.get("unity_layout_hint") or {}).get("component")
        if component:
            components.append(str(component))
            reasons.append("layout geometry maps to a Unity LayoutGroup")
    if node.get("unity_layout_element_hint"):
        components.append("LayoutElement")
        reasons.append("Figma auto-layout child sizing maps to a Unity LayoutElement")

    if semantic_type == "screen_root":
        mode = "container"
        components.append("RectTransform")
        reasons.append("screen root is a structural container")
    elif text.get("content") and not node.get("asset_ref"):
        mode = "editable_text"
        components.append("TextMeshProUGUI")
        editable = True
        reasons.append("node has editable text metadata and no raster asset")
    elif node.get("unity_layout_hint") and node.get("children") and not node.get("asset_ref"):
        mode = "layout_container"
        reasons.append("node should preserve child structure as a Unity layout container")
    elif unsupported_features:
        mode = "rasterized_group_image" if node.get("children") else "export_image"
        asset_required = bool(node.get("asset_ref"))
        requires_review = True
        reasons.append("source uses complex features: " + ", ".join(sorted(set(unsupported_features))))
    elif node.get("asset_ref"):
        asset_required = True
        if node.get("children"):
            mode = "rasterized_group_image"
            reasons.append("node has a raster asset and nested source structure")
        elif semantic_type in component_map:
            mode = "sprite_with_component"
            reasons.append("sprite should remain visible while Unity component handles behavior")
        else:
            mode = "sprite_image"
            reasons.append("node has a source image asset")
    elif semantic_type in component_map:
        mode = "interactive_container"
        reasons.append("component candidate can be created from structure and child refs")
    elif node_type == "shape":
        mode = "component_drawable"
        components.append("Image")
        editable = True
        reasons.append("shape has no raster asset and can be approximated with Unity Image")
    elif node.get("children"):
        mode = "container"
        components.append("RectTransform")
        reasons.append("node groups child layers")
    else:
        reasons.append("node carries metadata but no direct visual output")

    style = node.get("style") or {}
    if style.get("shadow"):
        components.append("Shadow")
        requires_review = True
        reasons.append("shadow may need Unity Shadow or raster fallback")
    if style.get("blur"):
        requires_review = True
        reasons.append("blur should use rendered asset export or visual diff for exact fidelity")
    blend_mode = str(style.get("blend_mode") or "").upper()
    if blend_mode not in {"", "NORMAL", "PASS_THROUGH"}:
        requires_review = True
        reasons.append("non-normal blend mode may not match Unity UI Image blending")
    if style.get("border"):
        reasons.append("border may need sprite/nine-slice or custom renderer")
    if asset and (asset.get("nine_slice_hint") or {}).get("candidate"):
        reasons.append("asset is a nine-slice candidate")

    components = _unique_preserve_order([component for component in components if component])
    return {
        "mode": mode,
        "target": "unity",
        "recommended_components": components,
        "asset_required": asset_required,
        "asset_ref": node.get("asset_ref"),
        "editable": editable,
        "preserve_children": preserve_children,
        "requires_review": requires_review,
        "reasons": _unique_preserve_order(reasons),
    }


def _source_semantics_for_node(node: dict[str, Any], provider: str | None) -> dict[str, Any]:
    hints = {
        key: node.get(key)
        for key in (
            "unity_interaction_hint",
            "unity_button_hint",
            "unity_slider_hint",
            "unity_toggle_hint",
            "unity_tab_group_hint",
            "unity_tab_hint",
            "unity_radio_group_hint",
            "unity_radio_hint",
            "unity_input_hint",
            "unity_dropdown_hint",
            "unity_mask_hint",
            "unity_layout_hint",
            "unity_layout_element_hint",
            "unity_anchor_hint",
            "unity_scroll_hint",
            "unity_scrollbar_hint",
            "unity_text_hint",
            "component_variant_hint",
            "variant_group_hint",
            "figma_interaction_hint",
            "unity_navigation_hint",
        )
        if node.get(key)
    }
    candidates = list(node.get("semantic_candidates") or [])
    reason_text = " ".join(node.get("semantic_reasons") or [])
    manual_tags = _node_manual_tags(node)
    explicit = "explicit" in reason_text.lower() or bool(manual_tags)
    source_metadata = node.get("source_metadata") or {}
    source_features = {
        key: source_metadata.get(key)
        for key in (
            "psd_layer_kind",
            "psd_layer_kind_normalized",
            "psd_blend_mode_normalized",
            "photoshop_layer_kind",
            "rasterized_export",
            "has_mask",
            "has_vector_mask",
            "has_clipping_mask",
            "has_layer_effects",
            "uses_non_normal_blend_mode",
            "is_smart_object",
            "is_adjustment_layer",
            "unsupported_psd_features",
            "unsupported_figma_features",
            "recommended_fidelity_mode",
            "figma_effects",
            "figma_type",
            "component_id",
            "component_set_id",
            "component_properties",
            "component_property_definitions",
            "variant_properties",
            "variant_axes",
            "prototype_reactions",
            "styles",
            "constraints",
            "blend_mode",
            "has_complex_effects",
            "has_mask",
            "layout_mode",
            "layout_align",
            "layout_grow",
            "layout_positioning",
            "layout_sizing_horizontal",
            "layout_sizing_vertical",
            "clips_content",
            "manual_tags",
        )
        if key in source_metadata
    }
    figma_features = {
        key: source_metadata.get(key)
        for key in (
            "figma_node_id",
            "figma_file_key",
            "figma_type",
            "component_id",
            "component_set_id",
            "variant_properties",
            "variant_axes",
            "prototype_reactions",
            "layout_mode",
            "constraints",
            "layout_align",
            "layout_grow",
            "layout_positioning",
            "layout_sizing_horizontal",
            "layout_sizing_vertical",
            "blend_mode",
            "figma_effects",
            "unsupported_figma_features",
            "has_complex_effects",
            "has_mask",
            "styles",
            "manual_tags",
        )
        if source_metadata.get(key) not in (None, {}, [])
    }
    return {
        "provider": provider or source_metadata.get("source_provider"),
        "primary": node.get("semantic_type"),
        "confidence": node.get("semantic_confidence"),
        "candidates": candidates,
        "reasons": node.get("semantic_reasons") or [],
        "manual_tags": manual_tags,
        "inference": {
            "automatic": bool(candidates),
            "explicit": explicit,
            "name_or_text_based": any("name" in str(reason).lower() or "text" in str(reason).lower() for reason in node.get("semantic_reasons") or []),
            "layout_inferred": "unity_layout_hint" in hints,
            "component_based": bool(source_metadata.get("component_id") or node.get("component_variant_hint") or node.get("variant_group_hint")),
            "variant_based": bool(source_metadata.get("variant_properties") or node.get("variant_group_hint")),
            "component_hints": sorted(hints.keys()),
        },
        "component_hints": hints,
        "source_features": source_features,
        "figma": figma_features,
    }


def attach_reusable_prefab_registry(packet: dict[str, Any]) -> None:
    """Attach stable prefab reuse hints without changing the source tree shape."""
    assets = {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}
    all_nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        all_nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    for root in packet.get("nodes") or []:
        walk(root)

    for node in all_nodes:
        node.pop("reusable_prefab_key", None)
        node.pop("reusable_prefab", None)

    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for node in all_nodes:
        descriptor = _reusable_prefab_descriptor(node, assets)
        if not descriptor:
            continue
        grouped.setdefault(descriptor["key"], []).append((descriptor, node))

    reusable_prefabs = []
    reused_node_count = 0
    for key, items in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        first_descriptor = items[0][0]
        definition_node = items[0][1]
        node_ids = [str(node.get("id")) for _, node in items]
        instance_count = len(items)
        is_reused = instance_count > 1
        suggested_name = _reusable_prefab_name(first_descriptor)
        suggested_path = f"Assets/DesignToUnity/Reusable/{first_descriptor['category']}/{suggested_name}.prefab"
        entry = {
            "key": key,
            "category": first_descriptor["category"],
            "semantic_type": first_descriptor.get("semantic_type"),
            "render_strategy_mode": first_descriptor.get("render_strategy_mode"),
            "signature_hash": first_descriptor["signature_hash"],
            "definition_node_id": definition_node.get("id"),
            "instance_node_ids": node_ids,
            "instance_count": instance_count,
            "suggested_prefab_name": suggested_name,
            "suggested_prefab_asset_path": suggested_path,
            "reuse_policy": {
                "mode": "create_once_then_instantiate",
                "definition": "first_occurrence",
                "instance_overrides": first_descriptor.get("instance_override_policy") or [],
            },
            "match_basis": first_descriptor.get("match_basis") or [],
            "variant_properties": first_descriptor.get("variant_properties") or {},
            "variant_override_fields": [
                item for item in (first_descriptor.get("instance_override_policy") or []) if str(item).startswith("figma.variant.")
            ],
            "reasons": first_descriptor.get("reasons") or [],
        }
        if is_reused:
            reusable_prefabs.append(entry)
            reused_node_count += instance_count

        for index, (descriptor, node) in enumerate(items):
            role = "definition" if is_reused and index == 0 else "instance" if is_reused else "unique"
            marker = {
                "candidate": True,
                "is_reused": is_reused,
                "key": key,
                "category": descriptor["category"],
                "instance_role": role,
                "definition_node_id": definition_node.get("id"),
                "instance_count": instance_count,
                "suggested_prefab_name": suggested_name,
                "suggested_prefab_asset_path": suggested_path,
                "match_basis": descriptor.get("match_basis") or [],
                "instance_overrides": _reusable_instance_overrides(node, descriptor.get("strip_text_content")),
                "variant_properties": descriptor.get("variant_properties") or {},
                "variant_override_fields": [
                    item for item in (descriptor.get("instance_override_policy") or []) if str(item).startswith("figma.variant.")
                ],
                "reasons": descriptor.get("reasons") or [],
            }
            if role == "instance":
                marker["instantiate_from_node_id"] = definition_node.get("id")
            node["reusable_prefab_key"] = key
            node["reusable_prefab"] = marker

    packet["reusable_prefabs"] = reusable_prefabs
    packet["reusable_prefab_summary"] = {
        "candidate_node_count": sum(len(items) for items in grouped.values()),
        "unique_candidate_group_count": len(grouped),
        "reused_group_count": len(reusable_prefabs),
        "reused_node_count": reused_node_count,
        "policy": "Use reusable_prefab.key to save the first definition node as a prefab, then instantiate later nodes with rect/text overrides.",
    }
    _attach_prefab_variant_registry(packet, all_nodes)


def _attach_prefab_variant_registry(packet: dict[str, Any], all_nodes: list[dict[str, Any]]) -> None:
    for node in all_nodes:
        node.pop("prefab_variant", None)

    reusable_by_key = {
        str(entry.get("key")): entry
        for entry in packet.get("reusable_prefabs") or []
        if entry.get("key")
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for node in all_nodes:
        metadata = node.get("source_metadata") or {}
        variant_properties = metadata.get("variant_properties")
        if not isinstance(variant_properties, dict) or not variant_properties:
            continue
        reuse = node.get("reusable_prefab") or {}
        reusable_key = node.get("reusable_prefab_key") or reuse.get("key")
        component_id = metadata.get("component_id")
        group_key = str(reusable_key or component_id or metadata.get("component_set_id") or "")
        if not group_key:
            continue
        grouped.setdefault(group_key, []).append(node)

    variant_groups: list[dict[str, Any]] = []
    for group_key, nodes in sorted(grouped.items()):
        distinct: dict[str, dict[str, Any]] = {}
        for node in nodes:
            properties = (node.get("source_metadata") or {}).get("variant_properties") or {}
            signature = json_like_signature(properties)
            distinct.setdefault(signature, node)
        if len(distinct) < 2 and not any((node.get("source_metadata") or {}).get("component_set_id") for node in nodes):
            continue

        reusable_entry = reusable_by_key.get(group_key)
        first = nodes[0]
        metadata = first.get("source_metadata") or {}
        base_prefab_path = reusable_entry.get("suggested_prefab_asset_path") if reusable_entry else None
        category = (reusable_entry or {}).get("category") or _reusable_prefab_category(first, None)
        group_hash = _hash({"group_key": group_key, "variants": sorted(distinct)})[:16]
        suggested_dir = f"Assets/DesignToUnity/Variants/{sanitize_filename(str(category), 'Variants')}"
        axes = _variant_axes_for_nodes(nodes)
        variants = []
        for signature, node in sorted(distinct.items(), key=lambda item: item[0]):
            properties = (node.get("source_metadata") or {}).get("variant_properties") or {}
            variant_hash = _hash({"group": group_hash, "variant": properties})[:12]
            variant_name = sanitize_filename(_variant_prefab_name(first, properties, variant_hash), f"Variant_{variant_hash}")
            variant_path = f"{suggested_dir}/{variant_name}.prefab"
            variant_entry = {
                "key": f"variant_{variant_hash}",
                "signature": signature,
                "node_id": node.get("id"),
                "source_node_id": (node.get("source_metadata") or {}).get("source_node_id"),
                "variant_properties": dict(sorted(properties.items())),
                "suggested_prefab_name": variant_name,
                "suggested_prefab_asset_path": variant_path,
                "base_prefab_asset_path": base_prefab_path,
                "overrides": (node.get("reusable_prefab") or {}).get("instance_overrides") or [],
            }
            variants.append(variant_entry)
            node["prefab_variant"] = {
                "candidate": True,
                "group_key": f"pvg_{group_hash}",
                "variant_key": variant_entry["key"],
                "base_prefab_asset_path": base_prefab_path,
                "suggested_prefab_asset_path": variant_path,
                "variant_properties": variant_entry["variant_properties"],
                "unity_strategy": "prefab_variant_asset",
            }

        variant_groups.append(
            {
                "key": f"pvg_{group_hash}",
                "provider": ((packet.get("source") or {}).get("provider") or "unknown"),
                "source": "source_metadata.variant_properties",
                "reusable_prefab_key": group_key if group_key in reusable_by_key else None,
                "component_id": metadata.get("component_id"),
                "component_set_id": metadata.get("component_set_id"),
                "category": category,
                "definition_node_id": (reusable_entry or {}).get("definition_node_id"),
                "base_prefab_asset_path": base_prefab_path,
                "suggested_variant_dir": suggested_dir,
                "variant_axes": axes,
                "variant_count": len(variants),
                "variant_property_keys": [axis["name"] for axis in axes],
                "unity_strategy": "prefab_variant_assets",
                "requires_editor_importer": True,
                "variants": variants,
                "reasons": [
                    "Figma component variant properties were grouped into Unity prefab variant candidates.",
                    "Use the reusable prefab definition as the base prefab, then save each distinct variant signature as a prefab variant asset.",
                ],
            }
        )

    packet["prefab_variant_groups"] = variant_groups
    packet["prefab_variant_summary"] = {
        "group_count": len(variant_groups),
        "variant_count": sum(len(group.get("variants") or []) for group in variant_groups),
        "policy": "Create prefab variant assets from reusable prefab definitions when Figma variant properties produce distinct signatures.",
    }


def json_like_signature(value: Any) -> str:
    if isinstance(value, dict):
        return "|".join(f"{key}={json_like_signature(item)}" for key, item in sorted(value.items()))
    if isinstance(value, list):
        return "[" + ",".join(json_like_signature(item) for item in value) + "]"
    return str(value)


def _variant_axes_for_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values_by_axis: dict[str, set[str]] = {}
    definitions: dict[str, dict[str, Any]] = {}
    for node in nodes:
        hint = node.get("variant_group_hint") or {}
        for axis in hint.get("variant_axes") or []:
            if isinstance(axis, dict) and axis.get("name"):
                definitions[str(axis["name"])] = axis
        properties = (node.get("source_metadata") or {}).get("variant_properties")
        if not isinstance(properties, dict):
            continue
        for key, value in properties.items():
            values_by_axis.setdefault(str(key), set()).add(str(value))

    result = []
    for name in sorted(values_by_axis):
        definition = definitions.get(name) or {}
        result.append(
            {
                "name": name,
                "values": sorted(values_by_axis[name]),
                "source_options": definition.get("variant_options") or definition.get("values") or [],
            }
        )
    return result


def _variant_prefab_name(node: dict[str, Any], properties: dict[str, Any], fallback_hash: str) -> str:
    base = str(node.get("semantic_type") or node.get("name") or "PrefabVariant")
    slots = [f"{key}_{value}" for key, value in sorted(properties.items())]
    if not slots:
        slots = [fallback_hash]
    return f"{base}_{'_'.join(slots)}"


def _reusable_prefab_descriptor(node: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    node_id = str(node.get("id") or "")
    semantic_type = node.get("semantic_type")
    if not node_id or semantic_type in _NON_REUSABLE_SEMANTICS:
        return None
    if node.get("visible") is False:
        return None

    asset = assets.get(str(node.get("asset_ref") or ""))
    if asset and asset.get("usage") == "design_reference":
        return None
    if asset and asset.get("is_large_background") and semantic_type not in _REUSABLE_COMPONENT_SEMANTICS:
        return None

    render_strategy = node.get("render_strategy") or {}
    source_metadata = node.get("source_metadata") or {}
    variant_properties = source_metadata.get("variant_properties") if isinstance(source_metadata.get("variant_properties"), dict) else {}
    mode = render_strategy.get("mode")
    has_text = bool((node.get("text") or {}).get("content"))
    has_asset = bool(node.get("asset_ref"))
    has_children = bool(node.get("children"))
    is_component = semantic_type in _REUSABLE_COMPONENT_SEMANTICS
    is_structural = semantic_type in _REUSABLE_STRUCTURAL_SEMANTICS
    is_asset_reusable = bool(
        asset
        and (
            asset.get("is_icon_like")
            or asset.get("is_button_like")
            or (asset.get("nine_slice_hint") or {}).get("candidate")
            or semantic_type in _REUSABLE_STRUCTURAL_SEMANTICS
        )
    )
    is_text_reusable = has_text and not has_asset and not has_children
    if not (is_component or is_structural or is_asset_reusable or is_text_reusable):
        return None

    strip_text_content = bool(is_component or semantic_type in {"tab_candidate", "radio_candidate"})
    signature = _node_reuse_signature(node, assets, is_root=True, strip_text_content=strip_text_content)
    signature_hash = _hash(signature)[:16]
    key = f"rpf_{signature_hash}"
    category = _reusable_prefab_category(node, asset)
    match_basis = _unique_preserve_order(
        [
            "semantic_type" if semantic_type else None,
            "render_strategy" if mode else None,
            "asset_signature" if has_asset else None,
            "size" if (node.get("render_rect") or node.get("local_rect") or node.get("global_rect")) else None,
            "style" if node.get("style") else None,
            "child_structure" if has_children else None,
            "text_style" if has_text else None,
        ]
    )
    reasons = []
    if is_component:
        reasons.append(f"{semantic_type} can be turned into a reusable Unity UI prefab")
    if is_structural:
        reasons.append(f"{semantic_type} can be reused as a structural/visual prefab")
    if is_asset_reusable:
        reasons.append("asset flags indicate icon/button/nine-slice reuse potential")
    if strip_text_content:
        reasons.append("text content is treated as an instance override for component reuse")
    if variant_properties:
        reasons.append("Figma component properties are treated as variant instance overrides")
    if is_text_reusable:
        reasons.append("standalone editable text can be reused when the text style and content match")

    instance_override_policy = ["rect", "text.content"] if strip_text_content else ["rect"]
    for key in sorted(variant_properties):
        instance_override_policy.append(f"figma.variant.{key}")

    return {
        "key": key,
        "category": category,
        "semantic_type": semantic_type,
        "render_strategy_mode": mode,
        "signature_hash": signature_hash,
        "signature": signature,
        "strip_text_content": strip_text_content,
        "instance_override_policy": _unique_preserve_order(instance_override_policy),
        "variant_properties": variant_properties,
        "match_basis": match_basis,
        "reasons": _unique_preserve_order(reasons),
    }


def _node_reuse_signature(
    node: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    is_root: bool,
    strip_text_content: bool,
) -> dict[str, Any]:
    rect = _rect_or_empty(node.get("render_rect") or node.get("local_rect") or node.get("global_rect"))
    rect_signature = {
        "width": rect["width"],
        "height": rect["height"],
    }
    if not is_root:
        rect_signature["x"] = rect["x"]
        rect_signature["y"] = rect["y"]

    asset = assets.get(str(node.get("asset_ref") or ""))
    text = node.get("text") or {}
    source_metadata = node.get("source_metadata") or {}
    child_strip_text = strip_text_content or node.get("semantic_type") in _REUSABLE_COMPONENT_SEMANTICS
    return _compact_signature(
        {
            "type": node.get("type"),
            "semantic_type": node.get("semantic_type"),
            "figma_component_id": source_metadata.get("component_id"),
            "figma_variant_slots": sorted((source_metadata.get("variant_properties") or {}).keys()) if isinstance(source_metadata.get("variant_properties"), dict) else None,
            "render_strategy_mode": (node.get("render_strategy") or {}).get("mode"),
            "recommended_components": sorted((node.get("render_strategy") or {}).get("recommended_components") or []),
            "rect": rect_signature,
            "asset": _asset_reuse_signature(asset) if asset else None,
            "style": _signature_payload(node.get("style")),
            "text": _text_reuse_signature(text, include_content=not strip_text_content),
            "component_hints": _component_hint_signature(node),
            "children": [
                _node_reuse_signature(child, assets, is_root=False, strip_text_content=child_strip_text)
                for child in node.get("children") or []
            ],
        }
    )


def _asset_reuse_signature(asset: dict[str, Any] | None) -> dict[str, Any] | None:
    if not asset:
        return None
    content_hash = asset.get("content_hash") or asset.get("file_hash")
    return _compact_signature(
        {
            "content_hash": content_hash,
            "source": None if content_hash else asset.get("remote_url") or asset.get("file_name") or asset.get("id"),
            "format": asset.get("format"),
            "logical_size": asset.get("logical_size"),
            "size": asset.get("size"),
            "nine_slice_hint": asset.get("nine_slice_hint"),
            "usage": asset.get("usage"),
        }
    )


def _text_reuse_signature(text: dict[str, Any], include_content: bool) -> dict[str, Any] | None:
    if not isinstance(text, dict) or not text:
        return None
    signature = {
        "content": text.get("content") if include_content else None,
        "font_family": text.get("font_family"),
        "font_size": text.get("font_size"),
        "font_style": text.get("font_style"),
        "font_weight": text.get("font_weight"),
        "color": text.get("color"),
        "align": text.get("align"),
        "vertical_align": text.get("vertical_align"),
        "line_height": text.get("line_height"),
        "letter_spacing": text.get("letter_spacing"),
        "effects": _signature_payload(text.get("effects")),
        "multi_style_runs": _signature_payload(text.get("multi_style_runs")),
    }
    if not include_content and text.get("content"):
        signature["content_override_slot"] = True
    return _compact_signature(signature)


def _component_hint_signature(node: dict[str, Any]) -> dict[str, Any] | None:
    hints = (node.get("source_semantics") or {}).get("component_hints") or {}
    if not isinstance(hints, dict):
        return None
    return _compact_signature({key: _signature_payload(value) for key, value in sorted(hints.items())})


def _signature_payload(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in sorted(value.items()):
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in {
                "id",
                "node_id",
                "parent_id",
                "source_node_id",
                "source_path",
                "path",
                "rect",
                "hit_rect",
                "global_rect",
                "local_rect",
                "render_rect",
                "visual_bounds",
                "label",
                "variant_properties",
            }:
                continue
            if lowered.endswith("_id") or lowered.endswith("_ids") or lowered.endswith("_path"):
                continue
            result[key_text] = _signature_payload(item)
        return _compact_signature(result)
    if isinstance(value, list):
        return [_signature_payload(item) for item in value if item is not None]
    if isinstance(value, float):
        return round(value, 4)
    return value


def _compact_signature(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: compacted
            for key, item in value.items()
            if (compacted := _compact_signature(item)) not in (None, {}, [])
        }
    if isinstance(value, list):
        return [compacted for item in value if (compacted := _compact_signature(item)) not in (None, {}, [])]
    return value


def _reusable_prefab_category(node: dict[str, Any], asset: dict[str, Any] | None) -> str:
    semantic_type = node.get("semantic_type")
    if semantic_type == "manual_prefab_candidate":
        return "ManualPrefabs"
    if semantic_type == "button_candidate":
        return "Buttons"
    if semantic_type in {"progress_candidate", "slider_candidate"}:
        return "Sliders"
    if semantic_type in {"toggle_candidate", "tab_candidate", "radio_candidate", "tab_group_candidate", "radio_group_candidate"}:
        return "Toggles"
    if semantic_type == "input_candidate":
        return "Inputs"
    if semantic_type == "dropdown_candidate":
        return "Dropdowns"
    if semantic_type in {"scroll_area_candidate", "scroll_viewport_candidate", "scroll_content_candidate", "scrollbar_candidate"}:
        return "Scroll"
    if semantic_type == "list_item_candidate":
        return "ListItems"
    if semantic_type == "mask_candidate":
        return "Masks"
    if semantic_type in {"panel_candidate", "dialog_candidate"}:
        return "Panels"
    if semantic_type == "icon_candidate" or (asset and asset.get("is_icon_like")):
        return "Icons"
    if node.get("type") == "text":
        return "Texts"
    return "Visuals"


def _reusable_prefab_name(descriptor: dict[str, Any]) -> str:
    semantic = str(descriptor.get("semantic_type") or descriptor.get("category") or "Prefab")
    return sanitize_filename(f"{semantic}_{descriptor['signature_hash']}", "ReusablePrefab")


def _reusable_instance_overrides(node: dict[str, Any], include_text: bool | None) -> list[dict[str, Any]]:
    overrides = [
        {
            "field": "rect",
            "source": "node.render_rect",
            "value": node.get("render_rect") or node.get("local_rect"),
        }
    ]
    if include_text:
        overrides.extend(_text_override_slots(node))
    source_metadata = node.get("source_metadata") or {}
    variant_properties = source_metadata.get("variant_properties") if isinstance(source_metadata.get("variant_properties"), dict) else {}
    for key, value in sorted(variant_properties.items()):
        overrides.append(
            {
                "field": f"figma.variant.{key}",
                "source": "source_metadata.variant_properties",
                "value": value,
            }
        )
    return [_compact_signature(override) for override in overrides]


def _text_override_slots(node: dict[str, Any]) -> list[dict[str, Any]]:
    slots = []

    def walk(current: dict[str, Any]) -> None:
        text = current.get("text") or {}
        if text.get("content"):
            slots.append(
                {
                    "field": "text.content",
                    "node_id": current.get("id"),
                    "path": current.get("path"),
                    "value": text.get("content"),
                }
            )
        for child in current.get("children") or []:
            walk(child)

    walk(node)
    return slots


def _expand_for_shadow(left: float, top: float, right: float, bottom: float, shadow: dict[str, Any]) -> tuple[float, float, float, float]:
    offset_x = _num(shadow.get("x"), shadow.get("offset_x"), shadow.get("offsetX")) or 0
    offset_y = _num(shadow.get("y"), shadow.get("offset_y"), shadow.get("offsetY")) or 0
    blur = _num(shadow.get("blur"), shadow.get("radius"), shadow.get("size")) or 0
    spread = _num(shadow.get("spread")) or 0
    expand = max(0, blur + spread)
    return (
        min(left, left + offset_x) - expand,
        min(top, top + offset_y) - expand,
        max(right, right + offset_x) + expand,
        max(bottom, bottom + offset_y) + expand,
    )


def _rect_or_empty(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    return {
        "x": round(_num(value.get("x")) or 0, 1),
        "y": round(_num(value.get("y")) or 0, 1),
        "width": round(max(0, _num(value.get("width")) or 0), 1),
        "height": round(max(0, _num(value.get("height")) or 0), 1),
    }


def _union_visual_rect(rects: list[dict[str, Any]]) -> dict[str, float]:
    valid = [_rect_or_empty(rect) for rect in rects if (_num((rect or {}).get("width")) or 0) > 0 and (_num((rect or {}).get("height")) or 0) > 0]
    if not valid:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    left = min(rect["x"] for rect in valid)
    top = min(rect["y"] for rect in valid)
    right = max(rect["x"] + rect["width"] for rect in valid)
    bottom = max(rect["y"] + rect["height"] for rect in valid)
    return {"x": round(left, 1), "y": round(top, 1), "width": round(right - left, 1), "height": round(bottom - top, 1)}


def _manual_semantic_tags(name: Any) -> list[str]:
    text = str(name or "")
    tags = re.findall(r"[@#]([a-zA-Z][\w-]*)", text)
    bracket_tags = re.findall(r"\[([a-zA-Z][\w-]*)\]", text)
    return sorted({tag.lower() for tag in tags + bracket_tags if tag})


def _node_manual_tags(node: dict[str, Any]) -> list[str]:
    metadata = node.get("source_metadata") if isinstance(node.get("source_metadata"), dict) else {}
    values: list[Any] = []
    values.extend(_manual_semantic_tags(node.get("name")))
    metadata_tags = metadata.get("manual_tags") if metadata else None
    if isinstance(metadata_tags, list):
        values.extend(metadata_tags)
    elif isinstance(metadata_tags, str):
        values.extend(item for item in re.split(r"[,\s]+", metadata_tags) if item)
    return sorted({str(value).strip().lower().lstrip("@#") for value in values if str(value).strip()})


def _unique_preserve_order(values: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for value in values:
        marker = repr(value)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


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
    raw = _lookup(layer, ["blendOptions.opacity.value", "opacity", "style.opacity", "props.style.opacity"])
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

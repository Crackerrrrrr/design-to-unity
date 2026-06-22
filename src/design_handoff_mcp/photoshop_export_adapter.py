from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .asset_store import _image_size, sanitize_filename
from .normalizer import _add_semantic, _apply_semantics, _enrich_assets, _hash, _semantic_summary, _unity_rect
from .profiles import build_handoff_profiles
from .psd_adapter import _attach_dropdown_hints, _attach_input_hints, _attach_layout_hints, _attach_mask_hint, _attach_radio_hints, _attach_scroll_hints, _attach_slider_hints, _attach_tab_hints, _attach_text_hints, _normalize_text_payload


class PhotoshopExportAdapterError(RuntimeError):
    pass


def photoshop_export_schema() -> dict[str, Any]:
    return {
        "schema": "design-to-unity.photoshop-export",
        "schema_version": 1,
        "manifest_names": ["design.json", "manifest.json", "export.json"],
        "required_files": ["design.json or compatible manifest JSON"],
        "recommended_files": ["preview.png", "assets/*.png"],
        "document_fields": {
            "name": "Design or document name.",
            "width": "Document pixel width before optional scale normalization.",
            "height": "Document pixel height before optional scale normalization.",
            "scale": "Optional numeric scale. Defaults to 1.",
            "preview": "Optional flattened Photoshop preview/reference image path.",
            "layers": "Array of root layer objects. Also accepts children or nodes.",
        },
        "layer_fields": {
            "id": "Stable Photoshop layer id. Strongly recommended.",
            "name": "Layer name. Used for Unity object names and semantic detection.",
            "kind": "pixel, group, type, shape, smartobject, placedlayer, levels, etc.",
            "bounds": "Object with x/y/width/height or left/top/right/bottom; arrays are accepted.",
            "asset": "Relative or absolute path to exported PNG/JPG/WebP for image/group layers.",
            "nine_slice": "Optional nine-slice data, for example {'border': {'left': 16, 'right': 16, 'top': 12, 'bottom': 12}}. Also accepts nineSlice, spriteBorder, or sprite_border.",
            "text": "String or object with content/fontSize/color/alignment plus optional fontFamily/fontStyle/fontWeight/lineHeight/letterSpacing/spans/stroke/dropShadow/tmpFontAssetGuid for editable TMP text.",
            "children": "Nested layers. Also accepts layers or nodes.",
            "role": "Optional explicit semantic_type, for example button_candidate or slider_candidate.",
            "opacity": "0..1, 0..100, or 0..255.",
            "blendMode": "Photoshop blend mode.",
            "hasMask": "Boolean or object/list describing layer mask.",
            "hasVectorMask": "Boolean or object/list describing vector mask.",
            "clipping": "Boolean clipping indicator.",
            "effects": "Layer effects object/list.",
            "rasterized": "Boolean. If true, the layer/group is treated as one Photoshop-rendered asset and nested children are ignored.",
        },
        "sample": {
            "document": {
                "name": "ShopPanel",
                "width": 1170,
                "height": 540,
                "scale": 1,
                "preview": "preview.png",
                "layers": [
                    {
                        "id": "bg",
                        "name": "bg",
                        "kind": "pixel",
                        "bounds": {"x": 0, "y": 0, "width": 1170, "height": 540},
                        "asset": "assets/bg.png",
                    },
                    {
                        "id": "btn_start",
                        "name": "btn_start",
                        "kind": "pixel",
                        "role": "button_candidate",
                        "bounds": {"x": 120, "y": 420, "width": 240, "height": 88},
                        "asset": "assets/btn_start.png",
                    },
                ],
            }
        },
    }


def validate_photoshop_export(export_path: str) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    try:
        manifest_path = _manifest_path(export_path)
    except Exception as exc:
        return {
            "status": "invalid",
            "errors": [{"code": "manifest_not_found", "message": str(exc)}],
            "warnings": [],
            "counts": {},
            "schema": photoshop_export_schema(),
        }

    export_dir = manifest_path.parent
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "invalid",
            "manifest_path": str(manifest_path),
            "export_dir": str(export_dir),
            "errors": [{"code": "manifest_json_invalid", "message": str(exc)}],
            "warnings": [],
            "counts": {},
            "schema": photoshop_export_schema(),
        }

    document = _document(manifest)
    width = _num(document.get("width")) or _num(manifest.get("width"))
    height = _num(document.get("height")) or _num(manifest.get("height"))
    if not width or width <= 0:
        errors.append({"code": "missing_document_width", "path": "document.width", "message": "Document width must be greater than zero."})
    if not height or height <= 0:
        errors.append({"code": "missing_document_height", "path": "document.height", "message": "Document height must be greater than zero."})
    if not (document.get("name") or manifest.get("name")):
        warnings.append({"code": "missing_document_name", "path": "document.name", "message": "Document name is missing; export directory name will be used."})

    reference_value = _pick(manifest, ("preview", "preview_path", "reference", "reference_path")) or _pick(document, ("preview", "preview_path", "reference", "reference_path"))
    reference_path = _resolve_optional_path(export_dir, reference_value)
    if not reference_path:
        warnings.append({"code": "missing_preview_reference", "path": "document.preview", "message": "No flattened preview/reference image was declared; visual diff will not be available."})
    elif not reference_path.exists():
        errors.append({"code": "preview_reference_not_found", "path": "document.preview", "message": f"Preview/reference image not found: {reference_path}"})

    layers = _root_layers(manifest, document)
    if not layers:
        errors.append({"code": "missing_layers", "path": "document.layers", "message": "No root layers found. Expected layers, children, or nodes array."})

    ids: dict[str, str] = {}
    counts = {
        "layer_count": 0,
        "asset_layer_count": 0,
        "text_layer_count": 0,
        "group_layer_count": 0,
        "missing_asset_count": 0,
        "missing_bounds_count": 0,
        "complex_feature_layer_count": 0,
    }
    for index, layer in enumerate(layers):
        _validate_export_layer(
            layer=layer,
            export_dir=export_dir,
            path=f"document.layers[{index}]",
            ids=ids,
            errors=errors,
            warnings=warnings,
            counts=counts,
        )

    status = "invalid" if errors else "valid_with_warnings" if warnings else "valid"
    return {
        "status": status,
        "manifest_path": str(manifest_path),
        "export_dir": str(export_dir),
        "document": {
            "name": document.get("name") or manifest.get("name") or export_dir.name,
            "width": width,
            "height": height,
            "scale": _num(document.get("scale")) or _num(manifest.get("scale")) or 1,
            "preview_path": str(reference_path) if reference_path else None,
        },
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
        "schema": photoshop_export_schema(),
        "next_steps": [
            "Fix all errors before calling psd_design_prepare_export_packet.",
            "Keep preview.png for visual diff QA.",
            "Use explicit role fields for known controls such as button_candidate, slider_candidate, and scroll_area_candidate.",
        ],
    }


def make_photoshop_export_packet(
    export_path: str,
    target: str = "unity",
    scale: float | None = None,
) -> dict[str, Any]:
    manifest_path = _manifest_path(export_path)
    export_dir = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    document = _document(manifest)
    detected_scale = scale or _num(document.get("scale")) or _num(manifest.get("scale")) or 1.0
    if detected_scale <= 0:
        raise ValueError("scale must be greater than zero")

    design_name = str(document.get("name") or manifest.get("name") or export_dir.name or "PhotoshopExport")
    width = _num(document.get("width")) or _num(manifest.get("width")) or 0
    height = _num(document.get("height")) or _num(manifest.get("height")) or 0
    design_info = {
        "name": design_name,
        "width": round(width / detected_scale, 1),
        "height": round(height / detected_scale, 1),
        "scale": detected_scale,
        "unit": "px",
        "coordinate_system": "top-left",
        "source_image_url": None,
    }
    packet_id = _packet_id(manifest_path, manifest, target, detected_scale)
    assets: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []

    reference_path = _resolve_optional_path(export_dir, _pick(manifest, ("preview", "preview_path", "reference", "reference_path")) or _pick(document, ("preview", "preview_path", "reference", "reference_path")))
    if reference_path and reference_path.exists():
        design_info["reference_asset_ref"] = _register_export_asset(
            assets=assets,
            name=f"{design_name}_reference",
            local_path=reference_path,
            rect={"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]},
            scale=detected_scale,
            usage="design_reference",
            source_node_id=None,
        )

    root_node = {
        "id": "root",
        "parent_id": None,
        "name": design_name,
        "unity_name_hint": _unity_name(0, design_name),
        "path": design_name,
        "type": "group",
        "semantic_type": "screen_root",
        "semantic_confidence": 1,
        "semantic_reasons": ["Photoshop export document root"],
        "visible": True,
        "z_index": 0,
        "global_rect": {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]},
        "local_rect": {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]},
        "unity_rect_hint": _unity_rect({"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]}),
        "style": {"opacity": 1},
        "children": [],
        "source_metadata": {
            "source_provider": "photoshop_export",
            "source_node_id": "root",
            "source_path": design_name,
        },
    }

    z_counter = [1]
    for layer in _root_layers(manifest, document):
        node = _normalize_export_layer(
            layer=layer,
            parent_id="root",
            parent_path=design_name,
            parent_global={"x": 0, "y": 0},
            export_dir=export_dir,
            assets=assets,
            warnings=warnings,
            z_counter=z_counter,
            scale=detected_scale,
            design_info=design_info,
        )
        if node:
            root_node["children"].append(node)

    _attach_text_hints(root_node, warnings)
    _attach_slider_hints(root_node, warnings)
    _attach_scroll_hints(root_node, warnings)
    _attach_layout_hints(root_node, warnings)
    _attach_input_hints(root_node, warnings)
    _attach_dropdown_hints(root_node, warnings)
    _attach_tab_hints(root_node, warnings)
    _attach_radio_hints(root_node, warnings)
    _enrich_assets(assets, root_node, design_info)
    packet = {
        "packet_id": packet_id,
        "source": {
            "provider": "psd",
            "file_path": str(manifest_path),
            "file_name": manifest_path.name,
            "export_dir": str(export_dir),
            "file_hash": _file_sha1(manifest_path),
            "mtime_ns": manifest_path.stat().st_mtime_ns,
            "schema_source": "photoshop-uxp",
            "rasterize_mode": "photoshop-export",
        },
        "design": design_info,
        "nodes": [root_node],
        "assets": list(assets.values()),
        "semantic_map": _semantic_summary(root_node),
        "handoff_profiles": build_handoff_profiles(design_info),
        "target": target,
        "warnings": warnings,
        "asset_export": {
            "asset_dir": str(export_dir),
            "results": [
                {"id": asset.get("id"), "path": asset.get("local_path"), "status": asset.get("download_status")}
                for asset in assets.values()
            ],
        },
    }
    packet["asset_download"] = packet["asset_export"]
    return packet


def _normalize_export_layer(
    layer: dict[str, Any],
    parent_id: str,
    parent_path: str,
    parent_global: dict[str, float],
    export_dir: Path,
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
    z_counter: list[int],
    scale: float,
    design_info: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(layer, dict) or layer.get("visible") is False:
        return None

    raw_name = str(layer.get("name") or layer.get("id") or layer.get("type") or "Layer")
    z_index = z_counter[0]
    z_counter[0] += 1
    node_id = _node_id(layer, z_index)
    path = f"{parent_path}/{raw_name}" if parent_path else raw_name
    global_rect = _scaled_rect(_rect_of(layer), scale)
    rasterized_export = _is_rasterized_export(layer)
    children_nodes = []
    for child in [] if rasterized_export else _children(layer):
        child_node = _normalize_export_layer(
            layer=child,
            parent_id=node_id,
            parent_path=path,
            parent_global={"x": global_rect["x"], "y": global_rect["y"]},
            export_dir=export_dir,
            assets=assets,
            warnings=warnings,
            z_counter=z_counter,
            scale=scale,
            design_info=design_info,
        )
        if child_node:
            children_nodes.append(child_node)

    if (global_rect["width"] <= 0 or global_rect["height"] <= 0) and children_nodes:
        global_rect = _union_rect([child["global_rect"] for child in children_nodes])
    local_rect = {
        "x": round(global_rect["x"] - parent_global["x"], 1),
        "y": round(global_rect["y"] - parent_global["y"], 1),
        "width": global_rect["width"],
        "height": global_rect["height"],
    }
    text = _text_info(layer, scale)
    layer_type = _node_type(layer, bool(children_nodes), bool(text))
    asset_ref = None
    asset_path = _resolve_optional_path(export_dir, _pick(layer, ("asset_path", "assetPath", "asset", "png", "image", "image_path", "imagePath")))
    if asset_path and asset_path.exists() and global_rect["width"] > 0 and global_rect["height"] > 0 and not text:
        asset_ref = _register_export_asset(
            assets=assets,
            name=raw_name,
            local_path=asset_path,
            rect=global_rect,
                scale=scale,
                usage=layer_type if layer_type in {"image", "shape", "text"} else "image",
                source_node_id=node_id,
                nine_slice_hint=_nine_slice_hint(layer, scale),
            )
        if layer_type == "unknown":
            layer_type = "image"
    elif asset_path and not asset_path.exists():
        warnings.append(
            {
                "node_id": node_id,
                "code": "missing_asset",
                "severity": "high",
                "message": f"Photoshop export asset not found for layer '{raw_name}': {asset_path}",
            }
        )

    style = _style_info(layer)
    feature_info = _feature_info(layer, style)
    _append_feature_warnings(raw_name, node_id, feature_info, warnings)
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
        "style": style,
        "text": text,
        "asset_ref": asset_ref,
        "children": children_nodes,
        "source_metadata": {
            "source_provider": "photoshop_export",
            "source_node_id": node_id,
            "source_path": path,
            "photoshop_layer_kind": layer.get("kind") or layer.get("type"),
            "photoshop_layer_name": raw_name,
            "rasterized_export": rasterized_export,
            **feature_info,
        },
    }
    node["content_hash"] = _hash(
        {
            "rect": global_rect,
            "style": style,
            "text": text,
            "asset_ref": asset_ref,
            "children": [child.get("content_hash") for child in children_nodes],
        }
    )
    _apply_semantics(node, design_info)
    _apply_explicit_semantics(node, layer)
    return node


def _validate_export_layer(
    layer: dict[str, Any],
    export_dir: Path,
    path: str,
    ids: dict[str, str],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    counts: dict[str, int],
) -> None:
    if not isinstance(layer, dict):
        errors.append({"code": "layer_not_object", "path": path, "message": "Layer entry must be an object."})
        return
    if layer.get("visible") is False:
        return

    counts["layer_count"] += 1
    name = str(layer.get("name") or layer.get("id") or layer.get("type") or "")
    layer_id = layer.get("id") or layer.get("layer_id") or layer.get("layerId")
    if layer_id is None:
        warnings.append({"code": "missing_layer_id", "path": path, "message": f"Layer '{name or path}' has no stable id; a hash id will be generated."})
    else:
        layer_id_text = str(layer_id)
        if layer_id_text in ids:
            errors.append({"code": "duplicate_layer_id", "path": path, "message": f"Layer id '{layer_id_text}' already used at {ids[layer_id_text]}."})
        ids[layer_id_text] = path
    if not name:
        warnings.append({"code": "missing_layer_name", "path": path, "message": "Layer has no name; id/type fallback will be used."})

    rasterized_export = _is_rasterized_export(layer)
    children = [] if rasterized_export else _children(layer)
    text = _text_info(layer, scale=1)
    rect = _rect_of(layer)
    if rect["width"] <= 0 or rect["height"] <= 0:
        counts["missing_bounds_count"] += 1
        if not children:
            errors.append({"code": "missing_layer_bounds", "path": path, "message": f"Layer '{name or path}' has no positive bounds."})
        else:
            warnings.append({"code": "group_bounds_inferred", "path": path, "message": f"Group '{name or path}' has no positive bounds; bounds will be inferred from children."})

    layer_type = _node_type(layer, bool(children), bool(text))
    if children:
        counts["group_layer_count"] += 1
    elif rasterized_export:
        counts["group_layer_count"] += 1
    if text:
        counts["text_layer_count"] += 1
    asset_value = _pick(layer, ("asset_path", "assetPath", "asset", "png", "image", "image_path", "imagePath"))
    asset_path = _resolve_optional_path(export_dir, asset_value)
    if asset_path:
        counts["asset_layer_count"] += 1
        if not asset_path.exists():
            counts["missing_asset_count"] += 1
            errors.append({"code": "layer_asset_not_found", "path": path, "message": f"Layer asset not found for '{name or path}': {asset_path}"})
    elif layer_type in {"image", "shape"} and not children:
        warnings.append({"code": "image_layer_without_asset", "path": path, "message": f"Image/shape layer '{name or path}' has no exported asset path."})
    if layer_type == "text" and not (text or {}).get("content"):
        errors.append({"code": "text_layer_missing_content", "path": path, "message": f"Text layer '{name or path}' has no text content."})

    feature_info = _feature_info(layer, _style_info(layer))
    if feature_info.get("unsupported_psd_features"):
        counts["complex_feature_layer_count"] += 1
        warnings.append(
            {
                "code": "complex_psd_feature",
                "path": path,
                "features": feature_info.get("unsupported_psd_features"),
                "message": f"Layer '{name or path}' uses complex Photoshop features; keep exported PNG/group rasterization and run visual diff.",
            }
        )

    for index, child in enumerate(children):
        _validate_export_layer(
            layer=child,
            export_dir=export_dir,
            path=f"{path}.layers[{index}]",
            ids=ids,
            errors=errors,
            warnings=warnings,
            counts=counts,
        )


def _is_rasterized_export(layer: dict[str, Any]) -> bool:
    return bool(_pick_bool(layer, ("rasterized", "rasterized_export", "rasterizedExport", "flattened", "flattenedGroup")))


def _manifest_path(export_path: str) -> Path:
    path = Path(export_path).expanduser().resolve()
    if path.is_file():
        return path
    if not path.is_dir():
        raise FileNotFoundError(f"Photoshop export path not found: {path}")
    for name in ("design.json", "manifest.json", "export.json"):
        candidate = path / name
        if candidate.exists():
            return candidate
    candidates = sorted(path.glob("*.json"))
    if not candidates:
        raise FileNotFoundError(f"No Photoshop export manifest JSON found in: {path}")
    return candidates[0]


def _document(manifest: dict[str, Any]) -> dict[str, Any]:
    for key in ("document", "design", "artboard"):
        value = manifest.get(key)
        if isinstance(value, dict):
            return value
    return manifest


def _root_layers(manifest: dict[str, Any], document: dict[str, Any]) -> list[dict[str, Any]]:
    for owner in (document, manifest):
        for key in ("layers", "children", "nodes"):
            value = owner.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _children(layer: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("children", "layers", "nodes"):
        value = layer.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _node_type(layer: dict[str, Any], has_children: bool, has_text: bool) -> str:
    if has_children:
        return "group"
    kind = _normalize_token(layer.get("kind") or layer.get("type") or layer.get("layerType"))
    if has_text or kind in {"type", "text", "textlayer"}:
        return "text"
    if kind in {"shape", "solidcolorfill", "gradientfill", "rectangle", "oval"}:
        return "shape"
    if kind in {"pixel", "image", "bitmap", "smartobject", "placedlayer"}:
        return "image"
    if _pick(layer, ("asset_path", "assetPath", "asset", "png", "image", "image_path", "imagePath")):
        return "image"
    return "unknown"


def _rect_of(layer: dict[str, Any]) -> dict[str, float]:
    for key in ("bounds", "bbox", "frame", "rect", "global_rect", "globalRect"):
        value = layer.get(key)
        rect = _rect_from_value(value)
        if rect:
            return rect
    x = _num(layer.get("x"))
    y = _num(layer.get("y"))
    width = _num(layer.get("width"))
    height = _num(layer.get("height"))
    if x is not None and y is not None and width is not None and height is not None:
        return {"x": x, "y": y, "width": max(0, width), "height": max(0, height)}
    return {"x": 0, "y": 0, "width": 0, "height": 0}


def _rect_from_value(value: Any) -> dict[str, float] | None:
    if isinstance(value, dict):
        if all(key in value for key in ("left", "top", "right", "bottom")):
            left = _num(value.get("left")) or 0
            top = _num(value.get("top")) or 0
            right = _num(value.get("right")) or 0
            bottom = _num(value.get("bottom")) or 0
            return {"x": left, "y": top, "width": max(0, right - left), "height": max(0, bottom - top)}
        x = _num(value.get("x"))
        y = _num(value.get("y"))
        width = _num(value.get("width"))
        height = _num(value.get("height"))
        if x is not None and y is not None and width is not None and height is not None:
            return {"x": x, "y": y, "width": max(0, width), "height": max(0, height)}
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        a, b, c, d = [_num(item) or 0 for item in value[:4]]
        if c >= a and d >= b:
            return {"x": a, "y": b, "width": max(0, c - a), "height": max(0, d - b)}
        return {"x": a, "y": b, "width": max(0, c), "height": max(0, d)}
    return None


def _style_info(layer: dict[str, Any]) -> dict[str, Any]:
    style = layer.get("style") if isinstance(layer.get("style"), dict) else {}
    opacity = _num(layer.get("opacity"))
    if opacity is None:
        opacity = _num(style.get("opacity"))
    if opacity is None:
        opacity = 1
    if opacity > 1:
        opacity = opacity / 100 if opacity <= 100 else opacity / 255
    blend_mode = layer.get("blend_mode") or layer.get("blendMode") or style.get("blend_mode") or style.get("blendMode")
    result = {
        "opacity": round(max(0, min(1, opacity)), 3),
        "blend_mode": str(blend_mode) if blend_mode else None,
    }
    return {key: value for key, value in result.items() if value is not None}


def _text_info(layer: dict[str, Any], scale: float) -> dict[str, Any] | None:
    raw = layer.get("text")
    if raw is None:
        raw = layer.get("text_data") or layer.get("textData")
    if raw is None:
        return None
    if isinstance(raw, str):
        content = raw
        text_style: dict[str, Any] = {}
    elif isinstance(raw, dict):
        content = raw.get("content") or raw.get("value") or raw.get("text")
        text_style = raw
    else:
        return None
    if content is None:
        return None
    return _normalize_text_payload(str(content), text_style, scale)


def _feature_info(layer: dict[str, Any], style: dict[str, Any]) -> dict[str, Any]:
    kind = _normalize_token(layer.get("kind") or layer.get("type") or layer.get("layerType"))
    blend_mode = _normalize_blend_mode(style.get("blend_mode") or layer.get("blendMode"))
    has_mask = bool(_pick_bool(layer, ("has_mask", "hasMask", "mask", "layer_mask", "layerMask")))
    has_vector_mask = bool(_pick_bool(layer, ("has_vector_mask", "hasVectorMask", "vector_mask", "vectorMask")))
    has_clipping_mask = bool(_pick_bool(layer, ("has_clipping_mask", "hasClippingMask", "clipping", "clipped")))
    has_layer_effects = bool(_pick_bool(layer, ("has_layer_effects", "hasLayerEffects", "effects", "layerEffects")))
    is_smart_object = bool(_pick_bool(layer, ("is_smart_object", "isSmartObject", "smart_object", "smartObject"))) or kind in {"smartobject", "placedlayer"}
    is_adjustment_layer = bool(_pick_bool(layer, ("is_adjustment_layer", "isAdjustmentLayer", "adjustment"))) or _is_adjustment_layer_kind(kind)
    uses_non_normal_blend = bool(blend_mode and blend_mode not in {"", "normal", "pass through", "passthrough", "pass_through"})
    unsupported = []
    if has_mask:
        unsupported.append("mask")
    if has_vector_mask:
        unsupported.append("vector_mask")
    if has_clipping_mask:
        unsupported.append("clipping_mask")
    if has_layer_effects:
        unsupported.append("layer_effects")
    if uses_non_normal_blend:
        unsupported.append("blend_mode")
    if is_smart_object:
        unsupported.append("smart_object")
    if is_adjustment_layer:
        unsupported.append("adjustment_layer")
    return {
        "psd_layer_kind_normalized": kind,
        "psd_blend_mode_normalized": blend_mode,
        "has_mask": has_mask,
        "has_vector_mask": has_vector_mask,
        "has_clipping_mask": has_clipping_mask,
        "has_layer_effects": has_layer_effects,
        "uses_non_normal_blend_mode": uses_non_normal_blend,
        "is_smart_object": is_smart_object,
        "is_adjustment_layer": is_adjustment_layer,
        "unsupported_psd_features": unsupported,
        "recommended_fidelity_mode": "group_or_document_rasterize" if unsupported else "layer",
    }


def _append_feature_warnings(name: str, node_id: str, feature_info: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    warning_map = [
        ("has_mask", "psd_mask_requires_review", "Layer uses a Photoshop mask; verify Unity output or rasterize the group."),
        ("has_vector_mask", "psd_mask_requires_review", "Layer uses a Photoshop vector mask; verify Unity output or rasterize the group."),
        ("has_clipping_mask", "psd_clipping_mask_requires_review", "Layer uses clipping; verify Unity output or rasterize the clipped group."),
        ("uses_non_normal_blend_mode", "psd_blend_mode_requires_review", "Layer uses a non-normal Photoshop blend mode; Unity Image blending may not match."),
        ("is_smart_object", "psd_smart_object_rasterized", "Layer is a smart object or placed layer; the exported PNG is used as the visual source."),
        ("is_adjustment_layer", "psd_adjustment_layer_requires_review", "Layer is an adjustment layer; prefer Photoshop-rendered group/document output for exact color."),
        ("has_layer_effects", "psd_layer_effect_requires_review", "Layer effects may not match exactly after Unity export; compare visually in Unity."),
    ]
    emitted = set()
    for flag, code, message in warning_map:
        if not feature_info.get(flag) or code in emitted:
            continue
        emitted.add(code)
        warnings.append(
            {
                "node_id": node_id,
                "code": code,
                "severity": "low" if code == "psd_smart_object_rasterized" else "medium",
                "message": f"Layer '{name}': {message}",
            }
        )


def _apply_explicit_semantics(node: dict[str, Any], layer: dict[str, Any]) -> None:
    semantic_type = layer.get("semantic_type") or layer.get("semanticType") or layer.get("role")
    if not semantic_type:
        return
    candidates = list(node.get("semantic_candidates") or [])
    _add_semantic(candidates, str(semantic_type), _num(layer.get("semantic_confidence") or layer.get("confidence")) or 0.95, ["explicit Photoshop export semantic"])
    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    primary = candidates[0]
    node["semantic_candidates"] = candidates
    node["semantic_type"] = primary["semantic_type"]
    node["semantic_confidence"] = primary["confidence"]
    node["semantic_reasons"] = primary["reasons"]
    _apply_explicit_control_hints(node, layer)


def _apply_explicit_control_hints(node: dict[str, Any], layer: dict[str, Any]) -> None:
    if node.get("semantic_type") == "mask_candidate":
        _attach_mask_hint(node)
        return

    if node.get("semantic_type") != "toggle_candidate":
        return

    explicit_value = _pick(layer, ("toggle_value", "toggleValue", "is_on", "isOn", "checked", "value", "state"))
    graphic_node_id = _pick(layer, ("graphic_node_id", "graphicNodeId", "checkmark_node_id", "checkmarkNodeId"))
    if not graphic_node_id:
        graphic = _first_named_child(node, ("check", "checkmark", "tick", "on", "selected", "knob", "handle", "勾", "选中"))
        graphic_node_id = (graphic or {}).get("id")
    else:
        graphic_node_id = _resolve_node_reference(node, graphic_node_id)

    node["unity_toggle_hint"] = {
        "can_add_toggle": True,
        "default_add_toggle": True,
        "value": _toggle_value(explicit_value, node.get("name")),
        "graphic_node_id": graphic_node_id,
        "requires_review": False,
        "notes": [
            "Toggle was inferred from explicit Photoshop export semantics.",
            "If graphic_node_id is empty, the Toggle component uses the target graphic as its state graphic.",
        ],
    }
    node["unity_interaction_hint"] = {
        "can_add_toggle": True,
        "default_add_toggle": True,
        "raycast_target_if_interactive": True,
    }


def _first_named_child(node: dict[str, Any], tokens: tuple[str, ...]) -> dict[str, Any] | None:
    for child in node.get("children") or []:
        name = str(child.get("name") or "").lower()
        if any(token in name for token in tokens):
            return child
    return None


def _resolve_node_reference(node: dict[str, Any], value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    candidates = {text, f"ps_export_layer_{text}"}
    for child in _descendants(node):
        child_id = str(child.get("id") or "")
        if child_id in candidates:
            return child_id
    return text


def _descendants(node: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for child in node.get("children") or []:
        result.append(child)
        result.extend(_descendants(child))
    return result


def _toggle_value(value: Any, fallback: Any = None) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = " ".join(str(part or "") for part in (value, fallback)).lower()
    if any(token in text for token in ("off", "unchecked", "uncheck", "disabled", "false", "关", "未选")):
        return False
    if any(token in text for token in ("on", "checked", "check", "selected", "true", "开", "选中", "勾选")):
        return True
    return None


def _register_export_asset(
    assets: dict[str, dict[str, Any]],
    name: str,
    local_path: Path,
    rect: dict[str, float],
    scale: float,
    usage: str,
    source_node_id: str | None,
    nine_slice_hint: dict[str, Any] | None = None,
) -> str:
    local_text = str(local_path.resolve())
    asset_id = "asset_" + hashlib.sha1(local_text.encode("utf-8")).hexdigest()[:12]
    safe = sanitize_filename(name, asset_id)
    if asset_id not in assets:
        assets[asset_id] = {
            "id": asset_id,
            "name": safe,
            "file_name": local_path.name,
            "type": "image",
            "remote_url": None,
            "local_path": local_text,
            "suggested_unity_path": f"Assets/DesignToUnity/Sprites/{local_path.name}",
            "format": local_path.suffix.lstrip(".").lower() or "png",
            "size": _image_size(local_path),
            "logical_size": {"width": rect["width"], "height": rect["height"]},
            "scale": scale,
            "has_alpha": True,
            "usage": usage,
            "nine_slice_hint": nine_slice_hint,
            "download_status": "exported",
            "source_node_id": source_node_id,
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


def _nine_slice_hint(layer: dict[str, Any], scale: float) -> dict[str, Any] | None:
    raw = _pick(layer, ("nine_slice", "nineSlice", "sprite_border", "spriteBorder"))
    if raw is None:
        return None
    if raw is True:
        return {
            "candidate": True,
            "requires_review": True,
            "reason": "source export marks this layer as nine-slice but did not provide a border",
        }
    if isinstance(raw, (list, tuple)):
        border = _scaled_border(raw, scale)
    elif isinstance(raw, dict):
        border_raw = _pick(raw, ("border", "spriteBorder", "sprite_border")) or raw
        border = _scaled_border(border_raw, scale)
    else:
        border = None
    if not border:
        return {
            "candidate": True,
            "requires_review": True,
            "reason": "source export marks this layer as nine-slice but the border could not be parsed",
        }
    return {
        "candidate": True,
        "border": border,
        "requires_review": False,
        "reason": "explicit nine-slice border supplied by Photoshop export",
    }


def _scaled_border(value: Any, scale: float) -> dict[str, float] | None:
    divisor = scale if scale > 0 else 1
    if isinstance(value, dict):
        left = _num(_pick(value, ("left", "l", "x")))
        right = _num(_pick(value, ("right", "r", "z")))
        top = _num(_pick(value, ("top", "t", "w")))
        bottom = _num(_pick(value, ("bottom", "b", "y")))
    elif isinstance(value, (list, tuple)) and len(value) >= 4:
        left = _num(value[0])
        bottom = _num(value[1])
        right = _num(value[2])
        top = _num(value[3])
    else:
        return None
    if left is None or right is None or top is None or bottom is None:
        return None
    return {
        "left": round(max(0, left / divisor), 4),
        "right": round(max(0, right / divisor), 4),
        "top": round(max(0, top / divisor), 4),
        "bottom": round(max(0, bottom / divisor), 4),
    }


def _resolve_optional_path(export_dir: Path, value: Any) -> Path | None:
    if not value:
        return None
    if isinstance(value, dict):
        value = value.get("path") or value.get("local_path") or value.get("file")
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = export_dir / path
    return path.resolve()


def _pick(source: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in source and source.get(name) is not None:
            return source.get(name)
    return None


def _pick_bool(source: dict[str, Any], names: tuple[str, ...]) -> bool:
    value = _pick(source, names)
    if isinstance(value, (list, tuple, dict, set, str, bytes)):
        return len(value) > 0
    return bool(value)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _scaled_rect(rect: dict[str, float], scale: float) -> dict[str, float]:
    return {key: round(value / scale, 1) for key, value in rect.items()}


def _union_rect(rects: list[dict[str, Any]]) -> dict[str, float]:
    valid = [rect for rect in rects if float(rect.get("width") or 0) > 0 and float(rect.get("height") or 0) > 0]
    if not valid:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    left = min(float(rect.get("x") or 0) for rect in valid)
    top = min(float(rect.get("y") or 0) for rect in valid)
    right = max(float(rect.get("x") or 0) + float(rect.get("width") or 0) for rect in valid)
    bottom = max(float(rect.get("y") or 0) + float(rect.get("height") or 0) for rect in valid)
    return {"x": round(left, 1), "y": round(top, 1), "width": round(right - left, 1), "height": round(bottom - top, 1)}


def _normalize_blend_mode(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    text = text.replace("_", " ").replace("-", " ").lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _normalize_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "", text)


_ADJUSTMENT_LAYER_KINDS = {
    "brightnesscontrast",
    "levels",
    "curves",
    "exposure",
    "vibrance",
    "huesaturation",
    "colorbalance",
    "blackwhite",
    "photofilter",
    "channelmixer",
    "colorlookup",
    "invert",
    "posterize",
    "threshold",
    "gradientmap",
    "selectivecolor",
}


def _is_adjustment_layer_kind(kind: str) -> bool:
    return kind in _ADJUSTMENT_LAYER_KINDS or kind.endswith("adjustment") or kind.endswith("adjustmentlayer")


def _node_id(layer: dict[str, Any], z_index: int) -> str:
    value = layer.get("id") or layer.get("layer_id") or layer.get("layerId")
    if value is not None:
        return f"ps_export_layer_{value}"
    raw = f"{layer.get('name')}:{_rect_of(layer)}:{z_index}"
    return "ps_export_layer_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _unity_name(z_index: int, name: str) -> str:
    safe = sanitize_filename(name, "Layer")
    return f"node_{z_index:03d}_{safe or 'Layer'}"


def _packet_id(path: Path, manifest: dict[str, Any], target: str, scale: float) -> str:
    raw = f"photoshop-export:{path}:{_file_sha1(path)}:{target}:{scale}:{manifest.get('version') or ''}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _file_sha1(path: Path) -> str:
    hasher = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

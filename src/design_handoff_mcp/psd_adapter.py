from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from .asset_store import sanitize_filename
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


class PsdAdapterError(RuntimeError):
    pass


_BUTTON_LABEL_TOKENS = (
    "start",
    "play",
    "game",
    "task",
    "setting",
    "settings",
    "quit",
    "exit",
    "mode",
    "war",
    "begin",
    "beging",
    "begins",
    "beginings",
    "raffle",
    "single",
    "ok",
    "yes",
    "no",
    "cancel",
    "confirm",
    "login",
    "register",
    "shop",
    "buy",
    "claim",
    "领取",
    "开始",
    "确定",
    "取消",
    "退出",
    "设置",
    "商店",
    "购买",
)


def make_psd_packet(
    file_path: str,
    target: str = "unity",
    asset_output_dir: str | Path | None = None,
    data_dir: str | Path | None = None,
    rasterize_mode: str = "layer",
    scale: float | None = None,
    include_hidden: bool = False,
    export_text_layers: bool = False,
    export_group_layers: bool = False,
    include_reference: bool = True,
    reference_image_path: str | Path | None = None,
) -> dict[str, Any]:
    try:
        from psd_tools import PSDImage
    except ImportError as exc:  # pragma: no cover - exercised in integration.
        raise PsdAdapterError(
            "PSD support requires the optional dependency 'psd-tools'. "
            "Install the project again after dependency sync: pip install -e ."
        ) from exc

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PSD file not found: {path}")
    if path.suffix.lower() not in {".psd", ".psb"}:
        raise ValueError("file_path must point to a .psd or .psb file")

    normalized_mode = rasterize_mode.strip().lower()
    if normalized_mode not in {"layer", "none", "visible", "all"}:
        raise ValueError("rasterize_mode must be one of: layer, none, visible, all")

    psd = PSDImage.open(path)
    file_hash = _file_sha1(path)
    detected_scale = scale or _detect_scale_from_name(path.name) or 1.0
    if detected_scale <= 0:
        raise ValueError("scale must be greater than zero")

    width = float(getattr(psd, "width", 0) or getattr(psd, "size", [0, 0])[0] or 0)
    height = float(getattr(psd, "height", 0) or getattr(psd, "size", [0, 0])[1] or 0)
    logical_width = round(width / detected_scale, 1)
    logical_height = round(height / detected_scale, 1)
    design_name = path.stem
    packet_id = _packet_id(path, file_hash, normalized_mode, target, detected_scale)
    export_dir = _asset_export_dir(path, packet_id, asset_output_dir, data_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    design_info = {
        "name": design_name,
        "width": logical_width,
        "height": logical_height,
        "scale": detected_scale,
        "unit": "px",
        "coordinate_system": "top-left",
        "source_image_url": None,
    }
    root_node = {
        "id": "root",
        "parent_id": None,
        "name": design_name,
        "unity_name_hint": _unity_name(0, design_name),
        "path": design_name,
        "type": "group",
        "semantic_type": "screen_root",
        "semantic_confidence": 1,
        "semantic_reasons": ["PSD document root"],
        "visible": True,
        "z_index": 0,
        "global_rect": {"x": 0, "y": 0, "width": logical_width, "height": logical_height},
        "local_rect": {"x": 0, "y": 0, "width": logical_width, "height": logical_height},
        "unity_rect_hint": _unity_rect({"x": 0, "y": 0, "width": logical_width, "height": logical_height}),
        "style": {"opacity": 1},
        "children": [],
        "source_metadata": {
            "source_provider": "psd",
            "source_node_id": "root",
            "source_path": design_name,
        },
    }
    assets: dict[str, dict[str, Any]] = {}
    warnings: list[dict[str, Any]] = []

    psd_children = _children(psd)
    root_node["children"] = _normalized_psd_children(
        layers=psd_children,
        parent_id="root",
        parent_path=design_name,
        parent_global={"x": 0, "y": 0},
        export_dir=export_dir,
        assets=assets,
        warnings=warnings,
        scale=detected_scale,
        design_info=design_info,
        include_hidden=include_hidden,
        rasterize_mode=normalized_mode,
        export_text_layers=export_text_layers,
        export_group_layers=export_group_layers,
    )
    effective_include_hidden = include_hidden
    auto_included_hidden_layers = False
    if psd_children and not root_node["children"] and not include_hidden:
        warnings.append(
            {
                "node_id": None,
                "code": "psd_no_visible_layers_auto_include_hidden",
                "severity": "medium",
                "message": "No visible PSD layers were found. Hidden layers were included automatically so Unity can still restore the document structure.",
            }
        )
        root_node["children"] = _normalized_psd_children(
            layers=psd_children,
            parent_id="root",
            parent_path=design_name,
            parent_global={"x": 0, "y": 0},
            export_dir=export_dir,
            assets=assets,
            warnings=warnings,
            scale=detected_scale,
            design_info=design_info,
            include_hidden=True,
            rasterize_mode=normalized_mode,
            export_text_layers=export_text_layers,
            export_group_layers=export_group_layers,
        )
        effective_include_hidden = True
        auto_included_hidden_layers = True

    if include_reference and normalized_mode != "none":
        reference_asset_id = None
        if reference_image_path:
            reference_asset_id = _export_external_reference_asset(
                reference_image_path=reference_image_path,
                export_dir=export_dir,
                design_name=design_name,
                design_info=design_info,
                assets=assets,
                warnings=warnings,
            )
        if not reference_asset_id:
            reference_asset_id = _export_reference_asset(
                psd,
                export_dir,
                design_name,
                design_info,
                assets,
                warnings,
                include_hidden_layers=auto_included_hidden_layers,
            )
        if reference_asset_id:
            design_info["reference_asset_ref"] = reference_asset_id
        else:
            reference_asset_id = _export_reference_from_exported_layers(
                root_node=root_node,
                assets=assets,
                export_dir=export_dir,
                design_name=design_name,
                design_info=design_info,
                warnings=warnings,
            )
            if reference_asset_id:
                design_info["reference_asset_ref"] = reference_asset_id
        if auto_included_hidden_layers and reference_asset_id:
            warnings.append(
                {
                    "node_id": None,
                    "code": "psd_reference_auto_include_hidden",
                    "severity": "low",
                    "message": "The flattened PSD reference was rendered with hidden layers included to match the auto-included layer tree.",
                }
            )

    _attach_text_hints(root_node, warnings)
    _attach_text_button_hints(root_node, warnings)
    _attach_slider_hints(root_node, warnings)
    _attach_scroll_hints(root_node, warnings)
    _attach_layout_hints(root_node, warnings)
    _attach_input_hints(root_node, warnings)
    _attach_dropdown_hints(root_node, warnings)
    _attach_tab_hints(root_node, warnings)
    _attach_radio_hints(root_node, warnings)
    _enrich_assets(assets, root_node, design_info)
    enrich_delivery_metadata(root_node, design_info, assets, provider="psd")
    packet = {
        "packet_id": packet_id,
        "source": {
            "provider": "psd",
            "file_path": str(path),
            "file_name": path.name,
            "file_hash": file_hash,
            "mtime_ns": path.stat().st_mtime_ns,
            "schema_source": "psd-tools",
            "rasterize_mode": normalized_mode,
            "include_hidden": effective_include_hidden,
            "auto_included_hidden_layers": auto_included_hidden_layers,
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
    attach_reusable_prefab_registry(packet)
    return packet


def _normalized_psd_children(
    layers: list[Any],
    parent_id: str,
    parent_path: str,
    parent_global: dict[str, float],
    export_dir: Path,
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
    scale: float,
    design_info: dict[str, Any],
    include_hidden: bool,
    rasterize_mode: str,
    export_text_layers: bool,
    export_group_layers: bool,
) -> list[dict[str, Any]]:
    children = []
    z_counter = [1]
    for layer in layers:
        node = _normalize_psd_layer(
            layer=layer,
            parent_id=parent_id,
            parent_path=parent_path,
            parent_global=parent_global,
            export_dir=export_dir,
            assets=assets,
            warnings=warnings,
            z_counter=z_counter,
            scale=scale,
            design_info=design_info,
            include_hidden=include_hidden,
            rasterize_mode=rasterize_mode,
            export_text_layers=export_text_layers,
            export_group_layers=export_group_layers,
        )
        if node:
            children.append(node)
    return children


def _normalize_psd_layer(
    layer: Any,
    parent_id: str,
    parent_path: str,
    parent_global: dict[str, float],
    export_dir: Path,
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
    z_counter: list[int],
    scale: float,
    design_info: dict[str, Any],
    include_hidden: bool,
    rasterize_mode: str,
    export_text_layers: bool,
    export_group_layers: bool,
) -> dict[str, Any] | None:
    if not include_hidden and not _is_visible(layer):
        return None

    raw_name = _layer_name(layer)
    z_index = z_counter[0]
    z_counter[0] += 1
    node_id = _layer_id(layer, z_index)
    path = f"{parent_path}/{raw_name}" if parent_path else raw_name
    global_rect = _scaled_rect(_bbox_rect(layer), scale)
    layer_type = _node_type(layer)
    text = _text_info(layer, scale, warnings, node_id)
    children_nodes: list[dict[str, Any]] = []

    for child in _children(layer):
        child_node = _normalize_psd_layer(
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
            include_hidden=include_hidden,
            rasterize_mode=rasterize_mode,
            export_text_layers=export_text_layers,
            export_group_layers=export_group_layers,
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
    style = _style_info(layer, warnings, node_id)
    feature_info = _psd_feature_info(layer, style)
    _append_feature_warnings(raw_name, node_id, feature_info, warnings)
    asset_ref = None
    should_export = _should_export_layer(layer_type, rasterize_mode, export_text_layers, export_group_layers)
    if should_export and global_rect["width"] > 0 and global_rect["height"] > 0:
        asset_ref = _export_layer_asset(layer, export_dir, raw_name, node_id, global_rect, scale, layer_type, assets, warnings)
        if asset_ref and layer_type == "unknown":
            layer_type = "image"

    if text and not export_text_layers:
        layer_type = "text"
        asset_ref = None
    elif text and export_text_layers and asset_ref:
        layer_type = "image"

    if layer_type == "unknown" and children_nodes:
        layer_type = "group"

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
            "source_provider": "psd",
            "source_node_id": node_id,
            "source_path": path,
            "psd_layer_kind": _layer_kind(layer),
            "psd_layer_name": raw_name,
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
    _apply_psd_semantics(node)
    return node


def _should_export_layer(layer_type: str, rasterize_mode: str, export_text_layers: bool, export_group_layers: bool) -> bool:
    if rasterize_mode == "none":
        return False
    if layer_type == "text":
        return export_text_layers or rasterize_mode == "all"
    if layer_type == "group":
        return export_group_layers or rasterize_mode in {"visible", "all"}
    return layer_type in {"image", "shape", "unknown"} or rasterize_mode == "all"


def _export_reference_asset(
    psd: Any,
    export_dir: Path,
    design_name: str,
    design_info: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
    include_hidden_layers: bool = False,
) -> str | None:
    try:
        if include_hidden_layers:
            image = psd.composite(layer_filter=lambda layer: True, ignore_preview=True)
        else:
            image = psd.composite()
    except Exception as exc:
        warnings.append(
            {
                "node_id": None,
                "code": "psd_reference_export_failed",
                "severity": "medium",
                "message": f"Could not export flattened PSD reference image: {exc}",
            }
        )
        return None
    if image is None:
        return None
    file_name = f"{sanitize_filename(design_name, 'psd')}_reference.png"
    path = export_dir / file_name
    _save_png(image, path)
    rect = {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]}
    return _register_local_asset(
        assets=assets,
        name=f"{design_name}_reference",
        local_path=path,
        rect=rect,
        scale=design_info["scale"],
        usage="design_reference",
        source_node_id=None,
    )


def _export_reference_from_exported_layers(
    root_node: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    export_dir: Path,
    design_name: str,
    design_info: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> str | None:
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return None

    width = max(1, int(round(float(design_info.get("width") or 0))))
    height = max(1, int(round(float(design_info.get("height") or 0))))
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    painted = 0
    for node, inherited_opacity in _walk_node_tree_with_opacity(root_node):
        asset_ref = node.get("asset_ref")
        if not asset_ref:
            continue
        asset = assets.get(asset_ref) or {}
        local_path = Path(str(asset.get("local_path") or "")).expanduser()
        if not local_path.exists():
            continue
        rect = node.get("global_rect") or {}
        layer_width = max(1, int(round(float(rect.get("width") or 0))))
        layer_height = max(1, int(round(float(rect.get("height") or 0))))
        if layer_width <= 0 or layer_height <= 0:
            continue
        try:
            layer_image = Image.open(local_path).convert("RGBA")
        except Exception:
            continue
        if layer_image.size != (layer_width, layer_height):
            layer_image = layer_image.resize((layer_width, layer_height), Image.Resampling.LANCZOS)
        if inherited_opacity < 0.999:
            layer_image = _apply_image_opacity(layer_image, inherited_opacity)
        if _alpha_composite_clipped(
            canvas=canvas,
            layer_image=layer_image,
            x=int(round(float(rect.get("x") or 0))),
            y=int(round(float(rect.get("y") or 0))),
        ):
            painted += 1

    if not painted:
        return None

    file_name = f"{sanitize_filename(design_name, 'psd')}_reference_from_layers.png"
    path = export_dir / file_name
    canvas.save(path, "PNG")
    warnings.append(
        {
            "node_id": None,
            "code": "psd_reference_composed_from_exported_layers",
            "severity": "medium",
            "message": "PSD flattened reference could not be rendered directly, so a best-effort reference was composed from exported layer PNGs in Unity draw order.",
        }
    )
    rect = {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]}
    return _register_local_asset(
        assets=assets,
        name=f"{design_name}_reference_from_layers",
        local_path=path,
        rect=rect,
        scale=design_info.get("scale") or 1,
        usage="design_reference",
        source_node_id=None,
    )


def _export_external_reference_asset(
    reference_image_path: str | Path,
    export_dir: Path,
    design_name: str,
    design_info: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> str | None:
    source_path = Path(reference_image_path).expanduser().resolve()
    if not source_path.exists():
        warnings.append(
            {
                "node_id": None,
                "code": "psd_external_reference_missing",
                "severity": "medium",
                "message": f"External PSD reference image was not found: {source_path}",
            }
        )
        return None

    expected_width = max(1, int(round(float(design_info.get("width") or 0))))
    expected_height = max(1, int(round(float(design_info.get("height") or 0))))
    file_name = f"{sanitize_filename(design_name, 'psd')}_external_reference.png"
    target_path = export_dir / file_name
    try:
        from PIL import Image

        image = Image.open(source_path).convert("RGBA")
        source_size = image.size
        if image.size != (expected_width, expected_height):
            image = image.resize((expected_width, expected_height), Image.Resampling.LANCZOS)
            warnings.append(
                {
                    "node_id": None,
                    "code": "psd_external_reference_resized",
                    "severity": "low",
                    "message": "External PSD reference image size differed from the design size and was resized for Unity visual QA.",
                    "source_size": {"width": source_size[0], "height": source_size[1]},
                    "target_size": {"width": expected_width, "height": expected_height},
                }
            )
        _save_png(image, target_path)
    except Exception:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)

    warnings.append(
        {
            "node_id": None,
            "code": "psd_external_reference_used",
            "severity": "low",
            "message": "An external Photoshop-rendered reference image was registered as the packet visual baseline.",
            "source_path": str(source_path),
        }
    )
    rect = {"x": 0, "y": 0, "width": design_info["width"], "height": design_info["height"]}
    return _register_local_asset(
        assets=assets,
        name=f"{design_name}_external_reference",
        local_path=target_path,
        rect=rect,
        scale=design_info.get("scale") or 1,
        usage="design_reference",
        source_node_id=None,
    )


def _alpha_composite_clipped(canvas: Any, layer_image: Any, x: int, y: int) -> bool:
    canvas_width, canvas_height = canvas.size
    layer_width, layer_height = layer_image.size
    dst_x = max(0, x)
    dst_y = max(0, y)
    src_x = max(0, -x)
    src_y = max(0, -y)
    crop_width = min(layer_width - src_x, canvas_width - dst_x)
    crop_height = min(layer_height - src_y, canvas_height - dst_y)
    if crop_width <= 0 or crop_height <= 0:
        return False
    cropped = layer_image.crop((src_x, src_y, src_x + crop_width, src_y + crop_height))
    canvas.alpha_composite(cropped, (dst_x, dst_y))
    return True


def _walk_node_tree(node: dict[str, Any]) -> list[dict[str, Any]]:
    result = [node]
    for child in node.get("children") or []:
        result.extend(_walk_node_tree(child))
    return result


def _walk_node_tree_with_opacity(node: dict[str, Any], parent_opacity: float = 1.0) -> list[tuple[dict[str, Any], float]]:
    opacity = parent_opacity * _node_opacity(node)
    result = [(node, opacity)]
    for child in node.get("children") or []:
        result.extend(_walk_node_tree_with_opacity(child, opacity))
    return result


def _node_opacity(node: dict[str, Any]) -> float:
    try:
        return max(0, min(1, float((node.get("style") or {}).get("opacity", 1))))
    except (TypeError, ValueError):
        return 1


def _apply_image_opacity(image: Any, opacity: float) -> Any:
    from PIL import Image

    red, green, blue, alpha = image.split()
    alpha = alpha.point(lambda value: int(round(value * opacity)))
    return Image.merge("RGBA", (red, green, blue, alpha))


def _export_layer_asset(
    layer: Any,
    export_dir: Path,
    name: str,
    node_id: str,
    rect: dict[str, float],
    scale: float,
    usage: str,
    assets: dict[str, dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> str | None:
    image = _layer_image(layer)
    if image is None:
        warnings.append(
            {
                "node_id": node_id,
                "code": "psd_layer_rasterize_failed",
                "severity": "medium",
                "message": f"Layer '{name}' could not be rasterized; it will be represented by metadata only.",
            }
        )
        return None
    safe = sanitize_filename(name, node_id)
    file_name = f"{safe}_{node_id[-8:]}.png"
    path = export_dir / file_name
    _save_png(image, path)
    return _register_local_asset(
        assets=assets,
        name=name,
        local_path=path,
        rect=rect,
        scale=scale,
        usage=usage if usage in {"image", "shape", "text"} else "image",
        source_node_id=node_id,
    )


def _register_local_asset(
    assets: dict[str, dict[str, Any]],
    name: str,
    local_path: Path,
    rect: dict[str, float],
    scale: float,
    usage: str,
    source_node_id: str | None,
) -> str:
    local_text = str(local_path.resolve())
    asset_id = "asset_" + hashlib.sha1(local_text.encode("utf-8")).hexdigest()[:12]
    safe = sanitize_filename(name, asset_id)
    if asset_id not in assets:
        content_hash = _file_sha1(local_path)
        assets[asset_id] = {
            "id": asset_id,
            "name": safe,
            "file_name": local_path.name,
            "type": "image",
            "remote_url": None,
            "local_path": local_text,
            "content_hash": content_hash,
            "file_hash": content_hash,
            "suggested_unity_path": f"Assets/DesignToUnity/Sprites/{local_path.name}",
            "format": "png",
            "size": _image_size(local_path),
            "logical_size": {"width": rect["width"], "height": rect["height"]},
            "scale": scale,
            "has_alpha": True,
            "usage": usage,
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


def _attach_scroll_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    lookup = {node.get("id"): node for node in nodes}
    for node in nodes:
        if node.get("semantic_type") == "screen_root":
            continue
        if node.get("type") != "group":
            continue
        children = node.get("children") or []
        if not children:
            continue
        name = str(node.get("name") or "").lower()
        if _has_any(name, ("scrollbar", "scroll_bar", "scroll bar", "滚动条")):
            continue
        strong_explicit = _has_any(name, ("scroll", "scrollview", "scroll_view", "滚动", "滑动"))
        explicit = strong_explicit or _has_any(name, ("list", "grid", "列表"))
        repeated = _has_repeated_items(children)
        if _is_scroll_child_semantic(node) and not strong_explicit:
            continue
        if not explicit and not repeated:
            continue

        if not node.get("semantic_type") or explicit or repeated:
            _add_semantic_to_node(
                node,
                "scroll_area_candidate",
                0.86 if explicit else 0.62,
                ["name suggests scroll/list container"] if explicit else ["children look like repeated list/grid items"],
            )
        if node.get("semantic_type") != "scroll_area_candidate":
            continue

        viewport = _first_named_child(node, ("viewport", "view_port", "mask", "clip", "裁剪", "视口"))
        content = _first_named_child(node, ("content", "container", "items", "list", "grid", "内容", "列表"))
        if content is None and viewport is not None and viewport is not node:
            content = _first_named_child(viewport, ("content", "container", "items", "list", "grid", "内容", "列表"))
            if content is None:
                content = _largest_child_with_children(viewport.get("children") or [])
        if content is None:
            content = _largest_child_with_children(children) or (children[0] if children else None)
        if viewport is None:
            viewport = node

        descendants = _descendants(node)
        horizontal_scrollbar = _best_scrollbar(node, descendants, "horizontal")
        vertical_scrollbar = _best_scrollbar(node, descendants, "vertical")
        if horizontal_scrollbar:
            _attach_scrollbar_hint(horizontal_scrollbar, node, "horizontal", warnings)
        if vertical_scrollbar:
            _attach_scrollbar_hint(vertical_scrollbar, node, "vertical", warnings)

        if content and content is not node:
            _add_semantic_to_node(content, "scroll_content_candidate", 0.9, ["child is likely ScrollRect content"])
        if viewport is not node:
            _add_semantic_to_node(viewport, "scroll_viewport_candidate", 0.9, ["child is likely ScrollRect viewport"])

        viewport_rect = viewport.get("global_rect") or node.get("global_rect") or {}
        content_rect = (content or {}).get("global_rect") or {}
        direction = _scroll_direction(viewport_rect, content_rect, children)
        item_ids = [child.get("id") for child in (content or node).get("children", []) if child.get("id")]
        node["unity_scroll_hint"] = {
            "can_add_scroll_rect": True,
            "default_add_scroll_rect": True,
            "direction": direction,
            "viewport_node_id": viewport.get("id"),
            "content_node_id": (content or {}).get("id"),
            "horizontal_scrollbar_node_id": (horizontal_scrollbar or {}).get("id"),
            "vertical_scrollbar_node_id": (vertical_scrollbar or {}).get("id"),
            "item_node_ids": item_ids,
            "requires_review": bool(
                viewport is node
                or not content
                or (horizontal_scrollbar and (horizontal_scrollbar.get("unity_scrollbar_hint") or {}).get("requires_review"))
                or (vertical_scrollbar and (vertical_scrollbar.get("unity_scrollbar_hint") or {}).get("requires_review"))
            ),
            "notes": [
                "ScrollRect binding is inferred from PSD group/layer names, scrollbar names, and repeated item geometry.",
                "Confirm viewport/content/scrollbar references in Unity before wiring business data.",
            ],
        }
        if viewport is node or not content:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "scroll_area_requires_review",
                    "severity": "medium",
                    "message": "Detected a likely scroll area but viewport/content structure is incomplete; verify ScrollRect bindings in Unity.",
                }
            )

        if content and content.get("id") in lookup:
            for child in content.get("children") or []:
                _add_semantic_to_node(child, "list_item_candidate", 0.7, ["child belongs to inferred scroll content"])


def _attach_layout_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    for node in _walk_node_tree(root):
        if node.get("semantic_type") == "screen_root":
            continue
        if node.get("type") != "group":
            continue
        children = _layout_item_children(node)
        if len(children) < 2:
            continue
        hint = _layout_hint_for_children(node, children)
        if not hint:
            continue
        node["unity_layout_hint"] = hint


def _best_scrollbar(owner: dict[str, Any], descendants: list[dict[str, Any]], direction: str) -> dict[str, Any] | None:
    scored: list[tuple[float, dict[str, Any]]] = []
    owner_rect = owner.get("global_rect") or {}
    for candidate in descendants:
        if candidate is owner:
            continue
        name = str(candidate.get("name") or "").lower()
        if not _has_any(name, ("scrollbar", "scroll_bar", "scroll bar", "滚动条")):
            continue
        score = 1.0
        rect = candidate.get("global_rect") or {}
        w = _rect_width(rect)
        h = _rect_height(rect)
        if direction == "vertical":
            if _has_any(name, ("horizontal", "horiz", "_h", "横", "横向")):
                continue
            explicit = _has_any(name, ("vertical", "vert", "_v", "竖", "纵向"))
            geometry_matches = h >= max(1.0, w) * 1.8
            if not explicit and not geometry_matches:
                continue
            if explicit:
                score += 0.6
            if geometry_matches:
                score += 0.45
            if owner_rect and abs((float(rect.get("x") or 0) + w) - (float(owner_rect.get("x") or 0) + _rect_width(owner_rect))) <= max(8.0, _rect_width(owner_rect) * 0.08):
                score += 0.2
        else:
            if _has_any(name, ("vertical", "vert", "_v", "竖", "纵向")):
                continue
            explicit = _has_any(name, ("horizontal", "horiz", "_h", "横", "横向"))
            geometry_matches = w >= max(1.0, h) * 1.8
            if not explicit and not geometry_matches:
                continue
            if explicit:
                score += 0.6
            if geometry_matches:
                score += 0.45
            if owner_rect and abs((float(rect.get("y") or 0) + h) - (float(owner_rect.get("y") or 0) + _rect_height(owner_rect))) <= max(8.0, _rect_height(owner_rect) * 0.08):
                score += 0.2
        scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best = scored[0]
    return best if best_score >= 1.2 else None


def _attach_scrollbar_hint(
    node: dict[str, Any],
    scroll_owner: dict[str, Any],
    direction: str,
    warnings: list[dict[str, Any]],
) -> None:
    handle = _best_scrollbar_handle(node)
    _add_semantic_to_node(node, "scrollbar_candidate", 0.9, [f"child is likely {direction} ScrollRect scrollbar"])
    if handle:
        _add_semantic_to_node(handle, "scrollbar_handle_candidate", 0.96, ["child is likely Scrollbar handle rect"])
    size = _scrollbar_size(node, handle, direction)
    node["unity_scrollbar_hint"] = {
        "can_add_scrollbar": True,
        "default_add_scrollbar": True,
        "direction": direction,
        "scroll_rect_node_id": scroll_owner.get("id"),
        "handle_node_id": (handle or {}).get("id"),
        "value": 0,
        "size": size,
        "requires_review": not bool(handle),
        "notes": [
            "Scrollbar binding is inferred from PSD/Photoshop layer names and geometry.",
            "The ScrollRect will bind this component as its horizontal or vertical scrollbar when possible.",
        ],
    }
    if not handle:
        warnings.append(
            {
                "node_id": node.get("id"),
                "code": "scrollbar_handle_requires_review",
                "severity": "medium",
                "message": "Detected a likely scrollbar but no handle layer could be bound; verify Scrollbar.handleRect in Unity.",
            }
        )


def _attach_slider_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    lookup = {node.get("id"): node for node in nodes}
    parent_by_id = {
        child.get("id"): node
        for node in nodes
        for child in node.get("children") or []
        if child.get("id")
    }

    for node in nodes:
        semantic_type = node.get("semantic_type")
        if semantic_type not in {"progress_candidate", "slider_candidate"}:
            continue

        descendants = _descendants(node)
        if not descendants:
            descendants = _nearby_slider_siblings(node, parent_by_id.get(node.get("id")))

        track = _best_slider_part(node, descendants, "track")
        fill = _best_slider_part(node, descendants, "fill", track)
        handle = _best_slider_part(node, descendants, "handle", fill or track)
        inferred_value = _slider_value_from_parts(node, fill, track)
        requires_review = bool(not fill or (semantic_type == "slider_candidate" and not handle))
        node["unity_slider_hint"] = {
            "can_add_slider": True,
            "default_add_slider": True,
            "interactable": semantic_type == "slider_candidate",
            "direction": "horizontal",
            "track_node_id": (track or {}).get("id"),
            "fill_node_id": (fill or {}).get("id"),
            "handle_node_id": (handle or {}).get("id"),
            "value": inferred_value,
            "requires_review": requires_review,
            "notes": [
                "Slider fill/handle binding is inferred from PSD layer names and geometry.",
                "Confirm handle binding for draggable gameplay controls before adding business callbacks.",
            ],
        }
        node["unity_interaction_hint"] = {
            "can_add_slider": True,
            "default_add_slider": True,
            "interactable": semantic_type == "slider_candidate",
            "requires_fill_handle_review": requires_review,
        }

        if fill and fill.get("id") in lookup:
            _add_semantic_to_node(fill, "slider_fill_candidate", 0.96, ["child is likely Slider fill rect"])
        if handle and handle.get("id") in lookup:
            _add_semantic_to_node(handle, "slider_handle_candidate", 0.96, ["child is likely Slider handle rect"])
        if track and track.get("id") in lookup:
            _add_semantic_to_node(track, "slider_track_candidate", 0.94, ["child is likely Slider track/background rect"])

        if requires_review:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "slider_binding_requires_review",
                    "severity": "medium",
                    "message": "Detected a slider/progress candidate but fill/handle binding is incomplete; verify Slider references in Unity.",
                }
            )


def _attach_text_button_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    parent_by_id = {
        child.get("id"): node
        for node in nodes
        for child in node.get("children") or []
        if child.get("id")
    }
    for text_node in nodes:
        if text_node.get("type") != "text":
            continue
        label = _button_label_text(text_node)
        if not label:
            continue
        backing = _best_button_backing_for_text(text_node, nodes, parent_by_id)
        if not backing:
            continue
        _add_semantic_to_node(
            backing,
            "button_candidate",
            0.92,
            ["text layer looks like an action label and is centered inside a button-like backing layer"],
        )
        _add_semantic_to_node(
            text_node,
            "button_label_candidate",
            0.76,
            ["text layer is likely the label for a nearby button backing layer"],
        )
        backing["unity_button_hint"] = {
            "can_add_button": True,
            "default_add_button": True,
            "label_node_id": text_node.get("id"),
            "label": label,
            "hit_node_id": backing.get("id"),
            "hit_rect": backing.get("global_rect"),
            "requires_review": False,
            "notes": [
                "Button was inferred from an action text layer inside a rectangular PSD backing layer.",
                "Keep event binding on the backing node so the clickable area covers the visual button.",
            ],
        }
        backing["unity_interaction_hint"] = {
            "can_add_button": True,
            "default_add_button": True,
            "label_node_id": text_node.get("id"),
        }


def _attach_text_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    for node in _walk_nodes(root):
        text = node.get("text") or {}
        if not text.get("content"):
            continue
        effects = text.get("effects") if isinstance(text.get("effects"), dict) else {}
        spans = text.get("spans") if isinstance(text.get("spans"), list) else []
        font_hint = text.get("font_hint") if isinstance(text.get("font_hint"), dict) else {}
        effect_components = []
        if effects.get("outline"):
            effect_components.append("Outline")
        if effects.get("shadow"):
            effect_components.append("Shadow")
        node["unity_text_hint"] = {
            "can_use_textmeshpro": True,
            "default_use_textmeshpro": True,
            "rich_text_enabled": bool(spans),
            "span_count": len(spans),
            "font_hint": font_hint,
            "effect_components": effect_components,
            "uses_outline_component": "Outline" in effect_components,
            "uses_shadow_component": "Shadow" in effect_components,
            "requires_visual_review": bool(text.get("style_quality") == "best_effort" or text.get("unsupported_text_features")),
            "notes": [
                "Text style is normalized for TextMeshProUGUI; compare against the Photoshop reference for final visual QA.",
                "Font mapping can be supplied with tmp_font_asset_map when writing the Unity prefab.",
            ],
        }
        if spans:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "psd_text_rich_style_detected",
                    "severity": "low",
                    "message": "Text has multiple style spans; direct YAML writes TMP rich text tags for color/size/bold/italic/underline where possible.",
                }
            )
        if effect_components:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "psd_text_effect_mapped",
                    "severity": "low",
                    "message": f"Text effects were mapped to Unity UI components: {', '.join(effect_components)}.",
                }
            )


def _walk_nodes(root: dict[str, Any]) -> list[dict[str, Any]]:
    result = []

    def walk(node: dict[str, Any]) -> None:
        result.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    return result


def _attach_input_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    for node in nodes:
        if node.get("semantic_type") != "input_candidate":
            continue
        text_node = _first_text_descendant(node)
        placeholder_node = _first_placeholder_descendant(node) or text_node
        node["unity_input_hint"] = {
            "can_add_tmp_input_field": True,
            "default_add_tmp_input_field": True,
            "text_component_node_id": (text_node or {}).get("id"),
            "placeholder_node_id": (placeholder_node or {}).get("id"),
            "text": ((text_node or {}).get("text") or {}).get("content"),
            "line_type": "single_line",
            "requires_review": not bool(text_node),
            "notes": [
                "TMP_InputField binding is inferred from PSD/Photoshop layer names and text children.",
                "Bind validation, submit, and value-changed callbacks in Unity after import.",
            ],
        }
        node["unity_interaction_hint"] = {
            "can_add_tmp_input_field": True,
            "default_add_tmp_input_field": True,
            "raycast_target_if_interactive": True,
        }
        if not text_node:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "input_text_component_requires_review",
                    "severity": "medium",
                    "message": "Detected an input field candidate but no text child could be bound as TMP_InputField.textComponent.",
                }
            )


def _attach_dropdown_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    for node in nodes:
        if node.get("semantic_type") != "dropdown_candidate":
            continue

        template = _first_named_descendant(
            node,
            ("template", "dropdown_menu", "dropdown menu", "menu", "options", "option_list", "list", "下拉", "选项"),
        )
        template_ids = {desc.get("id") for desc in _descendants(template or {}) if desc.get("id")} if template else set()
        caption_node = _first_text_descendant_excluding(node, template_ids)
        item_text_node = _first_text_descendant(template) if template else None
        option_texts = _dropdown_options(node, template, caption_node)

        if template:
            _add_semantic_to_node(template, "dropdown_template_candidate", 0.92, ["child is likely TMP_Dropdown template rect"])
        if caption_node:
            _add_semantic_to_node(caption_node, "dropdown_caption_candidate", 0.84, ["text layer is likely TMP_Dropdown caption"])
        if item_text_node:
            _add_semantic_to_node(item_text_node, "dropdown_item_text_candidate", 0.84, ["text layer is likely TMP_Dropdown item template text"])

        requires_review = not bool(template and caption_node and item_text_node and option_texts)
        node["unity_dropdown_hint"] = {
            "can_add_tmp_dropdown": True,
            "default_add_tmp_dropdown": True,
            "template_node_id": (template or {}).get("id"),
            "caption_text_node_id": (caption_node or {}).get("id"),
            "item_text_node_id": (item_text_node or {}).get("id"),
            "options": option_texts,
            "value": 0,
            "requires_review": requires_review,
            "notes": [
                "TMP_Dropdown binding is inferred from PSD/Photoshop layer names and text descendants.",
                "Template should usually be inactive in Unity; business callbacks remain empty for later binding.",
            ],
        }
        node["unity_interaction_hint"] = {
            "can_add_tmp_dropdown": True,
            "default_add_tmp_dropdown": True,
            "raycast_target_if_interactive": True,
        }
        if requires_review:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "dropdown_binding_requires_review",
                    "severity": "medium",
                    "message": "Detected a dropdown candidate but template/caption/item/options binding is incomplete; verify TMP_Dropdown references in Unity.",
                }
            )


def _button_label_text(node: dict[str, Any]) -> str | None:
    text = str((node.get("text") or {}).get("content") or node.get("name") or "").strip()
    if not text:
        return None
    lowered = text.lower()
    if not _has_any(lowered, _BUTTON_LABEL_TOKENS):
        return None
    rect = node.get("global_rect") or {}
    width = _rect_width(rect)
    height = _rect_height(rect)
    if width <= 0 or height <= 0:
        return None
    if height > 96 or width > 720:
        return None
    return text


def _first_text_descendant(node: dict[str, Any]) -> dict[str, Any] | None:
    for child in node.get("children") or []:
        if (child.get("text") or {}).get("content"):
            return child
        nested = _first_text_descendant(child)
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
        if _has_any(haystack, ("placeholder", "hint", "请输入", "输入", "占位")):
            return child
        nested = _first_placeholder_descendant(child)
        if nested:
            return nested
    return None


def _first_named_descendant(node: dict[str, Any], tokens: tuple[str, ...]) -> dict[str, Any] | None:
    for child in node.get("children") or []:
        haystack = " ".join(str(part or "") for part in (child.get("name"), child.get("path"))).lower()
        if _has_any(haystack, tokens):
            return child
        nested = _first_named_descendant(child, tokens)
        if nested:
            return nested
    return None


def _first_text_descendant_excluding(node: dict[str, Any], excluded_ids: set[str | None]) -> dict[str, Any] | None:
    for child in node.get("children") or []:
        if child.get("id") in excluded_ids:
            continue
        if (child.get("text") or {}).get("content"):
            return child
        nested = _first_text_descendant_excluding(child, excluded_ids)
        if nested:
            return nested
    return None


def _dropdown_options(
    node: dict[str, Any],
    template: dict[str, Any] | None,
    caption_node: dict[str, Any] | None,
) -> list[str]:
    options: list[str] = []
    source = template or node
    for descendant in _descendants(source):
        text = str((descendant.get("text") or {}).get("content") or "").strip()
        if text and text not in options:
            options.append(text)
    if not options and caption_node:
        text = str((caption_node.get("text") or {}).get("content") or "").strip()
        if text:
            options.append(text)
    return options


def _attach_tab_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    for node in nodes:
        if node.get("semantic_type") != "tab_group_candidate":
            continue
        tab_nodes = _tab_children(node)
        if len(tab_nodes) < 2:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "tab_group_requires_review",
                    "severity": "medium",
                    "message": "Detected a tab group candidate but fewer than two tab children could be inferred.",
                }
            )
            continue

        selected_ids = {tab.get("id") for tab in tab_nodes if _tab_selected_by_name(tab)}
        if not selected_ids and tab_nodes:
            selected_ids.add(tab_nodes[0].get("id"))
        node["unity_tab_group_hint"] = {
            "can_add_toggle_group": True,
            "default_add_toggle_group": True,
            "allow_switch_off": False,
            "tab_node_ids": [tab.get("id") for tab in tab_nodes if tab.get("id")],
            "selected_tab_node_id": next((tab.get("id") for tab in tab_nodes if tab.get("id") in selected_ids), None),
            "requires_review": False,
            "notes": [
                "Tab group is mapped to UnityEngine.UI.ToggleGroup.",
                "Each tab item is mapped to a Toggle whose m_Group references this ToggleGroup.",
            ],
        }
        for tab in tab_nodes:
            label = _first_text_descendant(tab)
            if label:
                _add_semantic_to_node(label, "tab_label_candidate", 0.82, ["text layer is likely the tab label"])
            _add_semantic_to_node(tab, "tab_candidate", 0.93, ["child belongs to inferred tab group"])
            tab["unity_tab_hint"] = {
                "can_add_toggle": True,
                "default_add_toggle": True,
                "group_node_id": node.get("id"),
                "label_node_id": (label or {}).get("id"),
                "value": tab.get("id") in selected_ids,
                "requires_review": False,
                "notes": [
                    "Tab item is mapped to UnityEngine.UI.Toggle.",
                    "Business page switching remains unbound for Unity MCP or project scripts.",
                ],
            }
            tab["unity_interaction_hint"] = {
                "can_add_toggle": True,
                "default_add_toggle": True,
                "raycast_target_if_interactive": True,
            }


def _attach_radio_hints(root: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    walk(root)
    for node in nodes:
        if node.get("semantic_type") != "radio_group_candidate":
            continue
        radio_nodes = _radio_children(node)
        if len(radio_nodes) < 2:
            warnings.append(
                {
                    "node_id": node.get("id"),
                    "code": "radio_group_requires_review",
                    "severity": "medium",
                    "message": "Detected a radio group candidate but fewer than two radio options could be inferred.",
                }
            )
            continue

        selected_ids = {radio.get("id") for radio in radio_nodes if _radio_selected_by_name(radio)}
        if not selected_ids and radio_nodes:
            selected_ids.add(radio_nodes[0].get("id"))
        node["unity_radio_group_hint"] = {
            "can_add_toggle_group": True,
            "default_add_toggle_group": True,
            "allow_switch_off": False,
            "radio_node_ids": [radio.get("id") for radio in radio_nodes if radio.get("id")],
            "selected_radio_node_id": next((radio.get("id") for radio in radio_nodes if radio.get("id") in selected_ids), None),
            "requires_review": False,
            "notes": [
                "Radio group is mapped to UnityEngine.UI.ToggleGroup.",
                "Each radio option is mapped to a Toggle whose m_Group references this ToggleGroup.",
            ],
        }
        for radio in radio_nodes:
            label = _first_text_descendant(radio)
            if label:
                _add_semantic_to_node(label, "radio_label_candidate", 0.82, ["text layer is likely the radio label"])
            _add_semantic_to_node(radio, "radio_candidate", 0.93, ["child belongs to inferred radio group"])
            radio["unity_radio_hint"] = {
                "can_add_toggle": True,
                "default_add_toggle": True,
                "group_node_id": node.get("id"),
                "label_node_id": (label or {}).get("id"),
                "value": radio.get("id") in selected_ids,
                "requires_review": False,
                "notes": [
                    "Radio option is mapped to UnityEngine.UI.Toggle.",
                    "Business value handling remains unbound for Unity MCP or project scripts.",
                ],
            }
            radio["unity_interaction_hint"] = {
                "can_add_toggle": True,
                "default_add_toggle": True,
                "raycast_target_if_interactive": True,
            }


def _tab_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for child in node.get("children") or []:
        if child.get("semantic_type") in {"background_candidate", "scrollbar_candidate"}:
            continue
        name = str(child.get("name") or "").lower()
        if _has_any(name, ("indicator", "underline", "divider", "line", "bg", "background", "指示", "分割", "背景")):
            continue
        if child.get("type") in {"group", "image", "shape", "text"} and (_first_text_descendant(child) or _looks_like_tab_item(child) or child.get("semantic_type") == "tab_candidate"):
            result.append(child)
    return result


def _looks_like_tab_item(node: dict[str, Any]) -> bool:
    rect = node.get("global_rect") or {}
    width = _rect_width(rect)
    height = _rect_height(rect)
    if width <= 0 or height <= 0:
        return False
    aspect = width / max(1.0, height)
    name = str(node.get("name") or "").lower()
    return 1.0 <= aspect <= 8.0 and 18 <= height <= 100 and (
        _has_any(name, ("tab", "页签", "标签", "nav", "menu"))
        or node.get("type") in {"group", "image", "shape"}
    )


def _radio_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for child in node.get("children") or []:
        if child.get("semantic_type") in {"background_candidate", "scrollbar_candidate", "dropdown_template_candidate"}:
            continue
        name = str(child.get("name") or "").lower()
        if _has_any(name, ("indicator", "divider", "line", "bg", "background", "标题", "title", "分割", "背景")):
            continue
        if child.get("type") in {"group", "image", "shape", "text"} and (
            _first_text_descendant(child)
            or _looks_like_radio_item(child)
            or child.get("semantic_type") == "radio_candidate"
        ):
            result.append(child)
    return result


def _looks_like_radio_item(node: dict[str, Any]) -> bool:
    rect = node.get("global_rect") or {}
    width = _rect_width(rect)
    height = _rect_height(rect)
    if width <= 0 or height <= 0:
        return False
    aspect = width / max(1.0, height)
    name = str(node.get("name") or "").lower()
    return 0.4 <= aspect <= 12.0 and 16 <= height <= 120 and (
        _has_any(name, ("radio", "choice", "option", "单选", "选项"))
        or node.get("type") in {"group", "image", "shape"}
    )


def _radio_selected_by_name(node: dict[str, Any]) -> bool:
    haystack = " ".join(str(part or "") for part in (node.get("name"), node.get("path"))).lower()
    return _has_any(haystack, ("selected", "active", "current", "on", "checked", "true", "选中", "当前", "激活"))


def _tab_selected_by_name(node: dict[str, Any]) -> bool:
    haystack = " ".join(str(part or "") for part in (node.get("name"), node.get("path"))).lower()
    return _has_any(haystack, ("selected", "active", "current", "on", "checked", "选中", "当前", "激活"))


def _best_button_backing_for_text(
    text_node: dict[str, Any],
    nodes: list[dict[str, Any]],
    parent_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    text_rect = text_node.get("global_rect") or {}
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in nodes:
        if candidate is text_node or candidate.get("type") == "text":
            continue
        if candidate.get("semantic_type") in {"screen_root", "background_candidate", "title_candidate", "input_candidate", "dropdown_candidate"}:
            continue
        rect = candidate.get("global_rect") or {}
        score = _button_backing_score(text_node, candidate, parent_by_id)
        if score <= 0:
            continue
        if _rect_width(rect) < _rect_width(text_rect) * 0.9:
            continue
        scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1] if scored[0][0] >= 5.0 else None


def _button_backing_score(
    text_node: dict[str, Any],
    candidate: dict[str, Any],
    parent_by_id: dict[str, dict[str, Any]],
) -> float:
    text_rect = text_node.get("global_rect") or {}
    candidate_rect = candidate.get("global_rect") or {}
    text_w = _rect_width(text_rect)
    text_h = _rect_height(text_rect)
    cand_w = _rect_width(candidate_rect)
    cand_h = _rect_height(candidate_rect)
    if not text_w or not text_h or not cand_w or not cand_h:
        return 0.0
    if cand_w < text_w * 0.9 or cand_h < text_h * 1.05:
        return 0.0
    if cand_w > max(text_w * 2.6, text_w + 180) or cand_h > max(text_h * 4.2, text_h + 80):
        return 0.0
    if cand_w / max(cand_h, 1) < 1.8:
        return 0.0

    overlap = _rect_overlap_ratio(text_rect, candidate_rect)
    if overlap < 0.55:
        return 0.0

    text_cx, text_cy = _rect_center(text_rect)
    cand_cx, cand_cy = _rect_center(candidate_rect)
    x_alignment = abs(text_cx - cand_cx) / max(cand_w, 1)
    y_alignment = abs(text_cy - cand_cy) / max(cand_h, 1)
    score = 4.0 + overlap * 2.0
    if x_alignment <= 0.18:
        score += 1.5
    if y_alignment <= 0.24:
        score += 1.5
    if parent_by_id.get(text_node.get("id")) is parent_by_id.get(candidate.get("id")):
        score += 2.0
    if candidate.get("type") in {"image", "shape"}:
        score += 1.0
    if candidate.get("semantic_type") in {"progress_candidate", "panel_candidate"}:
        score += 0.5
    return score


def _apply_psd_semantics(node: dict[str, Any]) -> None:
    name = str(node.get("name") or "").lower()
    if node.get("type") == "group" and _has_any(name, ("scroll", "scrollview", "scroll_view", "滚动", "滑动区域")):
        _add_semantic_to_node(node, "scroll_area_candidate", 0.86, ["PSD group name suggests scroll area"])
    if node.get("type") == "group" and _has_any(name, ("radiogroup", "radio_group", "radio group", "radiooptions", "radio_options", "choice_group", "单选组", "选项组")):
        _add_semantic_to_node(node, "radio_group_candidate", 0.88, ["PSD group name suggests radio group"])
    elif _has_any(name, ("radio_", "_radio", "radio-", "-radio", "单选")):
        _add_semantic_to_node(node, "radio_candidate", 0.78, ["PSD layer name suggests radio option"])
    if _has_any(name, ("viewport", "view_port", "视口")):
        _add_semantic_to_node(node, "scroll_viewport_candidate", 0.9, ["PSD layer name suggests viewport"])
    elif _has_any(name, ("clip", "mask", "clipping", "clip_rect", "cliprect", "裁剪", "蒙版", "遮罩")) or node.get("type") == "mask":
        _add_semantic_to_node(node, "mask_candidate", 0.84, ["PSD layer name suggests rectangular clipping/mask container"])
    if _has_any(name, ("content", "container", "items", "列表内容", "内容")):
        _add_semantic_to_node(node, "scroll_content_candidate", 0.9, ["PSD layer name suggests scroll content"])
    if node.get("semantic_type") == "toggle_candidate":
        graphic = _first_named_child(node, ("check", "checkmark", "tick", "on", "selected", "knob", "handle", "勾", "选中"))
        node["unity_toggle_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "value": _toggle_value_from_name(name),
            "graphic_node_id": (graphic or {}).get("id"),
            "requires_review": False,
            "notes": [
                "Toggle was inferred from PSD layer naming.",
                "If graphic_node_id is empty, the Toggle component uses the target graphic as its state graphic.",
            ],
        }
        node["unity_interaction_hint"] = {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "raycast_target_if_interactive": True,
        }


def _add_semantic_to_node(node: dict[str, Any], semantic_type: str, confidence: float, reasons: list[str]) -> None:
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
    if node.get("semantic_type") == "scroll_area_candidate":
        node["unity_interaction_hint"] = {
            "can_add_scroll_rect": True,
            "default_add_scroll_rect": True,
            "requires_content_viewport_review": True,
        }
    if node.get("semantic_type") == "mask_candidate":
        _attach_mask_hint(node)


def _attach_mask_hint(node: dict[str, Any]) -> None:
    node["unity_mask_hint"] = {
        "can_add_rect_mask_2d": True,
        "default_add_rect_mask_2d": True,
        "recommended_unity_component": "RectMask2D",
        "requires_review": False,
        "notes": [
            "Mask candidate is mapped to UnityEngine.UI.RectMask2D.",
            "This is rectangular UI clipping; Photoshop bitmap/vector masks still require visual QA or rasterized export.",
        ],
    }


def _toggle_value_from_name(name: str) -> bool | None:
    lowered = str(name or "").lower()
    if _has_any(lowered, ("off", "unchecked", "uncheck", "disabled", "false", "关", "未选")):
        return False
    if _has_any(lowered, ("on", "checked", "check", "selected", "true", "开", "选中", "勾选")):
        return True
    return None


def _children(layer: Any) -> list[Any]:
    try:
        return list(layer)
    except TypeError:
        return []
    except Exception:
        return []


def _is_visible(layer: Any) -> bool:
    method = getattr(layer, "is_visible", None)
    if callable(method):
        try:
            return bool(method())
        except Exception:
            return True
    return bool(getattr(layer, "visible", True))


def _is_group(layer: Any) -> bool:
    method = getattr(layer, "is_group", None)
    if callable(method):
        try:
            return bool(method())
        except Exception:
            return bool(_children(layer))
    return bool(_children(layer))


def _node_type(layer: Any) -> str:
    if _is_group(layer):
        return "group"
    kind = _layer_kind(layer).lower()
    if kind in {"type", "text", "textlayer"} or _text_content(layer):
        return "text"
    if kind in {"shape", "solidcolorfill", "gradientfill"}:
        return "shape"
    if kind in {"pixel", "smartobject", "placedlayer", "image"}:
        return "image"
    return "unknown"


def _layer_kind(layer: Any) -> str:
    return str(getattr(layer, "kind", "") or getattr(layer, "layer_kind", "") or type(layer).__name__)


def _layer_name(layer: Any) -> str:
    return str(getattr(layer, "name", None) or _layer_kind(layer) or "Layer").strip() or "Layer"


def _layer_id(layer: Any, z_index: int) -> str:
    for attr in ("layer_id", "id"):
        value = getattr(layer, attr, None)
        if value is not None:
            return f"psd_layer_{value}"
    raw = f"{_layer_name(layer)}:{_bbox_rect(layer)}:{z_index}"
    return "psd_layer_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _bbox_rect(layer: Any) -> dict[str, float]:
    bbox = getattr(layer, "bbox", None)
    if callable(bbox):
        bbox = bbox()
    left = top = right = bottom = 0.0
    if bbox is not None:
        for attrs in (("x1", "y1", "x2", "y2"), ("left", "top", "right", "bottom")):
            if all(hasattr(bbox, attr) for attr in attrs):
                left, top, right, bottom = [float(getattr(bbox, attr) or 0) for attr in attrs]
                break
        else:
            try:
                left, top, right, bottom = [float(value or 0) for value in bbox[:4]]
            except Exception:
                pass
    return {"x": left, "y": top, "width": max(0, right - left), "height": max(0, bottom - top)}


def _scaled_rect(rect: dict[str, float], scale: float) -> dict[str, float]:
    return {key: round(value / scale, 1) for key, value in rect.items()}


def _union_rect(rects: list[dict[str, Any]]) -> dict[str, float]:
    valid = [
        rect
        for rect in rects
        if float(rect.get("width") or 0) > 0 and float(rect.get("height") or 0) > 0
    ]
    if not valid:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    left = min(float(rect.get("x") or 0) for rect in valid)
    top = min(float(rect.get("y") or 0) for rect in valid)
    right = max(float(rect.get("x") or 0) + float(rect.get("width") or 0) for rect in valid)
    bottom = max(float(rect.get("y") or 0) + float(rect.get("height") or 0) for rect in valid)
    return {"x": round(left, 1), "y": round(top, 1), "width": round(right - left, 1), "height": round(bottom - top, 1)}


def _style_info(layer: Any, warnings: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    opacity = getattr(layer, "opacity", 255)
    try:
        opacity_value = float(opacity)
        if opacity_value > 1:
            opacity_value = opacity_value / 255 if opacity_value <= 255 else opacity_value / 100
    except (TypeError, ValueError):
        opacity_value = 1
    style = {
        "opacity": round(max(0, min(1, opacity_value)), 3),
        "blend_mode": str(getattr(layer, "blend_mode", "") or "") or None,
    }
    if _has_effects(layer):
        warnings.append(
            {
                "node_id": node_id,
                "code": "psd_layer_effect_requires_review",
                "severity": "medium",
                "message": "Layer effects may not match exactly after Unity export; compare visually in Unity.",
            }
        )
    return {key: value for key, value in style.items() if value is not None}


def _psd_feature_info(layer: Any, style: dict[str, Any]) -> dict[str, Any]:
    raw_kind = _layer_kind(layer)
    normalized_kind = _normalize_feature_token(raw_kind)
    blend_mode = _normalize_blend_mode(style.get("blend_mode") or getattr(layer, "blend_mode", None))
    has_mask = _has_psd_mask(layer)
    has_vector_mask = _truthy_psd_value(layer, ("has_vector_mask", "vector_mask", "vector_mask_data"))
    has_clipping_mask = _has_clipping_mask(layer)
    has_layer_effects = _has_effects(layer)
    is_smart_object = normalized_kind in {"smartobject", "placedlayer"} or _truthy_psd_value(layer, ("smart_object", "smartobject"))
    is_adjustment_layer = _is_adjustment_layer_kind(normalized_kind)
    uses_non_normal_blend = bool(blend_mode and blend_mode not in _NORMAL_BLEND_MODES)
    unsupported_features = []
    if has_mask:
        unsupported_features.append("mask")
    if has_vector_mask:
        unsupported_features.append("vector_mask")
    if has_clipping_mask:
        unsupported_features.append("clipping_mask")
    if has_layer_effects:
        unsupported_features.append("layer_effects")
    if uses_non_normal_blend:
        unsupported_features.append("blend_mode")
    if is_smart_object:
        unsupported_features.append("smart_object")
    if is_adjustment_layer:
        unsupported_features.append("adjustment_layer")
    return {
        "psd_layer_kind_normalized": normalized_kind,
        "psd_blend_mode_normalized": blend_mode,
        "has_mask": has_mask,
        "has_vector_mask": has_vector_mask,
        "has_clipping_mask": has_clipping_mask,
        "has_layer_effects": has_layer_effects,
        "uses_non_normal_blend_mode": uses_non_normal_blend,
        "is_smart_object": is_smart_object,
        "is_adjustment_layer": is_adjustment_layer,
        "unsupported_psd_features": unsupported_features,
        "recommended_fidelity_mode": "group_or_document_rasterize" if unsupported_features else "layer",
    }


def _append_feature_warnings(name: str, node_id: str, feature_info: dict[str, Any], warnings: list[dict[str, Any]]) -> None:
    if feature_info.get("has_mask") or feature_info.get("has_vector_mask"):
        warnings.append(
            {
                "node_id": node_id,
                "code": "psd_mask_requires_review",
                "severity": "medium",
                "message": f"Layer '{name}' uses a Photoshop mask; compare Unity output against the flattened PSD reference or export the group as a rasterized slice.",
            }
        )
    if feature_info.get("has_clipping_mask"):
        warnings.append(
            {
                "node_id": node_id,
                "code": "psd_clipping_mask_requires_review",
                "severity": "medium",
                "message": f"Layer '{name}' appears to use clipping; verify clipping behavior in Unity or rasterize the clipped group.",
            }
        )
    if feature_info.get("uses_non_normal_blend_mode"):
        warnings.append(
            {
                "node_id": node_id,
                "code": "psd_blend_mode_requires_review",
                "severity": "medium",
                "message": f"Layer '{name}' uses blend mode '{feature_info.get('psd_blend_mode_normalized')}'; Unity Image alpha blending may not match Photoshop.",
            }
        )
    if feature_info.get("is_smart_object"):
        warnings.append(
            {
                "node_id": node_id,
                "code": "psd_smart_object_rasterized",
                "severity": "low",
                "message": f"Layer '{name}' is a smart object or placed layer; it is exported as a raster image in the first-stage PSD adapter.",
            }
        )
    if feature_info.get("is_adjustment_layer"):
        warnings.append(
            {
                "node_id": node_id,
                "code": "psd_adjustment_layer_requires_review",
                "severity": "medium",
                "message": f"Layer '{name}' is an adjustment layer; prefer the flattened reference or a Photoshop UXP export for exact color output.",
            }
        )


_NORMAL_BLEND_MODES = {"", "normal", "pass through", "passthrough", "pass_through"}
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


def _normalize_blend_mode(value: Any) -> str | None:
    if value is None:
        return None
    for attr in ("name", "value"):
        nested = getattr(value, attr, None)
        if nested is not None and nested is not value:
            text = str(nested)
            break
    else:
        text = str(value)
    text = text.strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    text = text.replace("_", " ").replace("-", " ").lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _normalize_feature_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "", text)


def _has_psd_mask(layer: Any) -> bool:
    return _truthy_psd_value(
        layer,
        (
            "has_mask",
            "has_user_mask",
            "has_vector_mask",
            "has_filter_mask",
            "mask",
            "user_mask",
            "layer_mask",
            "vector_mask",
            "mask_data",
            "masks",
        ),
    )


def _has_clipping_mask(layer: Any) -> bool:
    return _truthy_psd_value(
        layer,
        (
            "is_clipping",
            "clipping",
            "clipped",
            "clip",
        ),
    )


def _truthy_psd_value(layer: Any, names: tuple[str, ...]) -> bool:
    for name in names:
        value = getattr(layer, name, None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                continue
            except Exception:
                continue
        if _is_meaningful_psd_value(value):
            return True
    return False


def _is_meaningful_psd_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (str, bytes, list, tuple, dict, set)):
        return len(value) > 0
    try:
        return bool(value)
    except Exception:
        return True


def _is_adjustment_layer_kind(normalized_kind: str) -> bool:
    if normalized_kind in _ADJUSTMENT_LAYER_KINDS:
        return True
    return normalized_kind.endswith("adjustment") or normalized_kind.endswith("adjustmentlayer")


def _text_info(layer: Any, scale: float, warnings: list[dict[str, Any]], node_id: str) -> dict[str, Any] | None:
    content = _text_content(layer)
    if content is None:
        return None
    engine = getattr(layer, "engine_dict", None) or getattr(getattr(layer, "text_data", None), "engine_dict", None)
    font_size = _find_first_number(engine, ("FontSize", "fontSize", "font-size"))
    color = _find_first_color(engine)
    if not font_size:
        rect = _scaled_rect(_bbox_rect(layer), scale)
        font_size = max(1, round((rect.get("height") or 24) * 0.7, 1))
    text = _normalize_text_payload(
        content=str(content),
        text_style={
            "font_family": _find_font_name(engine),
            "font_size": font_size,
            "font_weight": _find_font_weight(engine),
            "font_style": _find_font_style(engine),
            "color": color,
            "align": _find_alignment(engine),
            "spans": _text_spans_from_engine(engine, str(content), scale),
            "effects": _text_effects_from_layer(layer),
            "style_quality": "best_effort",
        },
        scale=scale,
    )
    warnings.append(
        {
            "node_id": node_id,
            "code": "psd_text_style_best_effort",
            "severity": "low",
            "message": "PSD text style was mapped best-effort to TextMeshProUGUI; verify font asset, alignment, and line spacing in Unity.",
        }
    )
    return text


def _normalize_text_payload(content: str, text_style: dict[str, Any], scale: float) -> dict[str, Any]:
    font_size = _coerce_scaled_number(text_style.get("font_size") or text_style.get("fontSize") or text_style.get("size"), scale, 24)
    line_height = _coerce_scaled_number(text_style.get("line_height") or text_style.get("lineHeight") or text_style.get("leading"), scale, None)
    letter_spacing = _coerce_scaled_number(text_style.get("letter_spacing") or text_style.get("letterSpacing") or text_style.get("tracking"), scale, 0)
    font_family = text_style.get("font_family") or text_style.get("fontFamily") or text_style.get("font")
    font_style = text_style.get("font_style") or text_style.get("fontStyle") or text_style.get("style")
    font_weight = text_style.get("font_weight") or text_style.get("fontWeight") or _font_weight_from_style(font_style)
    spans = _normalize_text_spans(
        text_style.get("spans") or text_style.get("runs") or text_style.get("styleRanges") or text_style.get("ranges"),
        content,
        scale,
    )
    effects = _normalize_text_effects(text_style)
    result: dict[str, Any] = {
        "content": content,
        "font_family": font_family,
        "font_size": font_size,
        "font_weight": font_weight,
        "font_style": font_style,
        "color": text_style.get("color") or text_style.get("fill"),
        "align": text_style.get("align") or text_style.get("alignment"),
        "line_height": line_height,
        "letter_spacing": letter_spacing or 0,
        "overflow": text_style.get("overflow") or "clip",
        "wrap": bool(text_style.get("wrap")) or "\n" in content,
        "style_quality": text_style.get("style_quality") or "explicit",
        "font_hint": {
            "source_font_family": font_family,
            "source_font_style": font_style,
            "source_font_weight": font_weight,
            "font_asset_lookup_key": _font_lookup_key(" ".join(str(item) for item in (font_family, font_style or font_weight or "") if item)),
            "tmp_font_asset_guid": text_style.get("tmp_font_asset_guid") or text_style.get("tmpFontAssetGuid") or text_style.get("unity_font_asset_guid") or text_style.get("unityFontAssetGuid"),
            "fallback_policy": "use_project_default_tmp_font",
        },
    }
    if spans:
        result["spans"] = spans
        result["rich_text"] = True
    if effects:
        result["effects"] = effects
    return {key: value for key, value in result.items() if value is not None}


def _normalize_text_spans(raw: Any, content: str, scale: float) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        start = int(_num(_first_present(item, ("start", "from", "offset"))) or 0)
        length = _num(item.get("length"))
        end = _num(_first_present(item, ("end", "to")))
        if length is None and end is not None:
            length = max(0, end - start)
        if length is None:
            length = len(content) - start
        if length <= 0:
            continue
        style = item.get("style") if isinstance(item.get("style"), dict) else item
        normalized = {
            "start": max(0, start),
            "length": max(0, int(length)),
            "font_family": style.get("font_family") or style.get("fontFamily") or style.get("font"),
            "font_size": _coerce_scaled_number(style.get("font_size") or style.get("fontSize") or style.get("size"), scale, None),
            "font_weight": style.get("font_weight") or style.get("fontWeight") or _font_weight_from_style(style.get("font_style") or style.get("fontStyle")),
            "font_style": style.get("font_style") or style.get("fontStyle") or style.get("style"),
            "color": style.get("color") or style.get("fill"),
            "underline": style.get("underline"),
            "italic": style.get("italic"),
        }
        result.append({key: value for key, value in normalized.items() if value is not None})
    return result


def _normalize_text_effects(style: dict[str, Any]) -> dict[str, Any]:
    effects: dict[str, Any] = {}
    raw_effects = style.get("effects") if isinstance(style.get("effects"), (dict, list)) else None
    outline = (
        style.get("outline")
        or style.get("stroke")
        or style.get("textStroke")
        or _effect_from_collection(raw_effects, ("outline", "stroke", "framefx"))
    )
    shadow = (
        style.get("shadow")
        or style.get("dropShadow")
        or style.get("drop_shadow")
        or _effect_from_collection(raw_effects, ("shadow", "dropshadow", "drop_shadow"))
    )
    stroke_width = _first_present(style, ("stroke_width", "strokeWidth", "outline_width", "outlineWidth"))
    stroke_color = _first_present(style, ("stroke_color", "strokeColor", "outline_color", "outlineColor"))
    if outline or stroke_width or stroke_color:
        outline_dict = outline if isinstance(outline, dict) else {}
        enabled = outline_dict.get("enabled", True)
        if enabled:
            effects["outline"] = {
                "width": _num(_first_present(outline_dict, ("width", "size"), stroke_width), 1),
                "color": outline_dict.get("color") or outline_dict.get("fill") or stroke_color or "rgba(0,0,0,1)",
                "use_graphic_alpha": outline_dict.get("use_graphic_alpha", True),
            }
    shadow_color = _first_present(style, ("shadow_color", "shadowColor"))
    shadow_x = _first_present(style, ("shadow_offset_x", "shadowOffsetX"))
    shadow_y = _first_present(style, ("shadow_offset_y", "shadowOffsetY"))
    if shadow or shadow_color or shadow_x is not None or shadow_y is not None:
        shadow_dict = shadow if isinstance(shadow, dict) else {}
        enabled = shadow_dict.get("enabled", True)
        if enabled:
            offset = shadow_dict.get("offset") if isinstance(shadow_dict.get("offset"), dict) else {}
            effects["shadow"] = {
                "color": shadow_dict.get("color") or shadow_color or "rgba(0,0,0,0.5)",
                "offset": {
                    "x": _num(_first_present(offset, ("x",), _first_present(shadow_dict, ("x",), shadow_x)), 1),
                    "y": _num(_first_present(offset, ("y",), _first_present(shadow_dict, ("y",), shadow_y)), -1),
                },
                "use_graphic_alpha": shadow_dict.get("use_graphic_alpha", True),
            }
    return effects


def _text_spans_from_engine(engine: Any, content: str, scale: float) -> list[dict[str, Any]]:
    run_array = _find_first_by_key(engine, ("RunArray", "runArray"))
    if not isinstance(run_array, list):
        return []
    result = []
    cursor = 0
    for run in run_array:
        if not isinstance(run, dict):
            continue
        length = int(_num(run.get("RunLength") or run.get("runLength"), 0))
        style_data = _find_first_by_key(run, ("StyleSheetData", "styleSheetData")) or run
        if length <= 0:
            continue
        result.append(
            {
                "start": cursor,
                "length": min(length, max(0, len(content) - cursor)),
                "font_family": _find_font_name(style_data),
                "font_size": _coerce_scaled_number(_find_first_number(style_data, ("FontSize", "fontSize", "font-size")), scale, None),
                "font_weight": _find_font_weight(style_data),
                "font_style": _find_font_style(style_data),
                "color": _find_first_color(style_data),
            }
        )
        cursor += length
    return [{key: value for key, value in span.items() if value is not None} for span in result if span.get("length")]


def _text_effects_from_layer(layer: Any) -> dict[str, Any]:
    raw = getattr(layer, "effects", None)
    if callable(raw):
        try:
            raw = raw()
        except Exception:
            raw = None
    return _normalize_text_effects({"effects": raw})


def _effect_from_collection(raw: Any, tokens: tuple[str, ...]) -> Any:
    if isinstance(raw, dict):
        for key, value in raw.items():
            normalized = _normalize_feature_token(key)
            if any(token in normalized for token in tokens):
                return value if isinstance(value, dict) else {"enabled": bool(value)}
        for value in raw.values():
            match = _effect_from_collection(value, tokens)
            if match:
                return match
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                effect_type = _normalize_feature_token(item.get("type") or item.get("name") or item.get("effect") or "")
                if any(token in effect_type for token in tokens):
                    return item
                match = _effect_from_collection(item, tokens)
                if match:
                    return match
            else:
                effect_type = _normalize_feature_token(item)
                if any(token in effect_type for token in tokens):
                    return {"enabled": True}
    return None


def _coerce_scaled_number(value: Any, scale: float, default: float | None) -> float | None:
    number = _num(value)
    if number is None:
        return default
    if scale > 1:
        number = number / scale
    return round(float(number), 3)


def _font_lookup_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _font_weight_from_style(value: Any) -> int | None:
    lowered = str(value or "").lower()
    if any(token in lowered for token in ("black", "heavy", "bold", "semibold", "demibold")):
        return 700
    if "medium" in lowered:
        return 500
    if "light" in lowered:
        return 300
    return None


def _find_font_weight(obj: Any) -> int | None:
    direct = _find_first_by_key(obj, ("FontWeight", "fontWeight", "weight"))
    if direct is not None:
        number = _num(direct)
        if number is not None:
            return int(number)
        return _font_weight_from_style(direct)
    return _font_weight_from_style(_find_font_style(obj))


def _find_font_style(obj: Any) -> str | None:
    for key, value in _walk_items(obj):
        lowered = str(key).lower()
        if lowered in {"fontstyle", "font_style", "style", "stylename"} and isinstance(value, str):
            return value
        if lowered in {"fauxbold", "bold"} and value:
            return "Bold"
        if lowered in {"fauxitalic", "italic"} and value:
            return "Italic"
    return None


def _find_first_by_key(obj: Any, names: tuple[str, ...]) -> Any:
    wanted = {name.lower() for name in names}
    for key, value in _walk_items(obj):
        if str(key).lower() in wanted:
            return value
    return None


def _first_present(obj: dict[str, Any], names: tuple[str, ...], default: Any = None) -> Any:
    for name in names:
        if name in obj and obj.get(name) is not None:
            return obj.get(name)
    return default


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text_content(layer: Any) -> str | None:
    for attr in ("text", "text_value"):
        value = getattr(layer, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:
                value = None
        if isinstance(value, str):
            return value
    text_data = getattr(layer, "text_data", None)
    for attr in ("text", "value"):
        value = getattr(text_data, attr, None)
        if isinstance(value, str):
            return value
    return None


def _layer_image(layer: Any) -> Any | None:
    for name in ("topil", "composite"):
        method = getattr(layer, name, None)
        if not callable(method):
            continue
        try:
            image = method()
        except Exception:
            continue
        if image is not None:
            return image
    return None


def _save_png(image: Any, path: Path) -> None:
    if getattr(image, "mode", "") != "RGBA":
        image = image.convert("RGBA")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


def _image_size(path: Path) -> dict[str, int] | None:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return {"width": int.from_bytes(data[16:20], "big"), "height": int.from_bytes(data[20:24], "big")}
    return None


def _has_effects(layer: Any) -> bool:
    for attr in ("effects", "tagged_blocks"):
        value = getattr(layer, attr, None)
        try:
            if value and len(value) > 0:
                return True
        except Exception:
            if value:
                return True
    return False


def _find_first_number(obj: Any, names: tuple[str, ...]) -> float | None:
    for key, value in _walk_items(obj):
        if str(key) in names:
            try:
                return float(value)
            except (TypeError, ValueError):
                nested = _find_first_number(value, names)
                if nested is not None:
                    return nested
    return None


def _find_first_color(obj: Any) -> str | None:
    for key, value in _walk_items(obj):
        lowered = str(key).lower()
        if "color" not in lowered and "fillcolor" not in lowered:
            continue
        color = _coerce_color(value)
        if color:
            return color
    return None


def _coerce_color(value: Any) -> str | None:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        channels = [float(item) for item in value[:4]]
        if max(channels[:3], default=1) <= 1:
            channels[:3] = [item * 255 for item in channels[:3]]
        r, g, b = [round(max(0, min(255, item))) for item in channels[:3]]
        a = channels[3] if len(channels) >= 4 else 1
        if a > 1:
            a = a / 255 if a <= 255 else a / 100
        return f"rgba({r},{g},{b},{round(max(0, min(1, a)), 3)})"
    if isinstance(value, dict):
        vals = value.get("Values") or value.get("values")
        if isinstance(vals, (list, tuple)) and len(vals) >= 3:
            return _coerce_color(vals)
    return None


def _find_font_name(obj: Any) -> str | None:
    for key, value in _walk_items(obj):
        if str(key).lower() in {"fontname", "font", "name"} and isinstance(value, str):
            return value
    return None


def _find_alignment(obj: Any) -> str | None:
    for key, value in _walk_items(obj):
        if "justification" in str(key).lower() or "align" in str(key).lower():
            return str(value)
    return None


def _walk_items(obj: Any) -> list[tuple[Any, Any]]:
    result: list[tuple[Any, Any]] = []
    if obj is None:
        return result
    if isinstance(obj, dict):
        for key, value in obj.items():
            result.append((key, value))
            result.extend(_walk_items(value))
    elif isinstance(obj, (list, tuple)):
        for index, value in enumerate(obj):
            result.append((index, value))
            result.extend(_walk_items(value))
    elif hasattr(obj, "items"):
        try:
            for key, value in obj.items():
                result.append((key, value))
                result.extend(_walk_items(value))
        except Exception:
            pass
    return result


def _descendants(node: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def walk(current: dict[str, Any]) -> None:
        for child in current.get("children") or []:
            result.append(child)
            walk(child)

    walk(node)
    return result


def _nearby_slider_siblings(node: dict[str, Any], parent: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not parent:
        return []
    owner_rect = node.get("global_rect") or {}
    owner_area = _rect_width(owner_rect) * _rect_height(owner_rect)
    result = []
    for sibling in parent.get("children") or []:
        if sibling.get("id") == node.get("id"):
            continue
        sibling_rect = sibling.get("global_rect") or {}
        sibling_area = _rect_width(sibling_rect) * _rect_height(sibling_rect)
        if owner_area and sibling_area > owner_area * 3:
            continue
        name = str(sibling.get("name") or "").lower()
        if _has_any(name, _SLIDER_PART_TOKENS) and _rect_overlap_ratio(owner_rect, sibling_rect) >= 0.2:
            result.append(sibling)
    return result


_SLIDER_PART_TOKENS = (
    "track",
    "rail",
    "bg",
    "background",
    "fill",
    "filled",
    "progress",
    "bar",
    "value",
    "foreground",
    "handle",
    "thumb",
    "knob",
    "drag",
    "dot",
    "底条",
    "底图",
    "背景",
    "填充",
    "进度",
    "前景",
    "滑块",
    "拖拽",
)
_SLIDER_TRACK_TOKENS = ("track", "rail", "bg", "background", "base", "empty", "底条", "底图", "背景")
_SLIDER_FILL_TOKENS = ("fill", "filled", "progress", "bar_fill", "value", "foreground", "front", "hp", "血", "填充", "进度", "前景")
_SLIDER_HANDLE_TOKENS = ("handle", "thumb", "knob", "drag", "dot", "slider_dot", "滑块", "拖拽", "圆点")


def _best_slider_part(
    owner: dict[str, Any],
    candidates: list[dict[str, Any]],
    part: str,
    anchor: dict[str, Any] | None = None,
    excluded_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    excluded_ids = excluded_ids or set()
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("id") or "")
        if not candidate_id or candidate_id in excluded_ids:
            continue
        if candidate.get("children"):
            continue
        if candidate.get("type") == "text":
            continue
        rect = candidate.get("global_rect") or {}
        if _rect_width(rect) <= 0 or _rect_height(rect) <= 0:
            continue
        score = _slider_name_score(candidate, part) + _slider_geometry_score(owner, candidate, part, anchor)
        if score > 0:
            scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    threshold = 4.0 if part == "handle" else 3.0
    return scored[0][1] if scored[0][0] >= threshold else None


def _slider_name_score(node: dict[str, Any], part: str) -> float:
    text = f"{node.get('name') or ''} {node.get('path') or ''}".lower()
    if part == "track":
        tokens = _SLIDER_TRACK_TOKENS
        conflicting = _SLIDER_FILL_TOKENS + _SLIDER_HANDLE_TOKENS
    elif part == "fill":
        tokens = _SLIDER_FILL_TOKENS
        conflicting = _SLIDER_HANDLE_TOKENS
    else:
        tokens = _SLIDER_HANDLE_TOKENS
        conflicting = _SLIDER_FILL_TOKENS + _SLIDER_TRACK_TOKENS
    score = 8.0 if _has_any(text, tokens) else 0.0
    if score and _has_any(text, conflicting):
        score -= 2.5
    return score


def _slider_geometry_score(
    owner: dict[str, Any],
    candidate: dict[str, Any],
    part: str,
    anchor: dict[str, Any] | None,
) -> float:
    owner_rect = owner.get("global_rect") or {}
    candidate_rect = candidate.get("global_rect") or {}
    base_rect = (anchor or owner).get("global_rect") or owner_rect
    owner_w = _rect_width(owner_rect)
    owner_h = _rect_height(owner_rect)
    base_w = _rect_width(base_rect) or owner_w
    base_h = _rect_height(base_rect) or owner_h
    cand_w = _rect_width(candidate_rect)
    cand_h = _rect_height(candidate_rect)
    if not owner_w or not owner_h or not cand_w or not cand_h:
        return 0.0

    score = 0.0
    overlap = _rect_overlap_ratio(owner_rect, candidate_rect)
    if overlap >= 0.55:
        score += 1.5
    elif overlap >= 0.25:
        score += 0.5

    width_ratio = cand_w / max(base_w, 1)
    height_ratio = cand_h / max(base_h or owner_h, 1)
    aspect = cand_w / max(cand_h, 1)
    if part == "track":
        if width_ratio >= 0.72 and 0.45 <= height_ratio <= 1.8:
            score += 3.0
        if aspect >= 3.0:
            score += 1.0
    elif part == "fill":
        if 0.04 <= width_ratio <= 1.02 and 0.35 <= height_ratio <= 1.8:
            score += 2.5
        if aspect >= 2.0:
            score += 1.0
        if abs(float(candidate_rect.get("x") or 0) - float(base_rect.get("x") or owner_rect.get("x") or 0)) <= max(4.0, base_w * 0.04):
            score += 2.0
        if width_ratio < 0.98:
            score += 1.0
    else:
        if cand_w <= owner_w * 0.45 and 0.45 <= cand_w / max(cand_h, 1) <= 2.2:
            score += 2.5
        if 0.35 <= cand_h / max(owner_h, 1) <= 2.2:
            score += 2.0
        if anchor:
            fill_rect = anchor.get("global_rect") or {}
            fill_right = float(fill_rect.get("x") or 0) + _rect_width(fill_rect)
            handle_center = float(candidate_rect.get("x") or 0) + cand_w / 2
            if abs(handle_center - fill_right) <= max(cand_w, owner_w * 0.08):
                score += 3.0
    return score


def _slider_value_from_parts(
    node: dict[str, Any],
    fill: dict[str, Any] | None,
    track: dict[str, Any] | None,
) -> float | None:
    haystack = " ".join(
        str(part or "")
        for part in (
            node.get("name"),
            node.get("path"),
            (node.get("text") or {}).get("content"),
            (fill or {}).get("name"),
            (fill or {}).get("path"),
        )
    )
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", haystack)
    if percent:
        return round(max(0, min(1, float(percent.group(1)) / 100)), 4)
    decimal = re.search(r"\b0\.\d+\b", haystack)
    if decimal:
        return round(max(0, min(1, float(decimal.group(0)))), 4)
    if fill:
        fill_rect = fill.get("global_rect") or {}
        base_rect = (track or node).get("global_rect") or {}
        base_w = _rect_width(base_rect)
        if base_w:
            return round(max(0, min(1, _rect_width(fill_rect) / base_w)), 4)
    return None


def _rect_width(rect: dict[str, Any]) -> float:
    try:
        return max(0.0, float(rect.get("width") or 0))
    except (TypeError, ValueError):
        return 0.0


def _rect_height(rect: dict[str, Any]) -> float:
    try:
        return max(0.0, float(rect.get("height") or 0))
    except (TypeError, ValueError):
        return 0.0


def _rect_overlap_ratio(a: dict[str, Any], b: dict[str, Any]) -> float:
    aw = _rect_width(a)
    ah = _rect_height(a)
    bw = _rect_width(b)
    bh = _rect_height(b)
    if not aw or not ah or not bw or not bh:
        return 0.0
    ax1 = float(a.get("x") or 0)
    ay1 = float(a.get("y") or 0)
    bx1 = float(b.get("x") or 0)
    by1 = float(b.get("y") or 0)
    ax2 = ax1 + aw
    ay2 = ay1 + ah
    bx2 = bx1 + bw
    by2 = by1 + bh
    overlap_w = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    overlap_h = max(0.0, min(ay2, by2) - max(ay1, by1))
    area = overlap_w * overlap_h
    return area / max(1.0, min(aw * ah, bw * bh))


def _rect_center(rect: dict[str, Any]) -> tuple[float, float]:
    return (
        float(rect.get("x") or 0) + _rect_width(rect) / 2,
        float(rect.get("y") or 0) + _rect_height(rect) / 2,
    )


def _first_named_child(node: dict[str, Any], tokens: tuple[str, ...]) -> dict[str, Any] | None:
    for child in node.get("children") or []:
        if _has_any(str(child.get("name") or "").lower(), tokens):
            return child
    return None


def _largest_child_with_children(children: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [child for child in children if child.get("children")]
    if not candidates:
        return None
    return max(candidates, key=lambda child: (child.get("global_rect") or {}).get("width", 0) * (child.get("global_rect") or {}).get("height", 0))


def _best_scrollbar_handle(scrollbar: dict[str, Any]) -> dict[str, Any] | None:
    children = scrollbar.get("children") or []
    if not children:
        return None
    named = _first_named_child(scrollbar, ("handle", "thumb", "knob", "bar", "滑块", "滑柄"))
    if named:
        return named
    return max(children, key=lambda child: _rect_width(child.get("global_rect") or {}) * _rect_height(child.get("global_rect") or {}))


def _scrollbar_size(scrollbar: dict[str, Any], handle: dict[str, Any] | None, direction: str) -> float:
    if not handle:
        return 0.2
    track_rect = scrollbar.get("global_rect") or {}
    handle_rect = handle.get("global_rect") or {}
    if direction == "horizontal":
        track = _rect_width(track_rect)
        value = _rect_width(handle_rect) / track if track else 0.2
    else:
        track = _rect_height(track_rect)
        value = _rect_height(handle_rect) / track if track else 0.2
    return round(max(0.05, min(1.0, value)), 4)


def _has_repeated_items(children: list[dict[str, Any]]) -> bool:
    if len(children) < 3:
        return False
    rects = [child.get("global_rect") or {} for child in children]
    widths = [float(rect.get("width") or 0) for rect in rects if rect.get("width")]
    heights = [float(rect.get("height") or 0) for rect in rects if rect.get("height")]
    if len(widths) < 3 or len(heights) < 3:
        return False
    width_close = max(widths) - min(widths) <= max(widths) * 0.25
    height_close = max(heights) - min(heights) <= max(heights) * 0.25
    return width_close or height_close


def _layout_item_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    semantic = node.get("semantic_type")
    name = str(node.get("name") or "").lower()
    eligible = semantic in {"scroll_content_candidate", "scroll_area_candidate"} or _has_any(
        name,
        ("content", "items", "list", "grid", "container", "列表", "内容"),
    )
    if not eligible:
        return []
    ignored = {
        "scrollbar_candidate",
        "scrollbar_handle_candidate",
        "scroll_viewport_candidate",
        "background_candidate",
        "dropdown_template_candidate",
    }
    result = []
    for child in node.get("children") or []:
        if child.get("semantic_type") in ignored:
            continue
        rect = child.get("global_rect") or {}
        if _rect_width(rect) <= 0 or _rect_height(rect) <= 0:
            continue
        result.append(child)
    return result


def _layout_hint_for_children(node: dict[str, Any], children: list[dict[str, Any]]) -> dict[str, Any] | None:
    rects = [child.get("global_rect") or {} for child in children]
    widths = [_rect_width(rect) for rect in rects]
    heights = [_rect_height(rect) for rect in rects]
    if not widths or not heights:
        return None
    avg_w = sum(widths) / len(widths)
    avg_h = sum(heights) / len(heights)
    if avg_w <= 0 or avg_h <= 0:
        return None
    width_close = max(widths) - min(widths) <= max(avg_w * 0.25, 2.0)
    height_close = max(heights) - min(heights) <= max(avg_h * 0.25, 2.0)
    if not (width_close or height_close):
        return None

    xs = [float(rect.get("x") or 0) for rect in rects]
    ys = [float(rect.get("y") or 0) for rect in rects]
    row_values = _cluster_positions(ys, max(4.0, avg_h * 0.45))
    col_values = _cluster_positions(xs, max(4.0, avg_w * 0.45))
    row_count = len(row_values)
    col_count = len(col_values)
    spacing_x = _spacing_from_positions(col_values, avg_w)
    spacing_y = _spacing_from_positions(row_values, avg_h)
    node_rect = node.get("global_rect") or {}
    padding = _layout_padding(node_rect, rects)

    if row_count >= 2 and col_count >= 2 and len(children) >= 4:
        component = "GridLayoutGroup"
        direction = "grid"
        constraint = "fixed_column_count"
        constraint_count = col_count
    elif row_count >= col_count:
        component = "VerticalLayoutGroup"
        direction = "vertical"
        constraint = None
        constraint_count = None
    else:
        component = "HorizontalLayoutGroup"
        direction = "horizontal"
        constraint = None
        constraint_count = None

    hint = {
        "can_add_layout_group": True,
        "default_add_layout_group": True,
        "component": component,
        "direction": direction,
        "item_node_ids": [child.get("id") for child in children if child.get("id")],
        "cell_size": {"width": round(avg_w, 3), "height": round(avg_h, 3)},
        "spacing": {"x": round(spacing_x, 3), "y": round(spacing_y, 3)},
        "padding": padding,
        "child_control_width": False,
        "child_control_height": False,
        "child_force_expand_width": False,
        "child_force_expand_height": False,
        "requires_review": False,
        "notes": [
            "LayoutGroup was inferred from repeated direct child geometry.",
            "Child sizes are preserved by default; the layout component mainly exposes arrangement semantics for Unity editing.",
        ],
    }
    if constraint:
        hint["constraint"] = constraint
        hint["constraint_count"] = constraint_count
    return hint


def _cluster_positions(values: list[float], tolerance: float) -> list[float]:
    if not values:
        return []
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or abs(value - (sum(clusters[-1]) / len(clusters[-1]))) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return [sum(cluster) / len(cluster) for cluster in clusters]


def _spacing_from_positions(positions: list[float], average_size: float) -> float:
    if len(positions) < 2:
        return 0.0
    gaps = [positions[index + 1] - positions[index] - average_size for index in range(len(positions) - 1)]
    return max(0.0, sum(gaps) / len(gaps))


def _layout_padding(node_rect: dict[str, Any], child_rects: list[dict[str, Any]]) -> dict[str, float]:
    node_x = float(node_rect.get("x") or 0)
    node_y = float(node_rect.get("y") or 0)
    node_w = float(node_rect.get("width") or 0)
    node_h = float(node_rect.get("height") or 0)
    min_x = min(float(rect.get("x") or 0) for rect in child_rects)
    min_y = min(float(rect.get("y") or 0) for rect in child_rects)
    max_x = max(float(rect.get("x") or 0) + _rect_width(rect) for rect in child_rects)
    max_y = max(float(rect.get("y") or 0) + _rect_height(rect) for rect in child_rects)
    return {
        "left": round(max(0.0, min_x - node_x), 3),
        "right": round(max(0.0, node_x + node_w - max_x), 3),
        "top": round(max(0.0, min_y - node_y), 3),
        "bottom": round(max(0.0, node_y + node_h - max_y), 3),
    }


def _is_scroll_child_semantic(node: dict[str, Any]) -> bool:
    return node.get("semantic_type") in {
        "scroll_content_candidate",
        "scroll_viewport_candidate",
        "scrollbar_candidate",
        "scrollbar_handle_candidate",
        "list_item_candidate",
    }


def _scroll_direction(viewport: dict[str, Any], content: dict[str, Any], children: list[dict[str, Any]]) -> str:
    viewport_w = float(viewport.get("width") or 0)
    viewport_h = float(viewport.get("height") or 0)
    content_w = float(content.get("width") or 0)
    content_h = float(content.get("height") or 0)
    if viewport_w and content_w > viewport_w * 1.05 and viewport_h and content_h > viewport_h * 1.05:
        return "grid"
    if viewport_w and content_w > viewport_w * 1.05:
        return "horizontal"
    if viewport_h and content_h > viewport_h * 1.05:
        return "vertical"
    ys = sorted(float((child.get("global_rect") or {}).get("y") or 0) for child in children)
    xs = sorted(float((child.get("global_rect") or {}).get("x") or 0) for child in children)
    if len(set(round(y, 1) for y in ys)) > len(set(round(x, 1) for x in xs)):
        return "vertical"
    if len(set(round(x, 1) for x in xs)) > 1:
        return "horizontal"
    return "vertical"


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _file_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _packet_id(path: Path, file_hash: str, rasterize_mode: str, target: str, scale: float) -> str:
    raw = f"psd:{path.name}:{file_hash}:{path.stat().st_mtime_ns}:{rasterize_mode}:{target}:{scale}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _asset_export_dir(
    path: Path,
    packet_id: str,
    asset_output_dir: str | Path | None,
    data_dir: str | Path | None,
) -> Path:
    if asset_output_dir:
        return Path(asset_output_dir).expanduser().resolve()
    root = Path(data_dir).expanduser() if data_dir else Path("data")
    return root / "assets" / "psd" / sanitize_filename(path.stem, "psd") / packet_id


def _detect_scale_from_name(name: str) -> float | None:
    match = re.search(r"@([1-9](?:\.\d+)?)x", name.lower())
    return float(match.group(1)) if match else None


def _unity_name(z_index: int, name: str) -> str:
    safe = re.sub(r"[^\w.-]+", "_", str(name).strip(), flags=re.UNICODE).strip("_")
    return f"node_{z_index:03d}_{safe or 'Layer'}"

from __future__ import annotations

import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from .asset_store import AssetStore
from .config import Settings
from .lanhu_client import LanhuClient
from .normalizer import make_packet
from .packet_store import PacketStore, collect_nodes, trim_node_tree
from .photoshop_export_adapter import make_photoshop_export_packet, photoshop_export_schema, validate_photoshop_export
from .psd_adapter import make_psd_packet
from .unity_editor_validator import install_unity_editor_validator
from .unity_prefab_verifier import verify_unity_prefab_yaml
from .unity_yaml_writer import write_unity_prefab_yaml
from .visual_diff import compare_packet_reference_to_screenshot


load_dotenv(override=False)

mcp = FastMCP("Design to Unity")


def _settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_dirs()
    return settings


def _find_nodes(packet: dict[str, Any], node_ids: list[str]) -> dict[str, Any]:
    all_nodes = []
    for root in packet.get("nodes") or []:
        all_nodes.extend(collect_nodes(root))
    lookup = {node.get("id"): node for node in all_nodes}
    found = [lookup[node_id] for node_id in node_ids if node_id in lookup]
    missing = [node_id for node_id in node_ids if node_id not in lookup]
    return {"found": found, "missing": missing}


def _asset_index(packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}


def _all_nodes(packet: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []

    def walk(node: dict[str, Any], parent_id: str | None) -> None:
        current = dict(node)
        current.setdefault("parent_id", parent_id)
        nodes.append(current)
        for child in node.get("children") or []:
            walk(child, current.get("id"))

    for root in packet.get("nodes") or []:
        walk(root, None)
    return nodes


def _unity_creation_order(packet: dict[str, Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    provider = ((packet.get("source") or {}).get("provider") or "lanhu").lower()
    reverse_siblings = provider != "psd"

    def walk_children(parent: dict[str, Any], parent_id: str | None) -> None:
        children = []
        for child in parent.get("children") or []:
            current = dict(child)
            current.setdefault("parent_id", parent_id)
            children.append(current)

        # Lanhu payloads observed so far are front-to-back, while psd-tools
        # traversal matched Photoshop composite when kept in ascending z order.
        children.sort(key=lambda item: item.get("z_index") or 0, reverse=reverse_siblings)
        for child in children:
            nodes.append(child)
            walk_children(child, child.get("id"))

    for root in packet.get("nodes") or []:
        walk_children(root, root.get("id"))
    return nodes


def _verify_prefab_result(prefab_result: dict[str, Any]) -> dict[str, Any]:
    return verify_unity_prefab_yaml(
        unity_project_path=str(prefab_result.get("unity_project_path") or ""),
        prefab_asset_path=str(prefab_result.get("prefab_asset_path") or ""),
        source_map_asset_path=str(prefab_result.get("source_map_asset_path") or ""),
    )


def _unity_component_for(node: dict[str, Any]) -> str:
    semantic_type = node.get("semantic_type")
    if semantic_type == "button_candidate":
        return "Image + Button"
    if semantic_type in {"progress_candidate", "slider_candidate"}:
        return "Slider"
    if semantic_type == "toggle_candidate":
        return "Toggle"
    if semantic_type == "tab_group_candidate":
        return "ToggleGroup"
    if semantic_type == "tab_candidate":
        return "Toggle + ToggleGroup"
    if semantic_type == "radio_group_candidate":
        return "ToggleGroup"
    if semantic_type == "radio_candidate":
        return "Toggle + ToggleGroup"
    if semantic_type == "input_candidate":
        return "TMP_InputField"
    if semantic_type == "dropdown_candidate":
        return "TMP_Dropdown"
    if semantic_type == "scroll_area_candidate":
        return "ScrollRect + RectMask2D"
    if semantic_type == "scrollbar_candidate":
        return "Scrollbar"
    if semantic_type == "scroll_viewport_candidate":
        return "RectMask2D candidate"
    if semantic_type == "mask_candidate":
        return "RectMask2D"
    if node.get("unity_layout_hint"):
        return str((node.get("unity_layout_hint") or {}).get("component") or "LayoutGroup")
    node_type = node.get("type")
    if node_type == "image":
        return "Image"
    if node_type == "text":
        return "TextMeshProUGUI"
    if node_type == "shape":
        return "Image"
    if node_type == "mask":
        return "RectMask2D candidate"
    return "RectTransform"


def _asset_flags(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "asset_role": asset.get("asset_role"),
        "is_large_background": asset.get("is_large_background"),
        "is_icon_like": asset.get("is_icon_like"),
        "is_button_like": asset.get("is_button_like"),
        "is_text_like": asset.get("is_text_like"),
        "is_panel_like": asset.get("is_panel_like"),
        "nine_slice_hint": asset.get("nine_slice_hint"),
    }


def _slice_entry(node: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "node_id": node.get("id"),
        "parent_id": node.get("parent_id"),
        "node_name": node.get("name"),
        "node_path": node.get("path"),
        "node_type": node.get("type"),
        "semantic_type": node.get("semantic_type"),
        "semantic_confidence": node.get("semantic_confidence"),
        "semantic_reasons": node.get("semantic_reasons") or [],
        "asset_ref": node.get("asset_ref"),
        "asset_name": asset.get("name"),
        "file_name": asset.get("file_name"),
        "local_path": asset.get("local_path"),
        "suggested_unity_path": asset.get("suggested_unity_path"),
        "remote_url": asset.get("remote_url"),
        "download_status": asset.get("download_status"),
        "format": asset.get("format"),
        "asset_role": asset.get("asset_role"),
        "asset_flags": _asset_flags(asset),
        "image_size": asset.get("size"),
        "logical_size": asset.get("logical_size"),
        "unity_import_hints": asset.get("unity_import_hints"),
        "global_rect": node.get("global_rect"),
        "local_rect": node.get("local_rect"),
        "unity_rect_hint": node.get("unity_rect_hint"),
        "style": node.get("style"),
        "text": node.get("text"),
    }


def _unity_create_step(node: dict[str, Any], asset: dict[str, Any] | None = None) -> dict[str, Any]:
    component = _unity_component_for(node)
    step = {
        "node_id": node.get("id"),
        "parent_id": node.get("parent_id"),
        "name": node.get("unity_name_hint") or node.get("name"),
        "source_name": node.get("name"),
        "source_path": node.get("path"),
        "type": node.get("type"),
        "component": component,
        "z_index": node.get("z_index"),
        "rect": node.get("local_rect"),
        "unity_rect_hint": node.get("unity_rect_hint"),
        "semantic_type": node.get("semantic_type"),
        "source_metadata": node.get("source_metadata"),
        "content_hash": node.get("content_hash"),
    }
    if asset:
        step["asset"] = {
            "asset_ref": asset.get("id"),
            "local_path": asset.get("local_path"),
            "suggested_unity_path": asset.get("suggested_unity_path"),
            "unity_import_hints": asset.get("unity_import_hints"),
            "asset_role": asset.get("asset_role"),
            "asset_flags": _asset_flags(asset),
        }
        step["image_settings"] = {
            "type": "Simple",
            "preserveAspect": False,
            "raycastTarget": bool(node.get("semantic_type") in {"button_candidate", "toggle_candidate", "tab_candidate", "radio_candidate", "input_candidate", "dropdown_candidate", "scrollbar_candidate"}),
        }
    if node.get("text"):
        step["text_settings"] = node.get("text")
    if node.get("style"):
        step["style"] = node.get("style")
    opacity = _opacity_of(node)
    if node.get("children") and 0 <= opacity < 0.999:
        step["canvas_group_settings"] = {
            "can_add_canvas_group": True,
            "default_add_canvas_group": True,
            "alpha": opacity,
            "interactable": True,
            "blocksRaycasts": True,
            "ignoreParentGroups": False,
        }
    if node.get("semantic_type") == "button_candidate":
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_button": True,
            "default_add_button": True,
            "raycast_target_if_interactive": True,
        }
    if node.get("semantic_type") == "toggle_candidate":
        toggle_hint = node.get("unity_toggle_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "raycast_target_if_interactive": True,
        }
        step["toggle_settings"] = {
            "isOn": toggle_hint.get("value", "infer from layer name or user data"),
            "targetGraphic": "self Image/Text unless overridden",
            "graphic": toggle_hint.get("graphic_node_id") or "targetGraphic",
            "requiresReview": toggle_hint.get("requires_review", False),
        }
    if node.get("semantic_type") == "tab_group_candidate":
        tab_group_hint = node.get("unity_tab_group_hint") or {}
        step["tab_group_settings"] = {
            "canAddToggleGroup": tab_group_hint.get("can_add_toggle_group", True),
            "allowSwitchOff": tab_group_hint.get("allow_switch_off", False),
            "tabNodeIds": tab_group_hint.get("tab_node_ids") or [],
            "selectedTabNodeId": tab_group_hint.get("selected_tab_node_id"),
            "requiresReview": tab_group_hint.get("requires_review", False),
        }
    if node.get("semantic_type") == "tab_candidate":
        tab_hint = node.get("unity_tab_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "raycast_target_if_interactive": True,
        }
        step["tab_settings"] = {
            "groupNodeId": tab_hint.get("group_node_id") or "requires tab_group_candidate",
            "labelNodeId": tab_hint.get("label_node_id") or None,
            "isOn": tab_hint.get("value", "infer from selected/current layer name"),
            "targetGraphic": "self Image/Text unless overridden",
            "toggleGroup": "parent tab_group_candidate ToggleGroup",
            "requiresReview": tab_hint.get("requires_review", False),
        }
    if node.get("semantic_type") == "radio_group_candidate":
        radio_group_hint = node.get("unity_radio_group_hint") or {}
        step["radio_group_settings"] = {
            "canAddToggleGroup": radio_group_hint.get("can_add_toggle_group", True),
            "allowSwitchOff": radio_group_hint.get("allow_switch_off", False),
            "radioNodeIds": radio_group_hint.get("radio_node_ids") or [],
            "selectedRadioNodeId": radio_group_hint.get("selected_radio_node_id"),
            "requiresReview": radio_group_hint.get("requires_review", False),
        }
    if node.get("semantic_type") == "radio_candidate":
        radio_hint = node.get("unity_radio_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_toggle": True,
            "default_add_toggle": True,
            "raycast_target_if_interactive": True,
        }
        step["radio_settings"] = {
            "groupNodeId": radio_hint.get("group_node_id") or "requires radio_group_candidate",
            "labelNodeId": radio_hint.get("label_node_id") or None,
            "isOn": radio_hint.get("value", "infer from selected/current layer name"),
            "targetGraphic": "self Image/Text unless overridden",
            "toggleGroup": "parent radio_group_candidate ToggleGroup",
            "requiresReview": radio_hint.get("requires_review", False),
        }
    if node.get("semantic_type") == "input_candidate":
        input_hint = node.get("unity_input_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_tmp_input_field": True,
            "default_add_tmp_input_field": True,
            "raycast_target_if_interactive": True,
        }
        step["input_field_settings"] = {
            "textComponent": input_hint.get("text_component_node_id") or "requires text child",
            "placeholder": input_hint.get("placeholder_node_id") or "none",
            "lineType": input_hint.get("line_type") or "single_line",
            "requiresReview": input_hint.get("requires_review", False),
        }
    if node.get("semantic_type") == "dropdown_candidate":
        dropdown_hint = node.get("unity_dropdown_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_tmp_dropdown": True,
            "default_add_tmp_dropdown": True,
            "raycast_target_if_interactive": True,
        }
        step["dropdown_settings"] = {
            "template": dropdown_hint.get("template_node_id") or "bind when an expanded menu/template child exists",
            "captionText": dropdown_hint.get("caption_text_node_id") or "bind caption text child",
            "itemText": dropdown_hint.get("item_text_node_id") or "bind option item text child",
            "options": dropdown_hint.get("options") or [],
            "value": dropdown_hint.get("value", 0),
            "requiresReview": dropdown_hint.get("requires_review", True),
        }
    if node.get("semantic_type") in {"progress_candidate", "slider_candidate"}:
        slider_hint = node.get("unity_slider_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_slider": True,
            "default_add_slider": True,
            "interactable": node.get("semantic_type") == "slider_candidate",
            "requires_fill_handle_review": True,
        }
        step["slider_settings"] = {
            "direction": "LeftToRight",
            "minValue": 0,
            "maxValue": 1,
            "value": slider_hint.get("value", "infer from design or user data"),
            "trackRect": slider_hint.get("track_node_id") or "bind when a track child can be identified",
            "fillRect": slider_hint.get("fill_node_id") or "bind when a fill child can be identified",
            "handleRect": slider_hint.get("handle_node_id") or "bind when a handle/thumb child can be identified",
            "requiresReview": slider_hint.get("requires_review", True),
        }
    if node.get("semantic_type") == "scroll_area_candidate":
        scroll_hint = node.get("unity_scroll_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_scroll_rect": True,
            "default_add_scroll_rect": True,
            "requires_content_viewport_review": True,
        }
        step["scroll_settings"] = {
            "direction": scroll_hint.get("direction") or "vertical",
            "viewportRect": scroll_hint.get("viewport_node_id") or "self",
            "contentRect": scroll_hint.get("content_node_id") or "bind manually",
            "horizontalScrollbar": scroll_hint.get("horizontal_scrollbar_node_id") or None,
            "verticalScrollbar": scroll_hint.get("vertical_scrollbar_node_id") or None,
            "itemNodeIds": scroll_hint.get("item_node_ids") or [],
            "requiresReview": scroll_hint.get("requires_review", True),
        }
    if node.get("semantic_type") == "scrollbar_candidate":
        scrollbar_hint = node.get("unity_scrollbar_hint") or {}
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_scrollbar": True,
            "default_add_scrollbar": True,
        }
        step["scrollbar_settings"] = {
            "direction": scrollbar_hint.get("direction") or "vertical",
            "scrollRect": scrollbar_hint.get("scroll_rect_node_id") or "bind manually",
            "handleRect": scrollbar_hint.get("handle_node_id") or "bind manually",
            "value": scrollbar_hint.get("value", 0),
            "size": scrollbar_hint.get("size", 0.2),
            "requiresReview": scrollbar_hint.get("requires_review", True),
        }
    if node.get("semantic_type") == "mask_candidate":
        mask_hint = node.get("unity_mask_hint") or {}
        step["mask_settings"] = {
            "canAddRectMask2D": mask_hint.get("can_add_rect_mask_2d", True),
            "recommendedUnityComponent": mask_hint.get("recommended_unity_component", "RectMask2D"),
            "requiresReview": mask_hint.get("requires_review", False),
        }
    if node.get("unity_layout_hint"):
        layout_hint = node.get("unity_layout_hint") or {}
        step["layout_group_settings"] = {
            "component": layout_hint.get("component"),
            "direction": layout_hint.get("direction"),
            "itemNodeIds": layout_hint.get("item_node_ids") or [],
            "cellSize": layout_hint.get("cell_size"),
            "spacing": layout_hint.get("spacing"),
            "padding": layout_hint.get("padding"),
            "requiresReview": layout_hint.get("requires_review", False),
        }
    return step


def _shorten(value: Any, limit: int = 80) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _opacity_of(node: dict[str, Any]) -> float:
    try:
        return round(float((node.get("style") or {}).get("opacity", 1)), 4)
    except (TypeError, ValueError):
        return 1.0


def _node_digest(node: dict[str, Any]) -> dict[str, Any]:
    text = node.get("text") or {}
    return {
        "node_id": node.get("id"),
        "parent_id": node.get("parent_id"),
        "name": node.get("name"),
        "path": node.get("path"),
        "type": node.get("type"),
        "semantic_type": node.get("semantic_type"),
        "semantic_confidence": node.get("semantic_confidence"),
        "requires_semantic_review": node.get("requires_semantic_review"),
        "rect": node.get("global_rect"),
        "z_index": node.get("z_index"),
        "asset_ref": node.get("asset_ref"),
        "text": _shorten(text.get("content"), 120) if text else None,
    }


def _tool_prefix(packet: dict[str, Any]) -> str:
    provider = ((packet.get("source") or {}).get("provider") or "lanhu").lower()
    return "psd_design" if provider == "psd" else "lanhu_design"


def _summary_for_packet(packet: dict[str, Any], max_items: int) -> dict[str, Any]:
    nodes = _all_nodes(packet)
    assets = packet.get("assets") or []
    max_items = max(3, min(int(max_items), 50))
    provider = ((packet.get("source") or {}).get("provider") or "lanhu").lower()
    sibling_order_rule = (
        "PSD siblings should be created by ascending z_index for Unity UGUI; later PSD traversal nodes render on top."
        if provider == "psd"
        else "Lanhu siblings should be created by descending z_index for Unity UGUI based on observed payloads."
    )

    type_counts = Counter(node.get("type") or "unknown" for node in nodes)
    semantic_counts = Counter(node.get("semantic_type") or "none" for node in nodes)
    asset_role_counts = Counter(asset.get("asset_role") or asset.get("usage") or "unknown" for asset in assets)
    download_counts = Counter(asset.get("download_status") or "unknown" for asset in assets)
    warning_counts = Counter(warning.get("code") or "unknown" for warning in packet.get("warnings") or [])

    semantic_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        semantic_type = node.get("semantic_type")
        if semantic_type and semantic_type != "screen_root":
            semantic_groups[semantic_type].append(_node_digest(node))

    text_nodes = [
        _node_digest(node)
        for node in nodes
        if (node.get("text") or {}).get("content")
    ]
    top_level_nodes = [
        _node_digest(node)
        for node in sorted(
            [node for node in nodes if node.get("parent_id") == "root"],
            key=lambda item: item.get("z_index") or 0,
            reverse=True,
        )
    ]

    return {
        "status": "success",
        "packet_id": packet.get("packet_id"),
        "source": packet.get("source"),
        "design": packet.get("design"),
        "counts": {
            "node_count": len(nodes),
            "asset_count": len(assets),
            "warning_count": len(packet.get("warnings") or []),
            "type_counts": dict(type_counts),
            "semantic_counts": dict(semantic_counts),
            "asset_role_counts": dict(asset_role_counts),
            "download_counts": dict(download_counts),
        },
        "top_level_nodes": top_level_nodes[:max_items],
        "semantic_candidates": {
            semantic_type: items[:max_items]
            for semantic_type, items in sorted(semantic_groups.items())
        },
        "text_preview": text_nodes[:max_items],
        "asset_insights": {
            "large_backgrounds": [
                asset for asset in assets if asset.get("is_large_background")
            ][:max_items],
            "button_sprites": [
                asset for asset in assets if asset.get("is_button_like")
            ][:max_items],
            "icons": [
                asset for asset in assets if asset.get("is_icon_like")
            ][:max_items],
            "nine_slice_candidates": [
                asset for asset in assets if (asset.get("nine_slice_hint") or {}).get("candidate")
            ][:max_items],
        },
        "warnings_by_code": dict(warning_counts),
        "warnings_preview": (packet.get("warnings") or [])[:max_items],
        "unity_readiness": {
            "has_unity_profile": bool((packet.get("handoff_profiles") or {}).get("unity")),
            "missing_asset_count": download_counts.get("failed", 0),
            "can_build_static_prefab": bool(assets) and download_counts.get("failed", 0) == 0,
            "sibling_order_rule": sibling_order_rule,
        },
        "recommended_next_tools": [
            f"{_tool_prefix(packet)}_get_slices",
            f"{_tool_prefix(packet)}_get_unity_plan",
            f"{_tool_prefix(packet)}_get_node_detail",
        ],
    }


def _unity_readiness_report(
    packet: dict[str, Any],
    prefab_result: dict[str, Any] | None = None,
    max_items: int = 20,
) -> dict[str, Any]:
    nodes = _all_nodes(packet)
    assets = packet.get("assets") or []
    asset_lookup = _asset_index(packet)
    warnings = packet.get("warnings") or []
    max_items = max(5, min(int(max_items), 100))

    missing_asset_nodes = []
    unresolved_asset_nodes = []
    for node in nodes:
        asset_ref = node.get("asset_ref")
        if not asset_ref:
            continue
        asset = asset_lookup.get(asset_ref)
        if not asset:
            missing_asset_nodes.append(_node_digest(node) | {"asset_ref": asset_ref})
            continue
        if asset.get("download_status") in {"failed", "missing"} or not asset.get("local_path"):
            unresolved_asset_nodes.append(
                _node_digest(node)
                | {
                    "asset_ref": asset_ref,
                    "download_status": asset.get("download_status"),
                    "local_path": asset.get("local_path"),
                }
            )

    semantic_counts = Counter(node.get("semantic_type") or "none" for node in nodes)
    type_counts = Counter(node.get("type") or "unknown" for node in nodes)
    warning_counts = Counter(warning.get("code") or "unknown" for warning in warnings)
    severity_counts = Counter(warning.get("severity") or "unknown" for warning in warnings)

    slider_review_nodes = [
        _node_digest(node) | {"unity_slider_hint": node.get("unity_slider_hint")}
        for node in nodes
        if node.get("semantic_type") in {"progress_candidate", "slider_candidate"}
        and (node.get("unity_slider_hint") or {}).get("requires_review")
    ]
    scroll_review_nodes = [
        _node_digest(node) | {"unity_scroll_hint": node.get("unity_scroll_hint")}
        for node in nodes
        if node.get("semantic_type") == "scroll_area_candidate"
        and (node.get("unity_scroll_hint") or {}).get("requires_review")
    ]
    semantic_review_nodes = [
        _node_digest(node)
        for node in nodes
        if node.get("requires_semantic_review")
    ]
    text_nodes = [
        _node_digest(node)
        for node in nodes
        if (node.get("text") or {}).get("content")
    ]
    effect_warning_nodes = [
        warning
        for warning in warnings
        if warning.get("code") == "psd_layer_effect_requires_review"
    ]
    complex_feature_warning_codes = {
        "psd_mask_requires_review",
        "psd_clipping_mask_requires_review",
        "psd_blend_mode_requires_review",
        "psd_smart_object_rasterized",
        "psd_adjustment_layer_requires_review",
    }
    complex_feature_warnings = [
        warning
        for warning in warnings
        if warning.get("code") in complex_feature_warning_codes
    ]

    renderable_node_count = sum(1 for node in nodes if node.get("asset_ref") or (node.get("text") or {}).get("content"))
    blockers = []
    review_items = []
    if not nodes or len(nodes) <= 1:
        blockers.append({"code": "no_design_nodes", "message": "No PSD layers were normalized into design nodes."})
    if renderable_node_count == 0:
        blockers.append({"code": "no_renderable_nodes", "message": "No image or text nodes are available for Unity output."})
    if missing_asset_nodes:
        blockers.append({"code": "missing_asset_refs", "count": len(missing_asset_nodes), "message": "Some nodes reference assets missing from the packet."})
    if unresolved_asset_nodes:
        blockers.append({"code": "unresolved_assets", "count": len(unresolved_asset_nodes), "message": "Some assets are not exported or do not have local paths."})

    if effect_warning_nodes:
        review_items.append(
            {
                "code": "psd_layer_effect_requires_review",
                "count": len(effect_warning_nodes),
                "message": "Layer effects were detected; compare generated prefab against the flattened PSD reference.",
            }
        )
    complex_feature_messages = {
        "psd_mask_requires_review": "Photoshop layer/vector masks were detected; verify clipping visually or rasterize affected groups.",
        "psd_clipping_mask_requires_review": "Photoshop clipping relationships were detected; verify Unity output or rasterize clipped groups.",
        "psd_blend_mode_requires_review": "Non-normal Photoshop blend modes were detected; Unity Image blending may not match exactly.",
        "psd_smart_object_rasterized": "Smart objects were detected and are treated as rasterized images by the first-stage adapter.",
        "psd_adjustment_layer_requires_review": "Adjustment layers were detected; prefer flattened/group rasterized output for exact color.",
    }
    for code, count in sorted(Counter(warning.get("code") for warning in complex_feature_warnings).items()):
        review_items.append(
            {
                "code": code,
                "count": count,
                "message": complex_feature_messages.get(code, "Complex PSD feature detected; verify visual fidelity."),
            }
        )
    if warning_counts.get("psd_text_style_best_effort"):
        review_items.append(
            {
                "code": "psd_text_style_best_effort",
                "count": warning_counts["psd_text_style_best_effort"],
                "message": "Editable TMP text was inferred best-effort; verify font asset, alignment, and line spacing.",
            }
        )
    if slider_review_nodes:
        review_items.append(
            {
                "code": "slider_binding_requires_review",
                "count": len(slider_review_nodes),
                "message": "Some Slider/ProgressBar candidates need fill or handle binding review.",
            }
        )
    if scroll_review_nodes:
        review_items.append(
            {
                "code": "scroll_area_requires_review",
                "count": len(scroll_review_nodes),
                "message": "Some ScrollRect candidates need viewport/content binding review.",
            }
        )
    if semantic_review_nodes:
        review_items.append(
            {
                "code": "low_confidence_semantics",
                "count": len(semantic_review_nodes),
                "message": "Some semantic guesses are below the confidence threshold.",
            }
        )

    component_candidates = {
        "image": sum(1 for node in nodes if node.get("asset_ref")),
        "textmeshpro": len(text_nodes),
        "button": semantic_counts.get("button_candidate", 0),
        "slider": semantic_counts.get("slider_candidate", 0) + semantic_counts.get("progress_candidate", 0),
        "toggle": semantic_counts.get("toggle_candidate", 0),
        "tab_group": semantic_counts.get("tab_group_candidate", 0),
        "tab": semantic_counts.get("tab_candidate", 0),
        "radio_group": semantic_counts.get("radio_group_candidate", 0),
        "radio": semantic_counts.get("radio_candidate", 0),
        "input_field": semantic_counts.get("input_candidate", 0),
        "dropdown": semantic_counts.get("dropdown_candidate", 0),
        "scroll_rect": semantic_counts.get("scroll_area_candidate", 0),
        "scrollbar": semantic_counts.get("scrollbar_candidate", 0),
        "mask": semantic_counts.get("mask_candidate", 0),
        "layout_group": sum(1 for node in nodes if (node.get("unity_layout_hint") or {}).get("can_add_layout_group")),
        "canvas_group": sum(1 for node in nodes if node.get("children") and 0 <= _opacity_of(node) < 0.999),
    }
    prefab_stats = {
        key: prefab_result.get(key)
        for key in (
            "node_count",
            "image_node_count",
            "tmp_text_node_count",
            "button_node_count",
            "slider_node_count",
            "toggle_node_count",
            "toggle_group_node_count",
            "tab_node_count",
            "radio_node_count",
            "input_field_node_count",
            "dropdown_node_count",
            "dropdown_template_bound_count",
            "dropdown_caption_bound_count",
            "dropdown_item_bound_count",
            "slider_fill_bound_count",
            "slider_handle_bound_count",
            "scroll_rect_node_count",
            "scrollbar_node_count",
            "scrollbar_handle_bound_count",
            "rect_mask_2d_node_count",
            "vertical_layout_group_node_count",
            "horizontal_layout_group_node_count",
            "grid_layout_group_node_count",
            "canvas_group_node_count",
            "copied_asset_count",
            "missing_asset_count",
            "source_map_node_count",
        )
        if prefab_result and key in prefab_result
    }

    score = 100
    score -= min(50, len(blockers) * 25)
    score -= min(25, len(review_items) * 5)
    score -= min(15, warning_counts.get("psd_layer_effect_requires_review", 0))
    score -= min(15, len(complex_feature_warnings) * 2)
    score -= min(10, warning_counts.get("psd_layer_rasterize_failed", 0) * 2)
    score = max(0, score)
    status = "blocked" if blockers else "ready_with_review" if review_items else "ready"

    next_actions = []
    if blockers:
        next_actions.append("Fix missing/unresolved PSD layer assets, then prepare the packet again.")
    if effect_warning_nodes:
        next_actions.append("Use the flattened reference image to compare Photoshop effects against the Unity prefab.")
    if complex_feature_warnings:
        next_actions.append("For masked, clipped, blended, smart-object, or adjustment-heavy PSD areas, prefer group rasterization or Photoshop UXP export before final visual QA.")
    if text_nodes:
        next_actions.append("Import or assign the project TMP Font Asset before final visual QA.")
    if component_candidates["slider"] or component_candidates["scroll_rect"] or component_candidates["scrollbar"] or component_candidates["mask"] or component_candidates["layout_group"] or component_candidates["toggle"] or component_candidates["tab"] or component_candidates["radio"] or component_candidates["input_field"] or component_candidates["dropdown"]:
        next_actions.append("Inspect Slider, Toggle/ToggleGroup, TMP_InputField, TMP_Dropdown, ScrollRect, Scrollbar, RectMask2D, and LayoutGroup bindings from the source map after Unity imports the prefab.")
    if prefab_result:
        next_actions.append("Open the generated prefab in Unity and capture a screenshot for visual diff.")
    else:
        next_actions.append("Call psd_design_write_unity_prefab_yaml or psd_design_convert_to_unity_prefab to generate the prefab.")

    return {
        "status": status,
        "readiness_score": score,
        "packet_id": packet.get("packet_id"),
        "source": packet.get("source"),
        "design": packet.get("design"),
        "counts": {
            "node_count": len(nodes),
            "asset_count": len(assets),
            "renderable_node_count": renderable_node_count,
            "type_counts": dict(type_counts),
            "semantic_counts": dict(semantic_counts),
            "warning_counts": dict(warning_counts),
            "severity_counts": dict(severity_counts),
            "component_candidates": component_candidates,
            "prefab_stats": prefab_stats,
        },
        "blockers": blockers,
        "review_items": review_items,
        "samples": {
            "missing_asset_nodes": missing_asset_nodes[:max_items],
            "unresolved_asset_nodes": unresolved_asset_nodes[:max_items],
            "text_nodes": text_nodes[:max_items],
            "slider_review_nodes": slider_review_nodes[:max_items],
            "scroll_review_nodes": scroll_review_nodes[:max_items],
            "semantic_review_nodes": semantic_review_nodes[:max_items],
            "complex_feature_warnings": complex_feature_warnings[:max_items],
            "warnings": warnings[:max_items],
        },
        "unity_yaml_capabilities": [
            "GameObject",
            "RectTransform",
            "CanvasRenderer",
            "Image",
            "TextMeshProUGUI",
            "Button",
            "Slider",
            "Toggle",
            "ToggleGroup",
            "Radio groups through ToggleGroup",
            "TMP_InputField",
            "TMP_Dropdown",
            "ScrollRect",
            "Scrollbar",
            "RectMask2D",
            "VerticalLayoutGroup",
            "HorizontalLayoutGroup",
            "GridLayoutGroup",
            "CanvasGroup",
            "deterministic sprite .meta",
            "prefab source map",
        ],
        "next_actions": next_actions,
    }


def _packet_response(packet: dict[str, Any], packet_id: str, tool_prefix: str) -> dict[str, Any]:
    root = packet["nodes"][0]
    node_count = len(collect_nodes(root))
    settings = _settings()
    if node_count > settings.max_nodes_per_response:
        return {
            "status": "too_large",
            "packet_id": packet_id,
            "node_count": node_count,
            "message": f"Packet is large. Use {tool_prefix}_get_node_tree and {tool_prefix}_get_node_detail instead.",
            "summary": {
                "source": packet.get("source"),
                "design": packet.get("design"),
                "asset_count": len(packet.get("assets") or []),
                "warning_count": len(packet.get("warnings") or []),
            },
        }
    return packet


def _asset_manifest_response(packet: dict[str, Any], packet_id: str) -> dict[str, Any]:
    return {
        "packet_id": packet_id,
        "design": packet.get("design"),
        "asset_download": packet.get("asset_download"),
        "asset_export": packet.get("asset_export"),
        "assets": packet.get("assets") or [],
        "warnings": [w for w in packet.get("warnings") or [] if w.get("code") in {"missing_asset", "psd_layer_rasterize_failed"}],
    }


def _slices_response(packet: dict[str, Any], packet_id: str, include_reference: bool) -> dict[str, Any]:
    assets = _asset_index(packet)
    slices = []
    missing_assets = []

    for node in _all_nodes(packet):
        asset_ref = node.get("asset_ref")
        if not asset_ref:
            continue
        asset = assets.get(asset_ref)
        if not asset:
            missing_assets.append({"node_id": node.get("id"), "asset_ref": asset_ref})
            continue
        if asset.get("usage") == "design_reference" and not include_reference:
            continue
        slices.append(_slice_entry(node, asset))

    slices.sort(
        key=lambda item: (
            (item.get("global_rect") or {}).get("y", 0),
            (item.get("global_rect") or {}).get("x", 0),
            item.get("node_id") or "",
        )
    )
    return {
        "status": "success",
        "packet_id": packet_id,
        "design": packet.get("design"),
        "total": len(slices),
        "slice_count": len(slices),
        "missing_assets": missing_assets,
        "slices": slices,
        "usage_note": "Use local_rect/unity_rect_hint when creating child nodes in Unity. Use global_rect for visual comparison and debugging.",
    }


def _unity_plan_response(packet: dict[str, Any], packet_id: str, include_reference: bool) -> dict[str, Any]:
    assets = _asset_index(packet)
    profile = (packet.get("handoff_profiles") or {}).get("unity", {})
    all_nodes = _all_nodes(packet)
    root = (packet.get("nodes") or [{}])[0]
    provider = ((packet.get("source") or {}).get("provider") or "lanhu").lower()

    asset_imports = []
    for asset in packet.get("assets") or []:
        if asset.get("usage") == "design_reference" and not include_reference:
            continue
        asset_imports.append(
            {
                "asset_ref": asset.get("id"),
                "name": asset.get("name"),
                "file_name": asset.get("file_name"),
                "local_path": asset.get("local_path"),
                "suggested_unity_path": asset.get("suggested_unity_path"),
                "download_status": asset.get("download_status"),
                "image_size": asset.get("size"),
                "logical_size": asset.get("logical_size"),
                "unity_import_hints": asset.get("unity_import_hints") or profile.get("asset_import_defaults"),
                "usage": asset.get("usage"),
            }
        )

    create_nodes = []
    for node in _unity_creation_order(packet):
        if node.get("id") == "root":
            continue
        asset = assets.get(node.get("asset_ref")) if node.get("asset_ref") else None
        if asset and asset.get("usage") == "design_reference":
            continue
        create_nodes.append(_unity_create_step(node, asset))

    semantic_candidates: dict[str, list[dict[str, Any]]] = {}
    for node in all_nodes:
        semantic_type = node.get("semantic_type")
        if not semantic_type or semantic_type == "screen_root":
            continue
        semantic_candidates.setdefault(semantic_type, []).append(
            {
                "node_id": node.get("id"),
                "name": node.get("name"),
                "path": node.get("path"),
                "confidence": node.get("semantic_confidence"),
                "reasons": node.get("semantic_reasons") or [],
                "rect": node.get("global_rect"),
                "unity_slider_hint": node.get("unity_slider_hint"),
                "unity_scroll_hint": node.get("unity_scroll_hint"),
            }
        )

    if provider == "psd":
        order_rule = "Create same-parent PSD siblings in ascending z_index order. Unity renders later siblings on top, matching observed psd-tools traversal and Photoshop composite output."
        verified_with = "psd-tools layer traversal and real PSD visual diff"
    else:
        order_rule = "Create siblings in descending z_index order. In observed Lanhu payloads, larger z_index nodes are behind smaller z_index nodes."
        verified_with = "-h-海报分享"

    return {
        "status": "success",
        "packet_id": packet_id,
        "target": "unity",
        "design": packet.get("design"),
        "asset_imports": asset_imports,
        "root": {
            "name": root.get("unity_name_hint") or "ViewRoot",
            "source_name": root.get("name"),
            "rect": root.get("local_rect"),
            "unity_rect_hint": root.get("unity_rect_hint"),
            "recommended_components": ["GameObject", "RectTransform"],
        },
        "create_nodes": create_nodes,
        "unity_sibling_order": {
            "rule": order_rule,
            "unity_reason": "Unity UGUI renders later siblings on top; create_nodes already applies the source-provider-specific sibling order.",
            "verified_with": verified_with,
        },
        "semantic_candidates": semantic_candidates,
        "warnings": packet.get("warnings") or [],
        "rules": profile.get("rules") or [],
        "coordinate_mapping": profile.get("coordinate_mapping"),
        "component_mapping": profile.get("component_mapping"),
        "recommended_sequence": [
            "Import all assets from asset_imports.",
            "Create ViewRoot using root.unity_rect_hint.",
            "Create nodes in create_nodes order. It is parent-before-child and uses the provider-specific sibling order described above.",
            "Assign Image sprites from asset.local_path or suggested_unity_path.",
            "Assign TMP text fields from text_settings.",
            "Add Button/Slider/TMP_Dropdown/ScrollRect/Scrollbar components when interaction_hint says default_add_* is true.",
            "For ScrollRect, bind viewportRect/contentRect/scrollbar references from scroll_settings and confirm repeated item structure.",
            "Treat semantic_candidates as hints only; do not bind business scripts without user intent.",
            "Write source_metadata/content_hash if Unity MCP supports custom metadata.",
            "Save prefab or scene, then capture a screenshot for visual comparison.",
        ],
    }


@mcp.tool()
async def lanhu_design_list(
    url: Annotated[str, "Lanhu design project URL. It should contain pid and optionally tid/image_id."],
) -> dict[str, Any]:
    """
    List design pages in a Lanhu project.

    Use this before preparing a Design Implementation Packet.
    """
    settings = _settings()
    client = LanhuClient(settings)
    try:
        result = await client.list_designs(url)
        result["next_step"] = "Call lanhu_design_prepare_packet with a design name or index."
        return result
    finally:
        await client.close()


@mcp.tool()
async def lanhu_design_prepare_packet(
    url: Annotated[str, "Lanhu design project URL. It should contain pid and optionally tid/image_id."],
    design_name_or_index: Annotated[
        str | int | None,
        "Design name, partial unique name, list index, or null to use image_id from URL.",
    ] = None,
    target: Annotated[str, "Target profile name: unity, web, or generic."] = "unity",
    asset_output_dir: Annotated[
        str | None,
        "Optional local directory where image assets should be downloaded. If omitted, DATA_DIR/assets is used.",
    ] = None,
    force_refresh: Annotated[bool, "Reserved for future cache invalidation. Current version always refreshes sources."] = False,
) -> dict[str, Any]:
    """
    Fetch one Lanhu design page, normalize it into a Design Implementation Packet,
    download referenced assets, and save the packet for later MCP queries.
    """
    settings = _settings()
    client = LanhuClient(settings)
    store = PacketStore(settings)
    assets = AssetStore(settings)

    try:
        parsed, design = await client.choose_design(url, design_name_or_index)
        sources = await client.fetch_design_sources(parsed, design)
        packet = make_packet(
            parsed_url=parsed,
            design=design,
            version_id=sources["version_id"],
            dds_schema=sources.get("dds_schema"),
            sketch_json=sources.get("sketch_json"),
            target=target,
        )
        download_result = await assets.download_packet_assets(packet, client, asset_output_dir)
        packet["asset_download"] = download_result
        packet_path = store.save(packet)

        root = packet["nodes"][0]
        node_count = len(collect_nodes(root))
        return {
            "status": "success",
            "packet_id": packet["packet_id"],
            "packet_path": str(packet_path),
            "source": packet["source"],
            "design": packet["design"],
            "node_count": node_count,
            "asset_count": len(packet.get("assets") or []),
            "asset_dir": download_result.get("asset_dir"),
            "warning_count": len(packet.get("warnings") or []),
            "warnings_preview": (packet.get("warnings") or [])[:10],
            "available_profiles": sorted((packet.get("handoff_profiles") or {}).keys()),
            "next_steps": [
                "Call lanhu_design_get_summary(packet_id) for a compact implementation overview.",
                "Call lanhu_design_get_handoff_profile(packet_id, target='unity') for Unity execution rules.",
                "Call lanhu_design_get_node_tree(packet_id) to inspect the hierarchy.",
                "Call lanhu_design_get_asset_manifest(packet_id) before asking Unity MCP to create UI nodes.",
            ],
        }
    finally:
        await client.close()


@mcp.tool()
async def lanhu_design_get_packet(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
) -> dict[str, Any]:
    """
    Return the full Design Implementation Packet.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _packet_response(packet, packet_id, "lanhu_design")


@mcp.tool()
async def lanhu_design_get_summary(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    max_items: Annotated[int, "Maximum items per summary section."] = 12,
) -> dict[str, Any]:
    """
    Return a compact implementation summary for AI planning.

    Use this before reading large node trees. It highlights structure, semantics,
    assets, warnings, and Unity readiness without returning every node.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _summary_for_packet(packet, max_items=max_items)


@mcp.tool()
async def lanhu_design_get_node_tree(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    max_depth: Annotated[int, "Maximum depth to return."] = 3,
    include_style: Annotated[bool, "Include style/text fields in tree response."] = True,
) -> dict[str, Any]:
    """
    Return a trimmed node hierarchy for staged AI reading.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    root = packet["nodes"][0]
    max_depth = max(0, min(int(max_depth), 20))
    return {
        "packet_id": packet_id,
        "design": packet.get("design"),
        "node_count": len(collect_nodes(root)),
        "tree": trim_node_tree(root, max_depth=max_depth, include_style=include_style),
    }


@mcp.tool()
async def lanhu_design_get_node_detail(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    node_ids: Annotated[list[str] | str, "One node id or a list of node ids."],
) -> dict[str, Any]:
    """
    Return full details for selected nodes.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    if isinstance(node_ids, str):
        node_ids = [node_ids]
    return {
        "packet_id": packet_id,
        **_find_nodes(packet, [str(node_id) for node_id in node_ids]),
    }


@mcp.tool()
async def lanhu_design_get_asset_manifest(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
) -> dict[str, Any]:
    """
    Return all image assets, local paths, suggested Unity paths, and import hints.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _asset_manifest_response(packet, packet_id)


@mcp.tool()
async def lanhu_design_get_slices(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    include_reference: Annotated[bool, "Include the full design reference image in the result."] = False,
) -> dict[str, Any]:
    """
    Return all image-backed design nodes with their asset paths and Unity rect hints.

    This is the preferred tool when another MCP only needs slice images and positions.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _slices_response(packet, packet_id, include_reference)


@mcp.tool()
async def lanhu_design_get_unity_plan(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    include_reference: Annotated[bool, "Include the design reference image as an import step."] = True,
) -> dict[str, Any]:
    """
    Build an ordered Unity execution plan from a prepared packet.

    The plan does not edit Unity directly. It tells the AI/Unity MCP what to import,
    which nodes to create, which components to use, and which warnings need review.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _unity_plan_response(packet, packet_id, include_reference)


@mcp.tool()
async def lanhu_design_write_unity_prefab_yaml(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    asset_root: Annotated[
        str,
        "Unity asset folder where generated sprites and prefab should be written. Must start with Assets/.",
    ] = "Assets/DesignToUnity",
    prefab_name: Annotated[
        str | None,
        "Optional prefab file name. The .prefab suffix is optional.",
    ] = None,
    overwrite: Annotated[bool, "Overwrite existing generated prefab and copied sprite files."] = True,
    include_reference: Annotated[bool, "Include the full design reference image as a sprite asset if it is used by a node."] = False,
    button_raycast: Annotated[bool, "Enable Image raycastTarget for button candidate nodes."] = False,
    use_text_components: Annotated[bool, "Create TextMeshProUGUI components for text nodes instead of using text slices as images."] = True,
    add_button_components: Annotated[bool, "Add UnityEngine.UI.Button components to button_candidate nodes."] = True,
    add_slider_components: Annotated[bool, "Add UnityEngine.UI.Slider components to progress_candidate and slider_candidate nodes."] = True,
    add_toggle_components: Annotated[bool, "Add UnityEngine.UI.Toggle components to toggle_candidate nodes."] = True,
    add_tab_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to tab_group_candidate/tab_candidate nodes."] = True,
    add_radio_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to radio_group_candidate/radio_candidate nodes."] = True,
    add_input_field_components: Annotated[bool, "Add TMPro.TMP_InputField components to input_candidate nodes."] = True,
    add_dropdown_components: Annotated[bool, "Add TMPro.TMP_Dropdown components to dropdown_candidate nodes."] = True,
    add_scroll_components: Annotated[bool, "Add UnityEngine.UI.ScrollRect, Scrollbar, and RectMask2D components to scroll_area_candidate nodes."] = True,
    add_mask_components: Annotated[bool, "Add UnityEngine.UI.RectMask2D components to mask_candidate nodes."] = True,
    add_layout_components: Annotated[bool, "Add UnityEngine.UI layout group components when repeated child geometry can be inferred."] = True,
    add_canvas_group_components: Annotated[bool, "Add UnityEngine.CanvasGroup components to semi-transparent group nodes."] = True,
    tmp_font_asset_guid: Annotated[
        str | None,
        "Optional TMP Font Asset guid. If omitted, the writer tries project Assets first, then uses a package fallback guid.",
    ] = None,
    tmp_font_asset_map_json: Annotated[
        str | None,
        "Optional JSON object mapping Photoshop font names/styles to TMP Font Asset guids.",
    ] = None,
) -> dict[str, Any]:
    """
    Experimentally write a Unity UGUI prefab by generating Unity YAML directly.

    This bypasses Unity MCP and Unity Editor APIs. It is useful for fast static UI
    snapshots and prefab diffs, while production pipelines should still prefer a
    Unity-side importer when component/script fidelity matters.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    prefab_result = write_unity_prefab_yaml(
        packet=packet,
        unity_project_path=unity_project_path,
        asset_root=asset_root,
        prefab_name=prefab_name,
        overwrite=overwrite,
        include_reference=include_reference,
        button_raycast=button_raycast,
        use_text_components=use_text_components,
        add_button_components=add_button_components,
        add_slider_components=add_slider_components,
        add_toggle_components=add_toggle_components,
        add_tab_components=add_tab_components,
        add_radio_components=add_radio_components,
        add_input_field_components=add_input_field_components,
        add_dropdown_components=add_dropdown_components,
        add_scroll_components=add_scroll_components,
        add_mask_components=add_mask_components,
        add_layout_components=add_layout_components,
        add_canvas_group_components=add_canvas_group_components,
        tmp_font_asset_guid=tmp_font_asset_guid,
        tmp_font_asset_map=tmp_font_asset_map_json,
    )
    prefab_result["verification"] = _verify_prefab_result(prefab_result)
    return prefab_result


@mcp.tool()
async def lanhu_design_verify_unity_prefab_yaml(
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    prefab_asset_path: Annotated[str, "Generated prefab Unity asset path, for example Assets/DesignToUnity/<packet>/Prefabs/View.prefab."],
    source_map_asset_path: Annotated[
        str | None,
        "Optional source map Unity asset path. If omitted, <prefab>.design-to-unity.json next to the prefab is used.",
    ] = None,
) -> dict[str, Any]:
    """
    Statically verify a generated Design to Unity prefab YAML and source map.

    This does not replace Unity import/compile validation, but it catches missing
    sprite files, meta guid mismatches, broken local fileID references, and source
    map count mismatches before asking Unity MCP to open the prefab.
    """
    return verify_unity_prefab_yaml(
        unity_project_path=unity_project_path,
        prefab_asset_path=prefab_asset_path,
        source_map_asset_path=source_map_asset_path,
    )


@mcp.tool()
async def psd_design_prepare_packet(
    file_path: Annotated[str, "Absolute or relative path to a local .psd or .psb file."],
    target: Annotated[str, "Target profile name: unity, web, or generic."] = "unity",
    asset_output_dir: Annotated[
        str | None,
        "Optional local directory where PSD layer PNG assets should be exported. If omitted, DATA_DIR/assets/psd is used.",
    ] = None,
    rasterize_mode: Annotated[
        str,
        "PSD rasterize mode: layer, visible, all, or none. 'layer' exports renderable layers; 'visible/all' may export groups too.",
    ] = "layer",
    scale: Annotated[
        float | None,
        "Optional PSD scale factor. If omitted, @2x/@3x in the file name is detected; otherwise 1x is used.",
    ] = None,
    include_hidden: Annotated[bool, "Include hidden PSD layers in the packet."] = False,
    export_text_layers: Annotated[
        bool,
        "Export PSD text layers as PNG slices. False keeps them editable as TextMeshProUGUI.",
    ] = False,
    export_group_layers: Annotated[bool, "Export group layers as composed PNG slices where possible."] = False,
    include_reference: Annotated[bool, "Export a flattened PSD reference image for visual comparison."] = True,
    reference_image_path: Annotated[
        str | None,
        "Optional Photoshop-rendered preview PNG/JPG to use as the packet reference instead of psd-tools compositing.",
    ] = None,
    force_refresh: Annotated[bool, "Reserved for future cache invalidation. Current version always refreshes sources."] = False,
) -> dict[str, Any]:
    """
    Parse a local PSD / PSB file into a Design Implementation Packet, export layer
    PNG assets, and save the packet for later MCP queries or direct Unity prefab
    YAML generation.
    """
    settings = _settings()
    store = PacketStore(settings)
    output_dir = Path(asset_output_dir).expanduser() if asset_output_dir else None
    packet = make_psd_packet(
        file_path=file_path,
        target=target,
        asset_output_dir=output_dir,
        rasterize_mode=rasterize_mode,
        scale=scale,
        include_hidden=include_hidden,
        export_text_layers=export_text_layers,
        export_group_layers=export_group_layers,
        include_reference=include_reference,
        reference_image_path=reference_image_path,
        data_dir=settings.data_dir,
    )
    packet_path = store.save(packet)
    root = packet["nodes"][0]
    node_count = len(collect_nodes(root))
    return {
        "status": "success",
        "packet_id": packet["packet_id"],
        "packet_path": str(packet_path),
        "source": packet["source"],
        "design": packet["design"],
        "node_count": node_count,
        "asset_count": len(packet.get("assets") or []),
        "asset_dir": (packet.get("asset_export") or {}).get("asset_dir"),
        "warning_count": len(packet.get("warnings") or []),
        "warnings_preview": (packet.get("warnings") or [])[:10],
        "available_profiles": sorted((packet.get("handoff_profiles") or {}).keys()),
        "next_steps": [
            "Call psd_design_get_summary(packet_id) for a compact implementation overview.",
            "Call psd_design_get_unity_readiness_report(packet_id) before writing Unity prefab assets.",
            "Call psd_design_get_unity_plan(packet_id) to inspect components and ScrollRect/Button/Slider candidates.",
            "Call psd_design_get_asset_manifest(packet_id) before asking Unity MCP to create UI nodes.",
            "Call psd_design_write_unity_prefab_yaml(packet_id, unity_project_path) to write a static prefab snapshot directly.",
            "Or call psd_design_convert_to_unity_prefab(file_path, unity_project_path) for the one-step flow.",
            "After Unity MCP captures a screenshot, call psd_design_compare_unity_screenshot(packet_id, screenshot_path).",
        ],
    }


@mcp.tool()
async def psd_design_get_export_schema() -> dict[str, Any]:
    """
    Return the supported Photoshop/UXP export manifest schema.

    Use this when writing a Photoshop UXP script or another exporter that should
    produce design.json, preview.png, and assets/*.png for Design to Unity.
    """
    return {
        "status": "success",
        "schema": photoshop_export_schema(),
        "recommended_tools": [
            "psd_design_validate_export",
            "psd_design_prepare_export_packet",
            "psd_design_convert_export_to_unity_prefab",
        ],
    }


@mcp.tool()
async def psd_design_validate_export(
    export_path: Annotated[
        str,
        "Path to a Photoshop/UXP export directory or manifest JSON. Expected files include design.json, preview.png, and assets/*.png.",
    ],
) -> dict[str, Any]:
    """
    Validate a Photoshop/UXP export directory before packet preparation.

    This catches missing manifest fields, duplicate layer ids, missing assets,
    missing preview images, invalid bounds, and complex PSD feature warnings.
    """
    return validate_photoshop_export(export_path)


@mcp.tool()
async def psd_design_prepare_export_packet(
    export_path: Annotated[
        str,
        "Path to a Photoshop/UXP export directory or manifest JSON. Expected files include design.json, preview.png, and assets/*.png.",
    ],
    target: Annotated[str, "Target profile name: unity, web, or generic."] = "unity",
    scale: Annotated[
        float | None,
        "Optional export scale factor. If omitted, the manifest scale is used; otherwise 1x is used.",
    ] = None,
    force_refresh: Annotated[bool, "Reserved for future cache invalidation. Current version always refreshes sources."] = False,
) -> dict[str, Any]:
    """
    Parse a Photoshop/UXP export directory into a Design Implementation Packet.

    This is the high-fidelity PSD path: Photoshop renders preview/layer/group PNGs,
    while this MCP normalizes the exported manifest into the same packet shape used
    by Lanhu and psd-tools sources.
    """
    settings = _settings()
    store = PacketStore(settings)
    packet = make_photoshop_export_packet(export_path=export_path, target=target, scale=scale)
    packet_path = store.save(packet)
    root = packet["nodes"][0]
    node_count = len(collect_nodes(root))
    return {
        "status": "success",
        "packet_id": packet["packet_id"],
        "packet_path": str(packet_path),
        "source": packet["source"],
        "design": packet["design"],
        "node_count": node_count,
        "asset_count": len(packet.get("assets") or []),
        "asset_dir": (packet.get("asset_export") or {}).get("asset_dir"),
        "warning_count": len(packet.get("warnings") or []),
        "warnings_preview": (packet.get("warnings") or [])[:10],
        "available_profiles": sorted((packet.get("handoff_profiles") or {}).keys()),
        "next_steps": [
            "Call psd_design_get_summary(packet_id) for a compact implementation overview.",
            "Call psd_design_get_unity_readiness_report(packet_id) before writing Unity prefab assets.",
            "Call psd_design_get_unity_plan(packet_id) to inspect component candidates.",
            "Call psd_design_write_unity_prefab_yaml(packet_id, unity_project_path) to write the prefab.",
            "Or call psd_design_convert_export_to_unity_prefab(export_path, unity_project_path) for the one-step flow.",
            "After Unity MCP captures a screenshot, call psd_design_compare_unity_screenshot(packet_id, screenshot_path).",
        ],
    }


@mcp.tool()
async def psd_design_get_packet(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
) -> dict[str, Any]:
    """
    Return the full PSD Design Implementation Packet.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _packet_response(packet, packet_id, "psd_design")


@mcp.tool()
async def psd_design_get_summary(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
    max_items: Annotated[int, "Maximum items per summary section."] = 12,
) -> dict[str, Any]:
    """
    Return a compact PSD implementation summary for AI planning.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _summary_for_packet(packet, max_items=max_items)


@mcp.tool()
async def psd_design_get_node_tree(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
    max_depth: Annotated[int, "Maximum depth to return."] = 3,
    include_style: Annotated[bool, "Include style/text fields in tree response."] = True,
) -> dict[str, Any]:
    """
    Return a trimmed PSD node hierarchy for staged AI reading.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    root = packet["nodes"][0]
    max_depth = max(0, min(int(max_depth), 20))
    return {
        "packet_id": packet_id,
        "design": packet.get("design"),
        "node_count": len(collect_nodes(root)),
        "tree": trim_node_tree(root, max_depth=max_depth, include_style=include_style),
    }


@mcp.tool()
async def psd_design_get_node_detail(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
    node_ids: Annotated[list[str] | str, "One node id or a list of node ids."],
) -> dict[str, Any]:
    """
    Return full details for selected PSD nodes.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    if isinstance(node_ids, str):
        node_ids = [node_ids]
    return {
        "packet_id": packet_id,
        **_find_nodes(packet, [str(node_id) for node_id in node_ids]),
    }


@mcp.tool()
async def psd_design_get_asset_manifest(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
) -> dict[str, Any]:
    """
    Return PSD-exported image assets, local paths, suggested Unity paths, and import hints.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _asset_manifest_response(packet, packet_id)


@mcp.tool()
async def psd_design_get_slices(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
    include_reference: Annotated[bool, "Include the flattened PSD reference image in the result."] = False,
) -> dict[str, Any]:
    """
    Return all image-backed PSD nodes with their exported assets and Unity rect hints.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _slices_response(packet, packet_id, include_reference)


@mcp.tool()
async def psd_design_get_unity_plan(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
    include_reference: Annotated[bool, "Include the flattened PSD reference image as an import step."] = True,
) -> dict[str, Any]:
    """
    Build an ordered Unity execution plan from a prepared PSD packet.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _unity_plan_response(packet, packet_id, include_reference)


@mcp.tool()
async def psd_design_get_unity_readiness_report(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
    max_items: Annotated[int, "Maximum sample items per report section."] = 20,
) -> dict[str, Any]:
    """
    Return a PSD-to-Unity readiness report.

    Use this before writing a prefab when you need to know whether the PSD has
    missing assets, best-effort text/style mappings, or component bindings that
    should be reviewed in Unity.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    return _unity_readiness_report(packet, max_items=max_items)


@mcp.tool()
async def psd_design_compare_unity_screenshot(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet or psd_design_convert_to_unity_prefab."],
    screenshot_path: Annotated[str, "Absolute or relative path to a Unity screenshot PNG/JPG captured from the generated prefab or scene."],
    output_dir: Annotated[
        str | None,
        "Optional directory for diff PNG and JSON report. If omitted, DATA_DIR/visual-diffs/<packet_id> is used.",
    ] = None,
    max_mean_delta: Annotated[
        float,
        "Pass threshold for normalized mean absolute pixel delta, from 0 to 1.",
    ] = 0.03,
    max_mismatch_ratio: Annotated[
        float,
        "Pass threshold for the ratio of pixels whose max channel delta exceeds per_pixel_threshold.",
    ] = 0.08,
    per_pixel_threshold: Annotated[
        float,
        "Normalized per-pixel max-channel delta threshold used to count mismatched pixels.",
    ] = 0.08,
    resize_screenshot: Annotated[
        bool,
        "Resize screenshot to the PSD reference size before comparison when dimensions differ.",
    ] = True,
    orientation: Annotated[
        str,
        "Screenshot orientation handling: auto, normal, or flip_y. Use auto for Unity RenderTexture/ReadPixels captures.",
    ] = "auto",
) -> dict[str, Any]:
    """
    Compare a Unity screenshot against the flattened PSD reference image.

    Use this after Unity MCP imports the generated prefab and captures a GameView
    or prefab preview screenshot. The result includes numeric metrics and a diff
    heatmap PNG for visual QA.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    diff_dir = Path(output_dir).expanduser() if output_dir else settings.data_dir / "visual-diffs" / packet_id
    return compare_packet_reference_to_screenshot(
        packet=packet,
        screenshot_path=screenshot_path,
        output_dir=diff_dir,
        max_mean_delta=max_mean_delta,
        max_mismatch_ratio=max_mismatch_ratio,
        per_pixel_threshold=per_pixel_threshold,
        resize_screenshot=resize_screenshot,
        orientation=orientation,
    )


@mcp.tool()
async def psd_design_install_unity_editor_validator(
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    asset_path: Annotated[
        str,
        "Unity asset path for the validator C# script. Must start with Assets/ and end with .cs.",
    ] = "Assets/Editor/DesignToUnity/DesignToUnityPrefabValidator.cs",
    overwrite: Annotated[bool, "Overwrite an existing validator script at asset_path."] = True,
) -> dict[str, Any]:
    """
    Install a Unity Editor validation script for generated Design to Unity prefabs.

    The script runs inside Unity after import, loads the generated prefab and
    source map, checks actual component counts against unity_import_manifest,
    and writes a JSON import report.
    """
    return install_unity_editor_validator(
        unity_project_path=unity_project_path,
        asset_path=asset_path,
        overwrite=overwrite,
    )


@mcp.tool()
async def psd_design_convert_export_to_unity_prefab(
    export_path: Annotated[
        str,
        "Path to a Photoshop/UXP export directory or manifest JSON. Expected files include design.json, preview.png, and assets/*.png.",
    ],
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    target: Annotated[str, "Target profile name: unity, web, or generic."] = "unity",
    scale: Annotated[
        float | None,
        "Optional export scale factor. If omitted, the manifest scale is used; otherwise 1x is used.",
    ] = None,
    asset_root: Annotated[
        str,
        "Unity asset folder where generated sprites and prefab should be written. Must start with Assets/.",
    ] = "Assets/DesignToUnity",
    prefab_name: Annotated[
        str | None,
        "Optional prefab file name. The .prefab suffix is optional.",
    ] = None,
    overwrite: Annotated[bool, "Overwrite existing generated prefab and copied sprite files."] = True,
    include_reference_in_prefab: Annotated[
        bool,
        "Include the Photoshop preview/reference image as a sprite asset if it is used by a node.",
    ] = False,
    prefab_visual_mode: Annotated[
        str,
        "Prefab visual strategy: layered or flattened_reference_overlay.",
    ] = "layered",
    button_raycast: Annotated[bool, "Enable Image raycastTarget for button candidate nodes."] = False,
    use_text_components: Annotated[bool, "Create TextMeshProUGUI components for text nodes instead of using text slices as images."] = True,
    add_button_components: Annotated[bool, "Add UnityEngine.UI.Button components to button_candidate nodes."] = True,
    add_slider_components: Annotated[bool, "Add UnityEngine.UI.Slider components to progress_candidate and slider_candidate nodes."] = True,
    add_toggle_components: Annotated[bool, "Add UnityEngine.UI.Toggle components to toggle_candidate nodes."] = True,
    add_tab_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to tab_group_candidate/tab_candidate nodes."] = True,
    add_radio_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to radio_group_candidate/radio_candidate nodes."] = True,
    add_input_field_components: Annotated[bool, "Add TMPro.TMP_InputField components to input_candidate nodes."] = True,
    add_dropdown_components: Annotated[bool, "Add TMPro.TMP_Dropdown components to dropdown_candidate nodes."] = True,
    add_scroll_components: Annotated[bool, "Add UnityEngine.UI.ScrollRect, Scrollbar, and RectMask2D components to scroll_area_candidate nodes."] = True,
    add_mask_components: Annotated[bool, "Add UnityEngine.UI.RectMask2D components to mask_candidate nodes."] = True,
    add_layout_components: Annotated[bool, "Add UnityEngine.UI layout group components when repeated child geometry can be inferred."] = True,
    add_canvas_group_components: Annotated[bool, "Add UnityEngine.CanvasGroup components to semi-transparent group nodes."] = True,
    tmp_font_asset_guid: Annotated[
        str | None,
        "Optional TMP Font Asset guid. If omitted, the writer tries project Assets first, then uses a package fallback guid.",
    ] = None,
    tmp_font_asset_map_json: Annotated[
        str | None,
        "Optional JSON object mapping Photoshop font names/styles to TMP Font Asset guids.",
    ] = None,
) -> dict[str, Any]:
    """
    One-step Photoshop/UXP export to Unity prefab conversion.

    Use this for high-fidelity PSD workflows where Photoshop already rendered
    preview/layer/group assets and exported a manifest JSON.
    """
    settings = _settings()
    store = PacketStore(settings)
    packet = make_photoshop_export_packet(export_path=export_path, target=target, scale=scale)
    packet_path = store.save(packet)
    prefab_result = write_unity_prefab_yaml(
        packet=packet,
        unity_project_path=unity_project_path,
        asset_root=asset_root,
        prefab_name=prefab_name,
        overwrite=overwrite,
        include_reference=include_reference_in_prefab,
        prefab_visual_mode=prefab_visual_mode,
        button_raycast=button_raycast,
        use_text_components=use_text_components,
        add_button_components=add_button_components,
        add_slider_components=add_slider_components,
        add_toggle_components=add_toggle_components,
        add_tab_components=add_tab_components,
        add_radio_components=add_radio_components,
        add_input_field_components=add_input_field_components,
        add_dropdown_components=add_dropdown_components,
        add_scroll_components=add_scroll_components,
        add_mask_components=add_mask_components,
        add_layout_components=add_layout_components,
        add_canvas_group_components=add_canvas_group_components,
        tmp_font_asset_guid=tmp_font_asset_guid,
        tmp_font_asset_map=tmp_font_asset_map_json,
    )
    prefab_verification = _verify_prefab_result(prefab_result)
    root = packet["nodes"][0]
    return {
        "status": "success",
        "packet_id": packet["packet_id"],
        "packet_path": str(packet_path),
        "source": packet["source"],
        "design": packet["design"],
        "node_count": len(collect_nodes(root)),
        "asset_count": len(packet.get("assets") or []),
        "asset_dir": (packet.get("asset_export") or {}).get("asset_dir"),
        "warning_count": len(packet.get("warnings") or []),
        "warnings_preview": (packet.get("warnings") or [])[:10],
        "unity_prefab": prefab_result,
        "unity_prefab_verification": prefab_verification,
        "readiness_report": _unity_readiness_report(packet, prefab_result=prefab_result, max_items=20),
        "next_steps": [
            "Open or refresh the Unity project so generated assets import.",
            "Review unity_prefab_verification before asking Unity MCP to load the prefab.",
            "Optionally call psd_design_install_unity_editor_validator and run the Unity-side import report.",
            "Use Unity MCP to load the prefab and verify component counts/source map import.",
            "Capture a Unity screenshot and call psd_design_compare_unity_screenshot for visual diff QA.",
        ],
    }


@mcp.tool()
async def psd_design_convert_to_unity_prefab(
    file_path: Annotated[str, "Absolute or relative path to a local .psd or .psb file."],
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    target: Annotated[str, "Target profile name: unity, web, or generic."] = "unity",
    asset_output_dir: Annotated[
        str | None,
        "Optional local directory where PSD layer PNG assets should be exported. If omitted, DATA_DIR/assets/psd is used.",
    ] = None,
    rasterize_mode: Annotated[
        str,
        "PSD rasterize mode: layer, visible, all, or none. 'layer' exports renderable layers; 'visible/all' may export groups too.",
    ] = "layer",
    scale: Annotated[
        float | None,
        "Optional PSD scale factor. If omitted, @2x/@3x in the file name is detected; otherwise 1x is used.",
    ] = None,
    include_hidden: Annotated[bool, "Include hidden PSD layers in the packet."] = False,
    export_text_layers: Annotated[
        bool,
        "Export PSD text layers as PNG slices. False keeps them editable as TextMeshProUGUI.",
    ] = False,
    export_group_layers: Annotated[bool, "Export group layers as composed PNG slices where possible."] = False,
    include_reference: Annotated[bool, "Export a flattened PSD reference image for visual comparison."] = True,
    reference_image_path: Annotated[
        str | None,
        "Optional Photoshop-rendered preview PNG/JPG to use as the packet reference instead of psd-tools compositing.",
    ] = None,
    asset_root: Annotated[
        str,
        "Unity asset folder where generated sprites and prefab should be written. Must start with Assets/.",
    ] = "Assets/DesignToUnity",
    prefab_name: Annotated[
        str | None,
        "Optional prefab file name. The .prefab suffix is optional.",
    ] = None,
    overwrite: Annotated[bool, "Overwrite existing generated prefab and copied sprite files."] = True,
    include_reference_in_prefab: Annotated[
        bool,
        "Include the flattened PSD reference image as a sprite asset if it is used by a node.",
    ] = False,
    prefab_visual_mode: Annotated[
        str,
        "Prefab visual strategy: layered or flattened_reference_overlay.",
    ] = "layered",
    button_raycast: Annotated[bool, "Enable Image raycastTarget for button candidate nodes."] = False,
    use_text_components: Annotated[bool, "Create TextMeshProUGUI components for text nodes instead of using text slices as images."] = True,
    add_button_components: Annotated[bool, "Add UnityEngine.UI.Button components to button_candidate nodes."] = True,
    add_slider_components: Annotated[bool, "Add UnityEngine.UI.Slider components to progress_candidate and slider_candidate nodes."] = True,
    add_toggle_components: Annotated[bool, "Add UnityEngine.UI.Toggle components to toggle_candidate nodes."] = True,
    add_tab_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to tab_group_candidate/tab_candidate nodes."] = True,
    add_radio_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to radio_group_candidate/radio_candidate nodes."] = True,
    add_input_field_components: Annotated[bool, "Add TMPro.TMP_InputField components to input_candidate nodes."] = True,
    add_dropdown_components: Annotated[bool, "Add TMPro.TMP_Dropdown components to dropdown_candidate nodes."] = True,
    add_scroll_components: Annotated[bool, "Add UnityEngine.UI.ScrollRect, Scrollbar, and RectMask2D components to scroll_area_candidate nodes."] = True,
    add_mask_components: Annotated[bool, "Add UnityEngine.UI.RectMask2D components to mask_candidate nodes."] = True,
    add_layout_components: Annotated[bool, "Add UnityEngine.UI layout group components when repeated child geometry can be inferred."] = True,
    add_canvas_group_components: Annotated[bool, "Add UnityEngine.CanvasGroup components to semi-transparent group nodes."] = True,
    tmp_font_asset_guid: Annotated[
        str | None,
        "Optional TMP Font Asset guid. If omitted, the writer tries project Assets first, then uses a package fallback guid.",
    ] = None,
    tmp_font_asset_map_json: Annotated[
        str | None,
        "Optional JSON object mapping Photoshop font names/styles to TMP Font Asset guids.",
    ] = None,
) -> dict[str, Any]:
    """
    One-step PSD to Unity prefab conversion.

    This prepares and stores a PSD Design Implementation Packet, writes a static
    UGUI prefab YAML plus sprites/source map into the Unity project, then returns
    a readiness report for follow-up Unity MCP validation.
    """
    settings = _settings()
    store = PacketStore(settings)
    output_dir = Path(asset_output_dir).expanduser() if asset_output_dir else None
    packet = make_psd_packet(
        file_path=file_path,
        target=target,
        asset_output_dir=output_dir,
        rasterize_mode=rasterize_mode,
        scale=scale,
        include_hidden=include_hidden,
        export_text_layers=export_text_layers,
        export_group_layers=export_group_layers,
        include_reference=include_reference,
        reference_image_path=reference_image_path,
        data_dir=settings.data_dir,
    )
    packet_path = store.save(packet)
    prefab_result = write_unity_prefab_yaml(
        packet=packet,
        unity_project_path=unity_project_path,
        asset_root=asset_root,
        prefab_name=prefab_name,
        overwrite=overwrite,
        include_reference=include_reference_in_prefab,
        prefab_visual_mode=prefab_visual_mode,
        button_raycast=button_raycast,
        use_text_components=use_text_components,
        add_button_components=add_button_components,
        add_slider_components=add_slider_components,
        add_toggle_components=add_toggle_components,
        add_tab_components=add_tab_components,
        add_radio_components=add_radio_components,
        add_input_field_components=add_input_field_components,
        add_dropdown_components=add_dropdown_components,
        add_scroll_components=add_scroll_components,
        add_mask_components=add_mask_components,
        add_layout_components=add_layout_components,
        add_canvas_group_components=add_canvas_group_components,
        tmp_font_asset_guid=tmp_font_asset_guid,
        tmp_font_asset_map=tmp_font_asset_map_json,
    )
    prefab_verification = _verify_prefab_result(prefab_result)
    root = packet["nodes"][0]
    return {
        "status": "success",
        "packet_id": packet["packet_id"],
        "packet_path": str(packet_path),
        "source": packet["source"],
        "design": packet["design"],
        "node_count": len(collect_nodes(root)),
        "asset_count": len(packet.get("assets") or []),
        "asset_dir": (packet.get("asset_export") or {}).get("asset_dir"),
        "warning_count": len(packet.get("warnings") or []),
        "warnings_preview": (packet.get("warnings") or [])[:10],
        "unity_prefab": prefab_result,
        "unity_prefab_verification": prefab_verification,
        "readiness_report": _unity_readiness_report(packet, prefab_result=prefab_result, max_items=20),
        "next_steps": [
            "Open or refresh the Unity project so generated assets import.",
            "Review unity_prefab_verification before asking Unity MCP to load the prefab.",
            "Optionally call psd_design_install_unity_editor_validator and run the Unity-side import report.",
            "Use Unity MCP to load the prefab and verify component counts/source map import.",
            "Capture a Unity screenshot and call psd_design_compare_unity_screenshot for visual diff QA.",
        ],
    }


@mcp.tool()
async def psd_design_write_unity_prefab_yaml(
    packet_id: Annotated[str, "Packet id returned by psd_design_prepare_packet."],
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    asset_root: Annotated[
        str,
        "Unity asset folder where generated sprites and prefab should be written. Must start with Assets/.",
    ] = "Assets/DesignToUnity",
    prefab_name: Annotated[
        str | None,
        "Optional prefab file name. The .prefab suffix is optional.",
    ] = None,
    overwrite: Annotated[bool, "Overwrite existing generated prefab and copied sprite files."] = True,
    include_reference: Annotated[bool, "Include the flattened PSD reference image as a sprite asset if it is used by a node."] = False,
    prefab_visual_mode: Annotated[
        str,
        "Prefab visual strategy: layered or flattened_reference_overlay.",
    ] = "layered",
    button_raycast: Annotated[bool, "Enable Image raycastTarget for button candidate nodes."] = False,
    use_text_components: Annotated[bool, "Create TextMeshProUGUI components for text nodes instead of using text slices as images."] = True,
    add_button_components: Annotated[bool, "Add UnityEngine.UI.Button components to button_candidate nodes."] = True,
    add_slider_components: Annotated[bool, "Add UnityEngine.UI.Slider components to progress_candidate and slider_candidate nodes."] = True,
    add_toggle_components: Annotated[bool, "Add UnityEngine.UI.Toggle components to toggle_candidate nodes."] = True,
    add_tab_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to tab_group_candidate/tab_candidate nodes."] = True,
    add_radio_components: Annotated[bool, "Add UnityEngine.UI.ToggleGroup plus Toggle components to radio_group_candidate/radio_candidate nodes."] = True,
    add_input_field_components: Annotated[bool, "Add TMPro.TMP_InputField components to input_candidate nodes."] = True,
    add_dropdown_components: Annotated[bool, "Add TMPro.TMP_Dropdown components to dropdown_candidate nodes."] = True,
    add_scroll_components: Annotated[bool, "Add UnityEngine.UI.ScrollRect, Scrollbar, and RectMask2D components to scroll_area_candidate nodes."] = True,
    add_mask_components: Annotated[bool, "Add UnityEngine.UI.RectMask2D components to mask_candidate nodes."] = True,
    add_layout_components: Annotated[bool, "Add UnityEngine.UI layout group components when repeated child geometry can be inferred."] = True,
    add_canvas_group_components: Annotated[bool, "Add UnityEngine.CanvasGroup components to semi-transparent group nodes."] = True,
    tmp_font_asset_guid: Annotated[
        str | None,
        "Optional TMP Font Asset guid. If omitted, the writer tries project Assets first, then uses a package fallback guid.",
    ] = None,
    tmp_font_asset_map_json: Annotated[
        str | None,
        "Optional JSON object mapping Photoshop font names/styles to TMP Font Asset guids.",
    ] = None,
) -> dict[str, Any]:
    """
    Experimentally write a Unity UGUI prefab from a PSD packet by generating Unity YAML directly.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    prefab_result = write_unity_prefab_yaml(
        packet=packet,
        unity_project_path=unity_project_path,
        asset_root=asset_root,
        prefab_name=prefab_name,
        overwrite=overwrite,
        include_reference=include_reference,
        prefab_visual_mode=prefab_visual_mode,
        button_raycast=button_raycast,
        use_text_components=use_text_components,
        add_button_components=add_button_components,
        add_slider_components=add_slider_components,
        add_toggle_components=add_toggle_components,
        add_tab_components=add_tab_components,
        add_radio_components=add_radio_components,
        add_input_field_components=add_input_field_components,
        add_dropdown_components=add_dropdown_components,
        add_scroll_components=add_scroll_components,
        add_mask_components=add_mask_components,
        add_layout_components=add_layout_components,
        add_canvas_group_components=add_canvas_group_components,
        tmp_font_asset_guid=tmp_font_asset_guid,
        tmp_font_asset_map=tmp_font_asset_map_json,
    )
    prefab_result["verification"] = _verify_prefab_result(prefab_result)
    return prefab_result


@mcp.tool()
async def psd_design_verify_unity_prefab_yaml(
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    prefab_asset_path: Annotated[str, "Generated prefab Unity asset path, for example Assets/DesignToUnity/<packet>/Prefabs/View.prefab."],
    source_map_asset_path: Annotated[
        str | None,
        "Optional source map Unity asset path. If omitted, <prefab>.design-to-unity.json next to the prefab is used.",
    ] = None,
) -> dict[str, Any]:
    """
    Statically verify a generated PSD-to-Unity prefab YAML and source map.

    Use this right after psd_design_write_unity_prefab_yaml or a one-step
    conversion when Unity MCP is unavailable or before opening the prefab in Unity.
    """
    return verify_unity_prefab_yaml(
        unity_project_path=unity_project_path,
        prefab_asset_path=prefab_asset_path,
        source_map_asset_path=source_map_asset_path,
    )


@mcp.tool()
async def lanhu_design_get_handoff_profile(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    target: Annotated[str, "Target profile name, for example unity or web."] = "unity",
) -> dict[str, Any]:
    """
    Return platform-specific execution rules for a prepared packet.
    """
    settings = _settings()
    packet = PacketStore(settings).load(packet_id)
    profiles = packet.get("handoff_profiles") or {}
    profile = profiles.get(target)
    if not profile:
        return {
            "status": "error",
            "message": f"Profile '{target}' does not exist.",
            "available_profiles": sorted(profiles.keys()),
        }
    return {
        "status": "success",
        "packet_id": packet_id,
        "target": target,
        "profile": profile,
        "handoff_reminder": [
            "Default flow: this MCP provides design facts and lets the target-platform MCP create/edit project files.",
            "Experimental direct flow: call lanhu_design_write_unity_prefab_yaml or psd_design_write_unity_prefab_yaml to write a static UGUI prefab YAML without Unity Editor APIs.",
            "Ask Unity MCP to import assets first, then create nodes using local_rect and unity_rect_hint.",
            "Use semantic_type only as a candidate signal, not as mandatory business binding.",
        ],
    }


def main() -> None:
    settings = _settings()
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
        return

    print(f"Design to Unity listening on http://{settings.server_host}:{settings.server_port}/mcp")
    print("Client config example:")
    print('{"mcpServers":{"DesignToUnity":{"url":"http://localhost:%d/mcp"}}}' % settings.server_port)
    mcp.run(transport="http", path="/mcp", host=settings.server_host, port=settings.server_port)


if __name__ == "__main__":
    main()

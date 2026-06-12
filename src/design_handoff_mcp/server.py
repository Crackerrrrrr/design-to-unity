from __future__ import annotations

import os
from collections import Counter, defaultdict
from typing import Annotated, Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from .asset_store import AssetStore
from .config import Settings
from .lanhu_client import LanhuClient
from .normalizer import make_packet
from .packet_store import PacketStore, collect_nodes, trim_node_tree
from .unity_yaml_writer import write_unity_prefab_yaml


load_dotenv(override=False)

mcp = FastMCP("LanhuUnityHandoffMcp")


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

    def walk_children(parent: dict[str, Any], parent_id: str | None) -> None:
        children = []
        for child in parent.get("children") or []:
            current = dict(child)
            current.setdefault("parent_id", parent_id)
            children.append(current)

        # Lanhu layer arrays observed so far are front-to-back. Unity renders later
        # siblings on top, so siblings must be created back-to-front.
        children.sort(key=lambda item: item.get("z_index") or 0, reverse=True)
        for child in children:
            nodes.append(child)
            walk_children(child, child.get("id"))

    for root in packet.get("nodes") or []:
        walk_children(root, root.get("id"))
    return nodes


def _unity_component_for(node: dict[str, Any]) -> str:
    semantic_type = node.get("semantic_type")
    if semantic_type == "button_candidate":
        return "Image + Button"
    if semantic_type in {"progress_candidate", "slider_candidate"}:
        return "Slider"
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
            "raycastTarget": bool(node.get("semantic_type") == "button_candidate"),
        }
    if node.get("text"):
        step["text_settings"] = node.get("text")
    if node.get("style"):
        step["style"] = node.get("style")
    if node.get("semantic_type") == "button_candidate":
        step["interaction_hint"] = node.get("unity_interaction_hint") or {
            "can_add_button": True,
            "default_add_button": True,
            "raycast_target_if_interactive": True,
        }
    if node.get("semantic_type") in {"progress_candidate", "slider_candidate"}:
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
            "value": "infer from design or user data",
            "fillRect": "bind when a fill child can be identified",
            "handleRect": "bind when a handle/thumb child can be identified",
        }
    return step


def _shorten(value: Any, limit: int = 80) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


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


def _summary_for_packet(packet: dict[str, Any], max_items: int) -> dict[str, Any]:
    nodes = _all_nodes(packet)
    assets = packet.get("assets") or []
    max_items = max(3, min(int(max_items), 50))

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
            "sibling_order_rule": "same-parent siblings should be created by descending z_index for Unity UGUI",
        },
        "recommended_next_tools": [
            "lanhu_design_get_slices",
            "lanhu_design_get_unity_plan",
            "lanhu_design_get_node_detail",
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
    root = packet["nodes"][0]
    node_count = len(collect_nodes(root))
    if node_count > settings.max_nodes_per_response:
        return {
            "status": "too_large",
            "packet_id": packet_id,
            "node_count": node_count,
            "message": "Packet is large. Use lanhu_design_get_node_tree and lanhu_design_get_node_detail instead.",
            "summary": {
                "source": packet.get("source"),
                "design": packet.get("design"),
                "asset_count": len(packet.get("assets") or []),
                "warning_count": len(packet.get("warnings") or []),
            },
        }
    return packet


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
    return {
        "packet_id": packet_id,
        "design": packet.get("design"),
        "asset_download": packet.get("asset_download"),
        "assets": packet.get("assets") or [],
        "warnings": [w for w in packet.get("warnings") or [] if w.get("code") == "missing_asset"],
    }


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
    assets = _asset_index(packet)
    profile = (packet.get("handoff_profiles") or {}).get("unity", {})
    all_nodes = _all_nodes(packet)
    root = (packet.get("nodes") or [{}])[0]

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
            }
        )

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
            "rule": "Create siblings in descending z_index order. In observed Lanhu payloads, larger z_index nodes are behind smaller z_index nodes.",
            "unity_reason": "Unity UGUI renders later siblings on top; descending creation makes lower z_index design layers appear in front.",
            "verified_with": "-h-海报分享",
        },
        "semantic_candidates": semantic_candidates,
        "warnings": packet.get("warnings") or [],
        "rules": profile.get("rules") or [],
        "coordinate_mapping": profile.get("coordinate_mapping"),
        "component_mapping": profile.get("component_mapping"),
        "recommended_sequence": [
            "Import all assets from asset_imports.",
            "Create ViewRoot using root.unity_rect_hint.",
            "Create nodes in create_nodes order. It is parent-before-child and same-parent siblings are back-to-front for Unity UGUI.",
            "Assign Image sprites from asset.local_path or suggested_unity_path.",
            "Assign TMP text fields from text_settings.",
            "Treat semantic_candidates as hints only; do not bind business scripts without user intent.",
            "Write source_metadata/content_hash if Unity MCP supports custom metadata.",
            "Save prefab or scene, then capture a screenshot for visual comparison.",
        ],
    }


@mcp.tool()
async def lanhu_design_write_unity_prefab_yaml(
    packet_id: Annotated[str, "Packet id returned by lanhu_design_prepare_packet."],
    unity_project_path: Annotated[str, "Absolute path to the Unity project root that contains the Assets folder."],
    asset_root: Annotated[
        str,
        "Unity asset folder where generated sprites and prefab should be written. Must start with Assets/.",
    ] = "Assets/DesignHandoff/LanhuUnityHandoffMcp",
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
    tmp_font_asset_guid: Annotated[
        str | None,
        "Optional TMP Font Asset guid. If omitted, the writer tries project Assets first, then uses a package fallback guid.",
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
    return write_unity_prefab_yaml(
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
        tmp_font_asset_guid=tmp_font_asset_guid,
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
            "Experimental direct flow: call lanhu_design_write_unity_prefab_yaml to write a static UGUI prefab YAML without Unity Editor APIs.",
            "Ask Unity MCP to import assets first, then create nodes using local_rect and unity_rect_hint.",
            "Use semantic_type only as a candidate signal, not as mandatory business binding.",
        ],
    }


def main() -> None:
    settings = _settings()
    if settings.transport == "stdio":
        mcp.run(transport="stdio")
        return

    print(f"LanhuUnityHandoffMcp listening on http://{settings.server_host}:{settings.server_port}/mcp")
    print("Client config example:")
    print('{"mcpServers":{"LanhuUnityHandoffMcp":{"url":"http://localhost:%d/mcp"}}}' % settings.server_port)
    mcp.run(transport="http", path="/mcp", host=settings.server_host, port=settings.server_port)


if __name__ == "__main__":
    main()

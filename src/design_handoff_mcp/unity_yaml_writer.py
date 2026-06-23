from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any


IMAGE_SCRIPT_GUID = "fe87c0e1cc204ed48ad3b37840f39efc"
TMP_TEXT_SCRIPT_GUID = "f4688fdb7df04437aeb418b961361dc5"
TMP_INPUT_FIELD_SCRIPT_GUID = "2da0c512f12947e489f739169773d7ca"
TMP_DROPDOWN_SCRIPT_GUID = "7b743370ac3e4ec2a1668f5455a8ef8a"
BUTTON_SCRIPT_GUID = "4e29b1a8efbd4b44bb3f3716e73f07ff"
SLIDER_SCRIPT_GUID = "67db9e8f0e2ae9c40bc1e2b64352a6b4"
TOGGLE_SCRIPT_GUID = "9085046f02f69544eb97fd06b6048fe2"
TOGGLE_GROUP_SCRIPT_GUID = "2fafe2cfe61f6974895a912c3755e8f1"
SCROLL_RECT_SCRIPT_GUID = "1aa08ab6e0800fa44ae55d278d1423e3"
SCROLLBAR_SCRIPT_GUID = "2a4db7a114972834c8e4117be1d82ba3"
RECT_MASK_2D_SCRIPT_GUID = "3312d7739989d2b4e91e6319e9a96d76"
VERTICAL_LAYOUT_GROUP_SCRIPT_GUID = "59f8146938fff824cb5fd77236b75775"
HORIZONTAL_LAYOUT_GROUP_SCRIPT_GUID = "30649d3a9faa99c48a7b1166b86bf2a0"
GRID_LAYOUT_GROUP_SCRIPT_GUID = "8a8695521f0d02e499659fee002a26c2"
LAYOUT_ELEMENT_SCRIPT_GUID = "306cc8c2b49d7114eaa3623786fc2126"
OUTLINE_SCRIPT_GUID = "e19747de3f5aca642ab2be37e372fb86"
SHADOW_SCRIPT_GUID = "cfabb0440166ab443bba8876756fdfa9"
DEFAULT_TMP_FONT_ASSET_GUID = "2f7116f10747a67409388e93052ae222"
TMP_FONT_ASSET_FILE_ID = 11400000
SPRITE_FILE_ID = 21300000


def write_unity_prefab_yaml(
    packet: dict[str, Any],
    unity_project_path: str,
    asset_root: str = "Assets/DesignToUnity",
    prefab_name: str | None = None,
    overwrite: bool = True,
    include_reference: bool = False,
    button_raycast: bool = False,
    use_text_components: bool = True,
    add_button_components: bool = True,
    add_slider_components: bool = True,
    add_toggle_components: bool = True,
    add_tab_components: bool = True,
    add_radio_components: bool = True,
    add_input_field_components: bool = True,
    add_dropdown_components: bool = True,
    add_scroll_components: bool = True,
    add_mask_components: bool = True,
    add_layout_components: bool = True,
    add_canvas_group_components: bool = True,
    tmp_font_asset_guid: str | None = None,
    tmp_font_asset_map: dict[str, str] | str | None = None,
    prefab_visual_mode: str = "layered",
) -> dict[str, Any]:
    project_root = Path(unity_project_path).expanduser().resolve()
    assets_dir = project_root / "Assets"
    if not assets_dir.is_dir():
        raise FileNotFoundError(f"Unity project Assets folder not found: {assets_dir}")

    packet_id = str(packet.get("packet_id") or "packet")
    design = packet.get("design") or {}
    safe_packet = _safe_name(packet_id)
    asset_root = asset_root.strip("/").replace("\\", "/")
    if not asset_root.startswith("Assets/"):
        raise ValueError("asset_root must be a Unity asset path under Assets/")
    normalized_visual_mode = _normalize_prefab_visual_mode(prefab_visual_mode)

    sprite_asset_dir = f"{asset_root}/{safe_packet}/Sprites"
    prefab_asset_dir = f"{asset_root}/{safe_packet}/Prefabs"
    raw_prefab_name = str(prefab_name or f"{packet_id[:8]}_ViewRoot").strip()
    if raw_prefab_name.lower().endswith(".prefab"):
        raw_prefab_name = raw_prefab_name[:-7]
    prefab_name = _safe_name(raw_prefab_name) + ".prefab"
    prefab_asset_path = f"{prefab_asset_dir}/{prefab_name}"

    (project_root / sprite_asset_dir).mkdir(parents=True, exist_ok=True)
    (project_root / prefab_asset_dir).mkdir(parents=True, exist_ok=True)

    assets = {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}
    nodes = _unity_creation_order(packet)
    if normalized_visual_mode == "flattened_reference_overlay":
        nodes = [_reference_overlay_node(packet, assets)] + nodes
    copied_assets, asset_guid_by_id, warnings = _write_sprite_assets(
        project_root=project_root,
        sprite_asset_dir=sprite_asset_dir,
        nodes=nodes,
        assets=assets,
        include_reference=include_reference or normalized_visual_mode == "flattened_reference_overlay",
        overwrite=overwrite,
        use_text_components=use_text_components,
        prefab_visual_mode=normalized_visual_mode,
    )
    tmp_font = _resolve_tmp_font(project_root, tmp_font_asset_guid)
    tmp_font_map = _normalize_tmp_font_asset_map(tmp_font_asset_map)
    tmp_font_guid = tmp_font.get("guid")
    tmp_font_material_file_id = tmp_font.get("material_file_id")
    if use_text_components:
        if not tmp_font_guid:
            warnings.append(
                {
                    "code": "missing_tmp_font",
                    "message": "No TMP font asset guid could be resolved. TextMeshProUGUI components will use empty font references.",
                }
            )
        if not _has_tmp_essential_resources(project_root):
            warnings.append(
                {
                    "code": "missing_tmp_essential_resources",
                    "message": "TextMeshProUGUI nodes require TMP Essential Resources. In Unity, import them from Window > TextMeshPro > Import TMP Essential Resources.",
                }
            )

    prefab_text, stats, source_map = _build_prefab_yaml(
        packet=packet,
        nodes=nodes,
        assets=assets,
        asset_guid_by_id=asset_guid_by_id,
        prefab_asset_path=prefab_asset_path,
        sprite_asset_dir=sprite_asset_dir,
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
        default_tmp_font=tmp_font,
        tmp_font_asset_map=tmp_font_map,
        prefab_visual_mode=normalized_visual_mode,
    )
    prefab_path = project_root / prefab_asset_path
    if prefab_path.exists() and not overwrite:
        raise FileExistsError(f"Prefab already exists: {prefab_path}")
    prefab_path.write_text(prefab_text, encoding="utf-8")

    prefab_meta_path = prefab_path.with_suffix(prefab_path.suffix + ".meta")
    if not prefab_meta_path.exists():
        prefab_meta_path.write_text(_prefab_meta(_new_guid()), encoding="utf-8")

    source_map_name = f"{Path(prefab_name).stem}.design-to-unity.json"
    source_map_asset_path = f"{prefab_asset_dir}/{source_map_name}"
    source_map_path = project_root / source_map_asset_path
    source_map_path.write_text(json.dumps(source_map, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    source_map_meta_path = source_map_path.with_suffix(source_map_path.suffix + ".meta")
    if not source_map_meta_path.exists():
        source_map_meta_path.write_text(_text_asset_meta(_guid_for_asset(f"{packet_id}:source-map", source_map_asset_path)), encoding="utf-8")

    return {
        "status": "success",
        "mode": "experimental_direct_yaml",
        "prefab_visual_mode": normalized_visual_mode,
        "packet_id": packet_id,
        "design": design,
        "unity_project_path": str(project_root),
        "prefab_asset_path": prefab_asset_path,
        "prefab_path": str(prefab_path),
        "prefab_meta_path": str(prefab_meta_path),
        "source_map_asset_path": source_map_asset_path,
        "source_map_path": str(source_map_path),
        "source_map_meta_path": str(source_map_meta_path),
        "source_map_node_count": len(source_map.get("nodes") or []),
        "sprite_asset_dir": sprite_asset_dir,
        "sprite_dir": str(project_root / sprite_asset_dir),
        "copied_asset_count": len(copied_assets),
        "node_count": stats["node_count"],
        "image_node_count": stats["image_node_count"],
        "tmp_text_node_count": stats["tmp_text_node_count"],
        "button_node_count": stats["button_node_count"],
        "slider_node_count": stats["slider_node_count"],
        "toggle_node_count": stats["toggle_node_count"],
        "toggle_group_node_count": stats["toggle_group_node_count"],
        "tab_node_count": stats["tab_node_count"],
        "radio_node_count": stats["radio_node_count"],
        "input_field_node_count": stats["input_field_node_count"],
        "dropdown_node_count": stats["dropdown_node_count"],
        "dropdown_template_bound_count": stats["dropdown_template_bound_count"],
        "dropdown_caption_bound_count": stats["dropdown_caption_bound_count"],
        "dropdown_item_bound_count": stats["dropdown_item_bound_count"],
        "slider_fill_bound_count": stats["slider_fill_bound_count"],
        "slider_handle_bound_count": stats["slider_handle_bound_count"],
        "scroll_rect_node_count": stats["scroll_rect_node_count"],
        "scrollbar_node_count": stats["scrollbar_node_count"],
        "scrollbar_handle_bound_count": stats["scrollbar_handle_bound_count"],
        "rect_mask_2d_node_count": stats["rect_mask_2d_node_count"],
        "vertical_layout_group_node_count": stats["vertical_layout_group_node_count"],
        "horizontal_layout_group_node_count": stats["horizontal_layout_group_node_count"],
        "grid_layout_group_node_count": stats["grid_layout_group_node_count"],
        "layout_element_node_count": stats["layout_element_node_count"],
        "outline_node_count": stats["outline_node_count"],
        "shadow_node_count": stats["shadow_node_count"],
        "canvas_group_node_count": stats["canvas_group_node_count"],
        "reusable_prefab_count": stats["reusable_prefab_count"],
        "reused_prefab_node_count": stats["reused_prefab_node_count"],
        "prefab_variant_group_count": stats["prefab_variant_group_count"],
        "prefab_variant_count": stats["prefab_variant_count"],
        "tmp_font_asset_guid": tmp_font_guid,
        "tmp_font_material_file_id": tmp_font_material_file_id,
        "tmp_font_asset_map_count": len(tmp_font_map),
        "missing_asset_count": len([w for w in warnings if w.get("code") == "missing_asset"]),
        "warnings": warnings,
        "caveats": [
            "This tool writes Unity YAML directly and is intentionally marked experimental.",
            "It creates static UGUI Image, TextMeshProUGUI, Button, and Slider components from best-effort semantics.",
            "It can add Toggle components for toggle_candidate nodes.",
            "It can add ToggleGroup + Toggle components for tab_group_candidate/tab_candidate nodes.",
            "It can add ToggleGroup + Toggle components for radio_group_candidate/radio_candidate nodes.",
            "It can add TMP_InputField components for input_candidate nodes.",
            "It can add TMP_Dropdown components for dropdown_candidate nodes when caption/template/item roles can be inferred.",
            "It can add ScrollRect, Scrollbar, and RectMask2D for scroll_area_candidate nodes when viewport/content/scrollbar roles can be inferred.",
            "It can add RectMask2D for mask_candidate nodes as rectangular UI clipping containers.",
            "It can add VerticalLayoutGroup, HorizontalLayoutGroup, or GridLayoutGroup from repeated child geometry.",
            "It can add LayoutElement for Figma auto-layout child sizing, stretch, grow, or absolute-positioning hints.",
            "It can add CanvasGroup for semi-transparent PSD groups.",
            "Slider fill/handle references are bound from best-effort PSD semantics when child roles can be inferred.",
            "flattened_reference_overlay mode uses the Photoshop-rendered reference as the visible baseline and keeps source nodes as editable/interactive overlays.",
            "Repeated component reuse is emitted as reusable_prefabs/source-map guidance; the experimental direct YAML output still expands the visible hierarchy for compatibility.",
            "Open the project in Unity after writing so Unity can import generated meta/prefab files.",
            "For production-safe output, prefer the Unity Editor API importer path when available.",
        ],
    }


def _write_sprite_assets(
    project_root: Path,
    sprite_asset_dir: str,
    nodes: list[dict[str, Any]],
    assets: dict[str, dict[str, Any]],
    include_reference: bool,
    overwrite: bool,
    use_text_components: bool,
    prefab_visual_mode: str,
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    copied = []
    guid_by_id: dict[str, str] = {}
    warnings: list[dict[str, Any]] = []
    used_asset_ids = []
    for node in nodes:
        if prefab_visual_mode == "flattened_reference_overlay" and not _is_reference_overlay_node(node):
            continue
        if use_text_components and _has_text(node):
            continue
        asset_ref = node.get("asset_ref")
        if asset_ref and asset_ref not in used_asset_ids:
            used_asset_ids.append(asset_ref)

    imported_by_signature: dict[str, dict[str, str]] = {}
    for asset_id in used_asset_ids:
        asset = assets.get(asset_id)
        if not asset:
            warnings.append({"code": "missing_asset", "asset_id": asset_id, "message": "Asset is referenced by a node but missing from packet assets."})
            continue
        if asset.get("usage") == "design_reference" and not include_reference:
            continue

        signature = _sprite_asset_reuse_signature(asset_id, asset)
        if signature in imported_by_signature:
            canonical = imported_by_signature[signature]
            guid_by_id[asset_id] = canonical["guid"]
            asset["duplicate_of"] = canonical["asset_id"]
            asset["deduped_unity_asset_path"] = canonical["asset_path"]
            continue

        local_path_text = str(asset.get("local_path") or "")
        if not local_path_text:
            warnings.append({"code": "missing_asset", "asset_id": asset_id, "message": "Asset has no local_path."})
            continue

        local_path = Path(local_path_text).expanduser()
        if not local_path.is_absolute():
            local_path = (Path.cwd() / local_path).resolve()
        if not local_path.exists():
            warnings.append({"code": "missing_asset", "asset_id": asset_id, "message": f"Local asset file not found: {local_path}"})
            continue

        file_name = _safe_file_name(str(asset.get("file_name") or local_path.name))
        target_asset_path = f"{sprite_asset_dir}/{file_name}"
        target_path = project_root / target_asset_path
        if target_path.exists() and not overwrite:
            meta_path = target_path.with_suffix(target_path.suffix + ".meta")
            guid = _read_meta_guid(meta_path)
            if not guid:
                guid = _guid_for_asset(asset_id, target_asset_path)
                meta_path.write_text(_texture_meta(guid, asset), encoding="utf-8")
            if guid:
                guid_by_id[asset_id] = guid
                imported_by_signature[signature] = {"asset_id": asset_id, "asset_path": target_asset_path, "guid": guid}
            continue

        shutil.copy2(local_path, target_path)
        meta_path = target_path.with_suffix(target_path.suffix + ".meta")
        guid = _read_meta_guid(meta_path) or _guid_for_asset(asset_id, target_asset_path)
        meta_path.write_text(_texture_meta(guid, asset), encoding="utf-8")
        guid_by_id[asset_id] = guid
        imported_by_signature[signature] = {"asset_id": asset_id, "asset_path": target_asset_path, "guid": guid}
        copied.append({"asset_id": asset_id, "asset_path": target_asset_path, "path": str(target_path), "guid": guid})

    return copied, guid_by_id, warnings


def _sprite_asset_reuse_signature(asset_id: str, asset: dict[str, Any]) -> str:
    if asset.get("content_hash") or asset.get("file_hash"):
        basis = {
            "content_hash": asset.get("content_hash") or asset.get("file_hash"),
            "format": asset.get("format"),
            "nine_slice_hint": asset.get("nine_slice_hint"),
            "unity_import_hints": asset.get("unity_import_hints"),
        }
        return "content:" + hashlib.sha1(repr(basis).encode("utf-8", "ignore")).hexdigest()
    if asset.get("source_image_ref"):
        basis = {
            "source_provider": asset.get("source_provider"),
            "source_image_ref": asset.get("source_image_ref"),
            "image_fill": asset.get("image_fill"),
            "format": asset.get("format"),
            "unity_import_hints": asset.get("unity_import_hints"),
        }
        return "figma-image-ref:" + hashlib.sha1(repr(basis).encode("utf-8", "ignore")).hexdigest()
    if asset.get("remote_url"):
        return "remote:" + str(asset.get("remote_url"))
    return "asset:" + asset_id


def _normalize_prefab_visual_mode(value: str | None) -> str:
    mode = str(value or "layered").strip().lower()
    if mode not in {"layered", "flattened_reference_overlay"}:
        raise ValueError("prefab_visual_mode must be one of: layered, flattened_reference_overlay")
    return mode


def _reference_overlay_node(packet: dict[str, Any], assets: dict[str, dict[str, Any]]) -> dict[str, Any]:
    design = packet.get("design") or {}
    reference_asset_ref = design.get("reference_asset_ref")
    if not reference_asset_ref or reference_asset_ref not in assets:
        raise ValueError("flattened_reference_overlay requires a packet design.reference_asset_ref asset.")
    width = _num(design.get("width"), 0)
    height = _num(design.get("height"), 0)
    source = packet.get("source") or {}
    return {
        "id": "__design_reference_overlay",
        "parent_id": "root",
        "name": "Design Reference Overlay",
        "unity_name_hint": "DesignReferenceOverlay",
        "path": f"{design.get('name') or 'Design'}/Design Reference Overlay",
        "type": "image",
        "semantic_type": "design_reference",
        "semantic_confidence": 1,
        "semantic_reasons": ["Photoshop-rendered flattened reference used as visible prefab baseline"],
        "visible": True,
        "z_index": -100000,
        "global_rect": {"x": 0, "y": 0, "width": width, "height": height},
        "local_rect": {"x": 0, "y": 0, "width": width, "height": height},
        "unity_rect_hint": {
            "anchoredPosition": {"x": 0, "y": 0},
            "sizeDelta": {"x": width, "y": height},
            "anchorMin": {"x": 0, "y": 1},
            "anchorMax": {"x": 0, "y": 1},
            "pivot": {"x": 0, "y": 1},
        },
        "style": {"opacity": 1},
        "asset_ref": reference_asset_ref,
        "children": [],
        "source_metadata": {
            "source_provider": source.get("provider") or "design",
            "source_node_id": "__design_reference_overlay",
            "source_path": "Design Reference Overlay",
            "visual_role": "flattened_reference",
            "prefab_visual_mode": "flattened_reference_overlay",
            "source_asset_ref": reference_asset_ref,
        },
        "content_hash": hashlib.sha1(f"{packet.get('packet_id')}:{reference_asset_ref}:overlay".encode("utf-8")).hexdigest(),
    }


def _is_reference_overlay_node(node: dict[str, Any]) -> bool:
    return str(node.get("id") or "") == "__design_reference_overlay"


def _suppresses_source_visual(prefab_visual_mode: str, node: dict[str, Any]) -> bool:
    return prefab_visual_mode == "flattened_reference_overlay" and not _is_reference_overlay_node(node)


def _build_prefab_yaml(
    packet: dict[str, Any],
    nodes: list[dict[str, Any]],
    assets: dict[str, dict[str, Any]],
    asset_guid_by_id: dict[str, str],
    prefab_asset_path: str,
    sprite_asset_dir: str,
    button_raycast: bool,
    use_text_components: bool,
    add_button_components: bool,
    add_slider_components: bool,
    add_toggle_components: bool,
    add_tab_components: bool,
    add_radio_components: bool,
    add_input_field_components: bool,
    add_dropdown_components: bool,
    add_scroll_components: bool,
    add_mask_components: bool,
    add_layout_components: bool,
    add_canvas_group_components: bool,
    default_tmp_font: dict[str, Any],
    tmp_font_asset_map: dict[str, str],
    prefab_visual_mode: str,
) -> tuple[str, dict[str, int], dict[str, Any]]:
    packet_id = str(packet.get("packet_id") or "packet")
    design = packet.get("design") or {}
    root = {
        "id": "root",
        "parent_id": None,
        "name": f"DesignToUnityView_{packet_id[:8]}",
        "unity_name_hint": f"DesignToUnityView_{packet_id[:8]}",
        "local_rect": {"x": 0, "y": 0, "width": design.get("width") or 0, "height": design.get("height") or 0},
        "style": {"opacity": 1},
        "asset_ref": None,
        "semantic_type": "screen_root",
        "z_index": 0,
    }
    all_nodes = [root] + nodes
    ids = {str(node.get("id")) for node in all_nodes}
    children: dict[str, list[str]] = {str(node.get("id")): [] for node in all_nodes}
    for node in nodes:
        node_id = str(node.get("id"))
        parent_id = str(node.get("parent_id") or "root")
        if parent_id not in ids:
            parent_id = "root"
        children.setdefault(parent_id, []).append(node_id)

    scroll_viewport_node_ids: set[str] = set()
    if add_scroll_components:
        for node in all_nodes:
            node_id = str(node.get("id"))
            if node.get("semantic_type") == "scroll_area_candidate":
                hint = node.get("unity_scroll_hint") or {}
                scroll_viewport_node_ids.add(str(hint.get("viewport_node_id") or node_id))
            if node.get("semantic_type") == "scroll_viewport_candidate":
                scroll_viewport_node_ids.add(node_id)

    used_file_ids: set[int] = set()
    object_ids: dict[str, dict[str, int | None]] = {}
    for node in all_nodes:
        node_id = str(node.get("id"))
        asset_ref = node.get("asset_ref")
        semantic_type = node.get("semantic_type")
        suppress_source_visual = _suppresses_source_visual(prefab_visual_mode, node)
        has_text = use_text_components and _has_text(node)
        has_sprite = bool(asset_ref and asset_ref in asset_guid_by_id and not has_text and not suppress_source_visual)
        has_button = bool(add_button_components and semantic_type == "button_candidate")
        has_slider = _should_add_slider_component(node, add_slider_components)
        has_toggle = bool(
            (add_toggle_components and semantic_type == "toggle_candidate")
            or (add_tab_components and semantic_type == "tab_candidate")
            or (add_radio_components and semantic_type == "radio_candidate")
        )
        has_toggle_group = bool(
            (add_tab_components and semantic_type == "tab_group_candidate")
            or (add_radio_components and semantic_type == "radio_group_candidate")
        )
        has_input_field = bool(add_input_field_components and semantic_type == "input_candidate")
        has_dropdown = bool(add_dropdown_components and semantic_type == "dropdown_candidate")
        has_scroll_rect = bool(add_scroll_components and semantic_type == "scroll_area_candidate")
        has_scrollbar = _should_add_scrollbar_component(node, add_scroll_components)
        has_rect_mask = bool((add_scroll_components and node_id in scroll_viewport_node_ids) or (add_mask_components and _should_add_mask_component(node)))
        layout_component = _layout_component(node, add_layout_components)
        has_layout_element = _should_add_layout_element(node, add_layout_components)
        has_canvas_group = bool(add_canvas_group_components and _needs_canvas_group(node, children.get(node_id) or []))
        text_effects = _text_effects(node)
        has_text_outline = bool(has_text and text_effects.get("outline"))
        has_text_shadow = bool(has_text and text_effects.get("shadow"))
        needs_control_hit_area = bool(
            (has_button or has_toggle or has_input_field or has_dropdown or has_scrollbar or semantic_type == "slider_candidate")
            and not has_sprite
            and not has_text
        )
        has_image = bool(has_sprite or needs_control_hit_area)
        has_canvas = bool(has_image or has_text)
        object_ids[node_id] = {
            "go": _file_id(packet_id, node_id, "go", used_file_ids),
            "rect": _file_id(packet_id, node_id, "rect", used_file_ids),
            "canvas": _file_id(packet_id, node_id, "canvas", used_file_ids) if has_canvas else None,
            "image": _file_id(packet_id, node_id, "image", used_file_ids) if has_image else None,
            "tmp_text": _file_id(packet_id, node_id, "tmp_text", used_file_ids) if has_text else None,
            "button": _file_id(packet_id, node_id, "button", used_file_ids) if has_button else None,
            "slider": _file_id(packet_id, node_id, "slider", used_file_ids) if has_slider else None,
            "toggle": _file_id(packet_id, node_id, "toggle", used_file_ids) if has_toggle else None,
            "toggle_group": _file_id(packet_id, node_id, "toggle_group", used_file_ids) if has_toggle_group else None,
            "tmp_input_field": _file_id(packet_id, node_id, "tmp_input_field", used_file_ids) if has_input_field else None,
            "tmp_dropdown": _file_id(packet_id, node_id, "tmp_dropdown", used_file_ids) if has_dropdown else None,
            "scroll_rect": _file_id(packet_id, node_id, "scroll_rect", used_file_ids) if has_scroll_rect else None,
            "scrollbar": _file_id(packet_id, node_id, "scrollbar", used_file_ids) if has_scrollbar else None,
            "rect_mask_2d": _file_id(packet_id, node_id, "rect_mask_2d", used_file_ids) if has_rect_mask else None,
            "vertical_layout_group": _file_id(packet_id, node_id, "vertical_layout_group", used_file_ids) if layout_component == "VerticalLayoutGroup" else None,
            "horizontal_layout_group": _file_id(packet_id, node_id, "horizontal_layout_group", used_file_ids) if layout_component == "HorizontalLayoutGroup" else None,
            "grid_layout_group": _file_id(packet_id, node_id, "grid_layout_group", used_file_ids) if layout_component == "GridLayoutGroup" else None,
            "layout_element": _file_id(packet_id, node_id, "layout_element", used_file_ids) if has_layout_element else None,
            "outline": _file_id(packet_id, node_id, "outline", used_file_ids) if has_text_outline else None,
            "shadow": _file_id(packet_id, node_id, "shadow", used_file_ids) if has_text_shadow else None,
            "canvas_group": _file_id(packet_id, node_id, "canvas_group", used_file_ids) if has_canvas_group else None,
        }

    lines = ["%YAML 1.1", "%TAG !u! tag:unity3d.com,2011:"]
    image_count = 0
    tmp_text_count = 0
    button_count = 0
    slider_count = 0
    toggle_count = 0
    toggle_group_count = 0
    tab_count = 0
    radio_count = 0
    input_field_count = 0
    dropdown_count = 0
    dropdown_template_bound_count = 0
    dropdown_caption_bound_count = 0
    dropdown_item_bound_count = 0
    slider_fill_bound_count = 0
    slider_handle_bound_count = 0
    scroll_rect_count = 0
    scrollbar_count = 0
    scrollbar_handle_bound_count = 0
    rect_mask_count = 0
    vertical_layout_group_count = 0
    horizontal_layout_group_count = 0
    grid_layout_group_count = 0
    layout_element_count = 0
    outline_count = 0
    shadow_count = 0
    canvas_group_count = 0
    for node in all_nodes:
        node_id = str(node.get("id"))
        ids_for_node = object_ids[node_id]
        child_rect_ids = [object_ids[child_id]["rect"] for child_id in children.get(node_id, [])]
        parent_id = str(node.get("parent_id") or "root")
        parent_rect = object_ids[parent_id]["rect"] if node_id != "root" and parent_id in object_ids else 0
        asset_ref = node.get("asset_ref")
        sprite_guid = asset_guid_by_id.get(asset_ref) if asset_ref else None
        semantic_type = node.get("semantic_type")
        has_button = bool(ids_for_node.get("button"))
        has_slider = bool(ids_for_node.get("slider"))
        has_toggle = bool(ids_for_node.get("toggle"))
        has_toggle_group = bool(ids_for_node.get("toggle_group"))
        has_input_field = bool(ids_for_node.get("tmp_input_field"))
        has_dropdown = bool(ids_for_node.get("tmp_dropdown"))
        has_text = bool(ids_for_node.get("tmp_text"))
        has_image = bool(ids_for_node.get("image"))
        suppress_source_visual = _suppresses_source_visual(prefab_visual_mode, node)
        lines.extend(_game_object_yaml(node, ids_for_node))
        lines.extend(_rect_transform_yaml(node, ids_for_node, parent_rect, child_rect_ids))
        if ids_for_node.get("canvas_group"):
            lines.extend(_canvas_group_yaml(node, ids_for_node))
            canvas_group_count += 1
        if ids_for_node.get("canvas"):
            lines.extend(_canvas_renderer_yaml(ids_for_node))
        if has_toggle_group:
            lines.extend(_toggle_group_yaml(node, ids_for_node))
            toggle_group_count += 1
        if has_image:
            asset = assets.get(asset_ref) or {}
            raycast = bool(
                has_button
                or has_toggle
                or has_input_field
                or has_dropdown
                or ids_for_node.get("scrollbar")
                or semantic_type == "slider_candidate"
                or (button_raycast and semantic_type == "button_candidate")
            )
            lines.extend(_image_yaml(node, ids_for_node, sprite_guid, asset, raycast_target=raycast, transparent=not bool(sprite_guid)))
            image_count += 1
        if has_text:
            raycast = bool(has_button)
            text_font = _resolve_tmp_font_for_text(node.get("text") or {}, default_tmp_font, tmp_font_asset_map)
            lines.extend(
                _tmp_text_yaml(
                    node,
                    ids_for_node,
                    text_font.get("guid"),
                    text_font.get("material_file_id"),
                    raycast_target=raycast,
                    transparent=suppress_source_visual,
                )
            )
            tmp_text_count += 1
        if ids_for_node.get("outline"):
            lines.extend(_outline_yaml(node, ids_for_node))
            outline_count += 1
        if ids_for_node.get("shadow"):
            lines.extend(_shadow_yaml(node, ids_for_node))
            shadow_count += 1
        if has_button:
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            lines.extend(_button_yaml(ids_for_node, target_graphic))
            button_count += 1
        if has_slider:
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            fill_rect, handle_rect = _slider_refs(node, object_ids)
            lines.extend(
                _slider_yaml(
                    node,
                    ids_for_node,
                    target_graphic,
                    fill_rect=fill_rect,
                    handle_rect=handle_rect,
                    interactable=semantic_type == "slider_candidate",
                )
            )
            slider_count += 1
            if fill_rect:
                slider_fill_bound_count += 1
            if handle_rect:
                slider_handle_bound_count += 1
        if has_toggle:
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            toggle_graphic = _toggle_graphic_ref(node, object_ids) or target_graphic
            toggle_group = _toggle_group_ref(node, object_ids)
            lines.extend(_toggle_yaml(node, ids_for_node, target_graphic, toggle_graphic, toggle_group))
            toggle_count += 1
            if semantic_type == "tab_candidate":
                tab_count += 1
            if semantic_type == "radio_candidate":
                radio_count += 1
        if has_input_field:
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            text_component, placeholder = _input_field_refs(node, object_ids)
            lines.extend(_tmp_input_field_yaml(node, ids_for_node, target_graphic, text_component, placeholder))
            input_field_count += 1
        if has_dropdown:
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            template_rect, caption_text, item_text = _dropdown_refs(node, object_ids)
            lines.extend(_tmp_dropdown_yaml(node, ids_for_node, target_graphic, template_rect, caption_text, item_text))
            dropdown_count += 1
            if template_rect:
                dropdown_template_bound_count += 1
            if caption_text:
                dropdown_caption_bound_count += 1
            if item_text:
                dropdown_item_bound_count += 1
        if ids_for_node.get("rect_mask_2d"):
            lines.extend(_rect_mask_2d_yaml(ids_for_node))
            rect_mask_count += 1
        if ids_for_node.get("vertical_layout_group"):
            lines.extend(_horizontal_or_vertical_layout_group_yaml(node, ids_for_node, "vertical_layout_group", VERTICAL_LAYOUT_GROUP_SCRIPT_GUID, "VerticalLayoutGroup"))
            vertical_layout_group_count += 1
        if ids_for_node.get("horizontal_layout_group"):
            lines.extend(_horizontal_or_vertical_layout_group_yaml(node, ids_for_node, "horizontal_layout_group", HORIZONTAL_LAYOUT_GROUP_SCRIPT_GUID, "HorizontalLayoutGroup"))
            horizontal_layout_group_count += 1
        if ids_for_node.get("grid_layout_group"):
            lines.extend(_grid_layout_group_yaml(node, ids_for_node))
            grid_layout_group_count += 1
        if ids_for_node.get("layout_element"):
            lines.extend(_layout_element_yaml(node, ids_for_node))
            layout_element_count += 1
        if ids_for_node.get("scrollbar"):
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            handle_rect = _scrollbar_handle_ref(node, object_ids)
            lines.extend(_scrollbar_yaml(node, ids_for_node, target_graphic, handle_rect))
            scrollbar_count += 1
            if handle_rect:
                scrollbar_handle_bound_count += 1
        if ids_for_node.get("scroll_rect"):
            content_rect, viewport_rect, horizontal_scrollbar, vertical_scrollbar = _scroll_refs(node, ids_for_node, object_ids)
            lines.extend(_scroll_rect_yaml(node, ids_for_node, content_rect, viewport_rect, horizontal_scrollbar, vertical_scrollbar))
            scroll_rect_count += 1

    stats = {
        "node_count": len(all_nodes),
        "image_node_count": image_count,
        "tmp_text_node_count": tmp_text_count,
        "button_node_count": button_count,
        "slider_node_count": slider_count,
        "toggle_node_count": toggle_count,
        "toggle_group_node_count": toggle_group_count,
        "tab_node_count": tab_count,
        "radio_node_count": radio_count,
        "input_field_node_count": input_field_count,
        "dropdown_node_count": dropdown_count,
        "dropdown_template_bound_count": dropdown_template_bound_count,
        "dropdown_caption_bound_count": dropdown_caption_bound_count,
        "dropdown_item_bound_count": dropdown_item_bound_count,
        "slider_fill_bound_count": slider_fill_bound_count,
        "slider_handle_bound_count": slider_handle_bound_count,
        "scroll_rect_node_count": scroll_rect_count,
        "scrollbar_node_count": scrollbar_count,
        "scrollbar_handle_bound_count": scrollbar_handle_bound_count,
        "rect_mask_2d_node_count": rect_mask_count,
        "vertical_layout_group_node_count": vertical_layout_group_count,
        "horizontal_layout_group_node_count": horizontal_layout_group_count,
        "grid_layout_group_node_count": grid_layout_group_count,
        "layout_element_node_count": layout_element_count,
        "outline_node_count": outline_count,
        "shadow_node_count": shadow_count,
        "canvas_group_node_count": canvas_group_count,
        "reusable_prefab_count": len(packet.get("reusable_prefabs") or []),
        "reused_prefab_node_count": (packet.get("reusable_prefab_summary") or {}).get("reused_node_count", 0),
        "prefab_variant_group_count": len(packet.get("prefab_variant_groups") or []),
        "prefab_variant_count": (packet.get("prefab_variant_summary") or {}).get("variant_count", 0),
    }
    source_map = _prefab_source_map(
        packet=packet,
        all_nodes=all_nodes,
        children=children,
        object_ids=object_ids,
        assets=assets,
        asset_guid_by_id=asset_guid_by_id,
        prefab_asset_path=prefab_asset_path,
        sprite_asset_dir=sprite_asset_dir,
        stats=stats,
        prefab_visual_mode=prefab_visual_mode,
        default_tmp_font=default_tmp_font,
        tmp_font_asset_map=tmp_font_asset_map,
    )
    return "\n".join(lines) + "\n", stats, source_map


def _prefab_source_map(
    packet: dict[str, Any],
    all_nodes: list[dict[str, Any]],
    children: dict[str, list[str]],
    object_ids: dict[str, dict[str, int | None]],
    assets: dict[str, dict[str, Any]],
    asset_guid_by_id: dict[str, str],
    prefab_asset_path: str,
    sprite_asset_dir: str,
    stats: dict[str, int],
    prefab_visual_mode: str,
    default_tmp_font: dict[str, Any],
    tmp_font_asset_map: dict[str, str],
) -> dict[str, Any]:
    source = packet.get("source") or {}
    design = packet.get("design") or {}
    node_entries = []
    unity_paths = _source_map_unity_paths(all_nodes)
    for node in all_nodes:
        node_id = str(node.get("id"))
        asset_ref = node.get("asset_ref")
        asset = assets.get(asset_ref) if asset_ref else None
        text_info = _source_map_text_info(node.get("text"), default_tmp_font, tmp_font_asset_map)
        component_file_ids = {
            key: value
            for key, value in (object_ids.get(node_id) or {}).items()
            if value
        }
        entry = {
            "node_id": node_id,
            "parent_id": node.get("parent_id"),
            "children": children.get(node_id) or [],
            "name": node.get("name"),
            "unity_name_hint": node.get("unity_name_hint") or node.get("name"),
            "unity_path": unity_paths.get(node_id),
            "path": node.get("path"),
            "type": node.get("type"),
            "semantic_type": node.get("semantic_type"),
            "semantic_confidence": node.get("semantic_confidence"),
            "semantic_reasons": node.get("semantic_reasons") or [],
            "requires_semantic_review": node.get("requires_semantic_review"),
            "global_rect": node.get("global_rect"),
            "local_rect": node.get("local_rect"),
            "visual_bounds": node.get("visual_bounds"),
            "render_rect": node.get("render_rect"),
            "unity_rect_hint": node.get("unity_rect_hint"),
            "unity_anchor_hint": node.get("unity_anchor_hint"),
            "unity_render_rect_hint": node.get("unity_render_rect_hint"),
            "render_strategy": node.get("render_strategy"),
            "source_semantics": node.get("source_semantics"),
            "unity_ignore": node.get("unity_ignore"),
            "figma_interaction_hint": node.get("figma_interaction_hint"),
            "unity_navigation_hint": node.get("unity_navigation_hint"),
            "reusable_prefab_key": node.get("reusable_prefab_key"),
            "reusable_prefab": node.get("reusable_prefab"),
            "prefab_variant": node.get("prefab_variant"),
            "style": node.get("style"),
            "text": text_info,
            "source_metadata": node.get("source_metadata"),
            "content_hash": node.get("content_hash"),
            "component_file_ids": component_file_ids,
            "unity_text_hint": node.get("unity_text_hint"),
            "unity_button_hint": node.get("unity_button_hint"),
            "unity_slider_hint": node.get("unity_slider_hint"),
            "unity_toggle_hint": node.get("unity_toggle_hint"),
            "unity_tab_group_hint": node.get("unity_tab_group_hint"),
            "unity_tab_hint": node.get("unity_tab_hint"),
            "unity_radio_group_hint": node.get("unity_radio_group_hint"),
            "unity_radio_hint": node.get("unity_radio_hint"),
            "unity_input_hint": node.get("unity_input_hint"),
            "unity_dropdown_hint": node.get("unity_dropdown_hint"),
            "unity_mask_hint": node.get("unity_mask_hint"),
            "unity_layout_hint": node.get("unity_layout_hint"),
            "unity_layout_element_hint": node.get("unity_layout_element_hint"),
            "unity_scroll_hint": node.get("unity_scroll_hint"),
            "unity_scrollbar_hint": node.get("unity_scrollbar_hint"),
            "figma_interaction_hint": node.get("figma_interaction_hint"),
            "unity_navigation_hint": node.get("unity_navigation_hint"),
            "incremental_update": _node_incremental_update(node, asset),
        }
        visual_suppressed = _suppresses_source_visual(prefab_visual_mode, node)
        if prefab_visual_mode == "flattened_reference_overlay":
            entry["prefab_visual_mode"] = prefab_visual_mode
            entry["visual_suppressed"] = visual_suppressed
        if asset and not visual_suppressed:
            entry["asset"] = {
                "asset_ref": asset_ref,
                "name": asset.get("name"),
                "file_name": asset.get("file_name"),
                "usage": asset.get("usage"),
                "unity_guid": asset_guid_by_id.get(asset_ref),
                "suggested_unity_path": asset.get("suggested_unity_path"),
                "deduped_unity_asset_path": asset.get("deduped_unity_asset_path"),
                "duplicate_of": asset.get("duplicate_of"),
                "content_hash": asset.get("content_hash") or asset.get("file_hash"),
                "source_image_ref": asset.get("source_image_ref"),
                "image_fill": asset.get("image_fill"),
                "logical_size": asset.get("logical_size"),
                "nine_slice_hint": asset.get("nine_slice_hint"),
            }
        elif asset and visual_suppressed:
            entry["source_asset"] = {
                "asset_ref": asset_ref,
                "name": asset.get("name"),
                "file_name": asset.get("file_name"),
                "usage": asset.get("usage"),
                "deduped_unity_asset_path": asset.get("deduped_unity_asset_path"),
                "duplicate_of": asset.get("duplicate_of"),
                "content_hash": asset.get("content_hash") or asset.get("file_hash"),
                "source_image_ref": asset.get("source_image_ref"),
                "image_fill": asset.get("image_fill"),
                "logical_size": asset.get("logical_size"),
                "nine_slice_hint": asset.get("nine_slice_hint"),
                "visual_suppressed": True,
            }
        node_entries.append(_drop_none(entry))

    return {
        "schema": "design-to-unity.prefab-source-map",
        "schema_version": 1,
        "packet_id": packet.get("packet_id"),
        "source": source,
        "design": design,
        "prefab_visual_mode": prefab_visual_mode,
        "visual_strategy": _visual_strategy_source_map(packet, prefab_visual_mode),
        "prefab_asset_path": prefab_asset_path,
        "sprite_asset_dir": sprite_asset_dir,
        "stats": stats,
        "reusable_prefabs": packet.get("reusable_prefabs") or [],
        "reusable_prefab_summary": packet.get("reusable_prefab_summary") or {},
        "prefab_variant_groups": packet.get("prefab_variant_groups") or [],
        "prefab_variant_summary": packet.get("prefab_variant_summary") or {},
        "nodes": node_entries,
        "assets": [
            _drop_none(
                {
                    "asset_ref": asset_id,
                    "name": asset.get("name"),
                    "file_name": asset.get("file_name"),
                    "usage": asset.get("usage"),
                    "unity_guid": asset_guid_by_id.get(asset_id),
                    "suggested_unity_path": asset.get("suggested_unity_path"),
                    "deduped_unity_asset_path": asset.get("deduped_unity_asset_path"),
                    "duplicate_of": asset.get("duplicate_of"),
                    "content_hash": asset.get("content_hash") or asset.get("file_hash"),
                    "source_image_ref": asset.get("source_image_ref"),
                    "image_fill": asset.get("image_fill"),
                    "source_node_id": asset.get("source_node_id"),
                    "logical_size": asset.get("logical_size"),
                    "nine_slice_hint": asset.get("nine_slice_hint"),
                }
            )
            for asset_id, asset in sorted(assets.items())
        ],
        "unity_import_manifest": _unity_import_manifest(
            design=design,
            prefab_asset_path=prefab_asset_path,
            sprite_asset_dir=sprite_asset_dir,
            stats=stats,
            prefab_visual_mode=prefab_visual_mode,
        ),
        "update_policy_hint": _update_policy_hint(),
        "incremental_update_plan": _incremental_update_plan(packet, stats),
        "usage_notes": [
            "Use node_id/content_hash to diff regenerated prefab snapshots.",
            "Use reusable_prefabs to save repeated definition nodes once and instantiate later nodes with rect/text overrides.",
            "Use component_file_ids when inspecting direct YAML output; Unity may rewrite fileIDs after editor-side prefab edits.",
            "Use source_metadata.source_path to map GameObjects back to PSD/Lanhu layers.",
            "In flattened_reference_overlay mode, the visible design is the reference overlay; source nodes are retained for structure, hit areas, text data, and future edits.",
        ],
    }


def _source_map_unity_paths(all_nodes: list[dict[str, Any]]) -> dict[str, str]:
    nodes_by_id = {str(node.get("id")): node for node in all_nodes}

    def object_name(node: dict[str, Any]) -> str:
        return _safe_name(str(node.get("unity_name_hint") or node.get("name") or node.get("id") or "Node"))

    siblings_by_parent: dict[str | None, list[str]] = {}
    base_name_by_id: dict[str, str] = {}
    segment_by_id: dict[str, str] = {}
    for node in all_nodes:
        node_id = str(node.get("id"))
        parent_id = str(node.get("parent_id")) if node.get("parent_id") is not None else None
        siblings_by_parent.setdefault(parent_id, []).append(node_id)
        base_name_by_id[node_id] = object_name(node)

    for siblings in siblings_by_parent.values():
        totals: dict[str, int] = {}
        seen: dict[str, int] = {}
        for node_id in siblings:
            totals[base_name_by_id[node_id]] = totals.get(base_name_by_id[node_id], 0) + 1
        for node_id in siblings:
            base_name = base_name_by_id[node_id]
            seen[base_name] = seen.get(base_name, 0) + 1
            segment_by_id[node_id] = f"{base_name}[{seen[base_name]}]" if totals[base_name] > 1 else base_name
    cache: dict[str, str] = {}

    def path_for(node_id: str) -> str:
        if node_id in cache:
            return cache[node_id]
        node = nodes_by_id.get(node_id) or {}
        name = segment_by_id.get(node_id) or object_name(node)
        parent_id = node.get("parent_id")
        if parent_id and str(parent_id) in nodes_by_id:
            value = f"{path_for(str(parent_id))}/{name}"
        else:
            value = name
        cache[node_id] = value
        return value

    return {node_id: path_for(node_id) for node_id in nodes_by_id}


def _source_map_text_info(text: Any, default_tmp_font: dict[str, Any], tmp_font_asset_map: dict[str, str]) -> dict[str, Any] | None:
    if not isinstance(text, dict):
        return None
    result = dict(text)
    resolved_font = _resolve_tmp_font_for_text(result, default_tmp_font, tmp_font_asset_map)
    if resolved_font.get("guid"):
        result["tmp_font_asset_guid"] = resolved_font.get("guid")
        result["tmp_font_material_file_id"] = resolved_font.get("material_file_id")
        result.setdefault("font_hint", {})
        if isinstance(result["font_hint"], dict):
            result["font_hint"]["tmp_font_asset_guid"] = resolved_font.get("guid")
            result["font_hint"]["tmp_font_material_file_id"] = resolved_font.get("material_file_id")
    return result


def _incremental_update_plan(packet: dict[str, Any], stats: dict[str, int]) -> dict[str, Any]:
    source = packet.get("source") or {}
    return {
        "status": "planned",
        "source_provider": source.get("provider"),
        "identity_keys": [
            "node_id",
            "unity_path",
            "source_metadata.source_node_id",
            "source_metadata.figma_node_id",
            "source_metadata.component_id",
            "source_metadata.source_path",
            "reusable_prefab_key",
            "asset.content_hash",
        ],
        "operations": [
            {
                "id": "match_existing_nodes",
                "description": "Match regenerated source-map nodes against existing Unity objects before applying field updates.",
            },
            {
                "id": "update_owned_fields",
                "description": "Overwrite only design-owned RectTransform, Graphic, TMP, and known UI component fields.",
            },
            {
                "id": "reuse_unchanged_assets",
                "description": "Skip sprite import when content_hash and suggested Unity path are unchanged.",
            },
            {
                "id": "refresh_reusable_definitions",
                "description": "Rebuild reusable prefab definitions only when their definition node or asset hashes change.",
            },
            {
                "id": "refresh_prefab_variants",
                "description": "Create or refresh prefab variant assets when Figma variant signatures change.",
            },
            {
                "id": "preserve_user_owned_fields",
                "description": "Preserve user scripts, event bindings, animations, runtime data bindings, and user-owned children by default.",
            },
        ],
        "node_update_fields": _update_policy_hint()["safe_to_overwrite"],
        "preserve_by_default": _update_policy_hint()["preserve_by_default"],
        "reusable_prefab_update": {
            "definition_key": "reusable_prefab_key",
            "definition_node_id": "reusable_prefabs[].definition_node_id",
            "instance_node_ids": "reusable_prefabs[].instance_node_ids",
            "override_fields": ["rect", "text.content", "asset_ref", "figma.variant", "source_semantics"],
        },
        "prefab_variant_update": {
            "group_key": "prefab_variant_groups[].key",
            "base_prefab_asset_path": "prefab_variant_groups[].base_prefab_asset_path",
            "variant_prefab_asset_path": "prefab_variant_groups[].variants[].suggested_prefab_asset_path",
            "identity_keys": ["prefab_variant.variant_key", "source_metadata.variant_properties", "reusable_prefab_key"],
        },
        "asset_update": {
            "identity_keys": ["content_hash", "source_node_id", "source_image_ref", "suggested_unity_path"],
            "skip_when_unchanged": True,
            "dedupe_fields": ["duplicate_of", "deduped_unity_asset_path"],
        },
        "delete_policy": {
            "default": "mark_pending_delete",
            "reason": "Avoid deleting Unity user edits until the importer has an explicit confirmation or ownership marker.",
        },
        "expected_scope": {
            "node_count": stats.get("node_count", 0),
            "asset_count": stats.get("asset_count", 0),
            "reusable_prefab_count": stats.get("reusable_prefab_count", 0),
            "prefab_variant_group_count": stats.get("prefab_variant_group_count", 0),
            "prefab_variant_count": stats.get("prefab_variant_count", 0),
        },
    }


def _node_incremental_update(node: dict[str, Any], asset: dict[str, Any] | None) -> dict[str, Any]:
    source_metadata = node.get("source_metadata") or {}
    identity_keys = ["node_id", "unity_path"]
    if source_metadata.get("source_node_id"):
        identity_keys.append("source_metadata.source_node_id")
    if source_metadata.get("figma_node_id"):
        identity_keys.append("source_metadata.figma_node_id")
    if source_metadata.get("component_id"):
        identity_keys.append("source_metadata.component_id")
    if source_metadata.get("source_path"):
        identity_keys.append("source_metadata.source_path")
    if node.get("reusable_prefab_key"):
        identity_keys.append("reusable_prefab_key")
    if asset and (asset.get("content_hash") or asset.get("file_hash")):
        identity_keys.append("asset.content_hash")

    owned_fields = [
        "RectTransform.anchoredPosition",
        "RectTransform.sizeDelta",
        "RectTransform.anchorMin",
        "RectTransform.anchorMax",
        "RectTransform.pivot",
    ]
    node_type = node.get("type")
    semantic_type = node.get("semantic_type")
    if asset:
        owned_fields.extend(["Image.sprite", "Image.color", "Image.raycastTarget"])
    if node_type == "text" or node.get("text"):
        owned_fields.extend(
            [
                "TextMeshProUGUI.text",
                "TextMeshProUGUI.fontSize",
                "TextMeshProUGUI.color",
                "TextMeshProUGUI.font",
                "TextMeshProUGUI.fontStyle",
                "TextMeshProUGUI.richText",
                "TextMeshProUGUI.lineSpacing",
                "TextMeshProUGUI.characterSpacing",
            ]
        )
    if semantic_type == "button_candidate":
        owned_fields.append("Button.targetGraphic")
    if semantic_type in {"slider_candidate", "progress_candidate"}:
        owned_fields.extend(["Slider.fillRect", "Slider.handleRect", "Slider.value"])
    if semantic_type in {"toggle_candidate", "tab_candidate", "radio_candidate"}:
        owned_fields.extend(["Toggle.targetGraphic", "Toggle.graphic", "Toggle.isOn", "Toggle.group"])
    if semantic_type == "scroll_area_candidate":
        owned_fields.extend(["ScrollRect.content", "ScrollRect.viewport", "ScrollRect.horizontalScrollbar", "ScrollRect.verticalScrollbar"])

    return {
        "stable_id": node.get("id"),
        "source_node_id": source_metadata.get("source_node_id") or source_metadata.get("figma_node_id"),
        "identity_keys": identity_keys,
        "ownership": "owned_by_design",
        "owned_fields": sorted(set(owned_fields)),
        "preserve_fields": _update_policy_hint()["preserve_by_default"],
        "delete_policy": "mark_pending_delete",
    }


def _visual_strategy_source_map(packet: dict[str, Any], prefab_visual_mode: str) -> dict[str, Any]:
    design = packet.get("design") or {}
    if prefab_visual_mode != "flattened_reference_overlay":
        return {"mode": "layered", "visible_baseline": "source_layers"}
    return {
        "mode": prefab_visual_mode,
        "visible_baseline": "design_reference",
        "reference_asset_ref": design.get("reference_asset_ref"),
        "source_nodes_visual_suppressed": True,
        "interactive_overlays": ["Button", "Slider", "Toggle", "ToggleGroup", "TMP_InputField", "TMP_Dropdown", "ScrollRect", "Scrollbar", "TextMeshProUGUI metadata"],
    }


def _unity_import_manifest(
    design: dict[str, Any],
    prefab_asset_path: str,
    sprite_asset_dir: str,
    stats: dict[str, int],
    prefab_visual_mode: str,
) -> dict[str, Any]:
    return {
        "target": "unity",
        "ui_system": "UGUI",
        "text_system": "TextMeshPro",
        "prefab_visual_mode": prefab_visual_mode,
        "prefab_asset_path": prefab_asset_path,
        "sprite_asset_dir": sprite_asset_dir,
        "view_root": {
            "name": Path(prefab_asset_path).stem,
            "size": {
                "width": design.get("width") or 0,
                "height": design.get("height") or 0,
            },
            "anchorMin": [0, 1],
            "anchorMax": [0, 1],
            "pivot": [0, 1],
        },
        "expected_components": {
            "GameObject": stats.get("node_count", 0),
            "RectTransform": stats.get("node_count", 0),
            "Image": stats.get("image_node_count", 0),
            "TextMeshProUGUI": stats.get("tmp_text_node_count", 0),
            "Button": stats.get("button_node_count", 0),
            "Slider": stats.get("slider_node_count", 0),
            "Toggle": stats.get("toggle_node_count", 0),
            "ToggleGroup": stats.get("toggle_group_node_count", 0),
            "TMP_InputField": stats.get("input_field_node_count", 0),
            "TMP_Dropdown": stats.get("dropdown_node_count", 0),
            "ScrollRect": stats.get("scroll_rect_node_count", 0),
            "Scrollbar": stats.get("scrollbar_node_count", 0),
            "RectMask2D": stats.get("rect_mask_2d_node_count", 0),
            "VerticalLayoutGroup": stats.get("vertical_layout_group_node_count", 0),
            "HorizontalLayoutGroup": stats.get("horizontal_layout_group_node_count", 0),
            "GridLayoutGroup": stats.get("grid_layout_group_node_count", 0),
            "LayoutElement": stats.get("layout_element_node_count", 0),
            "Outline": stats.get("outline_node_count", 0),
            "Shadow": stats.get("shadow_node_count", 0),
            "CanvasGroup": stats.get("canvas_group_node_count", 0),
        },
        "import_gates": [
            {
                "id": "static_prefab_verify",
                "tool": "psd_design_verify_unity_prefab_yaml",
                "required": True,
                "pass_statuses": ["pass", "pass_with_warnings"],
            },
            {
                "id": "unity_import",
                "tool": "Unity MCP or Unity Editor refresh",
                "required": True,
                "checks": ["no missing scripts", "source map imports as TextAsset", "sprites import as Sprite"],
            },
            {
                "id": "unity_prefab_screenshot",
                "tool": "DesignToUnityPrefabValidator.CapturePrefabFromCommandLine or Unity MCP screenshot capture",
                "required": False,
                "recommended_for": ["visual_diff", "psd", "photoshop_export"],
            },
            {
                "id": "visual_diff",
                "tool": "psd_design_compare_unity_screenshot",
                "required": False,
                "recommended_for": ["psd", "photoshop_export", "complex PSD features"],
            },
        ],
        "recommended_sequence": [
            "Refresh the Unity project so generated sprite meta files and prefab YAML import.",
            "Open the generated prefab and check expected component counts.",
            "Inspect source map nodes when rebinding Slider, ScrollRect, or custom scripts.",
            "Capture a prefab screenshot with the installed Unity Editor validator or Unity MCP.",
            "Capture a GameView or prefab preview screenshot and compare it with the PSD reference when visual fidelity matters.",
        ],
    }


def _update_policy_hint() -> dict[str, list[str]]:
    return {
        "safe_to_overwrite": [
            "RectTransform.anchoredPosition",
            "RectTransform.sizeDelta",
            "Image.sprite",
            "Image.color",
            "Image.raycastTarget",
            "TextMeshProUGUI.text",
            "TextMeshProUGUI.fontSize",
            "TextMeshProUGUI.color",
            "TextMeshProUGUI.font",
            "TextMeshProUGUI.fontStyle",
            "TextMeshProUGUI.richText",
            "TextMeshProUGUI.lineSpacing",
            "TextMeshProUGUI.characterSpacing",
            "Outline.effectColor",
            "Outline.effectDistance",
            "Shadow.effectColor",
            "Shadow.effectDistance",
            "Button.targetGraphic",
            "Slider.fillRect",
            "Slider.handleRect",
            "Slider.value",
            "Toggle.targetGraphic",
            "Toggle.graphic",
            "Toggle.isOn",
            "Toggle.group",
            "ToggleGroup.allowSwitchOff",
            "TMP_InputField.targetGraphic",
            "TMP_InputField.textComponent",
            "TMP_InputField.placeholder",
            "TMP_InputField.text",
            "ScrollRect.content",
            "ScrollRect.viewport",
            "ScrollRect.horizontalScrollbar",
            "ScrollRect.verticalScrollbar",
            "Scrollbar.handleRect",
            "Scrollbar.value",
            "Scrollbar.size",
            "CanvasGroup.alpha",
        ],
        "preserve_by_default": [
            "custom_scripts",
            "event_bindings",
            "animation",
            "user_added_children",
            "prefab_variant_overrides",
            "localization_bindings",
            "runtime_data_bindings",
        ],
        "identity_keys": [
            "node_id",
            "source_metadata.source_node_id",
            "source_metadata.source_path",
            "content_hash",
        ],
    }


def _game_object_yaml(node: dict[str, Any], ids: dict[str, int | None]) -> list[str]:
    component_lines = [f"  - component: {{fileID: {ids['rect']}}}"]
    if ids.get("canvas"):
        component_lines.append(f"  - component: {{fileID: {ids['canvas']}}}")
    if ids.get("image"):
        component_lines.append(f"  - component: {{fileID: {ids['image']}}}")
    if ids.get("tmp_text"):
        component_lines.append(f"  - component: {{fileID: {ids['tmp_text']}}}")
    if ids.get("button"):
        component_lines.append(f"  - component: {{fileID: {ids['button']}}}")
    if ids.get("slider"):
        component_lines.append(f"  - component: {{fileID: {ids['slider']}}}")
    if ids.get("toggle"):
        component_lines.append(f"  - component: {{fileID: {ids['toggle']}}}")
    if ids.get("toggle_group"):
        component_lines.append(f"  - component: {{fileID: {ids['toggle_group']}}}")
    if ids.get("tmp_input_field"):
        component_lines.append(f"  - component: {{fileID: {ids['tmp_input_field']}}}")
    if ids.get("tmp_dropdown"):
        component_lines.append(f"  - component: {{fileID: {ids['tmp_dropdown']}}}")
    if ids.get("rect_mask_2d"):
        component_lines.append(f"  - component: {{fileID: {ids['rect_mask_2d']}}}")
    if ids.get("vertical_layout_group"):
        component_lines.append(f"  - component: {{fileID: {ids['vertical_layout_group']}}}")
    if ids.get("horizontal_layout_group"):
        component_lines.append(f"  - component: {{fileID: {ids['horizontal_layout_group']}}}")
    if ids.get("grid_layout_group"):
        component_lines.append(f"  - component: {{fileID: {ids['grid_layout_group']}}}")
    if ids.get("layout_element"):
        component_lines.append(f"  - component: {{fileID: {ids['layout_element']}}}")
    if ids.get("scrollbar"):
        component_lines.append(f"  - component: {{fileID: {ids['scrollbar']}}}")
    if ids.get("scroll_rect"):
        component_lines.append(f"  - component: {{fileID: {ids['scroll_rect']}}}")
    if ids.get("outline"):
        component_lines.append(f"  - component: {{fileID: {ids['outline']}}}")
    if ids.get("shadow"):
        component_lines.append(f"  - component: {{fileID: {ids['shadow']}}}")
    if ids.get("canvas_group"):
        component_lines.append(f"  - component: {{fileID: {ids['canvas_group']}}}")
    active = 0 if node.get("semantic_type") == "dropdown_template_candidate" else 1
    return [
        f"--- !u!1 &{ids['go']}",
        "GameObject:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        "  serializedVersion: 6",
        "  m_Component:",
        *component_lines,
        "  m_Layer: 0",
        f"  m_Name: {_yaml_string(str(node.get('unity_name_hint') or node.get('name') or node.get('id')))}",
        "  m_TagString: Untagged",
        "  m_Icon: {fileID: 0}",
        "  m_NavMeshLayer: 0",
        "  m_StaticEditorFlags: 0",
        f"  m_IsActive: {active}",
    ]


def _canvas_group_yaml(node: dict[str, Any], ids: dict[str, int | None]) -> list[str]:
    alpha = _num((node.get("style") or {}).get("opacity"), 1)
    return [
        f"--- !u!225 &{ids['canvas_group']}",
        "CanvasGroup:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        f"  m_Alpha: {alpha}",
        "  m_Interactable: 1",
        "  m_BlocksRaycasts: 1",
        "  m_IgnoreParentGroups: 0",
    ]


def _rect_transform_yaml(node: dict[str, Any], ids: dict[str, int | None], parent_rect: int | None, child_rect_ids: list[int | None]) -> list[str]:
    rect = node.get("local_rect") or {}
    anchor = _rect_transform_anchor_values(node)
    children = " []" if not child_rect_ids else ""
    lines = [
        f"--- !u!224 &{ids['rect']}",
        "RectTransform:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_LocalRotation: {x: 0, y: 0, z: 0, w: 1}",
        "  m_LocalPosition: {x: 0, y: 0, z: 0}",
        "  m_LocalScale: {x: 1, y: 1, z: 1}",
        "  m_ConstrainProportionsScale: 0",
        f"  m_Children:{children}",
    ]
    if child_rect_ids:
        lines.extend([f"  - {{fileID: {child_id}}}" for child_id in child_rect_ids if child_id])
    lines.extend(
        [
            f"  m_Father: {{fileID: {parent_rect or 0}}}",
            "  m_LocalEulerAnglesHint: {x: 0, y: 0, z: 0}",
            f"  m_AnchorMin: {{x: {anchor['anchorMin'][0]}, y: {anchor['anchorMin'][1]}}}",
            f"  m_AnchorMax: {{x: {anchor['anchorMax'][0]}, y: {anchor['anchorMax'][1]}}}",
            f"  m_AnchoredPosition: {{x: {anchor['anchoredPosition'][0]}, y: {anchor['anchoredPosition'][1]}}}",
            f"  m_SizeDelta: {{x: {anchor['sizeDelta'][0]}, y: {anchor['sizeDelta'][1]}}}",
            f"  m_Pivot: {{x: {anchor['pivot'][0]}, y: {anchor['pivot'][1]}}}",
        ]
    )
    return lines


def _rect_transform_anchor_values(node: dict[str, Any]) -> dict[str, list[float]]:
    rect = node.get("local_rect") or {}
    hint = node.get("unity_anchor_hint") if isinstance(node.get("unity_anchor_hint"), dict) else {}
    return {
        "anchorMin": _vec2_hint(hint.get("anchorMin"), [0, 1]),
        "anchorMax": _vec2_hint(hint.get("anchorMax"), [0, 1]),
        "pivot": _vec2_hint(hint.get("pivot"), [0, 1]),
        "anchoredPosition": _vec2_hint(hint.get("anchoredPosition"), [_num(rect.get("x")), -_num(rect.get("y"))]),
        "sizeDelta": _vec2_hint(hint.get("sizeDelta"), [_num(rect.get("width")), _num(rect.get("height"))]),
    }


def _vec2_hint(value: Any, fallback: list[float]) -> list[float]:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return [round(_num(value[0]), 6), round(_num(value[1]), 6)]
    return [round(_num(fallback[0]), 6), round(_num(fallback[1]), 6)]


def _canvas_renderer_yaml(ids: dict[str, int | None]) -> list[str]:
    return [
        f"--- !u!222 &{ids['canvas']}",
        "CanvasRenderer:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_CullTransparentMesh: 1",
    ]


def _image_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    sprite_guid: str | None,
    asset: dict[str, Any],
    raycast_target: bool,
    transparent: bool = False,
) -> list[str]:
    opacity = _num((node.get("style") or {}).get("opacity"), 1)
    alpha = 0 if transparent else opacity
    raycast = 1 if raycast_target else 0
    image_type = 1 if (asset.get("nine_slice_hint") or {}).get("candidate") and (asset.get("nine_slice_hint") or {}).get("border") else 0
    sprite_ref = f"{{fileID: {SPRITE_FILE_ID}, guid: {sprite_guid}, type: 3}}" if sprite_guid else "{fileID: 0}"
    return [
        f"--- !u!114 &{ids['image']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {IMAGE_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.Image",
        "  m_Material: {fileID: 0}",
        f"  m_Color: {{r: 1, g: 1, b: 1, a: {alpha}}}",
        f"  m_RaycastTarget: {raycast}",
        "  m_RaycastPadding: {x: 0, y: 0, z: 0, w: 0}",
        "  m_Maskable: 1",
        "  m_OnCullStateChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
        f"  m_Sprite: {sprite_ref}",
        f"  m_Type: {image_type}",
        "  m_PreserveAspect: 0",
        "  m_FillCenter: 1",
        "  m_FillMethod: 4",
        "  m_FillAmount: 1",
        "  m_FillClockwise: 1",
        "  m_FillOrigin: 0",
        "  m_UseSpriteMesh: 0",
        "  m_PixelsPerUnitMultiplier: 1",
    ]


def _tmp_text_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    tmp_font_guid: str | None,
    tmp_font_material_file_id: int | None,
    raycast_target: bool,
    transparent: bool = False,
) -> list[str]:
    text = node.get("text") or {}
    color = _unity_color(text.get("color") or (node.get("style") or {}).get("fill_color"), fallback=(1, 1, 1, 1))
    if transparent:
        color = (color[0], color[1], color[2], 0)
    font_size = max(1, int(round(_num(text.get("font_size"), 24))))
    font_weight = _tmp_font_weight(text)
    font_style = _tmp_font_style(text)
    horizontal_alignment = _tmp_horizontal_alignment(text.get("align"))
    wrapping = 1 if text.get("wrap") else 0
    line_spacing = _tmp_line_spacing(text, font_size)
    content = _tmp_rich_text_content(text)
    font_asset = f"{{fileID: {TMP_FONT_ASSET_FILE_ID}, guid: {tmp_font_guid}, type: 2}}" if tmp_font_guid else "{fileID: 0}"
    shared_material = (
        f"{{fileID: {tmp_font_material_file_id}, guid: {tmp_font_guid}, type: 2}}"
        if tmp_font_guid and tmp_font_material_file_id
        else "{fileID: 0}"
    )
    raycast = 1 if raycast_target else 0
    return [
        f"--- !u!114 &{ids['tmp_text']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {TMP_TEXT_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: ",
        "  m_Material: {fileID: 0}",
        f"  m_Color: {_color_yaml(color)}",
        f"  m_RaycastTarget: {raycast}",
        "  m_RaycastPadding: {x: 0, y: 0, z: 0, w: 0}",
        "  m_Maskable: 1",
        "  m_OnCullStateChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
        f"  m_text: {_yaml_string(content)}",
        "  m_isRightToLeft: 0",
        f"  m_fontAsset: {font_asset}",
        f"  m_sharedMaterial: {shared_material}",
        "  m_fontSharedMaterials: []",
        "  m_fontMaterial: {fileID: 0}",
        "  m_fontMaterials: []",
        f"  m_fontColor32:\n    serializedVersion: 2\n    rgba: {_rgba32(color)}",
        f"  m_fontColor: {_color_yaml(color)}",
        "  m_enableVertexGradient: 0",
        "  m_colorMode: 3",
        "  m_fontColorGradient:",
        f"    topLeft: {_color_yaml(color)}",
        f"    topRight: {_color_yaml(color)}",
        f"    bottomLeft: {_color_yaml(color)}",
        f"    bottomRight: {_color_yaml(color)}",
        "  m_fontColorGradientPreset: {fileID: 0}",
        "  m_spriteAsset: {fileID: 0}",
        "  m_tintAllSprites: 0",
        "  m_StyleSheet: {fileID: 0}",
        "  m_TextStyleHashCode: -1183493901",
        "  m_overrideHtmlColors: 0",
        f"  m_faceColor:\n    serializedVersion: 2\n    rgba: {_rgba32(color)}",
        f"  m_fontSize: {font_size}",
        f"  m_fontSizeBase: {font_size}",
        f"  m_fontWeight: {font_weight}",
        "  m_enableAutoSizing: 0",
        f"  m_fontSizeMin: {max(1, min(font_size, 8))}",
        f"  m_fontSizeMax: {max(font_size, 72)}",
        f"  m_fontStyle: {font_style}",
        f"  m_HorizontalAlignment: {horizontal_alignment}",
        "  m_VerticalAlignment: 512",
        "  m_textAlignment: 65535",
        f"  m_characterSpacing: {_num(text.get('letter_spacing'), 0)}",
        "  m_wordSpacing: 0",
        f"  m_lineSpacing: {_num(line_spacing, 0)}",
        "  m_lineSpacingMax: 0",
        "  m_paragraphSpacing: 0",
        "  m_charWidthMaxAdj: 0",
        f"  m_TextWrappingMode: {wrapping}",
        "  m_wordWrappingRatios: 0.4",
        "  m_overflowMode: 0",
        "  m_linkedTextComponent: {fileID: 0}",
        "  parentLinkedComponent: {fileID: 0}",
        "  m_enableKerning: 0",
        "  m_ActiveFontFeatures: 6e72656b",
        "  m_enableExtraPadding: 0",
        "  checkPaddingRequired: 0",
        "  m_isRichText: 1",
        "  m_EmojiFallbackSupport: 1",
        "  m_parseCtrlCharacters: 1",
        "  m_isOrthographic: 1",
        "  m_isCullingEnabled: 0",
        "  m_horizontalMapping: 0",
        "  m_verticalMapping: 0",
        "  m_uvLineOffset: 0",
        "  m_geometrySortingOrder: 0",
        "  m_IsTextObjectScaleStatic: 0",
        "  m_VertexBufferAutoSizeReduction: 0",
        "  m_useMaxVisibleDescender: 1",
        "  m_pageToDisplay: 1",
        "  m_margin: {x: 0, y: 0, z: 0, w: 0}",
        "  m_isUsingLegacyAnimationComponent: 0",
        "  m_isVolumetricText: 0",
        "  m_hasFontAssetChanged: 0",
        "  m_baseMaterial: {fileID: 0}",
        "  m_maskOffset: {x: 0, y: 0, z: 0, w: 0}",
    ]


def _outline_yaml(node: dict[str, Any], ids: dict[str, int | None]) -> list[str]:
    outline = (_text_effects(node).get("outline") or {})
    color = _unity_color(outline.get("color"), fallback=(0, 0, 0, 1))
    width_source = outline.get("width") if outline.get("width") is not None else outline.get("size")
    width = max(0.0, _num(width_source, 1))
    return _mesh_effect_yaml(
        ids=ids,
        id_key="outline",
        script_guid=OUTLINE_SCRIPT_GUID,
        class_name="Outline",
        color=color,
        distance={"x": width, "y": -width},
        use_graphic_alpha=outline.get("use_graphic_alpha", True),
    )


def _shadow_yaml(node: dict[str, Any], ids: dict[str, int | None]) -> list[str]:
    shadow = (_text_effects(node).get("shadow") or {})
    color = _unity_color(shadow.get("color"), fallback=(0, 0, 0, 0.5))
    offset = shadow.get("offset") or shadow.get("distance") or {}
    if isinstance(offset, (list, tuple)):
        x = _num(offset[0], 1) if len(offset) > 0 else 1
        y = _num(offset[1], -1) if len(offset) > 1 else -1
    elif isinstance(offset, dict):
        x = _num(offset.get("x"), _num(shadow.get("x"), 1))
        y = _num(offset.get("y"), _num(shadow.get("y"), -1))
    else:
        x = _num(shadow.get("x"), 1)
        y = _num(shadow.get("y"), -1)
    return _mesh_effect_yaml(
        ids=ids,
        id_key="shadow",
        script_guid=SHADOW_SCRIPT_GUID,
        class_name="Shadow",
        color=color,
        distance={"x": x, "y": y},
        use_graphic_alpha=shadow.get("use_graphic_alpha", True),
    )


def _mesh_effect_yaml(
    ids: dict[str, int | None],
    id_key: str,
    script_guid: str,
    class_name: str,
    color: tuple[float, float, float, float],
    distance: dict[str, float],
    use_graphic_alpha: Any,
) -> list[str]:
    return [
        f"--- !u!114 &{ids[id_key]}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {script_guid}, type: 3}}",
        "  m_Name: ",
        f"  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.{class_name}",
        f"  m_EffectColor: {_color_yaml(color)}",
        f"  m_EffectDistance: {{x: {_num(distance.get('x'), 0)}, y: {_num(distance.get('y'), 0)}}}",
        f"  m_UseGraphicAlpha: {_bool_int(use_graphic_alpha)}",
    ]


def _button_yaml(ids: dict[str, int | None], target_graphic: int | None) -> list[str]:
    return [
        f"--- !u!114 &{ids['button']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {BUTTON_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: ",
        *_selectable_yaml(target_graphic),
        "  m_OnClick:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
    ]


def _toggle_group_yaml(node: dict[str, Any], ids: dict[str, int | None]) -> list[str]:
    hint = node.get("unity_tab_group_hint") or node.get("unity_radio_group_hint") or {}
    allow_switch_off = 1 if hint.get("allow_switch_off") else 0
    return [
        f"--- !u!114 &{ids['toggle_group']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {TOGGLE_GROUP_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.ToggleGroup",
        f"  m_AllowSwitchOff: {allow_switch_off}",
    ]


def _toggle_graphic_ref(node: dict[str, Any], object_ids: dict[str, dict[str, int | None]]) -> int:
    hint = node.get("unity_toggle_hint") or {}
    graphic_node_id = str(hint.get("graphic_node_id") or hint.get("checkmark_node_id") or "")
    if graphic_node_id:
        graphic_ids = object_ids.get(graphic_node_id) or {}
        return int(graphic_ids.get("image") or graphic_ids.get("tmp_text") or 0)
    return 0


def _toggle_group_ref(node: dict[str, Any], object_ids: dict[str, dict[str, int | None]]) -> int:
    hint = node.get("unity_tab_hint") or node.get("unity_radio_hint") or {}
    group_id = str(hint.get("group_node_id") or "")
    if not group_id:
        return 0
    return int((object_ids.get(group_id) or {}).get("toggle_group") or 0)


def _toggle_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    target_graphic: int | None,
    graphic: int | None,
    group: int | None = None,
) -> list[str]:
    return [
        f"--- !u!114 &{ids['toggle']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {TOGGLE_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.Toggle",
        *_selectable_yaml(target_graphic),
        "  toggleTransition: 1",
        f"  graphic: {{fileID: {graphic or 0}}}",
        f"  m_Group: {{fileID: {group or 0}}}",
        f"  m_IsOn: {_toggle_value(node)}",
        "  m_OnValueChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
    ]


def _input_field_refs(
    node: dict[str, Any],
    object_ids: dict[str, dict[str, int | None]],
) -> tuple[int | None, int | None]:
    hint = node.get("unity_input_hint") or {}
    text_id = str(hint.get("text_component_node_id") or "")
    placeholder_id = str(hint.get("placeholder_node_id") or "")
    text_component = (object_ids.get(text_id) or {}).get("tmp_text") if text_id else None
    placeholder = (object_ids.get(placeholder_id) or {}).get("tmp_text") if placeholder_id else None
    return text_component or 0, placeholder or 0


def _tmp_input_field_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    target_graphic: int | None,
    text_component: int | None,
    placeholder: int | None,
) -> list[str]:
    hint = node.get("unity_input_hint") or {}
    text = str(hint.get("text") or "")
    line_type = 2 if str(hint.get("line_type") or "").lower() in {"multi_line", "multiline", "multi"} else 0
    return [
        f"--- !u!114 &{ids['tmp_input_field']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {TMP_INPUT_FIELD_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: Unity.TextMeshPro::TMPro.TMP_InputField",
        *_selectable_yaml(target_graphic),
        "  m_TextViewport: {fileID: 0}",
        f"  m_TextComponent: {{fileID: {text_component or 0}}}",
        f"  m_Placeholder: {{fileID: {placeholder or 0}}}",
        "  m_VerticalScrollbar: {fileID: 0}",
        "  m_VerticalScrollbarEventHandler: {fileID: 0}",
        "  m_ScrollSensitivity: 1",
        "  m_ContentType: 0",
        "  m_InputType: 0",
        "  m_AsteriskChar: 42",
        "  m_KeyboardType: 0",
        f"  m_LineType: {line_type}",
        "  m_HideMobileInput: 0",
        "  m_HideSoftKeyboard: 0",
        "  m_CharacterValidation: 0",
        "  m_RegexValue: ",
        "  m_GlobalPointSize: 14",
        "  m_CharacterLimit: 0",
        *_unity_event_yaml("m_OnEndEdit"),
        *_unity_event_yaml("m_OnSubmit"),
        *_unity_event_yaml("m_OnSelect"),
        *_unity_event_yaml("m_OnDeselect"),
        *_unity_event_yaml("m_OnTextSelection"),
        *_unity_event_yaml("m_OnEndTextSelection"),
        *_unity_event_yaml("m_OnValueChanged"),
        *_unity_event_yaml("m_OnTouchScreenKeyboardStatusChanged"),
        "  m_OnValidateInput: {fileID: 0}",
        "  m_CaretColor: {r: 0.19607843, g: 0.19607843, b: 0.19607843, a: 1}",
        "  m_CustomCaretColor: 0",
        "  m_SelectionColor: {r: 0.65882355, g: 0.80784315, b: 1, a: 0.7529412}",
        f"  m_Text: {_yaml_string(text)}",
        "  m_CaretBlinkRate: 0.85",
        "  m_CaretWidth: 1",
        "  m_ReadOnly: 0",
        "  m_RichText: 1",
    ]


def _dropdown_refs(
    node: dict[str, Any],
    object_ids: dict[str, dict[str, int | None]],
) -> tuple[int | None, int | None, int | None]:
    hint = node.get("unity_dropdown_hint") or {}
    template_id = str(hint.get("template_node_id") or "")
    caption_id = str(hint.get("caption_text_node_id") or "")
    item_id = str(hint.get("item_text_node_id") or "")
    template_rect = (object_ids.get(template_id) or {}).get("rect") if template_id else None
    caption_text = (object_ids.get(caption_id) or {}).get("tmp_text") if caption_id else None
    item_text = (object_ids.get(item_id) or {}).get("tmp_text") if item_id else None
    return template_rect or 0, caption_text or 0, item_text or 0


def _tmp_dropdown_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    target_graphic: int | None,
    template_rect: int | None,
    caption_text: int | None,
    item_text: int | None,
) -> list[str]:
    hint = node.get("unity_dropdown_hint") or {}
    options = _dropdown_options_yaml_lines(hint.get("options") or [])
    value = _dropdown_value(hint.get("value"), len(options))
    return [
        f"--- !u!114 &{ids['tmp_dropdown']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {TMP_DROPDOWN_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: Unity.TextMeshPro::TMPro.TMP_Dropdown",
        *_selectable_yaml(target_graphic),
        f"  m_Template: {{fileID: {template_rect or 0}}}",
        f"  m_CaptionText: {{fileID: {caption_text or 0}}}",
        "  m_CaptionImage: {fileID: 0}",
        "  m_Placeholder: {fileID: 0}",
        f"  m_ItemText: {{fileID: {item_text or 0}}}",
        "  m_ItemImage: {fileID: 0}",
        f"  m_Value: {value}",
        "  m_MultiSelect: 0",
        "  m_Options:",
        "    m_Options:",
        *options,
        "  m_OnValueChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
        "  m_AlphaFadeSpeed: 0.15",
    ]


def _dropdown_options_yaml_lines(raw_options: list[Any]) -> list[str]:
    options: list[str] = []
    for option in raw_options:
        text = str(option or "").strip()
        if text and text not in options:
            options.append(text)
    if not options:
        options = ["Option"]
    lines: list[str] = []
    for text in options:
        lines.extend(
            [
                f"    - m_Text: {_yaml_string(text)}",
                "      m_Image: {fileID: 0}",
                "      m_Color: {r: 1, g: 1, b: 1, a: 1}",
            ]
        )
    return lines


def _dropdown_value(value: Any, option_line_count: int) -> int:
    option_count = max(1, option_line_count // 3)
    try:
        return max(0, min(option_count - 1, int(value or 0)))
    except (TypeError, ValueError):
        return 0


def _unity_event_yaml(name: str) -> list[str]:
    return [
        f"  {name}:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
    ]


def _should_add_slider_component(node: dict[str, Any], add_slider_components: bool) -> bool:
    if not add_slider_components:
        return False
    semantic_type = node.get("semantic_type")
    if semantic_type not in {"progress_candidate", "slider_candidate"}:
        return False
    hint = node.get("unity_slider_hint") or {}
    if not hint.get("can_add_slider") or hint.get("requires_review"):
        return False
    if not hint.get("fill_node_id"):
        return False
    if semantic_type == "slider_candidate" and not hint.get("handle_node_id"):
        return False
    return True


def _should_add_scrollbar_component(node: dict[str, Any], add_scroll_components: bool) -> bool:
    if not add_scroll_components:
        return False
    if node.get("semantic_type") != "scrollbar_candidate":
        return False
    hint = node.get("unity_scrollbar_hint") or {}
    return bool(hint.get("can_add_scrollbar") and hint.get("handle_node_id"))


def _should_add_mask_component(node: dict[str, Any]) -> bool:
    if node.get("semantic_type") == "mask_candidate" or node.get("type") == "mask":
        hint = node.get("unity_mask_hint") or {}
        return bool(hint.get("can_add_rect_mask_2d", True) and not hint.get("requires_review"))
    return False


def _layout_component(node: dict[str, Any], add_layout_components: bool) -> str | None:
    if not add_layout_components:
        return None
    hint = node.get("unity_layout_hint") or {}
    if not hint.get("can_add_layout_group") or hint.get("requires_review"):
        return None
    component = str(hint.get("component") or "")
    if component in {"VerticalLayoutGroup", "HorizontalLayoutGroup", "GridLayoutGroup"}:
        return component
    return None


def _should_add_layout_element(node: dict[str, Any], add_layout_components: bool) -> bool:
    if not add_layout_components:
        return False
    hint = node.get("unity_layout_element_hint") or {}
    return bool(hint.get("can_add_layout_element") and not hint.get("requires_review"))


def _slider_refs(
    node: dict[str, Any],
    object_ids: dict[str, dict[str, int | None]],
) -> tuple[int | None, int | None]:
    hint = node.get("unity_slider_hint") or {}
    fill_id = str(hint.get("fill_node_id") or "")
    handle_id = str(hint.get("handle_node_id") or "")
    fill_rect = (object_ids.get(fill_id) or {}).get("rect") if fill_id else None
    handle_rect = (object_ids.get(handle_id) or {}).get("rect") if handle_id else None
    return fill_rect or 0, handle_rect or 0


def _slider_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    target_graphic: int | None,
    fill_rect: int | None,
    handle_rect: int | None,
    interactable: bool,
) -> list[str]:
    return [
        f"--- !u!114 &{ids['slider']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {SLIDER_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.Slider",
        *_selectable_yaml(target_graphic, interactable=interactable),
        f"  m_FillRect: {{fileID: {fill_rect or 0}}}",
        f"  m_HandleRect: {{fileID: {handle_rect or 0}}}",
        "  m_Direction: 0",
        "  m_MinValue: 0",
        "  m_MaxValue: 1",
        "  m_WholeNumbers: 0",
        f"  m_Value: {_slider_value(node)}",
        "  m_OnValueChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
    ]


def _scrollbar_handle_ref(
    node: dict[str, Any],
    object_ids: dict[str, dict[str, int | None]],
) -> int:
    hint = node.get("unity_scrollbar_hint") or {}
    handle_id = str(hint.get("handle_node_id") or "")
    return int((object_ids.get(handle_id) or {}).get("rect") or 0) if handle_id else 0


def _scrollbar_component_ref(
    node_id: str | None,
    object_ids: dict[str, dict[str, int | None]],
) -> int:
    if not node_id:
        return 0
    return int((object_ids.get(str(node_id)) or {}).get("scrollbar") or 0)


def _scroll_refs(
    node: dict[str, Any],
    ids: dict[str, int | None],
    object_ids: dict[str, dict[str, int | None]],
) -> tuple[int | None, int | None, int, int]:
    hint = node.get("unity_scroll_hint") or {}
    content_id = str(hint.get("content_node_id") or "")
    viewport_id = str(hint.get("viewport_node_id") or node.get("id") or "")
    content_rect = (object_ids.get(content_id) or {}).get("rect") if content_id else None
    viewport_rect = (object_ids.get(viewport_id) or {}).get("rect") if viewport_id else None
    horizontal_scrollbar = _scrollbar_component_ref(hint.get("horizontal_scrollbar_node_id"), object_ids)
    vertical_scrollbar = _scrollbar_component_ref(hint.get("vertical_scrollbar_node_id"), object_ids)
    return content_rect or 0, viewport_rect or ids.get("rect") or 0, horizontal_scrollbar, vertical_scrollbar


def _scrollbar_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    target_graphic: int | None,
    handle_rect: int | None,
) -> list[str]:
    hint = node.get("unity_scrollbar_hint") or {}
    direction = str(hint.get("direction") or "vertical").lower()
    direction_value = 3 if direction == "vertical" else 0
    value = _clamped_float(hint.get("value"), default=0)
    size = _clamped_float(hint.get("size"), default=0.2)
    return [
        f"--- !u!114 &{ids['scrollbar']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {SCROLLBAR_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.Scrollbar",
        *_selectable_yaml(target_graphic),
        f"  m_HandleRect: {{fileID: {handle_rect or 0}}}",
        f"  m_Direction: {direction_value}",
        f"  m_Value: {value}",
        f"  m_Size: {size}",
        "  m_NumberOfSteps: 0",
        "  m_OnValueChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
    ]


def _scroll_rect_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    content_rect: int | None,
    viewport_rect: int | None,
    horizontal_scrollbar: int | None,
    vertical_scrollbar: int | None,
) -> list[str]:
    direction = str((node.get("unity_scroll_hint") or {}).get("direction") or "vertical").lower()
    horizontal = 1 if direction in {"horizontal", "grid", "both"} else 0
    vertical = 1 if direction in {"vertical", "grid", "both"} else 0
    if not horizontal and not vertical:
        vertical = 1
    return [
        f"--- !u!114 &{ids['scroll_rect']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {SCROLL_RECT_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: ",
        f"  m_Content: {{fileID: {content_rect or 0}}}",
        f"  m_Horizontal: {horizontal}",
        f"  m_Vertical: {vertical}",
        "  m_MovementType: 1",
        "  m_Elasticity: 0.1",
        "  m_Inertia: 1",
        "  m_DecelerationRate: 0.135",
        "  m_ScrollSensitivity: 1",
        f"  m_Viewport: {{fileID: {viewport_rect or 0}}}",
        f"  m_HorizontalScrollbar: {{fileID: {horizontal_scrollbar or 0}}}",
        f"  m_VerticalScrollbar: {{fileID: {vertical_scrollbar or 0}}}",
        "  m_HorizontalScrollbarVisibility: 0",
        "  m_VerticalScrollbarVisibility: 0",
        "  m_HorizontalScrollbarSpacing: 0",
        "  m_VerticalScrollbarSpacing: 0",
        "  m_OnValueChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
    ]


def _rect_mask_2d_yaml(ids: dict[str, int | None]) -> list[str]:
    return [
        f"--- !u!114 &{ids['rect_mask_2d']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {RECT_MASK_2D_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: ",
        "  m_Padding: {x: 0, y: 0, z: 0, w: 0}",
        "  m_Softness: {x: 0, y: 0}",
    ]


def _horizontal_or_vertical_layout_group_yaml(
    node: dict[str, Any],
    ids: dict[str, int | None],
    id_key: str,
    script_guid: str,
    class_name: str,
) -> list[str]:
    hint = node.get("unity_layout_hint") or {}
    padding = _layout_padding_from_hint(hint)
    spacing = _num((hint.get("spacing") or {}).get("y" if class_name == "VerticalLayoutGroup" else "x"), 0)
    child_alignment = _layout_child_alignment_enum(hint)
    return [
        f"--- !u!114 &{ids[id_key]}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {script_guid}, type: 3}}",
        "  m_Name: ",
        f"  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.{class_name}",
        f"  m_Padding: {{m_Left: {padding['left']}, m_Right: {padding['right']}, m_Top: {padding['top']}, m_Bottom: {padding['bottom']}}}",
        f"  m_ChildAlignment: {child_alignment}",
        f"  m_Spacing: {_num(spacing, 0)}",
        f"  m_ChildForceExpandWidth: {_bool_int(hint.get('child_force_expand_width'))}",
        f"  m_ChildForceExpandHeight: {_bool_int(hint.get('child_force_expand_height'))}",
        f"  m_ChildControlWidth: {_bool_int(hint.get('child_control_width'))}",
        f"  m_ChildControlHeight: {_bool_int(hint.get('child_control_height'))}",
        "  m_ChildScaleWidth: 0",
        "  m_ChildScaleHeight: 0",
        "  m_ReverseArrangement: 0",
    ]


def _grid_layout_group_yaml(node: dict[str, Any], ids: dict[str, int | None]) -> list[str]:
    hint = node.get("unity_layout_hint") or {}
    padding = _layout_padding_from_hint(hint)
    cell_size = hint.get("cell_size") or {}
    spacing = hint.get("spacing") or {}
    child_alignment = _layout_child_alignment_enum(hint)
    constraint = 1 if str(hint.get("constraint") or "") == "fixed_column_count" else 0
    constraint_count = max(1, int(_num(hint.get("constraint_count"), 1)))
    return [
        f"--- !u!114 &{ids['grid_layout_group']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {GRID_LAYOUT_GROUP_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.GridLayoutGroup",
        f"  m_Padding: {{m_Left: {padding['left']}, m_Right: {padding['right']}, m_Top: {padding['top']}, m_Bottom: {padding['bottom']}}}",
        f"  m_ChildAlignment: {child_alignment}",
        "  m_StartCorner: 0",
        "  m_StartAxis: 0",
        f"  m_CellSize: {{x: {_num(cell_size.get('width'), 100)}, y: {_num(cell_size.get('height'), 100)}}}",
        f"  m_Spacing: {{x: {_num(spacing.get('x'), 0)}, y: {_num(spacing.get('y'), 0)}}}",
        f"  m_Constraint: {constraint}",
        f"  m_ConstraintCount: {constraint_count}",
    ]


def _layout_element_yaml(node: dict[str, Any], ids: dict[str, int | None]) -> list[str]:
    hint = node.get("unity_layout_element_hint") or {}
    return [
        f"--- !u!114 &{ids['layout_element']}",
        "MonoBehaviour:",
        "  m_ObjectHideFlags: 0",
        "  m_CorrespondingSourceObject: {fileID: 0}",
        "  m_PrefabInstance: {fileID: 0}",
        "  m_PrefabAsset: {fileID: 0}",
        f"  m_GameObject: {{fileID: {ids['go']}}}",
        "  m_Enabled: 1",
        "  m_EditorHideFlags: 0",
        f"  m_Script: {{fileID: 11500000, guid: {LAYOUT_ELEMENT_SCRIPT_GUID}, type: 3}}",
        "  m_Name: ",
        "  m_EditorClassIdentifier: UnityEngine.UI::UnityEngine.UI.LayoutElement",
        f"  m_IgnoreLayout: {_bool_int(hint.get('ignore_layout'))}",
        f"  m_MinWidth: {_layout_float(hint.get('min_width'))}",
        f"  m_MinHeight: {_layout_float(hint.get('min_height'))}",
        f"  m_PreferredWidth: {_layout_float(hint.get('preferred_width'))}",
        f"  m_PreferredHeight: {_layout_float(hint.get('preferred_height'))}",
        f"  m_FlexibleWidth: {_layout_float(hint.get('flexible_width'))}",
        f"  m_FlexibleHeight: {_layout_float(hint.get('flexible_height'))}",
        f"  m_LayoutPriority: {max(1, int(_num(hint.get('layout_priority'), 1)))}",
    ]


def _layout_padding_from_hint(hint: dict[str, Any]) -> dict[str, int]:
    raw = hint.get("padding") or {}
    return {
        "left": int(round(_num(raw.get("left"), 0))),
        "right": int(round(_num(raw.get("right"), 0))),
        "top": int(round(_num(raw.get("top"), 0))),
        "bottom": int(round(_num(raw.get("bottom"), 0))),
    }


def _layout_child_alignment_enum(hint: dict[str, Any]) -> int:
    raw = hint.get("child_alignment_enum")
    if raw is not None:
        return max(0, min(8, int(_num(raw, 0))))
    mapping = {
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
    return mapping.get(str(hint.get("child_alignment") or ""), 0)


def _bool_int(value: Any) -> int:
    return 1 if bool(value) else 0


def _layout_float(value: Any) -> float:
    return round(_num(value, -1), 6)


def _selectable_yaml(target_graphic: int | None, interactable: bool = True) -> list[str]:
    target = target_graphic or 0
    return [
        "  m_Navigation:",
        "    m_Mode: 3",
        "    m_WrapAround: 0",
        "    m_SelectOnUp: {fileID: 0}",
        "    m_SelectOnDown: {fileID: 0}",
        "    m_SelectOnLeft: {fileID: 0}",
        "    m_SelectOnRight: {fileID: 0}",
        "  m_Transition: 1",
        "  m_Colors:",
        "    m_NormalColor: {r: 1, g: 1, b: 1, a: 1}",
        "    m_HighlightedColor: {r: 0.9607843, g: 0.9607843, b: 0.9607843, a: 1}",
        "    m_PressedColor: {r: 0.78431374, g: 0.78431374, b: 0.78431374, a: 1}",
        "    m_SelectedColor: {r: 0.9607843, g: 0.9607843, b: 0.9607843, a: 1}",
        "    m_DisabledColor: {r: 0.78431374, g: 0.78431374, b: 0.78431374, a: 0.5019608}",
        "    m_ColorMultiplier: 1",
        "    m_FadeDuration: 0.1",
        "  m_SpriteState:",
        "    m_HighlightedSprite: {fileID: 0}",
        "    m_PressedSprite: {fileID: 0}",
        "    m_SelectedSprite: {fileID: 0}",
        "    m_DisabledSprite: {fileID: 0}",
        "  m_AnimationTriggers:",
        "    m_NormalTrigger: Normal",
        "    m_HighlightedTrigger: Highlighted",
        "    m_PressedTrigger: Pressed",
        "    m_SelectedTrigger: Selected",
        "    m_DisabledTrigger: Disabled",
        f"  m_Interactable: {1 if interactable else 0}",
        f"  m_TargetGraphic: {{fileID: {target}}}",
    ]


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
        children.sort(key=lambda item: item.get("z_index") or 0, reverse=reverse_siblings)
        for child in children:
            if _is_ignored_node(child):
                continue
            nodes.append(child)
            walk_children(child, child.get("id"))

    for root in packet.get("nodes") or []:
        walk_children(root, root.get("id"))
    return nodes


def _is_ignored_node(node: dict[str, Any]) -> bool:
    if node.get("semantic_type") == "ignored_by_designer":
        return True
    if (node.get("unity_ignore") or {}).get("enabled"):
        return True
    metadata = node.get("source_metadata") if isinstance(node.get("source_metadata"), dict) else {}
    tags = metadata.get("manual_tags") if metadata else None
    if isinstance(tags, str):
        values = re.split(r"[,\s]+", tags)
    elif isinstance(tags, list):
        values = tags
    else:
        values = []
    return any(str(tag).strip().lower().lstrip("@#") == "ignore" for tag in values)


def _file_id(packet_id: str, node_id: str, kind: str, used: set[int]) -> int:
    seed = f"{packet_id}:{node_id}:{kind}"
    value = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:15], 16)
    value = max(value, 1)
    while value in used:
        value += 1
    used.add(value)
    return value


def _guid_for_asset(asset_id: str, asset_path: str) -> str:
    return hashlib.md5(f"design-to-unity:{asset_id}:{asset_path}".encode("utf-8")).hexdigest()


def _new_guid() -> str:
    return uuid.uuid4().hex


def _read_meta_guid(meta_path: Path) -> str | None:
    if not meta_path.exists():
        return None
    match = re.search(r"^guid:\s*([0-9a-fA-F]{32})\s*$", meta_path.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
    return match.group(1) if match else None


def _resolve_tmp_font(project_root: Path, explicit_guid: str | None) -> dict[str, Any]:
    if explicit_guid:
        match = re.fullmatch(r"[0-9a-fA-F]{32}", explicit_guid.strip())
        if not match:
            raise ValueError("tmp_font_asset_guid must be a 32-character Unity asset guid.")
        return {"guid": explicit_guid.strip().lower(), "material_file_id": None}

    for search_root in (project_root / "Assets", project_root / "Library" / "PackageCache"):
        if not search_root.exists():
            continue
        meta_paths = sorted(search_root.rglob("*.asset.meta"), key=lambda item: _tmp_font_priority(item))
        for meta_path in meta_paths:
            if "sdf" not in meta_path.name.lower() and "font" not in str(meta_path).lower():
                continue
            guid = _read_meta_guid(meta_path)
            if guid:
                return {"guid": guid, "material_file_id": _tmp_font_material_file_id(meta_path)}
    return {"guid": DEFAULT_TMP_FONT_ASSET_GUID, "material_file_id": None}


def _normalize_tmp_font_asset_map(value: dict[str, str] | str | None) -> dict[str, str]:
    if value is None:
        return {}
    raw = value
    if isinstance(value, str):
        if not value.strip():
            return {}
        raw = json.loads(value)
    if not isinstance(raw, dict):
        raise ValueError("tmp_font_asset_map must be a dict or a JSON object string.")
    if isinstance(raw.get("figma_font_to_tmp"), dict):
        raw = raw["figma_font_to_tmp"]
    elif isinstance(raw.get("font_asset_map"), dict):
        raw = raw["font_asset_map"]
    elif isinstance(raw.get("tmp_font_asset_map"), dict):
        raw = raw["tmp_font_asset_map"]
    result: dict[str, str] = {}
    for key, entry in raw.items():
        key_text = str(key or "").strip()
        if isinstance(entry, dict):
            guid = entry.get("guid") or entry.get("tmp_font_asset_guid") or entry.get("unity_font_asset_guid")
        else:
            guid = entry
        guid_text = str(guid or "").strip().lower()
        if not key_text:
            continue
        if not re.fullmatch(r"[0-9a-fA-F]{32}", guid_text):
            raise ValueError(f"TMP font asset guid for '{key_text}' must be a 32-character Unity asset guid.")
        result[_font_lookup_key(key_text)] = guid_text
    return result


def _resolve_tmp_font_for_text(text: dict[str, Any], default_font: dict[str, Any], font_map: dict[str, str]) -> dict[str, Any]:
    explicit_guid = (
        text.get("tmp_font_asset_guid")
        or text.get("unity_font_asset_guid")
        or ((text.get("font_hint") or {}).get("tmp_font_asset_guid") if isinstance(text.get("font_hint"), dict) else None)
    )
    if explicit_guid and re.fullmatch(r"[0-9a-fA-F]{32}", str(explicit_guid).strip()):
        return {"guid": str(explicit_guid).strip().lower(), "material_file_id": None}

    candidates = []
    font_family = text.get("font_family")
    font_style = text.get("font_style")
    font_weight = text.get("font_weight")
    if font_family and font_style:
        candidates.append(f"{font_family} {font_style}")
    if font_family and font_weight:
        candidates.append(f"{font_family} {font_weight}")
    if font_family:
        candidates.append(str(font_family))
    for candidate in candidates:
        guid = font_map.get(_font_lookup_key(candidate))
        if guid:
            return {"guid": guid, "material_file_id": None}
    return default_font


def _font_lookup_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _tmp_font_priority(meta_path: Path) -> tuple[int, str]:
    text = str(meta_path).lower()
    if "liberationsans" in text:
        return (0, text)
    if "inter-regular" in text:
        return (1, text)
    if "sdf" in text:
        return (2, text)
    return (3, text)


def _tmp_font_material_file_id(meta_path: Path) -> int | None:
    asset_path = meta_path.with_suffix("")
    if not asset_path.exists():
        return None
    match = re.search(r"^--- !u!21 &(-?\d+)\s*$", asset_path.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
    return int(match.group(1)) if match else None


def _has_tmp_essential_resources(project_root: Path) -> bool:
    assets_dir = project_root / "Assets"
    if not assets_dir.exists():
        return False
    for settings_asset in assets_dir.rglob("TMP Settings.asset"):
        parts = {part.lower() for part in settings_asset.parts}
        if "resources" in parts:
            return True
    return False


def _needs_canvas_group(node: dict[str, Any], child_ids: list[str]) -> bool:
    if str(node.get("id") or "") == "root" or not child_ids:
        return False
    opacity = _num((node.get("style") or {}).get("opacity"), 1)
    return 0 <= opacity < 0.999


def _has_text(node: dict[str, Any]) -> bool:
    text = node.get("text") or {}
    return bool(str(text.get("content") or "").strip())


def _text_effects(node: dict[str, Any]) -> dict[str, Any]:
    text = node.get("text") or {}
    effects = text.get("effects") if isinstance(text, dict) else None
    return effects if isinstance(effects, dict) else {}


def _tmp_rich_text_content(text: dict[str, Any]) -> str:
    content = str(text.get("content") or "")
    spans = text.get("spans") if isinstance(text.get("spans"), list) else []
    if not spans:
        return content
    pieces = []
    cursor = 0
    content_len = len(content)
    for span in sorted([item for item in spans if isinstance(item, dict)], key=lambda item: int(_num(item.get("start"), 0))):
        start = max(0, min(content_len, int(_num(span.get("start"), 0))))
        length = int(_num(span.get("length"), content_len - start))
        end = max(start, min(content_len, start + max(0, length)))
        if start > cursor:
            pieces.append(_tmp_escape_text(content[cursor:start]))
        if end > start:
            open_tags, close_tags = _tmp_rich_tags(span)
            pieces.append("".join(open_tags))
            pieces.append(_tmp_escape_text(content[start:end]))
            pieces.append("".join(reversed(close_tags)))
        cursor = max(cursor, end)
    if cursor < content_len:
        pieces.append(_tmp_escape_text(content[cursor:]))
    return "".join(pieces)


def _tmp_escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _tmp_rich_tags(style: dict[str, Any]) -> tuple[list[str], list[str]]:
    open_tags: list[str] = []
    close_tags: list[str] = []
    color = style.get("color")
    if color:
        open_tags.append(f"<color={_tmp_hex_color(color)}>")
        close_tags.append("</color>")
    font_size_source = style.get("font_size") if style.get("font_size") is not None else style.get("fontSize")
    font_size = _num(font_size_source)
    if font_size:
        open_tags.append(f"<size={_num(font_size, 0)}>")
        close_tags.append("</size>")
    font_style = str(style.get("font_style") or style.get("fontStyle") or "").lower()
    font_weight = str(style.get("font_weight") or style.get("fontWeight") or "").lower()
    if "bold" in font_style or "bold" in font_weight or font_weight in {"700", "800", "900"}:
        open_tags.append("<b>")
        close_tags.append("</b>")
    if "italic" in font_style or bool(style.get("italic")):
        open_tags.append("<i>")
        close_tags.append("</i>")
    if "underline" in font_style or bool(style.get("underline")):
        open_tags.append("<u>")
        close_tags.append("</u>")
    return open_tags, close_tags


def _tmp_hex_color(value: Any) -> str:
    color = _unity_color(value)
    r, g, b, a = [max(0, min(255, int(round(channel * 255)))) for channel in color]
    if a >= 255:
        return f"#{r:02X}{g:02X}{b:02X}"
    return f"#{r:02X}{g:02X}{b:02X}{a:02X}"


def _tmp_font_style(text: dict[str, Any]) -> int:
    value = str(text.get("font_style") or text.get("fontStyle") or "").lower()
    weight = str(text.get("font_weight") or text.get("fontWeight") or "").lower()
    result = 0
    if "bold" in value or "bold" in weight or weight in {"700", "800", "900"}:
        result |= 1
    if "italic" in value:
        result |= 2
    if "underline" in value:
        result |= 4
    return result


def _tmp_line_spacing(text: dict[str, Any], font_size: float) -> float:
    line_height_source = text.get("line_height") if text.get("line_height") is not None else text.get("lineHeight")
    line_height = _num(line_height_source)
    if not line_height:
        return 0
    return max(-100, round((line_height - font_size) / max(1, font_size) * 100, 3))


def _unity_color(value: Any, fallback: tuple[float, float, float, float] = (1, 1, 1, 1)) -> tuple[float, float, float, float]:
    if isinstance(value, dict):
        channels = []
        for keys in (("r", "red"), ("g", "green"), ("b", "blue"), ("a", "alpha", "opacity")):
            found = None
            for key in keys:
                if key in value:
                    found = value.get(key)
                    break
            if found is None and keys[0] != "a":
                return fallback
            channels.append(float(found) if found is not None else 1)
        if max(channels[:3], default=1) > 1:
            channels[:3] = [item / 255 for item in channels[:3]]
        if channels[3] > 1:
            channels[3] = channels[3] / 255 if channels[3] <= 255 else channels[3] / 100
        return tuple(round(max(0, min(1, item)), 4) for item in channels[:4])  # type: ignore[return-value]

    if isinstance(value, (list, tuple)) and len(value) >= 3:
        channels = [float(item) for item in value[:4]]
        if max(channels[:3], default=1) > 1:
            channels[:3] = [item / 255 for item in channels[:3]]
        while len(channels) < 4:
            channels.append(1)
        if channels[3] > 1:
            channels[3] = channels[3] / 255 if channels[3] <= 255 else channels[3] / 100
        return tuple(round(max(0, min(1, item)), 4) for item in channels[:4])  # type: ignore[return-value]

    text = str(value or "").strip()
    rgba = re.fullmatch(r"rgba?\(([^)]+)\)", text)
    if rgba:
        parts = [part.strip() for part in rgba.group(1).split(",")]
        if len(parts) >= 3:
            r = _color_channel(parts[0])
            g = _color_channel(parts[1])
            b = _color_channel(parts[2])
            a = _alpha_channel(parts[3]) if len(parts) >= 4 else 1
            return (r, g, b, a)

    hex_match = re.fullmatch(r"#?([0-9a-fA-F]{6})([0-9a-fA-F]{2})?", text)
    if hex_match:
        raw = hex_match.group(1)
        alpha = hex_match.group(2)
        return (
            int(raw[0:2], 16) / 255,
            int(raw[2:4], 16) / 255,
            int(raw[4:6], 16) / 255,
            int(alpha, 16) / 255 if alpha else 1,
        )

    return fallback


def _color_channel(value: str) -> float:
    value = value.strip()
    if value.endswith("%"):
        return round(max(0, min(1, float(value[:-1]) / 100)), 4)
    number = float(value)
    return round(max(0, min(1, number / 255 if number > 1 else number)), 4)


def _alpha_channel(value: str) -> float:
    value = value.strip()
    if value.endswith("%"):
        return round(max(0, min(1, float(value[:-1]) / 100)), 4)
    number = float(value)
    return round(max(0, min(1, number)), 4)


def _color_yaml(color: tuple[float, float, float, float]) -> str:
    r, g, b, a = color
    return f"{{r: {_num(r)}, g: {_num(g)}, b: {_num(b)}, a: {_num(a)}}}"


def _rgba32(color: tuple[float, float, float, float]) -> int:
    r, g, b, a = [max(0, min(255, int(round(channel * 255)))) for channel in color]
    return (a << 24) + (b << 16) + (g << 8) + r


def _tmp_font_weight(text: dict[str, Any]) -> int:
    value = text.get("font_weight")
    if isinstance(value, (int, float)):
        return int(value)
    lowered = str(value or "").lower()
    if "bold" in lowered or "heavy" in lowered or "black" in lowered:
        return 700
    return 400


def _tmp_horizontal_alignment(value: Any) -> int:
    lowered = str(value or "").lower()
    if "right" in lowered or "end" in lowered:
        return 4
    if "center" in lowered or "middle" in lowered or "居中" in lowered:
        return 2
    return 1


def _slider_value(node: dict[str, Any]) -> float:
    hint_value = (node.get("unity_slider_hint") or {}).get("value")
    if isinstance(hint_value, (int, float)):
        return _num(max(0, min(1, float(hint_value))))
    haystack = " ".join(
        str(part or "")
        for part in (
            node.get("name"),
            node.get("path"),
            (node.get("text") or {}).get("content"),
        )
    )
    percent = re.search(r"(\d+(?:\.\d+)?)\s*%", haystack)
    if percent:
        return _num(max(0, min(1, float(percent.group(1)) / 100)))
    decimal = re.search(r"\b0\.\d+\b", haystack)
    if decimal:
        return _num(max(0, min(1, float(decimal.group(0)))))
    return 0


def _toggle_value(node: dict[str, Any]) -> int:
    tab_hint = node.get("unity_tab_hint") or {}
    if isinstance(tab_hint.get("value"), bool):
        return 1 if tab_hint.get("value") else 0
    radio_hint = node.get("unity_radio_hint") or {}
    if isinstance(radio_hint.get("value"), bool):
        return 1 if radio_hint.get("value") else 0
    hint = node.get("unity_toggle_hint") or {}
    if isinstance(hint.get("value"), bool):
        return 1 if hint.get("value") else 0
    haystack = " ".join(
        str(part or "")
        for part in (
            hint.get("state"),
            node.get("name"),
            node.get("path"),
            (node.get("text") or {}).get("content"),
        )
    ).lower()
    if any(token in haystack for token in ("off", "unchecked", "uncheck", "disabled", "false", "关", "未选")):
        return 0
    if any(token in haystack for token in ("on", "checked", "check", "selected", "true", "开", "选中", "勾选")):
        return 1
    return 0


def _sprite_border(asset: dict[str, Any] | None) -> tuple[float, float, float, float]:
    hint = ((asset or {}).get("nine_slice_hint") or {}) if isinstance(asset, dict) else {}
    border = hint.get("border")
    if isinstance(border, dict):
        left = _first_num(border.get("left"), border.get("l"), border.get("x"))
        right = _first_num(border.get("right"), border.get("r"), border.get("z"))
        top = _first_num(border.get("top"), border.get("t"), border.get("w"))
        bottom = _first_num(border.get("bottom"), border.get("b"), border.get("y"))
    elif isinstance(border, (list, tuple)) and len(border) >= 4:
        left = _num(border[0], 0)
        bottom = _num(border[1], 0)
        right = _num(border[2], 0)
        top = _num(border[3], 0)
    else:
        left = bottom = right = top = 0
    return (
        max(0, float(left or 0)),
        max(0, float(bottom or 0)),
        max(0, float(right or 0)),
        max(0, float(top or 0)),
    )


def _first_num(*values: Any) -> float:
    for value in values:
        if value is None:
            continue
        return _num(value)
    return 0


def _texture_meta(guid: str, asset: dict[str, Any] | None = None) -> str:
    sprite_id = hashlib.md5(f"sprite:{guid}".encode("utf-8")).hexdigest()
    border_left, border_bottom, border_right, border_top = _sprite_border(asset)
    return f"""fileFormatVersion: 2
guid: {guid}
TextureImporter:
  internalIDToNameTable: []
  externalObjects: {{}}
  serializedVersion: 13
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
    fadeOut: 0
    borderMipMap: 0
    mipMapsPreserveCoverage: 0
    alphaTestReferenceValue: 0.5
    mipMapFadeDistanceStart: 1
    mipMapFadeDistanceEnd: 3
  bumpmap:
    convertToNormalMap: 0
    externalNormalMap: 0
    heightScale: 0.25
    normalMapFilter: 0
    flipGreenChannel: 0
  isReadable: 0
  streamingMipmaps: 0
  streamingMipmapsPriority: 0
  vTOnly: 0
  ignoreMipmapLimit: 0
  grayScaleToAlpha: 0
  generateCubemap: 6
  cubemapConvolution: 0
  seamlessCubemap: 0
  textureFormat: 1
  maxTextureSize: 2048
  textureSettings:
    serializedVersion: 2
    filterMode: 1
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 1
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  spriteMode: 1
  spriteExtrude: 1
  spriteMeshType: 1
  alignment: 0
  spritePivot: {{x: 0.5, y: 0.5}}
  spritePixelsToUnits: 100
  spriteBorder: {{x: {_num(border_left)}, y: {_num(border_bottom)}, z: {_num(border_right)}, w: {_num(border_top)}}}
  spriteGenerateFallbackPhysicsShape: 1
  alphaUsage: 1
  alphaIsTransparency: 1
  spriteTessellationDetail: -1
  textureType: 8
  textureShape: 1
  singleChannelComponent: 0
  flipbookRows: 1
  flipbookColumns: 1
  maxTextureSizeSet: 0
  compressionQualitySet: 0
  textureFormatSet: 0
  ignorePngGamma: 0
  applyGammaDecoding: 0
  swizzle: 50462976
  cookieLightType: 0
  platformSettings:
  - serializedVersion: 4
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 2048
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
    ignorePlatformSupport: 0
    androidETC2FallbackOverride: 0
    forceMaximumCompressionQuality_BC6H_BC7: 0
  spriteSheet:
    serializedVersion: 2
    sprites: []
    outline: []
    customData: 
    physicsShape: []
    bones: []
    spriteID: {sprite_id}
    internalID: 0
    vertices: []
    indices: 
    edges: []
    weights: []
    secondaryTextures: []
    spriteCustomMetadata:
      entries: []
    nameFileIdTable: {{}}
  mipmapLimitGroupName: 
  pSDRemoveMatte: 0
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""


def _prefab_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
PrefabImporter:
  externalObjects: {{}}
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""


def _text_asset_meta(guid: str) -> str:
    return f"""fileFormatVersion: 2
guid: {guid}
TextScriptImporter:
  externalObjects: {{}}
  userData: 
  assetBundleName: 
  assetBundleVariant: 
"""


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", str(value).strip(), flags=re.UNICODE).strip("_")
    return cleaned or "DesignToUnityPrefab"


def _safe_file_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", str(value).strip(), flags=re.UNICODE).strip("_")
    return cleaned or "asset.png"


def _num(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return default
        return round(float(value), 4)
    except (TypeError, ValueError):
        return default


def _clamped_float(value: Any, default: float = 0) -> float:
    try:
        if value is None:
            return _num(default)
        return _num(max(0.0, min(1.0, float(value))), default=default)
    except (TypeError, ValueError):
        return _num(default)

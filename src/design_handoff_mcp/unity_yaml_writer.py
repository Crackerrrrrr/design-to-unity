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
BUTTON_SCRIPT_GUID = "4e29b1a8efbd4b44bb3f3716e73f07ff"
SLIDER_SCRIPT_GUID = "67db9e8f0e2ae9c40bc1e2b64352a6b4"
DEFAULT_TMP_FONT_ASSET_GUID = "2f7116f10747a67409388e93052ae222"
TMP_FONT_ASSET_FILE_ID = 11400000
SPRITE_FILE_ID = 21300000


def write_unity_prefab_yaml(
    packet: dict[str, Any],
    unity_project_path: str,
    asset_root: str = "Assets/DesignHandoff/LanhuUnityHandoffMcp",
    prefab_name: str | None = None,
    overwrite: bool = True,
    include_reference: bool = False,
    button_raycast: bool = False,
    use_text_components: bool = True,
    add_button_components: bool = True,
    add_slider_components: bool = True,
    tmp_font_asset_guid: str | None = None,
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

    sprite_asset_dir = f"{asset_root}/{safe_packet}/Sprites"
    prefab_asset_dir = f"{asset_root}/{safe_packet}/Prefabs"
    raw_prefab_name = str(prefab_name or f"{packet_id[:8]}_ViewRoot").strip()
    if raw_prefab_name.lower().endswith(".prefab"):
        raw_prefab_name = raw_prefab_name[:-7]
    prefab_name = _safe_name(raw_prefab_name) + ".prefab"
    prefab_asset_path = f"{prefab_asset_dir}/{prefab_name}"

    (project_root / sprite_asset_dir).mkdir(parents=True, exist_ok=True)
    (project_root / prefab_asset_dir).mkdir(parents=True, exist_ok=True)

    nodes = _unity_creation_order(packet)
    assets = {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}
    copied_assets, asset_guid_by_id, warnings = _write_sprite_assets(
        project_root=project_root,
        sprite_asset_dir=sprite_asset_dir,
        nodes=nodes,
        assets=assets,
        include_reference=include_reference,
        overwrite=overwrite,
        use_text_components=use_text_components,
    )
    tmp_font = _resolve_tmp_font(project_root, tmp_font_asset_guid)
    tmp_font_guid = tmp_font.get("guid")
    tmp_font_material_file_id = tmp_font.get("material_file_id")
    if use_text_components and not tmp_font_guid:
        warnings.append(
            {
                "code": "missing_tmp_font",
                "message": "No TMP font asset guid could be resolved. TextMeshProUGUI components will use empty font references.",
            }
        )

    prefab_text, stats = _build_prefab_yaml(
        packet=packet,
        nodes=nodes,
        assets=assets,
        asset_guid_by_id=asset_guid_by_id,
        button_raycast=button_raycast,
        use_text_components=use_text_components,
        add_button_components=add_button_components,
        add_slider_components=add_slider_components,
        tmp_font_guid=tmp_font_guid,
        tmp_font_material_file_id=tmp_font_material_file_id,
    )
    prefab_path = project_root / prefab_asset_path
    if prefab_path.exists() and not overwrite:
        raise FileExistsError(f"Prefab already exists: {prefab_path}")
    prefab_path.write_text(prefab_text, encoding="utf-8")

    prefab_meta_path = prefab_path.with_suffix(prefab_path.suffix + ".meta")
    if not prefab_meta_path.exists():
        prefab_meta_path.write_text(_prefab_meta(_new_guid()), encoding="utf-8")

    return {
        "status": "success",
        "mode": "experimental_direct_yaml",
        "packet_id": packet_id,
        "design": design,
        "unity_project_path": str(project_root),
        "prefab_asset_path": prefab_asset_path,
        "prefab_path": str(prefab_path),
        "prefab_meta_path": str(prefab_meta_path),
        "sprite_asset_dir": sprite_asset_dir,
        "sprite_dir": str(project_root / sprite_asset_dir),
        "copied_asset_count": len(copied_assets),
        "node_count": stats["node_count"],
        "image_node_count": stats["image_node_count"],
        "tmp_text_node_count": stats["tmp_text_node_count"],
        "button_node_count": stats["button_node_count"],
        "slider_node_count": stats["slider_node_count"],
        "tmp_font_asset_guid": tmp_font_guid,
        "tmp_font_material_file_id": tmp_font_material_file_id,
        "missing_asset_count": len([w for w in warnings if w.get("code") == "missing_asset"]),
        "warnings": warnings,
        "caveats": [
            "This tool writes Unity YAML directly and is intentionally marked experimental.",
            "It creates static UGUI Image, TextMeshProUGUI, Button, and Slider components from best-effort semantics.",
            "Slider fill/handle references are left empty until a later semantic pass can bind child roles safely.",
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
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    copied = []
    guid_by_id: dict[str, str] = {}
    warnings: list[dict[str, Any]] = []
    used_asset_ids = []
    for node in nodes:
        if use_text_components and _has_text(node):
            continue
        asset_ref = node.get("asset_ref")
        if asset_ref and asset_ref not in used_asset_ids:
            used_asset_ids.append(asset_ref)

    for asset_id in used_asset_ids:
        asset = assets.get(asset_id)
        if not asset:
            warnings.append({"code": "missing_asset", "asset_id": asset_id, "message": "Asset is referenced by a node but missing from packet assets."})
            continue
        if asset.get("usage") == "design_reference" and not include_reference:
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
                meta_path.write_text(_texture_meta(guid), encoding="utf-8")
            if guid:
                guid_by_id[asset_id] = guid
            continue

        shutil.copy2(local_path, target_path)
        meta_path = target_path.with_suffix(target_path.suffix + ".meta")
        guid = _read_meta_guid(meta_path)
        if not guid:
            guid = _guid_for_asset(asset_id, target_asset_path)
            meta_path.write_text(_texture_meta(guid), encoding="utf-8")
        guid_by_id[asset_id] = guid
        copied.append({"asset_id": asset_id, "asset_path": target_asset_path, "path": str(target_path), "guid": guid})

    return copied, guid_by_id, warnings


def _build_prefab_yaml(
    packet: dict[str, Any],
    nodes: list[dict[str, Any]],
    assets: dict[str, dict[str, Any]],
    asset_guid_by_id: dict[str, str],
    button_raycast: bool,
    use_text_components: bool,
    add_button_components: bool,
    add_slider_components: bool,
    tmp_font_guid: str | None,
    tmp_font_material_file_id: int | None,
) -> tuple[str, dict[str, int]]:
    packet_id = str(packet.get("packet_id") or "packet")
    design = packet.get("design") or {}
    root = {
        "id": "root",
        "parent_id": None,
        "name": f"LanhuView_{packet_id[:8]}",
        "unity_name_hint": f"LanhuView_{packet_id[:8]}",
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

    used_file_ids: set[int] = set()
    object_ids: dict[str, dict[str, int | None]] = {}
    for node in all_nodes:
        node_id = str(node.get("id"))
        asset_ref = node.get("asset_ref")
        semantic_type = node.get("semantic_type")
        has_text = use_text_components and _has_text(node)
        has_sprite = bool(asset_ref and asset_ref in asset_guid_by_id and not has_text)
        has_button = bool(add_button_components and semantic_type == "button_candidate")
        has_slider = bool(add_slider_components and semantic_type in {"progress_candidate", "slider_candidate"})
        needs_control_hit_area = bool((has_button or semantic_type == "slider_candidate") and not has_sprite and not has_text)
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
        }

    lines = ["%YAML 1.1", "%TAG !u! tag:unity3d.com,2011:"]
    image_count = 0
    tmp_text_count = 0
    button_count = 0
    slider_count = 0
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
        has_text = bool(ids_for_node.get("tmp_text"))
        has_image = bool(ids_for_node.get("image"))
        lines.extend(_game_object_yaml(node, ids_for_node))
        lines.extend(_rect_transform_yaml(node, ids_for_node, parent_rect, child_rect_ids))
        if ids_for_node.get("canvas"):
            lines.extend(_canvas_renderer_yaml(ids_for_node))
        if has_image:
            asset = assets.get(asset_ref) or {}
            raycast = bool(has_button or semantic_type == "slider_candidate" or (button_raycast and semantic_type == "button_candidate"))
            lines.extend(_image_yaml(node, ids_for_node, sprite_guid, asset, raycast_target=raycast, transparent=not bool(sprite_guid)))
            image_count += 1
        if has_text:
            raycast = bool(has_button)
            lines.extend(_tmp_text_yaml(node, ids_for_node, tmp_font_guid, tmp_font_material_file_id, raycast_target=raycast))
            tmp_text_count += 1
        if has_button:
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            lines.extend(_button_yaml(ids_for_node, target_graphic))
            button_count += 1
        if has_slider:
            target_graphic = ids_for_node.get("image") or ids_for_node.get("tmp_text") or 0
            lines.extend(_slider_yaml(node, ids_for_node, target_graphic, interactable=semantic_type == "slider_candidate"))
            slider_count += 1

    return "\n".join(lines) + "\n", {
        "node_count": len(all_nodes),
        "image_node_count": image_count,
        "tmp_text_node_count": tmp_text_count,
        "button_node_count": button_count,
        "slider_node_count": slider_count,
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
        "  m_IsActive: 1",
    ]


def _rect_transform_yaml(node: dict[str, Any], ids: dict[str, int | None], parent_rect: int | None, child_rect_ids: list[int | None]) -> list[str]:
    rect = node.get("local_rect") or {}
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
            "  m_AnchorMin: {x: 0, y: 1}",
            "  m_AnchorMax: {x: 0, y: 1}",
            f"  m_AnchoredPosition: {{x: {_num(rect.get('x'))}, y: {-_num(rect.get('y'))}}}",
            f"  m_SizeDelta: {{x: {_num(rect.get('width'))}, y: {_num(rect.get('height'))}}}",
            "  m_Pivot: {x: 0, y: 1}",
        ]
    )
    return lines


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
) -> list[str]:
    text = node.get("text") or {}
    color = _unity_color(text.get("color") or (node.get("style") or {}).get("fill_color"), fallback=(1, 1, 1, 1))
    font_size = max(1, int(round(_num(text.get("font_size"), 24))))
    font_weight = _tmp_font_weight(text)
    horizontal_alignment = _tmp_horizontal_alignment(text.get("align"))
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
        f"  m_text: {_yaml_string(str(text.get('content') or ''))}",
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
        "  m_fontStyle: 0",
        f"  m_HorizontalAlignment: {horizontal_alignment}",
        "  m_VerticalAlignment: 512",
        "  m_textAlignment: 65535",
        f"  m_characterSpacing: {_num(text.get('letter_spacing'), 0)}",
        "  m_wordSpacing: 0",
        "  m_lineSpacing: 0",
        "  m_lineSpacingMax: 0",
        "  m_paragraphSpacing: 0",
        "  m_charWidthMaxAdj: 0",
        "  m_TextWrappingMode: 1",
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


def _slider_yaml(node: dict[str, Any], ids: dict[str, int | None], target_graphic: int | None, interactable: bool) -> list[str]:
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
        "  m_FillRect: {fileID: 0}",
        "  m_HandleRect: {fileID: 0}",
        "  m_Direction: 0",
        "  m_MinValue: 0",
        "  m_MaxValue: 1",
        "  m_WholeNumbers: 0",
        f"  m_Value: {_slider_value(node)}",
        "  m_OnValueChanged:",
        "    m_PersistentCalls:",
        "      m_Calls: []",
    ]


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

    def walk_children(parent: dict[str, Any], parent_id: str | None) -> None:
        children = []
        for child in parent.get("children") or []:
            current = dict(child)
            current.setdefault("parent_id", parent_id)
            children.append(current)
        children.sort(key=lambda item: item.get("z_index") or 0, reverse=True)
        for child in children:
            nodes.append(child)
            walk_children(child, child.get("id"))

    for root in packet.get("nodes") or []:
        walk_children(root, root.get("id"))
    return nodes


def _file_id(packet_id: str, node_id: str, kind: str, used: set[int]) -> int:
    seed = f"{packet_id}:{node_id}:{kind}"
    value = int(hashlib.sha1(seed.encode("utf-8")).hexdigest()[:15], 16)
    value = max(value, 1)
    while value in used:
        value += 1
    used.add(value)
    return value


def _guid_for_asset(asset_id: str, asset_path: str) -> str:
    return hashlib.md5(f"funplay-lanhu:{asset_id}:{asset_path}".encode("utf-8")).hexdigest()


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


def _has_text(node: dict[str, Any]) -> bool:
    text = node.get("text") or {}
    return bool(str(text.get("content") or "").strip())


def _unity_color(value: Any, fallback: tuple[float, float, float, float] = (1, 1, 1, 1)) -> tuple[float, float, float, float]:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        channels = [float(item) for item in value[:4]]
        if max(channels[:3], default=1) > 1:
            channels = [item / 255 for item in channels]
        while len(channels) < 4:
            channels.append(1)
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


def _texture_meta(guid: str) -> str:
    sprite_id = hashlib.md5(f"sprite:{guid}".encode("utf-8")).hexdigest()
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
  spriteBorder: {{x: 0, y: 0, z: 0, w: 0}}
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


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", str(value).strip(), flags=re.UNICODE).strip("_")
    return cleaned or "LanhuPrefab"


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

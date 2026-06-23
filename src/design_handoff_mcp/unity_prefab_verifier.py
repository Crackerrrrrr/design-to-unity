from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .unity_yaml_writer import (
    BUTTON_SCRIPT_GUID,
    GRID_LAYOUT_GROUP_SCRIPT_GUID,
    HORIZONTAL_LAYOUT_GROUP_SCRIPT_GUID,
    IMAGE_SCRIPT_GUID,
    LAYOUT_ELEMENT_SCRIPT_GUID,
    OUTLINE_SCRIPT_GUID,
    RECT_MASK_2D_SCRIPT_GUID,
    SCROLLBAR_SCRIPT_GUID,
    SCROLL_RECT_SCRIPT_GUID,
    SHADOW_SCRIPT_GUID,
    SLIDER_SCRIPT_GUID,
    TMP_DROPDOWN_SCRIPT_GUID,
    TMP_INPUT_FIELD_SCRIPT_GUID,
    TMP_TEXT_SCRIPT_GUID,
    TOGGLE_GROUP_SCRIPT_GUID,
    TOGGLE_SCRIPT_GUID,
    VERTICAL_LAYOUT_GROUP_SCRIPT_GUID,
)


def verify_unity_prefab_yaml(
    unity_project_path: str,
    prefab_asset_path: str,
    source_map_asset_path: str | None = None,
) -> dict[str, Any]:
    project_root = Path(unity_project_path).expanduser().resolve()
    prefab_asset = _asset_path(prefab_asset_path, project_root)
    source_map_asset = _asset_path(source_map_asset_path, project_root) if source_map_asset_path else _default_source_map_path(prefab_asset)
    prefab_path = project_root / prefab_asset
    source_map_path = project_root / source_map_asset
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not (project_root / "Assets").is_dir():
        errors.append({"code": "unity_assets_folder_missing", "message": f"Unity Assets folder not found: {project_root / 'Assets'}"})
    if not prefab_path.is_file():
        errors.append({"code": "prefab_missing", "message": f"Prefab file not found: {prefab_path}"})
    if not source_map_path.is_file():
        errors.append({"code": "source_map_missing", "message": f"Prefab source map not found: {source_map_path}"})
    if errors:
        return _result(project_root, prefab_asset, source_map_asset, errors, warnings, {}, {})

    prefab_text = prefab_path.read_text(encoding="utf-8", errors="ignore")
    try:
        source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append({"code": "source_map_invalid_json", "message": str(exc)})
        return _result(project_root, prefab_asset, source_map_asset, errors, warnings, {}, {})

    source_counts = _source_counts(source_map, errors, warnings, prefab_asset)
    yaml_counts = _yaml_counts(prefab_text)
    _compare_counts(source_counts, yaml_counts, errors)
    _verify_import_manifest(source_map, yaml_counts, errors, warnings)
    _verify_file_ids(prefab_text, source_map, errors)
    _verify_sprite_assets(project_root, source_map, prefab_text, errors, warnings)
    _component_binding_warnings(prefab_text, yaml_counts, source_counts, warnings)

    return _result(project_root, prefab_asset, source_map_asset, errors, warnings, yaml_counts, source_counts)


def _result(
    project_root: Path,
    prefab_asset: str,
    source_map_asset: str,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    yaml_counts: dict[str, int],
    source_counts: dict[str, int],
) -> dict[str, Any]:
    status = "fail" if errors else "pass_with_warnings" if warnings else "pass"
    return {
        "status": status,
        "unity_project_path": str(project_root),
        "prefab_asset_path": prefab_asset,
        "prefab_path": str(project_root / prefab_asset),
        "source_map_asset_path": source_map_asset,
        "source_map_path": str(project_root / source_map_asset),
        "counts": {
            "prefab_yaml": yaml_counts,
            "source_map": source_counts,
        },
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "next_steps": _next_steps(status),
    }


def _next_steps(status: str) -> list[str]:
    if status == "fail":
        return [
            "Regenerate the prefab or fix the listed missing files/references before opening it in Unity.",
            "If source-map counts disagree with YAML counts, keep the source map next to the generated prefab.",
        ]
    steps = [
        "Open or refresh the Unity project so generated assets import.",
        "Use Unity MCP or the Unity Editor to load the prefab and confirm no missing scripts appear.",
        "Capture a Unity screenshot and run psd_design_compare_unity_screenshot for visual QA.",
    ]
    if status == "pass_with_warnings":
        steps.insert(0, "Review warnings before treating this prefab as production-ready.")
    return steps


def _asset_path(value: str | None, project_root: Path) -> str:
    if not value:
        raise ValueError("asset path is required")
    path = Path(str(value).replace("\\", "/")).expanduser()
    if path.is_absolute():
        try:
            return path.resolve().relative_to(project_root).as_posix()
        except ValueError:
            raise ValueError(f"Path is outside Unity project: {path}") from None
    text = path.as_posix().strip("/")
    if not text.startswith("Assets/"):
        raise ValueError("Unity asset paths must start with Assets/")
    return text


def _default_source_map_path(prefab_asset: str) -> str:
    path = Path(prefab_asset)
    return (path.parent / f"{path.stem}.design-to-unity.json").as_posix()


def _source_counts(source_map: dict[str, Any], errors: list[dict[str, Any]], warnings: list[dict[str, Any]], prefab_asset: str) -> dict[str, int]:
    if source_map.get("schema") != "design-to-unity.prefab-source-map":
        errors.append({"code": "source_map_schema_mismatch", "message": "Expected design-to-unity.prefab-source-map source map schema."})
    if source_map.get("prefab_asset_path") and source_map.get("prefab_asset_path") != prefab_asset:
        warnings.append(
            {
                "code": "source_map_prefab_path_mismatch",
                "message": f"Source map points to {source_map.get('prefab_asset_path')}, but verifier was given {prefab_asset}.",
            }
        )
    nodes = source_map.get("nodes") if isinstance(source_map.get("nodes"), list) else []
    stats = source_map.get("stats") if isinstance(source_map.get("stats"), dict) else {}
    counts = {
        "node_count": int(stats.get("node_count") or len(nodes)),
        "image_node_count": int(stats.get("image_node_count") or 0),
        "tmp_text_node_count": int(stats.get("tmp_text_node_count") or 0),
        "button_node_count": int(stats.get("button_node_count") or 0),
        "slider_node_count": int(stats.get("slider_node_count") or 0),
        "toggle_node_count": int(stats.get("toggle_node_count") or 0),
        "toggle_group_node_count": int(stats.get("toggle_group_node_count") or 0),
        "tab_node_count": int(stats.get("tab_node_count") or 0),
        "radio_node_count": int(stats.get("radio_node_count") or 0),
        "input_field_node_count": int(stats.get("input_field_node_count") or 0),
        "dropdown_node_count": int(stats.get("dropdown_node_count") or 0),
        "scroll_rect_node_count": int(stats.get("scroll_rect_node_count") or 0),
        "scrollbar_node_count": int(stats.get("scrollbar_node_count") or 0),
        "rect_mask_2d_node_count": int(stats.get("rect_mask_2d_node_count") or 0),
        "vertical_layout_group_node_count": int(stats.get("vertical_layout_group_node_count") or 0),
        "horizontal_layout_group_node_count": int(stats.get("horizontal_layout_group_node_count") or 0),
        "grid_layout_group_node_count": int(stats.get("grid_layout_group_node_count") or 0),
        "layout_element_node_count": int(stats.get("layout_element_node_count") or 0),
        "outline_node_count": int(stats.get("outline_node_count") or 0),
        "shadow_node_count": int(stats.get("shadow_node_count") or 0),
        "canvas_group_node_count": int(stats.get("canvas_group_node_count") or 0),
    }
    if counts["node_count"] != len(nodes):
        errors.append(
            {
                "code": "source_map_node_count_mismatch",
                "message": f"source_map.stats.node_count={counts['node_count']} but nodes length is {len(nodes)}.",
            }
        )
    return counts


def _yaml_counts(prefab_text: str) -> dict[str, int]:
    return {
        "node_count": len(re.findall(r"^--- !u!1 &", prefab_text, re.MULTILINE)),
        "rect_transform_count": len(re.findall(r"^--- !u!224 &", prefab_text, re.MULTILINE)),
        "canvas_renderer_count": len(re.findall(r"^--- !u!222 &", prefab_text, re.MULTILINE)),
        "image_node_count": prefab_text.count(f"guid: {IMAGE_SCRIPT_GUID}"),
        "tmp_text_node_count": prefab_text.count(f"guid: {TMP_TEXT_SCRIPT_GUID}"),
        "button_node_count": prefab_text.count(f"guid: {BUTTON_SCRIPT_GUID}"),
        "slider_node_count": prefab_text.count(f"guid: {SLIDER_SCRIPT_GUID}"),
        "toggle_node_count": prefab_text.count(f"guid: {TOGGLE_SCRIPT_GUID}"),
        "toggle_group_node_count": prefab_text.count(f"guid: {TOGGLE_GROUP_SCRIPT_GUID}"),
        "input_field_node_count": prefab_text.count(f"guid: {TMP_INPUT_FIELD_SCRIPT_GUID}"),
        "dropdown_node_count": prefab_text.count(f"guid: {TMP_DROPDOWN_SCRIPT_GUID}"),
        "scroll_rect_node_count": prefab_text.count(f"guid: {SCROLL_RECT_SCRIPT_GUID}"),
        "scrollbar_node_count": prefab_text.count(f"guid: {SCROLLBAR_SCRIPT_GUID}"),
        "rect_mask_2d_node_count": prefab_text.count(f"guid: {RECT_MASK_2D_SCRIPT_GUID}"),
        "vertical_layout_group_node_count": prefab_text.count(f"guid: {VERTICAL_LAYOUT_GROUP_SCRIPT_GUID}"),
        "horizontal_layout_group_node_count": prefab_text.count(f"guid: {HORIZONTAL_LAYOUT_GROUP_SCRIPT_GUID}"),
        "grid_layout_group_node_count": prefab_text.count(f"guid: {GRID_LAYOUT_GROUP_SCRIPT_GUID}"),
        "layout_element_node_count": prefab_text.count(f"guid: {LAYOUT_ELEMENT_SCRIPT_GUID}"),
        "outline_node_count": prefab_text.count(f"guid: {OUTLINE_SCRIPT_GUID}"),
        "shadow_node_count": prefab_text.count(f"guid: {SHADOW_SCRIPT_GUID}"),
        "canvas_group_node_count": len(re.findall(r"^--- !u!225 &", prefab_text, re.MULTILINE)),
    }


def _compare_counts(source_counts: dict[str, int], yaml_counts: dict[str, int], errors: list[dict[str, Any]]) -> None:
    comparisons = [
        ("node_count", "node_count"),
        ("node_count", "rect_transform_count"),
        ("image_node_count", "image_node_count"),
        ("tmp_text_node_count", "tmp_text_node_count"),
        ("button_node_count", "button_node_count"),
        ("slider_node_count", "slider_node_count"),
        ("toggle_node_count", "toggle_node_count"),
        ("toggle_group_node_count", "toggle_group_node_count"),
        ("input_field_node_count", "input_field_node_count"),
        ("dropdown_node_count", "dropdown_node_count"),
        ("scroll_rect_node_count", "scroll_rect_node_count"),
        ("scrollbar_node_count", "scrollbar_node_count"),
        ("rect_mask_2d_node_count", "rect_mask_2d_node_count"),
        ("vertical_layout_group_node_count", "vertical_layout_group_node_count"),
        ("horizontal_layout_group_node_count", "horizontal_layout_group_node_count"),
        ("grid_layout_group_node_count", "grid_layout_group_node_count"),
        ("layout_element_node_count", "layout_element_node_count"),
        ("outline_node_count", "outline_node_count"),
        ("shadow_node_count", "shadow_node_count"),
        ("canvas_group_node_count", "canvas_group_node_count"),
    ]
    for source_key, yaml_key in comparisons:
        if source_counts.get(source_key) != yaml_counts.get(yaml_key):
            errors.append(
                {
                    "code": "prefab_count_mismatch",
                    "source_map_key": source_key,
                    "prefab_yaml_key": yaml_key,
                    "source_map_count": source_counts.get(source_key),
                    "prefab_yaml_count": yaml_counts.get(yaml_key),
                    "message": f"{source_key} does not match {yaml_key}.",
                }
            )


def _verify_import_manifest(
    source_map: dict[str, Any],
    yaml_counts: dict[str, int],
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    manifest = source_map.get("unity_import_manifest")
    if not isinstance(manifest, dict):
        warnings.append({"code": "unity_import_manifest_missing", "message": "Source map has no unity_import_manifest section for Unity MCP handoff."})
        return
    expected = manifest.get("expected_components")
    if not isinstance(expected, dict):
        warnings.append({"code": "expected_components_missing", "message": "unity_import_manifest has no expected_components section."})
        return
    mapping = {
        "GameObject": "node_count",
        "RectTransform": "rect_transform_count",
        "Image": "image_node_count",
        "TextMeshProUGUI": "tmp_text_node_count",
        "Button": "button_node_count",
        "Slider": "slider_node_count",
        "Toggle": "toggle_node_count",
        "ToggleGroup": "toggle_group_node_count",
        "TMP_InputField": "input_field_node_count",
        "TMP_Dropdown": "dropdown_node_count",
        "ScrollRect": "scroll_rect_node_count",
        "Scrollbar": "scrollbar_node_count",
        "RectMask2D": "rect_mask_2d_node_count",
        "VerticalLayoutGroup": "vertical_layout_group_node_count",
        "HorizontalLayoutGroup": "horizontal_layout_group_node_count",
        "GridLayoutGroup": "grid_layout_group_node_count",
        "LayoutElement": "layout_element_node_count",
        "Outline": "outline_node_count",
        "Shadow": "shadow_node_count",
        "CanvasGroup": "canvas_group_node_count",
    }
    for component_name, yaml_key in mapping.items():
        value = expected.get(component_name)
        if value is None:
            continue
        if int(value) != int(yaml_counts.get(yaml_key) or 0):
            errors.append(
                {
                    "code": "unity_import_manifest_count_mismatch",
                    "component": component_name,
                    "expected_count": int(value),
                    "prefab_yaml_count": int(yaml_counts.get(yaml_key) or 0),
                    "message": f"unity_import_manifest expected {component_name} count does not match prefab YAML.",
                }
            )
    gates = manifest.get("import_gates") if isinstance(manifest.get("import_gates"), list) else []
    if not any(isinstance(gate, dict) and gate.get("id") == "static_prefab_verify" for gate in gates):
        warnings.append({"code": "static_verification_gate_missing", "message": "unity_import_manifest does not declare the static_prefab_verify gate."})


def _verify_file_ids(prefab_text: str, source_map: dict[str, Any], errors: list[dict[str, Any]]) -> None:
    anchors = [int(value) for value in re.findall(r"^--- !u!\d+ &(-?\d+)\s*$", prefab_text, re.MULTILINE)]
    anchor_set = set(anchors)
    if len(anchor_set) != len(anchors):
        errors.append({"code": "duplicate_file_id", "message": "Prefab YAML contains duplicate local fileIDs."})

    missing_refs = sorted(
        {
            int(match.group(1))
            for match in re.finditer(r"\{fileID: (-?\d+)(?:,\s*guid:\s*([0-9a-fA-F]{32}),\s*type:\s*\d+)?\}", prefab_text)
            if int(match.group(1)) != 0 and not match.group(2) and int(match.group(1)) not in anchor_set
        }
    )
    for file_id in missing_refs[:20]:
        errors.append({"code": "missing_internal_file_id", "file_id": file_id, "message": f"Prefab references local fileID {file_id}, but no YAML object defines it."})

    for node in source_map.get("nodes") or []:
        component_ids = node.get("component_file_ids") if isinstance(node.get("component_file_ids"), dict) else {}
        for component_name, file_id in component_ids.items():
            if file_id and int(file_id) not in anchor_set:
                errors.append(
                    {
                        "code": "source_map_component_file_id_missing",
                        "node_id": node.get("node_id"),
                        "component": component_name,
                        "file_id": file_id,
                        "message": "Source map component fileID does not exist in the prefab YAML.",
                    }
                )


def _verify_sprite_assets(
    project_root: Path,
    source_map: dict[str, Any],
    prefab_text: str,
    errors: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
) -> None:
    sprite_asset_dir = str(source_map.get("sprite_asset_dir") or "").strip("/")
    if not sprite_asset_dir.startswith("Assets/"):
        errors.append({"code": "sprite_asset_dir_invalid", "message": "Source map sprite_asset_dir must start with Assets/."})
        return

    for asset in source_map.get("assets") or []:
        guid = asset.get("unity_guid")
        file_name = asset.get("file_name")
        if not guid:
            continue
        if guid not in prefab_text:
            warnings.append({"code": "asset_guid_not_referenced", "asset_ref": asset.get("asset_ref"), "guid": guid, "message": "Copied sprite asset guid is not referenced by the prefab YAML."})
        if not file_name:
            errors.append({"code": "source_map_asset_missing_file_name", "asset_ref": asset.get("asset_ref"), "message": "Source map asset has a Unity guid but no file_name."})
            continue
        deduped_asset_path = str(asset.get("deduped_unity_asset_path") or "").strip("/")
        sprite_path = project_root / deduped_asset_path if deduped_asset_path.startswith("Assets/") else project_root / sprite_asset_dir / file_name
        meta_path = sprite_path.with_suffix(sprite_path.suffix + ".meta")
        if not sprite_path.is_file():
            errors.append({"code": "sprite_file_missing", "asset_ref": asset.get("asset_ref"), "message": f"Sprite file not found: {sprite_path}"})
            continue
        if not meta_path.is_file():
            errors.append({"code": "sprite_meta_missing", "asset_ref": asset.get("asset_ref"), "message": f"Sprite meta file not found: {meta_path}"})
            continue
        meta_guid = _read_meta_guid(meta_path)
        if meta_guid != guid:
            errors.append(
                {
                    "code": "sprite_meta_guid_mismatch",
                    "asset_ref": asset.get("asset_ref"),
                    "expected_guid": guid,
                    "actual_guid": meta_guid,
                    "message": f"Sprite meta guid does not match source map for {sprite_path.name}.",
                }
            )
        expected_border = _border_from_hint((asset.get("nine_slice_hint") or {}).get("border") if isinstance(asset.get("nine_slice_hint"), dict) else None)
        if expected_border:
            actual_border = _read_sprite_border(meta_path)
            if not actual_border:
                errors.append(
                    {
                        "code": "sprite_border_missing",
                        "asset_ref": asset.get("asset_ref"),
                        "message": f"Sprite meta is missing spriteBorder for nine-slice asset {sprite_path.name}.",
                    }
                )
            elif not _border_close(actual_border, expected_border):
                errors.append(
                    {
                        "code": "sprite_border_mismatch",
                        "asset_ref": asset.get("asset_ref"),
                        "expected_border": expected_border,
                        "actual_border": actual_border,
                        "message": f"Sprite meta spriteBorder does not match source map for {sprite_path.name}.",
                    }
                )

    for node in source_map.get("nodes") or []:
        component_ids = node.get("component_file_ids") if isinstance(node.get("component_file_ids"), dict) else {}
        asset = node.get("asset") if isinstance(node.get("asset"), dict) else {}
        if component_ids.get("image") and asset and not asset.get("unity_guid"):
            errors.append(
                {
                    "code": "image_asset_not_copied",
                    "node_id": node.get("node_id"),
                    "asset_ref": asset.get("asset_ref"),
                    "message": "Image component node has a source asset but no copied Unity guid.",
                }
            )


def _component_binding_warnings(prefab_text: str, yaml_counts: dict[str, int], source_counts: dict[str, int], warnings: list[dict[str, Any]]) -> None:
    fill_unbound = len(re.findall(r"^\s*m_FillRect: \{fileID: 0\}", prefab_text, re.MULTILINE))
    handle_unbound = len(re.findall(r"^\s*m_HandleRect: \{fileID: 0\}", prefab_text, re.MULTILINE))
    scroll_content_unbound = len(re.findall(r"^\s*m_Content: \{fileID: 0\}", prefab_text, re.MULTILINE))
    scrollbars_unbound_to_scroll_rect = 0
    if yaml_counts.get("scrollbar_node_count"):
        scrollbar_refs = len(re.findall(r"^\s*m_(?:Horizontal|Vertical)Scrollbar: \{fileID: [1-9]\d*\}", prefab_text, re.MULTILINE))
        scrollbars_unbound_to_scroll_rect = max(0, int(yaml_counts.get("scrollbar_node_count") or 0) - scrollbar_refs)
    target_graphic_unbound = len(re.findall(r"^\s*m_TargetGraphic: \{fileID: 0\}", prefab_text, re.MULTILINE))
    toggle_graphic_unbound = len(re.findall(r"^\s*(?:m_Graphic|graphic): \{fileID: 0\}", prefab_text, re.MULTILINE))
    input_text_unbound = len(re.findall(r"^\s*m_TextComponent: \{fileID: 0\}", prefab_text, re.MULTILINE))
    dropdown_template_unbound = len(re.findall(r"^\s*m_Template: \{fileID: 0\}", prefab_text, re.MULTILINE))
    dropdown_caption_unbound = len(re.findall(r"^\s*m_CaptionText: \{fileID: 0\}", prefab_text, re.MULTILINE))
    dropdown_item_unbound = len(re.findall(r"^\s*m_ItemText: \{fileID: 0\}", prefab_text, re.MULTILINE))
    toggle_group_refs = len(re.findall(r"^\s*m_Group: \{fileID: [1-9]\d*\}", prefab_text, re.MULTILINE))
    empty_tmp_fonts = len(re.findall(r"^\s*m_fontAsset: \{fileID: 0\}", prefab_text, re.MULTILINE))
    if fill_unbound:
        warnings.append({"code": "slider_fill_rect_unbound", "count": fill_unbound, "message": "One or more Slider components have no fill RectTransform binding."})
    if handle_unbound:
        warnings.append({"code": "slider_handle_rect_unbound", "count": handle_unbound, "message": "One or more Slider components have no handle RectTransform binding."})
    if scroll_content_unbound:
        warnings.append({"code": "scroll_content_rect_unbound", "count": scroll_content_unbound, "message": "One or more ScrollRect components have no content RectTransform binding."})
    if scrollbars_unbound_to_scroll_rect:
        warnings.append({"code": "scrollbar_not_bound_to_scroll_rect", "count": scrollbars_unbound_to_scroll_rect, "message": "One or more Scrollbar components are not referenced by any ScrollRect."})
    if target_graphic_unbound and (
        yaml_counts.get("button_node_count")
        or yaml_counts.get("slider_node_count")
        or yaml_counts.get("toggle_node_count")
        or yaml_counts.get("input_field_node_count")
        or yaml_counts.get("dropdown_node_count")
        or yaml_counts.get("scrollbar_node_count")
    ):
        warnings.append({"code": "selectable_target_graphic_unbound", "count": target_graphic_unbound, "message": "One or more Button/Slider/Toggle/TMP_InputField/TMP_Dropdown/Scrollbar components have no target graphic."})
    if toggle_graphic_unbound and yaml_counts.get("toggle_node_count"):
        warnings.append({"code": "toggle_graphic_unbound", "count": toggle_graphic_unbound, "message": "One or more Toggle components have no state graphic binding."})
    tab_count = int(source_counts.get("tab_node_count") or 0)
    radio_count = int(source_counts.get("radio_node_count") or 0)
    grouped_toggle_count = tab_count + radio_count
    if grouped_toggle_count and toggle_group_refs < grouped_toggle_count:
        code = "tab_toggle_group_unbound" if tab_count and not radio_count else "grouped_toggle_group_unbound"
        warnings.append(
            {
                "code": code,
                "count": grouped_toggle_count - toggle_group_refs,
                "message": "One or more tab/radio Toggle components have no ToggleGroup binding.",
            }
        )
    if input_text_unbound and yaml_counts.get("input_field_node_count"):
        warnings.append({"code": "input_text_component_unbound", "count": input_text_unbound, "message": "One or more TMP_InputField components have no textComponent binding."})
    if dropdown_template_unbound and yaml_counts.get("dropdown_node_count"):
        warnings.append({"code": "dropdown_template_unbound", "count": dropdown_template_unbound, "message": "One or more TMP_Dropdown components have no template RectTransform binding."})
    if dropdown_caption_unbound and yaml_counts.get("dropdown_node_count"):
        warnings.append({"code": "dropdown_caption_text_unbound", "count": dropdown_caption_unbound, "message": "One or more TMP_Dropdown components have no captionText binding."})
    if dropdown_item_unbound and yaml_counts.get("dropdown_node_count"):
        warnings.append({"code": "dropdown_item_text_unbound", "count": dropdown_item_unbound, "message": "One or more TMP_Dropdown components have no itemText binding."})
    if empty_tmp_fonts:
        warnings.append({"code": "tmp_font_asset_unbound", "count": empty_tmp_fonts, "message": "One or more TextMeshProUGUI components have no TMP font asset reference."})


def _read_meta_guid(meta_path: Path) -> str | None:
    if not meta_path.exists():
        return None
    match = re.search(r"^guid:\s*([0-9a-fA-F]{32})\s*$", meta_path.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE)
    return match.group(1).lower() if match else None


def _read_sprite_border(meta_path: Path) -> dict[str, float] | None:
    if not meta_path.exists():
        return None
    text = meta_path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(
        r"^\s*spriteBorder:\s*\{x:\s*([-+]?\d+(?:\.\d+)?),\s*y:\s*([-+]?\d+(?:\.\d+)?),\s*z:\s*([-+]?\d+(?:\.\d+)?),\s*w:\s*([-+]?\d+(?:\.\d+)?)\}",
        text,
        re.MULTILINE,
    )
    if not match:
        return None
    return {
        "left": float(match.group(1)),
        "bottom": float(match.group(2)),
        "right": float(match.group(3)),
        "top": float(match.group(4)),
    }


def _border_from_hint(border: Any) -> dict[str, float] | None:
    if isinstance(border, dict):
        left = _border_num(border.get("left"), border.get("l"), border.get("x"))
        bottom = _border_num(border.get("bottom"), border.get("b"), border.get("y"))
        right = _border_num(border.get("right"), border.get("r"), border.get("z"))
        top = _border_num(border.get("top"), border.get("t"), border.get("w"))
    elif isinstance(border, (list, tuple)) and len(border) >= 4:
        left = _border_num(border[0])
        bottom = _border_num(border[1])
        right = _border_num(border[2])
        top = _border_num(border[3])
    else:
        return None
    if left is None or bottom is None or right is None or top is None:
        return None
    if max(left, bottom, right, top) <= 0:
        return None
    return {"left": left, "bottom": bottom, "right": right, "top": top}


def _border_num(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            continue
    return None


def _border_close(actual: dict[str, float], expected: dict[str, float]) -> bool:
    return all(abs(float(actual.get(key) or 0) - float(expected.get(key) or 0)) <= 0.001 for key in ("left", "bottom", "right", "top"))

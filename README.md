# Design to Unity

[中文介绍](README.zh-CN.md)

[GitHub Repository](https://github.com/Crackerrrrrr/design-to-unity) · `Crackerrrrrr/design-to-unity`

<p align="center">
  <img src="docs/assets/design-to-unity-flow.svg" alt="Design to Unity workflow diagram" width="100%">
</p>

Design to Unity is an MCP server for turning Lanhu, Figma, and PSD / Photoshop UI designs into structured handoff packets, downloadable assets, and Unity-ready UGUI prefab YAML snapshots.

For Figma teams, it acts as a bridge between design files and game UI production: the MCP can read Figma files, frames, components, local snapshots, or plugin exports; preserve layout, text, assets, component relationships, variants, variables, prototype reactions, and visual-risk metadata; then produce Unity source maps, prefab YAML, and Unity Editor importer input that AI agents or Unity tooling can continue from.

The server is built for an AI-assisted UI implementation workflow:

- expose design structure, positions, text, assets, and semantic hints through MCP tools
- prepare Unity handoff data that another Unity MCP can consume
- optionally write a static UGUI prefab YAML directly for quick inspection
- keep source maps and verification metadata beside generated prefabs
- keep Figma-specific intent such as Auto Layout, constraints, component instances, variants, and image fills available for Unity reconstruction

## Why Design to Unity

| Advantage | What it means in production |
| --- | --- |
| Unified design packet | Lanhu, Figma, PSD / PSB, and plugin exports all become the same AI-readable handoff format instead of separate one-off converters. |
| Better context for AI agents | Every important node can expose geometry, text, assets, component hints, render strategy, source semantics, confidence, and reasons. |
| Unity-ready but not Unity-locked | The packet is engine-neutral, while Unity output gets practical prefab YAML, source maps, TMP text, UGUI hints, and Editor importer support. |
| Reuse by default | Image hashes, Figma image refs, component keys, reusable prefab candidates, variants, and 9-slice hints reduce duplicate assets and repeated UI work. |
| Safer iteration | Readiness reports, source maps, incremental importer protection, and visual diff support make generated UI easier to inspect and update. |
| Designed for game UI | Button, slider, toggle, scroll view, list, tab, input, dropdown, layout group, mask, and canvas hints are first-class conversion targets. |

## Features

- Lanhu project and design-page extraction
- Figma file/frame/component extraction through REST API or local JSON snapshots
- batch Figma page/component-library packet preparation and prefab YAML writing
- Figma plugin export ingestion for selected frames/components, embedded preview images, manual semantic tags, and rendered complex visual assets
- local PSD / PSB packet preparation
- Photoshop / UXP export-folder ingestion
- asset manifest and slice metadata
- Unity layout and component hints
- Figma Auto Layout padding, spacing, child alignment, control, expand, and child LayoutElement hints are consumed by YAML / Editor importer output
- per-node render strategy, visual bounds, and source semantic evidence
- asset `content_hash` metadata so identical sprites are imported once
- reusable prefab registry for repeated buttons, tabs, sliders, and other UI components
- Figma component variant properties are exposed as reusable prefab instance overrides and Unity prefab variant candidates
- Figma corner radius / stroke metadata can infer `nine_slice_hint.border` for stretchable buttons, panels, and cards
- optional Figma variables are normalized into design tokens for Unity theme/token binding
- Figma prototype reactions are preserved as Unity navigation/event hints
- Figma constraints are mapped to Unity RectTransform anchor hints and consumed by YAML / Editor importer output
- Figma blur, blend mode, gradient/multiple fills, and mask risk are surfaced in source semantics, visual bounds, and readiness reports
- Figma plugin exporter includes constraints, Auto Layout child sizing, component variants, prototype reactions, rich text override metadata, and complex visual export triggers
- direct UGUI prefab YAML writer
- source map generation for prefab-to-design traceability
- static prefab YAML verification
- optional Unity Editor validator script installation
- visual diff helper for comparing Unity screenshots with Figma / PSD design references

## Figma To Unity Workflow

The Figma pipeline is designed for more than screenshot restoration:

- REST API mode reads live Figma files, pages, frames, components, styles, variables, image fills, and export URLs.
- Snapshot mode lets teams run local regression tests without depending on network access.
- Plugin export mode captures the current Figma selection, manual semantic tags, preview PNGs, and complex vector/image assets that should be rasterized.
- The packet preserves `render_strategy`, `render_rect`, `visual_bounds`, `source_semantics`, Auto Layout hints, constraints, text metadata, and reusable prefab candidates.
- Unity output can be generated as quick prefab YAML or imported through `DesignToUnityPrefabImporter.cs` for Editor API based prefab creation, reusable definitions, nested instances, and variant prefab assets.

Supported Unity UI component hints include:

- `Image`
- `TextMeshProUGUI`
- `Outline`
- `Shadow`
- `Button`
- `Slider`
- `Toggle`
- `ToggleGroup`
- `TMP_InputField`
- `TMP_Dropdown`
- `ScrollRect`
- `Scrollbar`
- `RectMask2D`
- `VerticalLayoutGroup`
- `HorizontalLayoutGroup`
- `GridLayoutGroup`
- `CanvasGroup`

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set `LANHU_COOKIE` for Lanhu and/or `FIGMA_TOKEN` for Figma in `.env`, then run:

```bash
DesignToUnity
```

For stdio clients:

```bash
MCP_TRANSPORT=stdio DesignToUnity
```

## Lanhu Tools

- `lanhu_design_list`
- `lanhu_design_prepare_packet`
- `lanhu_design_get_packet`
- `lanhu_design_get_summary`
- `lanhu_design_get_node_tree`
- `lanhu_design_get_node_detail`
- `lanhu_design_get_asset_manifest`
- `lanhu_design_get_slices`
- `lanhu_design_get_unity_plan`
- `lanhu_design_get_handoff_profile`
- `lanhu_design_write_unity_prefab_yaml`
- `lanhu_design_verify_unity_prefab_yaml`

## Figma Tools

- `figma_design_list_pages`
- `figma_design_list_frames`
- `figma_design_list_components`
- `figma_design_list_variables`
- `figma_design_get_export_schema`
- `figma_design_validate_export`
- `figma_design_prepare_packet`
- `figma_design_prepare_batch_packets`
- `figma_design_prepare_export_packet`
- `figma_design_export_assets`
- `figma_design_prepare_snapshot_packet`
- `figma_design_prepare_batch_snapshot_packets`
- `figma_design_get_component_usage`
- `figma_design_get_packet`
- `figma_design_get_summary`
- `figma_design_get_node_tree`
- `figma_design_get_node_detail`
- `figma_design_get_asset_manifest`
- `figma_design_get_slices`
- `figma_design_get_unity_plan`
- `figma_design_get_unity_readiness_report`
- `figma_design_compare_unity_screenshot`
- `figma_design_write_unity_prefab_yaml`
- `figma_design_write_batch_unity_prefab_yaml`
- `figma_design_verify_unity_prefab_yaml`
- `figma_design_convert_to_unity_prefab`
- `figma_design_convert_export_to_unity_prefab`
- `figma_design_install_unity_editor_importer`

## Unity Editor Importer

- `design_to_unity_install_unity_editor_importer`

This installs `Assets/Editor/DesignToUnity/DesignToUnityPrefabImporter.cs` into a Unity project. The importer reads a generated `*.design-to-unity.json` source map and creates a UGUI prefab through Unity Editor APIs, including basic TMP text, Image, Button, Slider, Toggle, ScrollRect, LayoutGroup, reusable prefab definition / nested instance output, and Figma variant prefab assets.

After installation, use the Unity menu:

```text
Tools/Design To Unity/Import Prefab From Source Map
```

Or run Unity batchmode with:

```bash
Unity -batchmode \
  -projectPath /path/to/UnityProject \
  -executeMethod DesignToUnityPrefabImporter.ImportFromCommandLine \
  -d2uSourceMap Assets/DesignToUnity/<packet>/Prefabs/<name>.design-to-unity.json \
  -d2uOutputPrefab Assets/DesignToUnity/<packet>/Prefabs/<name>.editor-imported.prefab \
  -d2uIncremental true \
  -d2uReport Assets/DesignToUnity/<packet>/Prefabs/<name>.import-report.json
```

When `-d2uIncremental true` is used and the output prefab already exists, the importer matches source-map `unity_path` entries, updates design-owned fields, creates new nodes, and preserves unmatched existing children by default. During reusable prefab replacement, user-added children are moved into the new nested prefab instance, while source-owned nodes with custom components or persistent event bindings are protected from replacement and reported. The generated import report records created, updated, preserved, protected, reusable prefab definition, reused prefab instance, and prefab variant counts.

For page/component-library batches:

```bash
Unity -batchmode \
  -projectPath /path/to/UnityProject \
  -executeMethod DesignToUnityPrefabImporter.ImportFromCommandLine \
  -d2uSourceMaps "Assets/DesignToUnity/a/Prefabs/a.design-to-unity.json;Assets/DesignToUnity/b/Prefabs/b.design-to-unity.json" \
  -d2uOutputDir Assets/DesignToUnity/ImportedPrefabs \
  -d2uIncremental true \
  -d2uBatchReport Assets/DesignToUnity/import-batch-report.json
```

You can also pass `-d2uSourceMapDir Assets/DesignToUnity` to import every `*.design-to-unity.json` source map under a folder, or pass `-d2uOutputPrefabs` when each source map needs an explicit output prefab path.

## TMP Font Mapping

Figma / PSD text is generated as editable `TextMeshProUGUI` by default. Pass `tmp_font_asset_guid` / `tmp_font_asset_map_json` on writer tools, or configure defaults in `.env`:

```env
UNITY_TMP_FONT_ASSET_GUID=
UNITY_TMP_FONT_ASSET_MAP_JSON={"figma_font_to_tmp":{"Inter":"11111111111111111111111111111111"}}
UNITY_TMP_FONT_ASSET_MAP_PATH=/path/to/font-map.json
```

The readiness report includes `font_requirements`, `missing_tmp_font_mapping_count`, and sample nodes so missing TMP mappings can be fixed before Unity import.

## PSD / Photoshop Tools

- `psd_design_get_export_schema`
- `psd_design_validate_export`
- `psd_design_prepare_packet`
- `psd_design_prepare_export_packet`
- `psd_design_get_summary`
- `psd_design_get_node_tree`
- `psd_design_get_node_detail`
- `psd_design_get_asset_manifest`
- `psd_design_get_slices`
- `psd_design_get_unity_plan`
- `psd_design_get_unity_readiness_report`
- `psd_design_compare_unity_screenshot`
- `psd_design_install_unity_editor_validator`
- `psd_design_write_unity_prefab_yaml`
- `psd_design_verify_unity_prefab_yaml`
- `psd_design_convert_to_unity_prefab`
- `psd_design_convert_export_to_unity_prefab`

## Figma Plugin Exporter

A starter Figma plugin exporter is included in `templates/figma-plugin-exporter`.

It exports a single `*-design-to-unity.json` file with the selected node tree,
preview PNG, manual semantic tags, and rendered vector/image assets embedded as base64. The MCP can
read it with `figma_design_prepare_export_packet` or convert it directly with
`figma_design_convert_export_to_unity_prefab`.

## Photoshop UXP Exporter

A starter Photoshop UXP exporter is included in `templates/photoshop-uxp-exporter`.

It exports:

- `design.json`
- `preview.png`
- layer PNG assets
- editable text metadata when Photoshop exposes it
- complex-group rasterization markers

The MCP can read the export folder with `psd_design_prepare_export_packet` or convert it directly with `psd_design_convert_export_to_unity_prefab`.

## Reuse And Deduplication

Each packet includes two reuse layers:

- Asset reuse: image assets carry `content_hash` / `file_hash`; Figma image fills also retain `source_image_ref` / `image_fill` / `source_image_fill_url`. The direct Unity YAML writer copies identical-content, same Figma imageRef, or same-source sprites once, then records `duplicate_of` / `deduped_unity_asset_path` for later references.
- Node reuse: component candidates carry `reusable_prefab_key` and `reusable_prefab`. The packet-level `reusable_prefabs` registry lists definition nodes, instance nodes, suggested prefab paths, and instance override fields.
- Variant reuse: Figma component variant signatures are grouped into `prefab_variant_groups`, including base prefab paths, variant axes, variant node ids, and suggested Unity prefab variant asset paths.
- 9-slice reuse: Figma image/complex nodes that look like stretchable buttons, panels, or cards and carry corner radius or stroke data get `nine_slice_hint.border`; the Unity YAML writer emits Sprite `spriteBorder`.

A Unity MCP can read `reusable_prefabs`, save the definition node once, instantiate the remaining nodes from that prefab, and apply rect/text overrides. It can then read `prefab_variant_groups` to create state-specific prefab variants. The experimental direct YAML writer still expands a full static hierarchy for compatibility; the Unity Editor importer uses the source map to save reusable definitions, create variant prefab assets, and replace later instances with real nested prefab instances.

## Direct Unity Prefab YAML

The direct writer can create:

- copied sprite files under a Unity `Assets/...` folder
- deterministic `.png.meta` files
- a `.prefab` YAML file
- a sibling `*.design-to-unity.json` source map
- a `.prefab.meta` file when needed

This path is intended for static UI restoration, prefab review, and AI-assisted follow-up work. Project-specific business scripts, animation wiring, and custom runtime behavior should be added in Unity.

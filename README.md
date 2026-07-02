# Design to Unity

<!-- mcp-name: io.github.crackerrrrrr/design-to-unity -->

[中文介绍](README.zh-CN.md) · [GitHub Repository](https://github.com/Crackerrrrrr/design-to-unity) · `Crackerrrrrr/design-to-unity`

<p align="center">
  <img src="docs/assets/design-to-unity-flow.svg" alt="Design to Unity workflow diagram" width="100%">
</p>

Design to Unity is an MCP server for turning Lanhu, Figma, PSD / PSB, and Photoshop UI designs into structured implementation packets, downloadable assets, and Unity-ready UGUI prefab outputs.

It is built for AI-assisted game UI production. Instead of asking an AI agent to guess from a flat screenshot, Design to Unity exposes the real design structure: nodes, bounds, text, slices, reusable components, render strategy, source semantics, warnings, and Unity import hints.

## At A Glance

| Question | Answer |
| --- | --- |
| What does it read? | Lanhu pages, Figma files, Figma plugin exports, PSD / PSB files, and Photoshop UXP exports. |
| What does it produce? | A unified Design Implementation Packet, asset manifest, source map, readiness report, prefab YAML, and Unity Editor importer input. |
| Who is it for? | Game teams, technical artists, Unity developers, and AI agents that need reliable UI reconstruction data. |
| Does it replace Unity? | No. It prepares the data and optional prefab snapshots so Unity MCP or Unity Editor tooling can continue the work. |
| Is it screenshot-only? | No. Reference images are used for verification; layout should come from nodes, assets, text, and source metadata. |

## What You Get

- A single AI-readable packet format across Lanhu, Figma, PSD / PSB, and plugin exports.
- Per-node geometry, hierarchy, asset references, text metadata, semantic candidates, and Unity RectTransform hints.
- Component hints for `Button`, `Slider`, `Toggle`, `ScrollRect`, `Scrollbar`, `TMP_InputField`, `TMP_Dropdown`, masks, and layout groups.
- Asset deduplication through content hashes, Figma image refs, and reusable prefab candidates.
- TMP editable text by default, with readiness warnings when source fonts do not have configured TMP mappings.
- Direct static UGUI prefab YAML for quick inspection.
- Unity Editor importer input for Editor API based prefab creation, reusable definitions, nested instances, and variant prefab assets.
- Source maps, readiness reports, validators, and visual diff helpers for review and regression.

## Source Coverage

<p align="center">
  <img src="docs/assets/design-to-unity-source-coverage.svg" alt="Supported Design to Unity sources" width="100%">
</p>

| Source | Preserved information |
| --- | --- |
| Lanhu | Project pages, design pages, slice assets, node positions, text, handoff notes, and Unity layout/component hints. |
| Figma | Files, frames, components, plugin exports, Auto Layout, constraints, image fills, variants, variables, prototype reactions, and visual risk metadata. |
| PSD / PSB | Layer tree, bounds, editable text metadata when available, blend/effect risk markers, grouped assets, and raster fallback slices. |
| Photoshop UXP export | `design.json`, `preview.png`, layer PNG assets, text metadata, semantic markers, and complex-group rasterization hints. |
| Unity output | Engine-neutral packet, asset manifest, reusable prefab registry, source map, UGUI prefab YAML, readiness report, and Editor importer input. |

## Packet Anatomy

<p align="center">
  <img src="docs/assets/design-to-unity-packet-anatomy.svg" alt="Design Implementation Packet anatomy" width="100%">
</p>

The Design Implementation Packet is the stable middle layer. It keeps source-specific intent while giving AI and Unity a common structure:

| Packet area | Why it matters |
| --- | --- |
| `nodes` | Keeps hierarchy, z-order, names, parent links, and node types. |
| `global_rect` / `local_rect` / `unity_rect_hint` | Gives Unity predictable position, size, pivot, and anchor hints. |
| `render_strategy` | Explains whether a node should be text, image, group, rasterized group, or component candidate. |
| `render_rect` / `visual_bounds` | Handles shadows, strokes, effects, and other visuals that extend outside the layout rect. |
| `source_semantics` | Stores component guesses, naming evidence, layout inference, confidence, and review flags. |
| `asset_manifest` | Lists sprites, hashes, duplicates, Unity paths, and import hints. |
| `reusable_prefabs` | Marks repeated UI structures such as buttons, tabs, sliders, and list items. |
| `source_map` | Tracks design nodes to Unity objects/components for verification and incremental import. |
| `readiness_report` | Surfaces missing assets, missing TMP mappings, complex visuals, low-confidence semantics, and next actions. |

## Unity Output Options

<p align="center">
  <img src="docs/assets/design-to-unity-unity-output.svg" alt="Design to Unity output options" width="100%">
</p>

Design to Unity supports three Unity landing paths:

| Path | Use it when |
| --- | --- |
| Unity MCP handoff | An AI agent should inspect the packet and create or adjust Unity objects interactively. |
| Direct prefab YAML | You want a fast static UGUI prefab snapshot for review, diffing, or regression. |
| Unity Editor importer | You want Unity Editor APIs to create UGUI objects, TMP text, reusable definitions, nested instances, and variant prefabs. |

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set credentials only when you need live Lanhu or Figma access:

```bash
LANHU_COOKIE=your_lanhu_cookie
FIGMA_TOKEN=your_figma_personal_access_token
```

Start the HTTP MCP server:

```bash
DesignToUnity
```

For stdio MCP clients:

```bash
MCP_TRANSPORT=stdio DesignToUnity
```

## Common Workflows

### Lanhu To Unity

```text
lanhu_design_list
lanhu_design_prepare_packet
lanhu_design_get_summary
lanhu_design_get_unity_plan
lanhu_design_write_unity_prefab_yaml
lanhu_design_verify_unity_prefab_yaml
```

Use this for live Lanhu pages where slices, node positions, text, and layout notes should drive the Unity result.

### Figma To Unity

```text
figma_design_list_pages / figma_design_list_frames
figma_design_prepare_packet
figma_design_get_component_usage
figma_design_get_unity_readiness_report
figma_design_write_unity_prefab_yaml
figma_design_install_unity_editor_importer
```

Use this for Figma files with Auto Layout, constraints, components, variants, image fills, and prototype metadata.

### PSD / Photoshop To Unity

```text
psd_design_prepare_packet
psd_design_get_unity_readiness_report
psd_design_write_unity_prefab_yaml
psd_design_verify_unity_prefab_yaml
```

Use this for local PSD / PSB files or Photoshop UXP export folders. UXP exports are recommended when Photoshop exposes richer text, layer, and rasterized-group metadata than a raw PSD parser can provide.

## Tool Reference

### Lanhu Tools

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

### Figma Tools

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

### PSD / Photoshop Tools

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

### Shared Unity Tool

- `design_to_unity_install_unity_editor_importer`

## Unity Editor Importer

`design_to_unity_install_unity_editor_importer` installs:

```text
Assets/Editor/DesignToUnity/DesignToUnityPrefabImporter.cs
```

The importer reads generated `*.design-to-unity.json` source maps and creates UGUI prefabs through Unity Editor APIs. It supports basic TMP text, Image, Button, Slider, Toggle, ScrollRect, LayoutGroup, reusable prefab definition / nested instance output, and Figma variant prefab assets.

After installation, use the Unity menu:

```text
Tools/Design To Unity/Import Prefab From Source Map
```

Or run Unity batchmode:

```bash
Unity -batchmode \
  -projectPath /path/to/UnityProject \
  -executeMethod DesignToUnityPrefabImporter.ImportFromCommandLine \
  -d2uSourceMap Assets/DesignToUnity/<packet>/Prefabs/<name>.design-to-unity.json \
  -d2uOutputPrefab Assets/DesignToUnity/<packet>/Prefabs/<name>.editor-imported.prefab \
  -d2uIncremental true \
  -d2uReport Assets/DesignToUnity/<packet>/Prefabs/<name>.import-report.json
```

For page or component-library batches:

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

When `-d2uIncremental true` is used and the output prefab already exists, the importer matches source-map `unity_path` entries, updates design-owned fields, creates new nodes, and preserves unmatched existing children by default. During reusable prefab replacement, user-added children are moved into the new nested prefab instance, while source-owned nodes with custom components or persistent event bindings are protected from replacement and reported.

## TMP Text And Font Mapping

Figma, PSD, and Lanhu text is generated as editable `TextMeshProUGUI` by default. Missing TMP fonts are reported instead of silently rasterizing text.

Pass `tmp_font_asset_guid` / `tmp_font_asset_map_json` on writer tools, or configure defaults in `.env`:

```env
UNITY_TMP_FONT_ASSET_GUID=
UNITY_TMP_FONT_ASSET_MAP_JSON={"figma_font_to_tmp":{"Inter":"11111111111111111111111111111111"}}
UNITY_TMP_FONT_ASSET_MAP_PATH=/path/to/font-map.json
```

The readiness report includes `text_restoration_policy`, `font_requirements`, `missing_tmp_font_mapping_count`, and sample nodes so missing TMP mappings can be fixed before final Unity visual QA.

## Reuse And Deduplication

Design to Unity handles reuse at several levels:

| Reuse layer | How it works |
| --- | --- |
| Asset reuse | Image assets carry `content_hash` / `file_hash`; Figma image fills also retain `source_image_ref` / `image_fill` / `source_image_fill_url`. |
| Node reuse | Component candidates carry `reusable_prefab_key` and `reusable_prefab`; packet-level `reusable_prefabs` list definitions, instances, paths, and override fields. |
| Variant reuse | Figma component variant signatures are grouped into `prefab_variant_groups` with axes, variant node ids, and suggested Unity prefab variant paths. |
| 9-slice reuse | Stretchable buttons, panels, and cards can carry `nine_slice_hint.border`; the Unity YAML writer emits Sprite `spriteBorder`. |

The direct YAML writer expands a full static hierarchy for compatibility. The Unity Editor importer can use the source map to save reusable definitions, create variant prefab assets, and replace later instances with nested prefab instances.

## Direct Unity Prefab YAML

The direct writer can create:

- copied sprite files under a Unity `Assets/...` folder
- deterministic `.png.meta` files
- a `.prefab` YAML file
- a sibling `*.design-to-unity.json` source map
- a `.prefab.meta` file when needed

This path is intended for static UI restoration, prefab review, and AI-assisted follow-up work. Project-specific business scripts, animation wiring, and custom runtime behavior should be added in Unity.

## Exporter Templates

### Figma Plugin Exporter

A starter Figma plugin exporter is included in `templates/figma-plugin-exporter`.

It exports a single `*-design-to-unity.json` file with the selected node tree, preview PNG, manual semantic tags, and rendered vector/image assets embedded as base64. The MCP can read it with `figma_design_prepare_export_packet` or convert it directly with `figma_design_convert_export_to_unity_prefab`.

### Photoshop UXP Exporter

A starter Photoshop UXP exporter is included in `templates/photoshop-uxp-exporter`.

It exports:

- `design.json`
- `preview.png`
- layer PNG assets
- editable text metadata when Photoshop exposes it
- complex-group rasterization markers

The MCP can read the export folder with `psd_design_prepare_export_packet` or convert it directly with `psd_design_convert_export_to_unity_prefab`.

## Documentation Path

- Product overview and quick use: this README and [README.zh-CN.md](README.zh-CN.md).
- Exporter integration: `templates/photoshop-uxp-exporter/README.md` and `templates/figma-plugin-exporter/README.md`.
- Release and repository maintenance: `docs/publishing.md` and `docs/launch-kit.md`.
- Internal architecture notes, test evidence, and generated outputs are kept in the development workspace and are not part of the product release.

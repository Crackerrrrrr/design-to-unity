# Design to Unity

[GitHub Repository](https://github.com/Crackerrrrrr/design-to-unity) · `Crackerrrrrr/design-to-unity`

Design to Unity is an MCP server for turning Lanhu and PSD / Photoshop UI designs into structured handoff packets, downloadable assets, and Unity-ready UGUI prefab YAML snapshots.

The server is built for an AI-assisted UI implementation workflow:

- expose design structure, positions, text, assets, and semantic hints through MCP tools
- prepare Unity handoff data that another Unity MCP can consume
- optionally write a static UGUI prefab YAML directly for quick inspection
- keep source maps and verification metadata beside generated prefabs

## Features

- Lanhu project and design-page extraction
- local PSD / PSB packet preparation
- Photoshop / UXP export-folder ingestion
- asset manifest and slice metadata
- Unity layout and component hints
- direct UGUI prefab YAML writer
- source map generation for prefab-to-design traceability
- static prefab YAML verification
- optional Unity Editor validator script installation
- visual diff helper for comparing Unity screenshots with design references

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

Set `LANHU_COOKIE` in `.env`, then run:

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

## Photoshop UXP Exporter

A starter Photoshop UXP exporter is included in `templates/photoshop-uxp-exporter`.

It exports:

- `design.json`
- `preview.png`
- layer PNG assets
- editable text metadata when Photoshop exposes it
- complex-group rasterization markers

The MCP can read the export folder with `psd_design_prepare_export_packet` or convert it directly with `psd_design_convert_export_to_unity_prefab`.

## Direct Unity Prefab YAML

The direct writer can create:

- copied sprite files under a Unity `Assets/...` folder
- deterministic `.png.meta` files
- a `.prefab` YAML file
- a sibling `*.design-to-unity.json` source map
- a `.prefab.meta` file when needed

This path is intended for static UI restoration, prefab review, and AI-assisted follow-up work. Project-specific business scripts, animation wiring, and custom runtime behavior should be added in Unity.

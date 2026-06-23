# Design to Unity Figma Exporter

This starter Figma plugin exports the current selection into a Design to Unity
manifest that can be read by the MCP without a Figma API token.

## What It Exports

- selected frame/component/page node tree
- `absoluteBoundingBox`, `absoluteRenderBounds`, constraints, Auto Layout fields
- Auto Layout child fields such as `layoutGrow`, `layoutAlign`, `layoutPositioning`, and `layoutSizingHorizontal/Vertical`
- text content and basic text style fields
- text override tables for rich-text review
- fills, strokes, effects, corner radius, clipping/mask metadata, blend mode
- component properties, component property definitions, and prototype reactions
- manual semantic tags from layer names or plugin data
- PNG preview for the selected root
- PNG assets for complex vector/image/effect nodes

The plugin downloads a single JSON file with embedded base64 PNG data:

```text
<selection>-design-to-unity.json
```

The MCP can read this file directly:

```bash
figma_design_validate_export("/path/to/Main_Menu-design-to-unity.json")
figma_design_prepare_export_packet("/path/to/Main_Menu-design-to-unity.json")
figma_design_convert_export_to_unity_prefab("/path/to/Main_Menu-design-to-unity.json", "/path/to/UnityProject")
```

## Development Install

1. Open Figma.
2. Go to Plugins > Development > Import plugin from manifest.
3. Select `templates/figma-plugin-exporter/manifest.json`.
4. Select one frame/component or leave nothing selected to export the current page.
5. Run `Design to Unity Exporter`.

## Manual Semantic Tags

Add tags to layer/component names when the automatic recognizer needs an explicit hint:

- `Play Button @button` exports a Unity `Button` candidate.
- `Volume @slider` exports a Unity `Slider` candidate.
- `Inventory List @scroll` exports a `ScrollRect` candidate.
- `Reusable Card @prefab` forces the node into the reusable prefab registry.
- `Reference Notes @ignore` keeps the node in packet metadata but skips Unity prefab creation.

The exporter also reads comma/space separated tags from plugin data keys
`manualTags`, `tags`, or `designToUnityTags`, including shared plugin data under
`design-to-unity` / `design_to_unity`.

## Output Schema

The exported JSON follows:

```json
{
  "schema": "design-to-unity.figma-export",
  "schema_version": 1,
  "plugin_version": "0.2.0",
  "file_name": "Game UI",
  "root": {},
  "preview": {
    "file_name": "preview.png",
    "mime_type": "image/png",
    "data": "data:image/png;base64,..."
  },
  "assets": [
    {
      "node_id": "12:34",
      "file_name": "Icon_12_34.png",
      "usage": "image",
      "mime_type": "image/png",
      "data": "data:image/png;base64,..."
    }
  ]
}
```

Folder exports are also supported by the MCP when another exporter writes:

```text
figma-export/
  design.json
  preview.png
  assets/*.png
```

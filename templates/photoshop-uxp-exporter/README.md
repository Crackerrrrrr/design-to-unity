# Design to Unity Photoshop Exporter

This folder is a Photoshop UXP panel template that exports the active document into the format consumed by the Design to Unity MCP Photoshop-export tools.

## Output

```text
export/
  design.json
  preview.png
  assets/
    layer_or_group.png
```

`design.json` uses the `design-to-unity.photoshop-export` schema. The MCP reads it with:

```text
psd_design_validate_export(export_path)
psd_design_prepare_export_packet(export_path)
psd_design_convert_export_to_unity_prefab(export_path, unity_project_path)
```

## Local Test Flow

1. Open Adobe UXP Developer Tool.
2. Add this folder as a plugin.
3. Load the plugin in Photoshop.
4. Open a PSD / PSB document.
5. Open the `Design to Unity` panel.
6. Choose an export folder.
7. Click `Export Active Document`.
8. Run `psd_design_validate_export(export_path)` before writing Unity files.

The template exports a flattened `preview.png`, layer tree metadata, editable text metadata when Photoshop exposes it, and PNG assets for visible non-text leaf layers. When `Rasterize complex groups` is enabled, groups with masks, layer effects, clipping, smart objects, adjustment layers, or non-normal blend modes are exported as a single PNG and marked with `rasterized: true`.

For scalable buttons or panels, add explicit nine-slice data in `design.json` with `nine_slice`, `nineSlice`, `spriteBorder`, or `sprite_border`. The MCP will write the copied Sprite `.meta` `spriteBorder`, set the UGUI Image to Sliced, and verify the border during static prefab validation.

For explicit single-choice controls, mark the parent as `role: "radio_group_candidate"` and each option as `role: "radio_candidate"`. The MCP writes a Unity `ToggleGroup`, binds each option `Toggle.group`, and infers the default selected option from names such as `selected`, `active`, `checked`, or `选中`.

For rectangular clipping containers such as avatar masks or clipped content windows, mark the node as `role: "mask_candidate"`. The MCP writes a Unity `RectMask2D` on that GameObject and keeps `unity_mask_hint` in the source map. Irregular Photoshop bitmap/vector masks should still be rasterized or checked with visual diff.

For repeated content containers, use clear names such as `Content`, `ItemList`, or `GridContent`, or set `role: "scroll_content_candidate"` when the group is a ScrollRect content node. The MCP can infer `VerticalLayoutGroup`, `HorizontalLayoutGroup`, or `GridLayoutGroup` from direct child geometry and keeps `unity_layout_hint` in the source map.

## Notes

- The panel requires Manifest v5 and Photoshop 24.2 or newer so the Layer text API is available.
- Layer asset export duplicates the active document, hides everything except the target branch, crops to the layer bounds, saves PNG, then closes the duplicate without saving.
- This exporter is intentionally conservative. Use the generated `preview.png` plus `psd_design_compare_unity_screenshot` to verify real Unity output.

## References

- Adobe UXP Manifest v5: https://developer.adobe.com/photoshop/uxp/2022/guides/uxp-guide/uxp-misc/manifest-v5/
- Adobe Photoshop Layer API: https://developer.adobe.com/photoshop/uxp/2022/ps-reference/classes/layer
- Adobe Photoshop Document API: https://developer.adobe.com/photoshop/uxp/2022/ps-reference/classes/document
- Adobe UXP Folder API: https://developer.adobe.com/photoshop/uxp/2022/uxp/reference-js/Modules/uxp/Persistent%20File%20Storage/Folder/

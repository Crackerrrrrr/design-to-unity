# Design to Unity

This MCP server extracts Lanhu design pages into platform-neutral Design Implementation Packets.

The default flow is information-first: it provides structured design facts, downloaded assets, and target handoff profiles so an AI assistant can call the proper target-platform MCP to implement the UI.

It also includes an explicit Unity path that can write a static UGUI prefab YAML directly. For the current PSD-to-Unity milestone, the accepted loop is direct prefab YAML plus source map, static verification, Unity-side validator, and Unity MCP smoke checks; a full Unity Editor API importer is treated as future work.

PSD / PSB is now supported as a local source adapter. See [PSD到Unity预制体扩展方案.md](PSD到Unity预制体扩展方案.md).

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

## Tools

- `lanhu_design_list`
- `lanhu_design_prepare_packet`
- `lanhu_design_get_packet`
- `lanhu_design_get_summary`
- `lanhu_design_get_node_tree`
- `lanhu_design_get_node_detail`
- `lanhu_design_get_asset_manifest`
- `lanhu_design_get_slices`
- `lanhu_design_get_unity_plan`
- `lanhu_design_write_unity_prefab_yaml`
- `lanhu_design_verify_unity_prefab_yaml`
- `lanhu_design_get_handoff_profile`

## PSD Tools

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

The PSD adapter parses local `.psd` / `.psb` files with `psd-tools`, exports layer PNGs, keeps text editable through `TextMeshProUGUI` by default, and emits component semantics for `Button`, `Slider`, `ProgressBar`, `Toggle`, `ToggleGroup` tabs/radio groups, `TMP_InputField`, `TMP_Dropdown`, `ScrollRect`, `Scrollbar`, rectangular `RectMask2D` clipping containers, and repeated-content `LayoutGroup` containers. Slider track/fill/handle, Toggle state graphic, tab/radio ToggleGroup membership/default selection, TMP input text/placeholder references, TMP dropdown caption/template/item references, mask/clip RectMask2D hints, ScrollRect viewport/content/scrollbar references, and Vertical/Horizontal/GridLayoutGroup hints are bound when the PSD layer structure can be inferred safely.

It also exposes complex Photoshop feature risks in packet metadata and readiness reports, including masks, clipping, non-normal blend modes, smart objects, adjustment layers, and layer effects.

For higher fidelity PSD flows, Photoshop or a UXP script can export `design.json`, `preview.png`, and `assets/*.png`; call `psd_design_prepare_export_packet` or `psd_design_convert_export_to_unity_prefab` to reuse the same Unity plan, prefab writer, source map, readiness report, and visual diff tools.

A starter Photoshop UXP exporter lives in [templates/photoshop-uxp-exporter](templates/photoshop-uxp-exporter). Load that folder with Adobe UXP Developer Tool, export the active PSD, then pass the export folder to the MCP tools below. The exporter writes `rasterized: true` for Photoshop-rendered complex groups so the MCP treats them as one trusted PNG instead of duplicating child layers.

Photoshop/UXP manifests can explicitly provide nine-slice data on a layer with `nine_slice`, `nineSlice`, `spriteBorder`, or `sprite_border`. When a border is present, the direct Unity writer sets the copied Sprite `.meta` `spriteBorder`, emits a sliced UGUI `Image`, preserves the border in the source map, and the static verifier checks the meta border against the source map.

For complex game PSDs that rely on Photoshop-only blend modes, masks, smart objects, or layer effects, use a Photoshop-rendered preview as `reference_image_path` and write the prefab with `prefab_visual_mode="flattened_reference_overlay"`. That mode uses the true Photoshop preview as the visible baseline, keeps PSD nodes in the source map, and adds transparent interactive overlays such as Button hit areas and editable TMP text metadata.

Before preparing an export packet, call:

```text
psd_design_get_export_schema()
psd_design_validate_export(export_path)
```

The validator catches missing preview files, missing layer assets, invalid bounds, duplicate ids, and complex Photoshop feature warnings before Unity files are written.

For the shortest Unity flow, call:

```text
psd_design_convert_to_unity_prefab(file_path, unity_project_path)
```

It prepares the packet, exports slices, writes the prefab YAML/source map into the Unity project, and returns both a readiness report and a static prefab verification report.

For a Photoshop-rendered export directory, call:

```text
psd_design_convert_export_to_unity_prefab(export_path, unity_project_path)
```

After direct YAML generation, call:

```text
psd_design_verify_unity_prefab_yaml(unity_project_path, prefab_asset_path, source_map_asset_path)
```

The verifier checks the generated prefab/source-map pair before Unity import. It catches missing files, broken local fileID references, sprite meta GUID mismatches, nine-slice spriteBorder mismatches, source-map count mismatches, LayoutGroup count mismatches, and unbound Slider/Button/Toggle/ToggleGroup tab/radio/TMP_InputField/TMP_Dropdown/ScrollRect references that need review.

To validate the imported prefab inside Unity, install the optional Editor script:

```text
psd_design_install_unity_editor_validator(unity_project_path)
```

Unity will then expose `Tools/Design To Unity/Validate Selected Prefab`, plus a batchmode entry point: `DesignToUnityPrefabValidator.ValidateFromCommandLine`. The Unity-side report checks imported component counts against `unity_import_manifest.expected_components`, source map import, Sprite references, TMP fonts, Button target graphics, Slider bindings, Toggle target/state graphics, ToggleGroup tab/radio membership, TMP_InputField text bindings, TMP_Dropdown template/text bindings, ScrollRect bindings, Scrollbar handle/target bindings, and LayoutGroup component counts.

The same installed Editor script also exposes `DesignToUnityPrefabValidator.CapturePrefabFromCommandLine`, which renders the generated prefab to a PNG. Feed that PNG to `psd_design_compare_unity_screenshot` for the automated visual QA loop.

Current Unity MCP smoke coverage:

- MCP endpoint: `DesignToUnity` starts on `http://127.0.0.1:8125/mcp`; `tools/list` exposes PSD tools, and `psd_design_convert_to_unity_prefab` has been called through MCP JSON-RPC successfully.
- Real PSD image page: `/Users/shangfei/Downloads/75-76/75/图集/旧.psd` imports into `/Users/shangfei/myproject/LanHuMcp` with `34` GameObjects, `33` Images, no missing sprites, and a `pass` Unity import report.
- Semantic component prefab: `SemanticComponentSmoke.prefab` imports with `Button=1`, `Slider=1`, `ScrollRect=1`, `RectMask2D=1`, `TextMeshProUGUI=2`, `Image=11`, and a clean `pass` Unity import report through Unity MCP `http://127.0.0.1:8785`.
- Tab smoke prefab: `Assets/DesignToUnityTabSmoke/f06f44f4a3dad7902e8e/Prefabs/TabSmoke.prefab` imports with `ToggleGroup=1`, `Toggle=2`, both tabs bound to the same group, exactly one default selected tab, and source map import verified through Unity MCP.
- Nine-slice smoke prefab: `Assets/DesignToUnityNineSliceSmoke/a2986acc0fc876d2a971/Prefabs/NineSliceSmoke.prefab` imports with `Image.Type=Sliced`, `Sprite.border=(16,8,16,8)`, and source map border verified through Unity MCP.
- LayoutGroup smoke prefab: `Assets/DesignToUnityLayoutSmoke/6b4b1da04ffc4f3536cc/Prefabs/LayoutSmoke.prefab` imports with `VerticalLayoutGroup=1`, `HorizontalLayoutGroup=1`, `GridLayoutGroup=1`, grid `FixedColumnCount=2`, and source map import verified through Unity MCP.
- Auto capture: `DesignToUnityPrefabValidator.CapturePrefab` wrote `OldPsd_CurrentCodeSmoke.auto-unity-screenshot.png`; visual diff against the PSD reference passed with `mean_abs_delta=0.001419` and `mismatch_ratio=0.009735`.
- Complex game PSD overlay: `/Users/shangfei/Downloads/游戏页面_爱给网_aigei_com/游戏页面/素材CNN sccnn.com _201312141503.psd` plus Photoshop preview `/Users/shangfei/Downloads/20260622-142307.png` generated `AigeiGamePageOverlay.prefab` with `Button=6`, `TextMeshProUGUI=8`, `Image=7`, `copied_asset_count=1`, Unity import report `pass`, and visual diff `mean_abs_delta=0`, `mismatch_ratio=0`.

After Unity MCP captures the generated prefab or scene, call:

```text
psd_design_compare_unity_screenshot(packet_id, screenshot_path)
```

It compares the Unity screenshot with the flattened PSD reference, writes a diff heatmap PNG, and returns mean delta / RMSE / mismatch ratio metrics for visual QA.

## Direct Unity Prefab YAML

`lanhu_design_write_unity_prefab_yaml` and `psd_design_write_unity_prefab_yaml` write:

- copied sprite files under a Unity `Assets/...` folder
- generated `.png.meta` files with deterministic GUIDs
- a `.prefab` YAML file containing `GameObject`, `RectTransform`, `CanvasRenderer`, `Image`, `TextMeshProUGUI`, `Button`, `Slider`, `Toggle`, `ToggleGroup`, `TMP_InputField`, `TMP_Dropdown`, `ScrollRect`, `Scrollbar`, `RectMask2D`, `VerticalLayoutGroup`, `HorizontalLayoutGroup`, `GridLayoutGroup`, and `CanvasGroup` components
- a `.prefab.meta` file when needed
- a sibling `*.design-to-unity.json` source map for node ids, source paths, content hashes, component fileIDs, and inferred bindings
- a Unity import manifest inside the source map with expected component counts, validation gates, and reimport/update policy hints

This path is best for static UI restoration, editable TMP text, basic interaction candidates, and prefab diffs. A production-grade Unity Editor API importer, project-specific import rules, animation binding, and custom script wiring are outside the current milestone.

## Verified With Lanhu

The `-h-海报分享` design page has been prepared successfully:

- 77 normalized nodes
- 77 downloaded assets, including the full design reference
- 76 slice-backed nodes with positions
- 0 failed downloads
- Unity plan output with asset imports, parent ids, component hints, and rect hints
- Direct prefab YAML writer smoke test in a mock Unity project: 77 GameObjects, 65 Images, 11 TextMeshProUGUI components, 10 Buttons, 65 copied sprites
- Summary output with semantic counts, asset roles, warning counts, and Unity readiness
- Asset roles include `background`, `button_sprite`, `icon`, `text_sprite`, `panel`, and `design_reference`

## Verified With PSD

The PSD pipeline has been smoke-tested with fake semantic PSD data and real local PSD files:

- fake PSD coverage for editable TMP text, Button, Slider fill/handle binding, Toggle state binding, Tab and radio ToggleGroup binding, TMP_InputField text binding, TMP_Dropdown template/caption/item binding, mask_candidate RectMask2D, ScrollRect/Scrollbar/RectMask2D, VerticalLayoutGroup, CanvasGroup, and source map output
- fake PSD coverage for mask, clipping, blend mode, smart object, and adjustment-layer warnings
- fake Photoshop/UXP export coverage for `design.json`, preview reference, layer PNG assets, explicit nine-slice spriteBorder, TMP text, Button, Slider, Toggle, ToggleGroup tabs/radio groups, mask_candidate RectMask2D, Vertical/Horizontal/GridLayoutGroup, TMP_InputField, TMP_Dropdown, source map, readiness report, and visual diff
- Photoshop/UXP export validator coverage for schema, missing preview, missing layer asset, invalid bounds, and complex feature warnings
- Unity Editor validator template coverage for install path, menu/command-line entry point, expected component checks, and TMP/UI component checks
- real PSD atlas import from `/Users/shangfei/Downloads/75-76/75/图集/旧.psd`
- generated Unity prefab imported through `/Users/shangfei/myproject/LanHuMcp`
- 33 Image components, 0 missing Sprite references, source map imported as TextAsset
- visual diff helper tested against matching and intentionally changed screenshots
- real Unity-rendered prefab screenshot compared against the PSD reference: `mean_abs_delta=0.001419`, `mismatch_ratio=0.009735`, status `pass`
- complex PSD fallback coverage for all-hidden layers, external Photoshop preview references, `flattened_reference_overlay`, inferred text-on-button hit areas, and visual diff `needs_review` when only best-effort layer-composed references are available
- static prefab verifier coverage for source-map count checks, local fileID references, sprite/meta GUID consistency, and component binding warnings
- Unity MCP reported no compilation errors after import

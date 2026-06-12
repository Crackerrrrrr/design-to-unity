# lanhu-unity-handoff-mcp

This MCP server extracts Lanhu design pages into Unity-ready Design Implementation Packets.

The default flow is information-first: it provides structured design facts, downloaded assets, and target handoff profiles so an AI assistant can call the proper target-platform MCP to implement the UI.

It also includes an explicit experimental Unity path that can write a static UGUI prefab YAML directly. Use that path when you want a fast prefab snapshot without going through Unity MCP or Unity Editor APIs.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set `LANHU_COOKIE` in `.env`, then run:

```bash
lanhu-unity-handoff-mcp
```

For stdio clients:

```bash
MCP_TRANSPORT=stdio lanhu-unity-handoff-mcp
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
- `lanhu_design_get_handoff_profile`

## Direct Unity Prefab YAML

`lanhu_design_write_unity_prefab_yaml` writes:

- copied sprite files under a Unity `Assets/...` folder
- generated `.png.meta` files with deterministic GUIDs
- a `.prefab` YAML file containing `GameObject`, `RectTransform`, `CanvasRenderer`, `Image`, `TextMeshProUGUI`, `Button`, and `Slider` components
- a `.prefab.meta` file when needed

This is intentionally marked experimental. It is best for static UI restoration, editable TMP text, basic interaction candidates, and prefab diffs. For production output with custom scripts, exact TMP font assets, layout components, animation, or project-specific import rules, keep using the Unity MCP / Unity Editor API flow.

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

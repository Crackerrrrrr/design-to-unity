# FunPlayLanhuGameMcp

This MCP server extracts Lanhu design pages into platform-neutral Design Implementation Packets.

The server does not edit Unity, Cocos, Godot, Unreal, or frontend projects directly. It provides structured design facts, downloaded assets, and target handoff profiles so an AI assistant can call the proper target-platform MCP to implement the UI.

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

Set `LANHU_COOKIE` in `.env`, then run:

```bash
FunPlayLanhuGameMcp
```

For stdio clients:

```bash
MCP_TRANSPORT=stdio FunPlayLanhuGameMcp
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
- `lanhu_design_get_handoff_profile`

## Verified With Lanhu

The `-h-海报分享` design page has been prepared successfully:

- 77 normalized nodes
- 77 downloaded assets, including the full design reference
- 76 slice-backed nodes with positions
- 0 failed downloads
- Unity plan output with asset imports, parent ids, component hints, and rect hints
- Summary output with semantic counts, asset roles, warning counts, and Unity readiness
- Asset roles include `background`, `button_sprite`, `icon`, `text_sprite`, `panel`, and `design_reference`

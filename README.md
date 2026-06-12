# lanhu-unity-handoff-mcp

English | [中文](README.zh-CN.md)

`lanhu-unity-handoff-mcp` is an MCP server that reads Lanhu design pages and turns them into Unity-ready Design Implementation Packets.

The default workflow is information-first: the server extracts structured design facts, downloads assets, builds a node tree, and returns Unity handoff plans so an AI assistant can call the right Unity MCP or editor-side tool to implement the UI.

It also includes an experimental direct Unity path that writes a static UGUI prefab YAML snapshot. Use that only when you want a fast, inspectable prefab draft without going through Unity MCP or Unity Editor APIs.

## Why This MCP

- Works with Unity MCP: this server can provide clean design facts, asset paths, RectTransform hints, node hierarchy, and ordered Unity creation plans, then let Unity MCP or Unity Editor APIs create the final UI inside your real project.
- Can generate prefabs directly: when you need a quick static result, `lanhu_design_write_unity_prefab_yaml` can write sprites, `.meta` files, and a UGUI `.prefab` YAML snapshot without opening Unity.
- Recognizes common UI components: the normalizer marks likely buttons, text, icons, backgrounds, panels, list items, titles, progress bars, and sliders so an AI assistant has useful semantic hints instead of raw layer names only.
- Produces implementation-ready packets: each packet contains normalized nodes, downloaded assets, asset roles, local and Unity paths, coordinates, style/text data, warnings, and target handoff profiles.
- Supports staged AI reading: assistants can start with summaries, then request node trees, selected node details, slices, or a Unity plan, which avoids dumping the whole design into one oversized response.
- Keeps production control in your hands: the default path does not edit your Unity project directly, so custom scripts, animations, prefab variants, event bindings, and import settings can stay under your project pipeline.

## What You Need

- Python 3.10 or newer.
- A Lanhu account that can access the target design project.
- The Lanhu design URL you want to process.
- A Lanhu browser session cookie copied from your own logged-in browser.
- Optional: a Unity project if you want to export a direct UGUI prefab YAML snapshot.

Never commit your real cookie. Keep it only in your local `.env` file.

## 1. Get Your Lanhu Cookie

The server uses your Lanhu cookie to call the same design data endpoints your browser can access after login.

1. Open [Lanhu](https://lanhuapp.com) in Chrome or another Chromium-based browser.
2. Log in with the account that can open the target project.
3. Open the target design project page.
4. Open Developer Tools:
   - macOS: `Option + Command + I`
   - Windows/Linux: `Ctrl + Shift + I`
5. Go to the `Network` tab.
6. Refresh the Lanhu page while DevTools stays open.
7. Click a request whose domain is `lanhuapp.com` or `dds.lanhuapp.com`.
8. In `Headers`, find `Request Headers`.
9. Copy the full value of the `Cookie` request header.

The copied value usually looks like one long line with many `key=value` pairs separated by semicolons:

```text
key1=value1; key2=value2; key3=value3
```

Do not copy only one cookie item. Copy the whole `Cookie:` request header value.

If assets fail to download later, repeat the same process on a `dds.lanhuapp.com` request and put that value in `DDS_COOKIE`. In most cases, `LANHU_COOKIE` is enough.

## 2. Install

Clone the repository and create a virtual environment:

```bash
gh repo clone Crackerrrrrr/lanhu-unity-handoff-mcp
cd lanhu-unity-handoff-mcp

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

If you do not use GitHub CLI:

```bash
git clone https://github.com/Crackerrrrrr/lanhu-unity-handoff-mcp.git
cd lanhu-unity-handoff-mcp

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 3. Configure `.env`

Create a local `.env` file:

```bash
cp .env.example .env
```

Open `.env` and paste your full cookie:

```bash
LANHU_COOKIE="key1=value1; key2=value2; key3=value3"
DATA_DIR=./data
HTTP_TIMEOUT=30
SERVER_HOST=127.0.0.1
SERVER_PORT=8125
MCP_TRANSPORT=http
DEFAULT_IMAGE_SCALE=2x
MAX_NODES_PER_RESPONSE=200
DEBUG=false
```

Only set `DDS_COOKIE` if Lanhu image assets require a different cookie:

```bash
DDS_COOKIE="key1=value1; key2=value2; key3=value3"
```

Recommended rule: if you are not sure, leave `DDS_COOKIE` unset.

## 4. Run As An HTTP MCP Server

Start the server:

```bash
lanhu-unity-handoff-mcp
```

By default it listens at:

```text
http://127.0.0.1:8125/mcp
```

Example MCP client config:

```json
{
  "mcpServers": {
    "LanhuUnityHandoffMcp": {
      "url": "http://localhost:8125/mcp"
    }
  }
}
```

## 5. Run As A Stdio MCP Server

For MCP clients that start local commands directly, use the included script:

```bash
./run-stdio.sh
```

Example MCP client config:

```json
{
  "mcpServers": {
    "LanhuUnityHandoffMcp": {
      "command": "/absolute/path/to/lanhu-unity-handoff-mcp/run-stdio.sh"
    }
  }
}
```

For Codex CLI, a typical registration command is:

```bash
codex mcp add lanhu-unity-handoff-mcp -- /absolute/path/to/lanhu-unity-handoff-mcp/run-stdio.sh
```

Restart the MCP client after changing its MCP configuration.

## 6. Basic Workflow

Use these tools in order.

1. List Lanhu design pages:

```text
lanhu_design_list(url="<Lanhu project or design URL>")
```

2. Prepare a Design Implementation Packet:

```text
lanhu_design_prepare_packet(
  url="<Lanhu project or design URL>",
  design_name_or_index="<design name or list index>",
  target="unity"
)
```

This downloads source data and assets into `DATA_DIR`, then returns a `packet_id`.

3. Read the implementation summary:

```text
lanhu_design_get_summary(packet_id="<packet_id>")
```

4. Read the Unity execution plan:

```text
lanhu_design_get_unity_plan(packet_id="<packet_id>")
```

5. Read image slices and positions:

```text
lanhu_design_get_slices(packet_id="<packet_id>")
```

6. Ask your Unity MCP or Unity Editor tool to import the assets and create the UI using the plan.

## 7. Direct Unity Prefab YAML Export

The direct YAML writer is experimental. It is useful for quick static UGUI snapshots, prefab diffs, and visual inspection. For production UI with project scripts, animations, exact TMP fonts, or custom import rules, prefer a Unity MCP or Unity Editor API importer.

Call:

```text
lanhu_design_write_unity_prefab_yaml(
  packet_id="<packet_id>",
  unity_project_path="/absolute/path/to/YourUnityProject",
  asset_root="Assets/DesignHandoff/LanhuUnityHandoffMcp",
  prefab_name="LanhuGenerated.prefab",
  overwrite=true
)
```

It writes:

- copied sprite files under the chosen Unity `Assets/...` folder
- generated `.png.meta` files with deterministic GUIDs
- a `.prefab` YAML file with UGUI objects and components
- a `.prefab.meta` file when needed

The generated prefab can include `GameObject`, `RectTransform`, `CanvasRenderer`, `Image`, `TextMeshProUGUI`, `Button`, and `Slider` components.

## Tool Reference

- `lanhu_design_list`: list design pages in a Lanhu project.
- `lanhu_design_prepare_packet`: fetch design data, normalize nodes, download assets, and create a packet.
- `lanhu_design_get_packet`: return the full packet.
- `lanhu_design_get_summary`: return a compact AI-friendly implementation summary.
- `lanhu_design_get_node_tree`: return a trimmed node hierarchy.
- `lanhu_design_get_node_detail`: return full details for selected nodes.
- `lanhu_design_get_asset_manifest`: return downloaded assets and Unity import hints.
- `lanhu_design_get_slices`: return image-backed nodes with local asset paths and rect hints.
- `lanhu_design_get_unity_plan`: return ordered Unity creation/import steps.
- `lanhu_design_write_unity_prefab_yaml`: experimentally write a static Unity UGUI prefab YAML.
- `lanhu_design_get_handoff_profile`: return target-platform handoff rules.

## Troubleshooting

If Lanhu requests fail with authorization errors:

- Make sure you copied the full `Cookie` request header value.
- Make sure the browser account can open the target project.
- Refresh Lanhu, copy a fresh cookie, and update `.env`.
- Restart the MCP server after editing `.env`.

If assets are missing:

- Copy a cookie from a `dds.lanhuapp.com` request.
- Add it to `.env` as `DDS_COOKIE="..."`.
- Run `lanhu_design_prepare_packet` again.

If the MCP client cannot see the tools:

- Confirm the server is running.
- Confirm the MCP URL is `http://localhost:8125/mcp` for HTTP mode.
- Confirm `run-stdio.sh` uses an absolute path for stdio mode.
- Restart the MCP client after configuration changes.

If Unity prefab export fails:

- Make sure `unity_project_path` points to a Unity project root that contains an `Assets` folder.
- Make sure `asset_root` starts with `Assets/`.
- Close Unity or let Unity reimport after files are written.

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

# Publishing Guide

This guide is the release checklist for Design to Unity.

## 1. Version Check

Keep these versions aligned:

- `pyproject.toml` -> `project.version`
- `server.json` -> `version`
- `server.json` -> `packages[0].version`
- `CHANGELOG.md` release heading

The MCP Registry server name is:

```text
io.github.crackerrrrrr/design-to-unity
```

The PyPI package README must contain:

```html
<!-- mcp-name: io.github.crackerrrrrr/design-to-unity -->
```

## 2. Local Validation

```bash
python -m pip install -e ".[dev]"
python -m compileall -q src templates
python -m pytest -q
python -m json.tool server.json >/tmp/design-to-unity-server.json
curl -fsSL https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json -o /tmp/mcp-server.schema.json
python - <<'PY'
import json
from pathlib import Path
import jsonschema

schema = json.loads(Path("/tmp/mcp-server.schema.json").read_text())
instance = json.loads(Path("server.json").read_text())
jsonschema.Draft7Validator.check_schema(schema)
jsonschema.validate(instance=instance, schema=schema)
print("server-schema-ok")
PY
```

## 3. Build And Upload To PyPI

```bash
rm -rf dist build
python -m build
python -m twine check dist/*
python -m twine upload dist/*
```

After upload, confirm the package page contains the hidden `mcp-name` comment in the rendered project description source.

## 4. Publish To MCP Registry

Install or update the publisher tool following the official MCP Registry quickstart, then:

```bash
mcp-publisher login github
mcp-publisher publish
```

If the publisher reports package ownership verification issues, confirm that:

- `server.json` uses the exact PyPI package name `design-to-unity`.
- `README.md` contains the exact hidden `mcp-name` comment.
- The PyPI package was uploaded after the README comment was added.

## 5. GitHub Repository Setup

Recommended GitHub About description:

```text
MCP server that converts Lanhu, Figma, PSD, and Photoshop UI designs into Unity UGUI handoff packets and prefabs.
```

Recommended topics:

```text
mcp
model-context-protocol
unity
ugui
figma
lanhu
psd
photoshop
design-to-code
game-ui
unity-editor
prefab
```

## 6. Directory Submissions

After PyPI and MCP Registry are live, submit the repository to MCP directories and communities:

- Official MCP Registry
- GitHub MCP Registry
- mcp.so
- Glama MCP servers
- Smithery
- PulseMCP
- V2EX, Reddit, Hacker News, X, Zhihu, Juejin, Bilibili, and Unity communities

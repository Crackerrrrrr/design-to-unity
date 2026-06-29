# Launch Kit

## GitHub Release Title

```text
Design to Unity v0.1.0 - Lanhu, Figma, PSD, and Photoshop UI to Unity MCP
```

## GitHub Release Body

````markdown
Design to Unity v0.1.0 is the first public release of our MCP server for turning game UI design sources into Unity-ready implementation data.

It supports Lanhu, Figma, PSD / PSB, and Photoshop UXP exports, then normalizes them into design handoff packets with node trees, geometry, text, assets, source semantics, reusable prefab hints, readiness reports, source maps, and Unity prefab outputs.

Highlights:

- Lanhu design page extraction with slices, Unity plan, and static prefab YAML output
- Figma REST, snapshot, plugin export, batch packet, and prefab workflows
- PSD / PSB and Photoshop UXP export workflows
- Unity Editor importer and validator templates
- Source maps, visual diff, TMP font mapping, resource deduplication, reusable prefab registry, variant groups, and 9-slice hints
- MCP Registry-ready metadata through `server.json`

Install from source:

```bash
git clone https://github.com/Crackerrrrrr/design-to-unity.git
cd design-to-unity
python -m venv .venv
source .venv/bin/activate
pip install -e .
MCP_TRANSPORT=stdio DesignToUnity
```

The project is early, but already designed around production UI iteration: AI agents get structured design facts instead of screenshots, and Unity teams get inspectable source maps and importer inputs instead of one-off generated output.
````

## Chinese Launch Post

```markdown
我们开源了 Design to Unity v0.1.0：一个面向游戏 UI 落地的 MCP 服务。

它可以把蓝湖、Figma、PSD / PSB、Photoshop UXP 导出物转换成统一的 Design Implementation Packet，并继续输出 Unity 可用的资源清单、节点树、布局坐标、文本、组件提示、source map、readiness report、视觉 diff，以及 UGUI prefab YAML / Unity Editor importer 输入。

简单说，它不是“截图转 UI”，而是把设计稿整理成 AI 和 Unity 都能读懂的结构化实现计划：

- 支持蓝湖设计页和切图
- 支持 Figma REST、snapshot、插件导出和批量页面 / 组件处理
- 支持 PSD / PSB 和 Photoshop UXP 导出目录
- 支持 Unity 静态 prefab YAML、source map、Editor importer 和 validator
- 支持 TMP 字体映射、资源去重、可复用 prefab、variant、9-slice 和视觉差异检查

仓库地址：
https://github.com/Crackerrrrrr/design-to-unity

我们希望它能帮助游戏团队把设计稿到 Unity UI 的还原过程变得更可检查、更可复用，也更适合 AI agent 协作。
```

## English Launch Post

```markdown
We just open-sourced Design to Unity v0.1.0, an MCP server for turning game UI design sources into Unity-ready handoff data.

It reads Lanhu, Figma, PSD / PSB, and Photoshop UXP exports, then produces structured packets with node trees, geometry, text, assets, component hints, source maps, readiness reports, visual diff support, and UGUI prefab outputs.

The goal is not screenshot-to-UI magic. The goal is to give AI agents and Unity tools a low-ambiguity implementation plan they can inspect, update, and continue from.

Highlights:

- Lanhu, Figma, PSD / PSB, and Photoshop UXP source coverage
- Figma REST, snapshot, plugin-export, batch page, and component workflows
- Static Unity prefab YAML writer
- Unity Editor importer / validator templates
- Source maps, TMP font mapping, reusable prefab registry, variant groups, 9-slice hints, resource deduplication, and visual diff

GitHub:
https://github.com/Crackerrrrrr/design-to-unity
```

## Short Demo Script

```text
1. Open a Lanhu / Figma / PSD source.
2. Call the MCP prepare-packet tool.
3. Show the generated summary, node tree, asset manifest, and Unity plan.
4. Generate Unity prefab YAML or install the Unity Editor importer.
5. Open Unity and inspect the source-map-backed prefab.
6. Run readiness report / visual diff to show what still needs human review.
```

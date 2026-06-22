# PSD 到 Unity 预制体扩展方案

## 1. 目标

在现有蓝湖 MCP 已经具备较完整 Design Implementation Packet、Unity Handoff Profile、Unity prefab YAML writer 的基础上，扩展本地 PSD / PSB 文件输入能力。

目标不是重新写一条 PSD 专用链路，而是让 PSD 成为新的 Source Adapter：

```text
PSD / PSB
  ↓
PSD Source Adapter
  ↓
Design Implementation Packet
  ↓
Unity Handoff Profile
  ↓
Unity MCP 或 Direct Prefab YAML Writer
  ↓
Unity prefab
```

这样蓝湖、PSD、后续 Figma / Sketch 都可以共享同一套：

- 节点树。
- 切图资源。
- 文本信息。
- 坐标转换。
- 语义识别。
- Unity 执行计划。
- 直接 prefab YAML 写入能力。

## 2. 推荐路线

### 2.1 第一阶段：离线 PSD 解析

第一阶段使用 Python 侧 PSD 解析器读取本地 PSD 文件，生成 packet。

推荐以 `psd-tools` 为核心：

- 读取 PSD / PSB 基础结构。
- 遍历图层和分组。
- 获取画布尺寸。
- 获取图层 bbox。
- 获取图层名称、可见性、透明度。
- 导出像素图层为 PNG。
- 尝试读取文本图层内容和样式。

第一阶段的目标是稳定生成可落地 Unity prefab，不追求 100% 还原 Photoshop 的所有高级效果。

适合支持：

- 普通像素图层。
- 普通分组。
- 普通文本图层。
- 透明 PNG 切图。
- 基础不透明度。
- 基于图层名的按钮、进度条、滑块、开关、页签语义识别。
- 基于子图层名称和几何关系推断 Slider 的 track / fill / handle。
- 基于重复子节点几何关系推断 Vertical / Horizontal / Grid LayoutGroup。

第一阶段不强制支持：

- 完整图层样式还原。
- 智能对象内部结构解析。
- 复杂蒙版。
- 剪贴蒙版精确拆解。
- 混合模式精确还原。
- Photoshop 调整图层。

遇到这些高级能力时，优先把图层或分组整体 rasterize 成 PNG，以视觉还原为先。

### 2.2 第二阶段：Photoshop UXP 高保真导出器

第二阶段增加 Photoshop UXP 插件或脚本，由 Photoshop 自己负责高保真渲染。

UXP 导出器输出：

```text
export/
  design.json
  preview.png
  assets/
    layer_xxx.png
    group_xxx.png
```

`design.json` 应包含：

- 文档尺寸。
- 图层树。
- 图层 bbox。
- 图层类型。
- 文本内容和文本样式。
- 图层不透明度。
- 是否为智能对象。
- 是否有蒙版、剪贴蒙版、图层样式、混合模式。
- 已导出切图资源路径。

MCP 读取这份导出物，再转换成 Design Implementation Packet。

当前仓库已提供一个基础模板：

```text
templates/photoshop-uxp-exporter/
  manifest.json
  index.html
  index.js
  sample-design.json
```

用 Adobe UXP Developer Tool 加载该目录后，可以在 Photoshop 中导出当前 PSD。模板会输出文档 preview、图层树、文本信息、图层 PNG，并在复杂分组使用 Photoshop 自身渲染结果时写入 `rasterized: true`。MCP 读取到该字段后会把该分组作为单张可信 PNG 处理，不再继续展开子图层。

这一阶段用于处理：

- 智能对象。
- 复杂图层样式。
- Photoshop 真实文本渲染。
- 复杂蒙版。
- 复杂混合模式。
- PSD 与 Photoshop 显示结果高度一致的需求。

## 3. MCP 工具设计

### 3.1 保留蓝湖工具

现有蓝湖工具继续保留：

```text
lanhu_design_list
lanhu_design_prepare_packet
lanhu_design_get_packet
lanhu_design_get_summary
lanhu_design_get_node_tree
lanhu_design_get_asset_manifest
lanhu_design_get_unity_plan
lanhu_design_write_unity_prefab_yaml
```

### 3.2 已实现 PSD 工具

第一版提供 PSD 前缀工具：

```text
psd_design_get_export_schema()
psd_design_validate_export(export_path)
psd_design_prepare_packet(file_path, target="unity", rasterize_mode="layer")
psd_design_prepare_export_packet(export_path, target="unity")
psd_design_get_summary(packet_id)
psd_design_get_node_tree(packet_id)
psd_design_get_node_detail(packet_id, node_ids)
psd_design_get_asset_manifest(packet_id)
psd_design_get_slices(packet_id)
psd_design_get_unity_plan(packet_id)
psd_design_get_unity_readiness_report(packet_id)
psd_design_compare_unity_screenshot(packet_id, screenshot_path)
psd_design_install_unity_editor_validator(unity_project_path)
psd_design_write_unity_prefab_yaml(packet_id, unity_project_path)
psd_design_verify_unity_prefab_yaml(unity_project_path, prefab_asset_path)
psd_design_convert_to_unity_prefab(file_path, unity_project_path)
psd_design_convert_export_to_unity_prefab(export_path, unity_project_path)
```

为了减少重复实现，除 `psd_design_prepare_packet` 外，其余工具复用现有 packet 查询和 Unity 写入逻辑。

其中 `psd_design_convert_to_unity_prefab` 是一键落地入口：

```text
本地 PSD / PSB
  ↓
prepare packet
  ↓
export layer PNG assets
  ↓
write Unity prefab YAML
  ↓
write source map
  ↓
return readiness report
```

返回结果必须包含：

- `packet_id` 与 `packet_path`。
- 导出的 `asset_dir`。
- `unity_prefab.prefab_asset_path`。
- `unity_prefab.source_map_asset_path`。
- `readiness_report.status`。
- `readiness_report.blockers`。
- `readiness_report.review_items`。
- `readiness_report.counts.component_candidates`。
- `readiness_report.counts.prefab_stats`。

`psd_design_prepare_export_packet` / `psd_design_convert_export_to_unity_prefab` 是 Photoshop 高保真导出物入口。它读取：

```text
export/
  design.json
  preview.png
  assets/
    layer_bg.png
    group_panel.png
    btn_start.png
```

`design.json` 支持宽松字段：

```json
{
  "document": {
    "name": "ShopPanel",
    "width": 1170,
    "height": 540,
    "scale": 1,
    "preview": "preview.png",
    "layers": [
      {
        "id": "btn_start",
        "name": "btn_start",
        "kind": "pixel",
        "role": "button_candidate",
        "bounds": {"x": 100, "y": 300, "width": 220, "height": 80},
        "asset": "assets/btn_start.png"
      }
    ]
  }
}
```

这一路线的职责边界：

- Photoshop / UXP 负责真实渲染 preview、layer PNG 或 group PNG。
- MCP 负责把导出物归一化成 Design Implementation Packet。
- 后续继续复用 `get_unity_plan`、`write_unity_prefab_yaml`、source map、readiness report 和 visual diff。

导出前后应先调用：

```text
psd_design_get_export_schema()
psd_design_validate_export(export_path)
```

validator 会检查：

- manifest 是否存在并且 JSON 可解析。
- document width / height 是否有效。
- preview / reference 是否存在。
- layer id 是否重复。
- 可见图层 bounds 是否有效。
- image / shape layer 是否有对应导出资源。
- asset 文件是否存在。
- mask、clipping、blend mode、smart object、adjustment layer 等复杂特性是否需要 review。

`psd_design_get_unity_readiness_report` 用于分步流。AI 在写 prefab 前可以先判断：

- 是否存在缺失资源。
- 是否没有可渲染节点。
- 是否有 Photoshop 图层效果需要视觉复核。
- editable TMP 文本是否需要字体、对齐、行高复核。
- Slider 的 fill / handle 是否绑定完整。
- ScrollRect 的 viewport / content / scrollbar 是否绑定完整。
- 是否存在低置信度语义识别。

`psd_design_compare_unity_screenshot` 用于视觉验收。Unity MCP 导入 prefab 后截图，再把截图路径交给本工具：

```text
Unity screenshot
  ↓
compare with PSD flattened reference
  ↓
write diff heatmap PNG
  ↓
return mean delta / RMSE / mismatch ratio
```

这让“是否还原成功”不只停留在组件数量验证，也能进入像素级 QA。

对于大量依赖 Photoshop 混合模式、蒙版、智能对象、图层特效的游戏 PSD，推荐使用双层策略：

```text
Photoshop-rendered preview.png / reference_image_path
  -> prefab_visual_mode = flattened_reference_overlay
  -> 真实预览图作为可见底图
  -> PSD 图层树继续进入 source map
  -> Button / Slider / ScrollRect / TMP 作为透明或可编辑覆盖层
```

这个模式不把 `OVERLAY`、`MULTIPLY`、`SCREEN`、`SOFT_LIGHT` 等 Photoshop-only 图层强行当普通 UGUI Image 叠加，避免黑块、光效块、蒙版丢失等问题。AI 仍可通过 source map 读取每个图层的位置、文字、语义候选和组件 fileID。

如果没有 Photoshop/UXP 真实预览图，只能用导出的单层 PNG 临时合成 reference，`psd_design_compare_unity_screenshot` 在复杂 PSD 上会返回 `needs_review`，保留差异指标和 diff PNG，但不会把这种 best-effort reference 误判成 prefab 必然失败。

`psd_design_verify_unity_prefab_yaml` 用于 direct YAML 的静态验收。它不替代 Unity 导入，但可以在打开 Unity 前先检查：

- prefab 文件和 source map 是否存在。
- source map schema 与统计是否匹配。
- prefab YAML 内部 fileID 引用是否断裂。
- source map 记录的 component fileID 是否真实存在。
- Sprite 文件、`.meta` 文件和 GUID 是否一致。
- 显式九宫格资源的 `nine_slice_hint.border` 是否和 `.png.meta` 中的 `spriteBorder` 一致。
- Slider fill/handle、ToggleGroup tab/radio group、ScrollRect content/viewport/scrollbar、Scrollbar handle、LayoutGroup 组件数量、Selectable target graphic、TMP font 是否存在未绑定项。
- `unity_import_manifest.expected_components` 是否和 prefab YAML 实际组件数量一致。

一键转换工具会自动返回 `unity_prefab_verification`，让 AI 可以先依据静态验收结果决定是否继续调用 Unity MCP。

`psd_design_install_unity_editor_validator` 用于把 Unity 侧验证脚本安装到目标项目：

```text
Assets/Editor/DesignToUnity/DesignToUnityPrefabValidator.cs
```

Unity 导入后可以通过菜单或命令行运行：

```text
Tools/Design To Unity/Validate Selected Prefab
DesignToUnityPrefabValidator.ValidateFromCommandLine
```

Unity 侧报告会验证 prefab 是否真的被 Unity 识别，包含组件数量、source map TextAsset、Sprite 绑定、TMP 字体、Button targetGraphic、Slider fill/handle、ToggleGroup tab/radio 绑定、ScrollRect content/viewport/scrollbar、Scrollbar handle 和 LayoutGroup 数量。

同一脚本还提供自动截图入口：

```text
DesignToUnityPrefabValidator.CapturePrefabFromCommandLine
```

Unity MCP 或 batchmode 可以用它把生成的 prefab 渲染为 PNG，然后把 PNG 路径传给 `psd_design_compare_unity_screenshot`。完整视觉验收链路为：

```text
psd_design_convert_to_unity_prefab
  -> Unity import report
  -> Unity prefab screenshot
  -> psd_design_compare_unity_screenshot
```

真实 PSD visual diff 已用于修正 PSD sibling 顺序：PSD 来源应按 `z_index` 升序写入同父节点，保证 Unity 后渲染的 sibling 覆盖前面的 sibling。修正后 `/Users/shangfei/Downloads/75-76/75/图集/旧.psd` 的 Unity 渲染截图对比 PSD reference 得到：

```text
status: pass
mean_abs_delta: 0.001419
rmse: 0.009134
mismatch_ratio: 0.009735
```

复杂游戏 PSD 已用 Photoshop 真实预览图验证 overlay 模式。`/Users/shangfei/Downloads/游戏页面_爱给网_aigei_com/游戏页面/素材CNN sccnn.com _201312141503.psd` 的 PSD 图层全部处于 hidden 状态，MCP 自动开启 hidden layer fallback，并使用 `/Users/shangfei/Downloads/20260622-142307.png` 作为 Photoshop reference。生成结果：

```text
prefab: Assets/DesignToUnityPsdOverlay/5dac398e1466a65ea6f4/Prefabs/AigeiGamePageOverlay.prefab
prefab_visual_mode: flattened_reference_overlay
Button: 6
TextMeshProUGUI: 8
Image: 7
copied_asset_count: 1
Unity import report: pass, 0 errors, 0 warnings
visual diff: pass
mean_abs_delta: 0
rmse: 0
mismatch_ratio: 0
```

本次样本还补了“文字叠在按钮底图上”的识别：当菜单文字位于矩形/图片底图内部时，底图节点会被标记为 `button_candidate`，并写入 `unity_button_hint.label` 与点击区域。该样本识别出 `War Begings`、`single game`、`single task`、`raffle mode`、`game settings`、`quit the game` 六个按钮。

### 3.3 后续统一工具命名

当 PSD 稳定后，可以抽象成统一 Source API：

```text
design_prepare_packet(source="lanhu" | "psd", input="url or file_path")
design_get_summary(packet_id)
design_get_node_tree(packet_id)
design_get_asset_manifest(packet_id)
design_get_unity_plan(packet_id)
design_write_unity_prefab_yaml(packet_id, unity_project_path)
```

短期不急着改名，避免破坏现有蓝湖工具调用习惯。

## 4. Packet 映射规范

PSD adapter 最终必须输出与蓝湖一致的 Design Implementation Packet。

### 4.1 source

```json
{
  "provider": "psd",
  "file_path": "/path/to/ui.psd",
  "file_name": "ui.psd",
  "file_hash": "sha1...",
  "mtime": 1780000000,
  "schema_source": "psd-tools"
}
```

如果来自 UXP 导出器：

```json
{
  "provider": "psd",
  "file_path": "/path/to/ui.psd",
  "export_path": "/path/to/export/design.json",
  "schema_source": "photoshop-uxp"
}
```

### 4.2 design

```json
{
  "name": "ShopPanel",
  "width": 1170,
  "height": 540,
  "scale": 1,
  "unit": "px",
  "coordinate_system": "top-left",
  "source_image_url": null
}
```

PSD 默认以文档像素为逻辑尺寸。是否引入 `scale=2/3/4`，应由用户配置或文件命名规则决定，例如 `@2x`、`@3x`。

### 4.3 node

PSD 图层节点应映射为：

```json
{
  "id": "psd_layer_123",
  "parent_id": "psd_group_1",
  "name": "btn_start",
  "unity_name_hint": "node_012_btn_start",
  "path": "Root/Footer/btn_start",
  "type": "image",
  "semantic_type": "button_candidate",
  "visible": true,
  "z_index": 12,
  "global_rect": {
    "x": 100,
    "y": 300,
    "width": 220,
    "height": 80
  },
  "local_rect": {
    "x": 20,
    "y": 10,
    "width": 220,
    "height": 80
  },
  "unity_rect_hint": {
    "anchorMin": [0, 1],
    "anchorMax": [0, 1],
    "pivot": [0, 1],
    "anchoredPosition": [20, -10],
    "sizeDelta": [220, 80]
  },
  "style": {
    "opacity": 1
  },
  "text": null,
  "asset_ref": "asset_btn_start",
  "source_metadata": {
    "source_provider": "psd",
    "source_node_id": "123",
    "source_path": "Root/Footer/btn_start",
    "psd_layer_kind": "pixel",
    "has_mask": false,
    "has_layer_effects": false,
    "blend_mode": "normal"
  }
}
```

### 4.4 asset

PSD 导出的切图资源：

```json
{
  "id": "asset_btn_start",
  "name": "btn_start",
  "type": "image",
  "remote_url": null,
  "local_path": "data/assets/psd/xxx/btn_start.png",
  "suggested_unity_path": "Assets/DesignToUnity/Sprites/btn_start.png",
  "format": "png",
  "size": {
    "width": 220,
    "height": 80
  },
  "logical_size": {
    "width": 220,
    "height": 80
  },
  "scale": 1,
  "has_alpha": true,
  "usage": "pixel_layer",
  "unity_import_hints": {
    "textureType": "Sprite",
    "spriteMode": "Single",
    "alphaIsTransparency": true,
    "sRGBTexture": true,
    "mipmapEnabled": false,
    "wrapMode": "Clamp",
    "filterMode": "Bilinear",
    "compression": "None",
    "pixelsPerUnit": 100
  }
}
```

## 5. PSD 图层到 Unity 的映射

### 5.1 基础映射

```text
PSD Document -> ViewRoot
PSD Group -> GameObject + RectTransform
Pixel Layer -> Image + Sprite
Smart Object -> Image + Sprite
Shape Layer -> Image + Sprite 或 Image + color
Text Layer -> TextMeshProUGUI
Hidden Layer -> 默认跳过
```

### 5.2 交互语义

图层名或路径命中以下规则时，写入语义候选：

```text
btn / button / 按钮 / start / play / close -> button_candidate
progress / loading / hp / exp / energy / 进度条 / 血条 -> progress_candidate
slider / thumb / handle / 滑块 -> slider_candidate
scroll / scrollview / viewport / content / list / grid / 滚动 / 滑动区域 -> scroll_area_candidate
title / 标题 / headline -> title_candidate
bg / background / 背景 -> background_candidate
icon / ico / close / arrow -> icon_candidate
item / cell / row / list -> list_item_candidate
```

直接 prefab YAML writer 的默认行为：

```text
button_candidate -> Button
progress_candidate -> Slider, interactable=false
slider_candidate -> Slider, interactable=true
toggle_candidate -> Toggle
tab_group_candidate / tab_candidate -> ToggleGroup + Toggle
radio_group_candidate / radio_candidate -> ToggleGroup + Toggle
mask_candidate -> RectMask2D
scroll_area_candidate -> ScrollRect + Scrollbar + RectMask2D/Mask + Content
repeated content/group -> VerticalLayoutGroup / HorizontalLayoutGroup / GridLayoutGroup
semi-transparent group -> CanvasGroup
text -> TextMeshProUGUI
```

当 PSD 中的 slider/progress 分组包含可识别的 `track`、`fill`、`handle/thumb` 子图层时，packet 会写入 `unity_slider_hint`：

```json
{
  "track_node_id": "track_bg_node_id",
  "fill_node_id": "fill_node_id",
  "handle_node_id": "handle_node_id",
  "value": 0.75,
  "requires_review": false
}
```

direct prefab YAML writer 会用该 hint 写入：

```text
Slider.m_FillRect = fill node RectTransform
Slider.m_HandleRect = handle node RectTransform
Slider.m_Value = inferred value
```

如果 PSD 是扁平进度条，没有可安全绑定的子图层，则只写入 `Slider.value`，并通过 `requires_review=true` 提醒 Unity 侧人工确认。

### 5.3 可滑动区域识别

PSD 中的可滑动区域通常不是单个图层，而是一个分组结构。识别时应优先以 group 为单位判断。

建议识别为：

```text
scroll_area_candidate
```

并进一步识别子角色：

```text
viewport_role
content_role
scroll_item_role
scrollbar_role
scrollbar_handle_role
```

### 5.3.1 识别信号

命名信号：

- group 名包含 `scroll`、`scrollview`、`viewport`、`content`。
- group 名包含 `list`、`grid`、`rank_list`、`mail_list`、`shop_list`。
- 中文名包含 `滚动`、`滑动区域`、`列表`、`背包`、`排行榜`。
- 子图层名包含 `item`、`cell`、`row`、`slot`。
- 子图层名包含 `scrollbar`、`bar`、`handle`、`thumb`。

几何信号：

- group 内存在多个尺寸接近、间距规律的 item。
- item 沿同一方向重复排列。
- content 高度明显大于 viewport 高度，或 content 宽度明显大于 viewport 宽度。
- viewport 区域通常有遮罩、裁剪、面板边界或背景框。
- 右侧或底部存在窄条状 scrollbar。

结构信号：

```text
ScrollArea
  ├── Viewport / Mask
  │   └── Content
  │       ├── Item_01
  │       ├── Item_02
  │       └── Item_03
  └── Scrollbar
      └── Handle
```

如果 PSD 没有明确 `Viewport` / `Content` 分组，但存在重复 item，也可以将外层 group 标记为 `scroll_area_candidate`，并写入 warning，提示需要确认 viewport 和 content。

### 5.3.2 方向判断

方向判断规则：

```text
item 的 y 变化明显、x 基本一致 -> vertical
item 的 x 变化明显、y 基本一致 -> horizontal
item 同时按行列重复 -> grid
```

输出建议：

```json
{
  "semantic_type": "scroll_area_candidate",
  "semantic_confidence": 0.82,
  "semantic_reasons": [
    "group name suggests scroll/list",
    "children repeat vertically with similar size"
  ],
  "unity_scroll_hint": {
    "can_add_scroll_rect": true,
    "default_add_scroll_rect": true,
    "direction": "vertical",
    "viewport_node_id": "node_viewport",
    "content_node_id": "node_content",
    "item_node_ids": ["item_01", "item_02", "item_03"],
    "requires_layout_review": true
  }
}
```

### 5.3.3 Unity 映射

直接 prefab YAML writer 的长期目标映射：

```text
scroll_area_candidate -> ScrollRect
scrollbar_candidate -> Scrollbar
scrollbar_handle_candidate -> Scrollbar.handleRect
viewport_role -> RectMask2D 或 Mask + Image
content_role -> RectTransform
scroll_item_role -> 普通子节点，后续可替换为 item prefab
scrollbar_role -> Scrollbar
scrollbar_handle_role -> Scrollbar handleRect
```

推荐 Unity 层级：

```text
ScrollArea
  ├── Viewport
  │   └── Content
  │       ├── Item_01
  │       ├── Item_02
  │       └── Item_03
  └── Scrollbar Vertical
      └── Sliding Area
          └── Handle
```

第一版输出：

- packet 标记 `scroll_area_candidate`。
- `unity_scroll_hint` 给出方向、viewport、content、items。
- Unity plan 提示可加 `ScrollRect`。
- Direct YAML writer 可在推断到可滑动区域时写入 `ScrollRect`，在 viewport 节点写入 `RectMask2D`，并在识别到 scrollbar/handle 时写入 `Scrollbar` 与 `handleRect`。
- Direct YAML writer 可在 content 或列表/grid 容器上写入 `VerticalLayoutGroup`、`HorizontalLayoutGroup` 或 `GridLayoutGroup`。

### 5.3.3 重复布局与 LayoutGroup

对于背包格子、排行榜列表、横向 chip/tab 列表这类重复内容，PSD/UXP 不要求显式写 Unity 组件名。MCP 会优先用父容器名称和直接子节点几何关系推断：

```text
单列重复项 -> VerticalLayoutGroup
单行重复项 -> HorizontalLayoutGroup
多行多列重复项 -> GridLayoutGroup
```

packet 中会写入：

```json
{
  "unity_layout_hint": {
    "component": "GridLayoutGroup",
    "direction": "grid",
    "item_node_ids": ["slot_01", "slot_02", "slot_03", "slot_04"],
    "cell_size": {"width": 54, "height": 40},
    "spacing": {"x": 16, "y": 12},
    "padding": {"left": 0, "right": 26, "top": 0, "bottom": 12},
    "constraint": "fixed_column_count",
    "constraint_count": 2,
    "requires_review": false
  }
}
```

Direct YAML 默认保留所有原始子节点，并额外添加 LayoutGroup 组件。为了避免导入时改变 PSD 静态视觉，`child_control_width`、`child_control_height`、`child_force_expand_width`、`child_force_expand_height` 默认都是 false；这个组件主要用于暴露布局语义，后续 Unity MCP 或人工可以再改成项目真正需要的自适应布局。

如果已经能确定 viewport 和 content，会写入：

```text
ScrollRect.m_Content = content RectTransform
ScrollRect.m_Viewport = viewport RectTransform
ScrollRect.m_HorizontalScrollbar / m_VerticalScrollbar = scrollbar component
Scrollbar.m_HandleRect = handle RectTransform
ScrollRect.m_Horizontal = direction in horizontal/grid
ScrollRect.m_Vertical = direction in vertical/grid
```

### 5.3.4 命名规范建议

为了提高 PSD 自动识别率，建议设计侧使用：

```text
scroll_mail
scroll_mail_viewport
scroll_mail_content
scroll_mail_item_01
scroll_mail_item_02
scroll_mail_scrollbar
scroll_mail_handle
```

或：

```text
list_shop
list_shop_viewport
list_shop_content
item_product_01
item_product_02
```

### 5.3.5 风险和 warning

需要写 warning 的情况：

- 只识别到重复 item，但无法确定 viewport。
- content 尺寸没有超过 viewport，可能只是静态列表。
- item 尺寸差异过大，可能不是滚动列表。
- 存在复杂遮罩或剪贴蒙版，离线 PSD 解析无法保证裁剪一致。
- scrollbar 存在但 handle 无法定位。

warning 示例：

```json
{
  "code": "scroll_area_requires_review",
  "severity": "medium",
  "message": "检测到疑似可滑动列表，但 viewport/content 关系不明确，Unity 中需要人工确认 ScrollRect 绑定。"
}
```

### 5.4 文本策略

第一阶段优先生成可编辑 TMP 文本：

- `content` -> `TextMeshProUGUI.text`
- `font_size` -> `TextMeshProUGUI.fontSize`
- `color` -> `TextMeshProUGUI.color`
- `align` -> `TextMeshProUGUI.alignment`
- `font_family` -> TMP Font Asset 候选，不保证自动匹配

如果文本层有复杂样式，例如：

- 多段混排。
- 描边。
- 阴影。
- 渐变。
- 变形文本。
- 图层样式。

则应增加 warning：

```json
{
  "code": "psd_text_complex_style",
  "severity": "medium",
  "message": "该 PSD 文本层存在复杂样式，TextMeshProUGUI 可能无法完全还原，建议导出文字切图或人工检查。"
}
```

工具参数应允许：

```text
use_text_components=true
```

当设置为 false 时，文本层按图片切图还原，以视觉一致性优先。

### 5.5 复杂 Photoshop 特性识别

第一阶段不会在 Unity 中重建 Photoshop 的完整渲染模型，但必须把高风险特性结构化暴露给 AI 和 Unity MCP。

PSD adapter 会在 `source_metadata` 写入：

```json
{
  "has_mask": true,
  "has_vector_mask": true,
  "has_clipping_mask": true,
  "has_layer_effects": true,
  "uses_non_normal_blend_mode": true,
  "is_smart_object": true,
  "is_adjustment_layer": true,
  "unsupported_psd_features": ["mask", "blend_mode", "smart_object"],
  "recommended_fidelity_mode": "group_or_document_rasterize"
}
```

对应 warning：

```text
psd_mask_requires_review
psd_clipping_mask_requires_review
psd_blend_mode_requires_review
psd_smart_object_rasterized
psd_adjustment_layer_requires_review
psd_layer_effect_requires_review
```

这些 warning 会进入 `psd_design_get_unity_readiness_report.review_items`。推荐策略：

- 简单图层继续按 Image / TMP / Button / Slider / ScrollRect / Scrollbar 落地。
- 含 mask、clipping、非 normal blend mode、smart object、adjustment layer 的区域优先使用 group rasterize。
- 如果视觉一致性要求高，改走 Photoshop UXP 导出器，让 Photoshop 自己输出 flatten/group PNG。
- 最终必须使用 `psd_design_compare_unity_screenshot` 做截图 diff。

## 6. PSD 解析模式

### 6.1 layer 模式

```text
rasterize_mode="layer"
```

每个可见像素图层独立导出 PNG。

优点：

- 图层结构完整。
- 方便后续绑定按钮、文本、图标。
- 节点粒度细。

缺点：

- 复杂蒙版和剪贴关系可能不完整。
- Unity 节点数量较多。

### 6.2 group 模式

```text
rasterize_mode="group"
```

对特殊分组整体导出 PNG。

适合：

- 复杂图层样式。
- 多图层组成的按钮背景。
- 弹窗底板。
- 不需要拆开的装饰组合。

缺点：

- 子结构减少。
- 文本和按钮语义可能需要额外保留 metadata。

### 6.3 hybrid 模式

```text
rasterize_mode="hybrid"
```

默认推荐的长期模式。

规则：

- 简单文本层保留为 TMP。
- 简单像素层导出为 Image。
- 命中按钮、进度条、滑块的组尽量保留结构。
- 命中复杂效果的图层或组整体 rasterize。
- 对无法判断的情况写 warning。

## 7. 缓存与目录结构

建议目录：

```text
data/
  psd_exports/
    {file_hash}/
      source_info.json
      preview.png
      packet.json
      assets/
        layer_001_bg.png
        layer_002_btn_start.png
  packets/
    {packet_id}.json
```

packet_id 建议：

```text
sha1("psd:{file_hash}:{mtime}:{rasterize_mode}:{target}")
```

缓存命中条件：

- PSD 文件路径相同。
- 文件 hash 相同。
- rasterize_mode 相同。
- target 相同。
- parser version 相同。

## 8. 第一版实现模块

建议新增文件：

```text
src/design_handoff_mcp/psd_client.py
src/design_handoff_mcp/psd_normalizer.py
src/design_handoff_mcp/psd_asset_store.py
```

也可以更直接：

```text
src/design_handoff_mcp/psd_adapter.py
```

第一版保持简单，推荐先做一个 `psd_adapter.py`。

核心函数：

```python
def make_psd_packet(
    file_path: str,
    target: str = "unity",
    rasterize_mode: str = "layer",
    asset_output_dir: str | None = None,
) -> dict:
    ...
```

返回值必须与蓝湖 `make_packet` 产物保持同构。

## 9. 实施计划

### 9.1 MVP

目标：本地 PSD 可以生成 Unity prefab。

已落地任务：

- 引入 PSD 解析依赖。
- 实现 `psd_design_prepare_packet`。
- 遍历 PSD 图层树。
- 导出像素图层 PNG。
- 读取文本层基础信息。
- 生成 packet。
- 复用 summary、node tree、asset manifest、slices、Unity plan 查询逻辑。
- 复用 Direct YAML writer 写 prefab。
- 直接 YAML writer 支持 `Slider.m_FillRect` / `Slider.m_HandleRect` 的 best-effort 子图层绑定。
- 直接 YAML writer 支持 `ScrollRect` / `Scrollbar` / `RectMask2D` 的基础引用写入。
- 直接 YAML writer 支持 `mask_candidate` 到 `RectMask2D` 的通用矩形裁剪容器映射。
- 直接 YAML writer 支持重复内容容器到 `VerticalLayoutGroup` / `HorizontalLayoutGroup` / `GridLayoutGroup` 的映射。
- 直接 YAML writer 支持半透明 PSD group 到 `CanvasGroup` 的映射。
- 直接 YAML writer 写入 `*.design-to-unity.json` source map，保留 PSD 图层到 Unity fileID / 组件的映射。
- 新增 `psd_design_get_unity_readiness_report`，在写入前暴露 blockers、review items、组件候选和 prefab 统计。
- 新增 `psd_design_convert_to_unity_prefab`，支持 PSD 到 Unity prefab/source map 的一键流程。
- 新增 `psd_design_compare_unity_screenshot`，支持 Unity 截图与 PSD 参考图的像素差异报告。
- 新增复杂 PSD 特性识别：mask、vector mask、clipping、非 normal blend mode、smart object、adjustment layer 和 layer effects。
- 新增 Photoshop/UXP 导出物读取：`psd_design_prepare_export_packet` 和 `psd_design_convert_export_to_unity_prefab`。
- 新增 Photoshop/UXP 导出物 schema 和 validator：`psd_design_get_export_schema`、`psd_design_validate_export`。
- 新增 Unity Editor 导入后验证脚本安装工具：`psd_design_install_unity_editor_validator`。
- 新增 Toggle 识别与 prefab 写入：`toggle_candidate` 会生成 `UnityEngine.UI.Toggle`，支持 `targetGraphic`、状态 `graphic` 和初始 `isOn`。
- 新增 Tab / ToggleGroup 识别与 prefab 写入：`tab_group_candidate` 会生成 `UnityEngine.UI.ToggleGroup`，`tab_candidate` 会生成绑定到该组的 `Toggle`，支持默认选中项。
- 新增 Radio / ToggleGroup 识别与 prefab 写入：`radio_group_candidate` 会生成 `UnityEngine.UI.ToggleGroup`，`radio_candidate` 会生成绑定到该组的 `Toggle`，支持默认选中项。
- 新增 Mask / Clip 识别与 prefab 写入：`mask_candidate` 会生成 `UnityEngine.UI.RectMask2D`，用于矩形 UI 裁剪；复杂 Photoshop mask 仍走 rasterize / overlay / visual diff。
- 新增重复布局识别与 prefab 写入：重复子节点容器会生成 `VerticalLayoutGroup`、`HorizontalLayoutGroup` 或 `GridLayoutGroup`，并保留 cell size、spacing、padding、grid column count。
- 新增输入框识别与 prefab 写入：`input_candidate` 会生成 `TMPro.TMP_InputField`，支持 `targetGraphic`、`textComponent`、`placeholder` 和初始 `text`。
- 新增下拉框识别与 prefab 写入：`dropdown_candidate` 会生成 `TMPro.TMP_Dropdown`，支持 `targetGraphic`、`template`、`captionText`、`itemText` 和 options。
- 新增外部 Photoshop reference 输入：`reference_image_path` 可以把 Photoshop/人工导出的真实预览图注册为 packet 的 visual baseline。
- 新增 direct prefab 可视策略：`prefab_visual_mode="flattened_reference_overlay"`，用真实预览图保真显示，同时保留 PSD 图层结构、TMP、Button 等透明覆盖层。
- 新增文本覆盖按钮识别：菜单文案位于矩形/图片底图内时，自动把底图标记为 `button_candidate` 并写入 `unity_button_hint`。
- 已用真实 PSD 图集文件验证 Unity 导入：33 个 Image 均成功绑定 Sprite，source map 可作为 TextAsset 导入，Unity 无编译错误。
- 已用真实 Unity 渲染截图验证 PSD sibling 顺序，visual diff 通过。
- 已用真实复杂游戏 PSD 验证 `flattened_reference_overlay`，Unity import report 与 visual diff 均通过。
- 仍需要对更多复杂 PSD 做视觉截图 diff 验证，尤其是复杂蒙版、剪贴蒙版、图层混合模式和 Photoshop-only 效果。

验收：

```text
给一个 PSD 文件路径
  -> 生成 packet_id
  -> 可查看 node tree
  -> 可查看 asset manifest
  -> 可查看 readiness report
  -> 可写出 Unity prefab YAML
  -> 可一键转换到 Unity prefab
  -> Unity 打开后 prefab 可导入
  -> Unity 截图后可与 PSD reference 做 visual diff
```

### 9.2 高保真增强

任务：

- 增加 group rasterize。
- 增加更多真实 mask / clipping / blend mode 样本的 visual diff 回归。
- 增加 @2x / @3x scale 识别。
- 增加 PSD preview 参考图。
- 增加 Unity 自动截图封装，减少手动传截图路径。
- 扩展更多 UI 组件识别：tab，以及更复杂的 scroll view / nested scroll。

### 9.3 Photoshop UXP 导出器

当前状态：

- 已新增 `templates/photoshop-uxp-exporter` 基础模板。
- 已在模板中声明 Manifest v5、Photoshop host、local filesystem request 权限和面板入口。
- 已实现 active document preview、layer tree metadata、text metadata、layer/group PNG 的基础导出。
- 已实现复杂分组 `rasterized: true` 标记，并在 MCP 读取侧忽略该分组子节点，避免视觉重复。
- 已扩展文本 metadata：字体 family/style/weight、字号、行高、字距、颜色、对齐、`textStyleRange` 多样式 spans、stroke、drop shadow。
- MCP 读取后会生成 `unity_text_hint`，direct YAML 会写入 TMP rich text、字体映射、`UnityEngine.UI.Outline` 和 `UnityEngine.UI.Shadow`。

本次目标边界：

- 本次只要求 MCP 能读取 UXP 导出物、校验 schema、消费 `preview.png` / `assets/*.png` / `rasterized: true` 并写入 Unity prefab。
- 不把 UXP 导出器生产化作为本次验收项；多 Photoshop 版本兼容、大量真实 PSD 回归和面板交互打磨放到后续路线。

本次继续项：

- 根据真实项目命名继续调优 Button / Slider / ScrollArea 的语义词表。
- 把 Unity 自动截图和 visual diff 串成更少手动步骤的回归工具。

后续路线：

- 用更多真实复杂 PSD 在 Photoshop 内验证导出脚本兼容性。
- 补交互式导出面板。
- 支持选择导出目录和导出参数预设。

## 10. 风险和取舍

### 10.1 离线 PSD 解析不等于 Photoshop 渲染

PSD 是复杂格式。离线解析器很难完整复现 Photoshop 的显示结果。

策略：

- 第一版以结构和可落地为主。
- 复杂视觉效果以 rasterize PNG 保真。
- 高保真场景交给 Photoshop UXP 导出器。

### 10.2 文本可编辑和视觉一致性冲突

可编辑 TMP 文本不一定和 Photoshop 文本完全一致。

策略：

- 默认生成 `TextMeshProUGUI`。
- 多样式文本写入 TMP rich text tags，支持颜色、字号、粗体、斜体和下划线。
- Photoshop 字体通过 `font_hint` 和 `tmp_font_asset_map_json` 映射到项目 TMP FontAsset。
- 文本 stroke 映射为 `UnityEngine.UI.Outline`，drop shadow 映射为 `UnityEngine.UI.Shadow`。
- 提供 `use_text_components=false` 回退文字切图。
- 记录字体候选、best-effort warning 和 visual diff 复核点；blur、spread、多重特效和复杂 OpenType 排版仍以 Photoshop reference 为准。

### 10.3 组件识别不应绑定业务

按钮、进度条、滑块可以加 Unity 组件，但不自动绑定业务脚本。

策略：

- `Button.onClick` 留空。
- `Slider.onValueChanged` 留空。
- 只写结构和默认可交互状态。
- 业务绑定交给用户和 AI 后续操作。

## 11. 推荐下一步

MVP 当前状态：

```text
1. 已新增 psd_adapter.py
2. 已新增 psd_design_prepare_packet、查询、预检、写入和一键转换工具
3. 已接入 psd-tools 离线读取
4. 已输出 Design Implementation Packet
5. 已接入 Direct Prefab YAML writer
6. 已通过 fake PSD 单测覆盖 Button / Slider / Toggle / TMP_InputField / TMP_Dropdown / ScrollRect / Scrollbar / CanvasGroup / TMP / source map
7. 已通过真实 PSD 图集文件验证 Unity prefab 导入、Sprite 绑定、source map 导入和 Unity 编译状态
8. 已补 Unity 截图与 PSD 参考图的 visual diff 工具
9. 已通过真实 Unity 渲染截图 visual diff 修正并验证 PSD sibling 顺序
10. 已补 Photoshop/UXP 导出物读取与一键 prefab 写入
11. 已补 Photoshop/UXP 导出物 schema 与 validator
12. 已补 Photoshop UXP 脚本模板
13. 已补 direct prefab YAML 静态验证器和 `psd_design_verify_unity_prefab_yaml`
14. 已补 Unity Editor 导入后验证脚本模板和 `psd_design_install_unity_editor_validator`
15. 已用 Unity MCP `http://127.0.0.1:8785` 验证真实 PSD 图片页导入，报告 `pass`
16. 已用 Unity MCP 验证语义组件 prefab，`Button=1`、`Slider=1`、`ScrollRect=1`、`RectMask2D=1`、`TextMeshProUGUI=2`，报告 `pass`
17. 已收紧 ScrollRect source map 归属：只有外层 `scroll_area_candidate` 写 `unity_scroll_hint`，`Content` / `Viewport` / `Item` 子节点不会被重复列表规则误标为新的滚动区域
18. 已补 Toggle 识别、`unity_toggle_hint`、direct prefab YAML、source map、静态 verifier 和 Unity Editor validator 检查
19. 已补 TMP_InputField 识别、`unity_input_hint`、direct prefab YAML、source map、静态 verifier 和 Unity Editor validator 检查
20. 已补 TMP_Dropdown 识别、`unity_dropdown_hint`、direct prefab YAML、source map、静态 verifier 和 Unity Editor validator 检查
21. 已补 Unity Editor prefab 自动截图入口，并用 Unity MCP 生成截图后跑通 `psd_design_compare_unity_screenshot`
22. 已补外部 Photoshop reference 与 `flattened_reference_overlay`，复杂 PSD 可用真实预览图保真落地，同时保留 Button/TMP/source map 覆盖层
23. 已补文本覆盖按钮识别，并用真实游戏 PSD 识别 6 个 Button
24. 已用 Unity MCP 验证复杂游戏 PSD overlay prefab，Unity import report `pass`，visual diff `mean_abs_delta=0`、`mismatch_ratio=0`
25. 已用 Unity MCP 验证 Tab smoke prefab，`ToggleGroup=1`、`Toggle=2`、两个 tab 均绑定同一 ToggleGroup，默认选中项正确，source map 导入成功
26. 已补 Photoshop/UXP 显式九宫格 border 到 Unity Sprite `spriteBorder` 的写入、source map 保留和静态 verifier 校验，并用 Unity MCP 验证 `Image.Type=Sliced`、`Sprite.border=(16,8,16,8)`
27. 已补 Radio / ToggleGroup 识别与 direct YAML/source map/静态 verifier 测试覆盖，PSD 自动识别和 Photoshop/UXP 显式 role 两条入口均可生成绑定到组的 Toggle，并用 Unity MCP 验证 Radio smoke prefab：`ToggleGroup=1`、`Toggle=2`、两个 radio 均绑定同一 ToggleGroup，默认选中项正确，source map 导入成功
28. 已补 Mask / Clip 到 RectMask2D 的 direct YAML/source map/静态 verifier 测试覆盖，PSD 自动识别和 Photoshop/UXP 显式 role 两条入口均可生成矩形裁剪容器，并用 Unity MCP 验证 Mask smoke prefab：`RectMask2D=1`，source map 导入成功
29. 已补重复布局识别与 LayoutGroup 写入：PSD/UXP 的重复列表、横向内容和网格容器可生成 `VerticalLayoutGroup`、`HorizontalLayoutGroup`、`GridLayoutGroup`，source map 和静态 verifier 会校验预期数量；Unity MCP 已验证 LayoutGroup smoke prefab：`VerticalLayoutGroup=1`、`HorizontalLayoutGroup=1`、`GridLayoutGroup=1`、Grid `FixedColumnCount=2`
30. 已补高级文本视觉一致性：PSD/UXP 文本样式归一化、rich text spans、字体映射、TMP font asset map、Outline/Shadow 写入、source map/import manifest/verifier/Unity Editor validator 组件计数，以及复杂文本单测覆盖
31. 下一步聚焦 direct YAML 当前能力的收口：补更多自动截图 diff 样本，并继续扩展嵌套滚动、复杂复合布局等当前 Unity prefab 组件候选
```

MCP 侧已经具备读取 UXP 导出物的能力；UXP 导出器生产化、正式 Unity Editor API importer 和跨引擎 writer 暂不纳入本次目标。

## 12. 参考资料

- psd-tools: https://psd-tools.readthedocs.io/
- Adobe Photoshop UXP: https://developer.adobe.com/photoshop/uxp/2022/
- Adobe Photoshop Layer API: https://developer.adobe.com/photoshop/uxp/2022/ps-reference/classes/layer
- Unity YAML 文本序列化格式: https://docs.unity3d.com/6000.4/Documentation/Manual/FormatDescription.html

# Unity 导出规范

## 1. 文档目标

本文档定义 Design to Unity 面向 Unity 输出信息与生成静态 prefab 快照时应遵循的规则。

本次 PSD 到 Unity 目标采用 direct prefab YAML 作为落地出口：Design to Unity 生成静态 UGUI prefab、Sprite meta、source map，并通过 static verifier、Unity Editor validator 和 Unity MCP 实测确认 Unity 可导入。

完整 Unity Editor API importer 暂不纳入本次目标；后续如果要支持项目级导入规则、动画、脚本绑定和增量重导入，再单独设计 Editor importer。

本规范的目标是：

- 让 AI 能稳定理解蓝湖设计稿如何映射到 Unity UGUI。
- 让 Unity MCP 能根据 Design Implementation Packet 校验、检查和继续加工可还原的 UI 层级。
- 让 YAML writer 能在不启动 Unity 的情况下生成可导入的静态 UGUI prefab。
- 避免坐标、层级、资源、文本、交互候选等信息产生歧义。
- 为后续重导入、局部更新、组件化替换保留稳定依据。

## 2. 总体原则

### 2.1 职责边界

Design to Unity 负责提供：

- 设计图元数据。
- 标准化节点树。
- 坐标和尺寸。
- 样式信息。
- 文本信息。
- 图片和切图资源清单。
- Unity 专用 handoff profile。
- 节点语义候选。
- warnings 和不确定项。
- 在显式调用实验工具时，生成静态 UGUI prefab YAML 和 Sprite meta。

Unity MCP 负责执行：

- 创建或打开 prefab。
- 创建 GameObject 层级。
- 添加 RectTransform、Image、TextMeshProUGUI、Button 等组件。
- 导入 Sprite 资源。
- 设置 RectTransform。
- 设置 Image / TMP 参数。
- 保存 prefab / scene。
- 截图和验证。

### 2.2 Unity YAML 写入策略

本次目标只手写 `.prefab` 快照和配套 `.meta` / source map，不手写完整 `.unity` 场景或业务 `.asset`。

原因：

- Unity 文件依赖 `fileID`、`guid`、序列化版本和内部引用关系。
- 直接写 YAML 容易造成引用损坏。
- 正式 Unity Editor API importer 可以规避很多序列化细节，但不作为本次验收项。

允许范围：

- 目标是静态 UGUI prefab 快照，不是完整场景、不含业务脚本绑定。
- 生成 `GameObject`、`RectTransform`、`CanvasRenderer`、`UnityEngine.UI.Image`、`TextMeshProUGUI`、`Button`、`Slider`、`Toggle`、`ToggleGroup`、`TMP_InputField`、`TMP_Dropdown`、`ScrollRect`、`Scrollbar`、`RectMask2D`、`VerticalLayoutGroup`、`HorizontalLayoutGroup`、`GridLayoutGroup` 和 `CanvasGroup` 的 YAML。
- 文本节点默认生成可编辑的 `TextMeshProUGUI`；如果需要绝对视觉一致，可在工具参数中关闭文本组件并回退到文字切图。
- `button_candidate` 默认添加 `Button`，并打开目标 Graphic 的 raycast。
- `progress_candidate` / `slider_candidate` 默认添加 `Slider`；能够推断子图层角色时写入 `fillRect` / `handleRect`，否则留空并输出 review hint。
- `toggle_candidate` 默认添加 `Toggle`；host 节点写入 `targetGraphic`，checkmark / knob / selected 子图层可作为 `graphic`，并根据命名或导出字段写入初始 `isOn`。
- `tab_group_candidate` / `tab_candidate` 默认添加 `ToggleGroup` + `Toggle`；tab Toggle 写入 `group` 引用，默认选中项来自 selected / current / active / 选中 等命名。
- `radio_group_candidate` / `radio_candidate` 默认添加 `ToggleGroup` + `Toggle`；radio Toggle 写入 `group` 引用，默认选中项来自 selected / current / active / 选中 等命名。
- `input_candidate` 默认添加 `TMPro.TMP_InputField`；host 节点写入 `targetGraphic`，文本子图层写入 `textComponent` / `placeholder`，并根据占位文本写入初始 `text`。
- `dropdown_candidate` 默认添加 `TMPro.TMP_Dropdown`；host 节点写入 `targetGraphic`，caption / template / item text 子图层可写入 `captionText`、`template`、`itemText`，options 从文本子图层提取。
- `scroll_area_candidate` 默认添加 `ScrollRect`；如果能推断 viewport，则为 viewport 节点添加 `RectMask2D`，并写入 content / viewport / scrollbar 引用。
- `mask_candidate` 默认添加 `RectMask2D`，用于明确的矩形 UI 裁剪容器；Photoshop 不规则/alpha/vector mask 仍需 rasterize 或 visual diff 复核。
- 重复内容容器默认可以添加 `VerticalLayoutGroup`、`HorizontalLayoutGroup` 或 `GridLayoutGroup`；组件类型来自直接子节点的行列分布、cell size、spacing 和 padding 推断。
- 半透明 group 默认添加 `CanvasGroup`，把 PSD group opacity 作用到整组子节点。
- 生成路径必须在调用者指定的 `Assets/...` 目录下。
- 写入后必须打开 Unity 让 Unity 自己重新导入并校验引用。

直接 YAML writer 的定位是“快速生成可检查 prefab”，不是 Unity 序列化系统的完整替代。

### 2.3 第一版目标

第一版目标是高保真静态 UI 落地。

优先支持：

- RectTransform 位置和尺寸还原。
- 图片 Sprite 还原。
- 文本 TMP 还原。
- 纯色形状还原。
- 图层层级还原。
- 基础透明度还原。
- 候选按钮标记。

第一版不强制支持：

- 自动业务绑定。
- 复杂自适应布局。
- 自动替换项目已有组件。
- 复杂 shader 效果。
- 动画。
- 运行时数据绑定。

## 3. Canvas 和根节点规范

### 3.1 根节点结构建议

Unity MCP 创建 prefab 时，建议结构如下：

```text
DesignName.prefab
└── ViewRoot
    ├── node_001_background
    ├── node_002_title
    └── node_003_button_start
```

如果目标是 scene，可以外层包含 Canvas：

```text
Canvas
└── ViewRoot
    └── ...
```

如果目标是 prefab，推荐只生成 `ViewRoot` 及其子节点，不强制生成 Canvas。是否挂到 Canvas 由项目决定。

### 3.2 ViewRoot 规范

`ViewRoot` 应包含：

- `RectTransform`
- 尺寸等于设计图逻辑尺寸。
- 默认锚点固定在左上角。

示例：

```json
{
  "name": "ViewRoot",
  "rectTransform": {
    "anchorMin": [0, 1],
    "anchorMax": [0, 1],
    "pivot": [0, 1],
    "anchoredPosition": [0, 0],
    "sizeDelta": [375, 667]
  }
}
```

### 3.3 CanvasScaler 建议

如果 Unity MCP 需要创建 Canvas，推荐使用：

```text
Canvas Render Mode: Screen Space - Overlay
CanvasScaler UI Scale Mode: Scale With Screen Size
Reference Resolution: 设计图逻辑尺寸
Screen Match Mode: Match Width Or Height
Match: 0.5
```

如果用户项目已有 Canvas，则不要擅自修改已有 CanvasScaler。

### 3.4 Safe Area

第一版不自动处理 Safe Area。

如果设计图中存在明显状态栏、刘海、安全区标注，Design to Unity 应在 warnings 中提示：

```json
{
  "code": "safe_area_possible",
  "message": "设计图顶部存在状态栏或安全区元素，Unity 落地时可能需要接入项目 SafeArea 组件。"
}
```

## 4. 坐标系统规范

### 4.1 原始坐标

蓝湖设计稿默认使用左上角坐标系：

```text
x: 距离画布左侧
y: 距离画布顶部
width: 节点宽度
height: 节点高度
```

Design Node 必须保留原始坐标：

```json
{
  "rect": {
    "x": 48,
    "y": 720,
    "width": 280,
    "height": 88
  }
}
```

### 4.2 Unity RectTransform 基础转换

默认使用左上角锚点和左上角 pivot：

```text
anchorMin = (0, 1)
anchorMax = (0, 1)
pivot = (0, 1)
anchoredPosition = (x, -y)
sizeDelta = (width, height)
```

Design to Unity 应直接在 Unity Profile 中提供转换结果：

```json
{
  "unity_rect_hint": {
    "anchorMin": [0, 1],
    "anchorMax": [0, 1],
    "pivot": [0, 1],
    "anchoredPosition": [48, -720],
    "sizeDelta": [280, 88]
  }
}
```

### 4.3 父子节点坐标

Design to Unity 必须明确每个节点坐标是：

- `global_rect`: 相对设计画布。
- `local_rect`: 相对父节点。

推荐结构：

```json
{
  "global_rect": {
    "x": 100,
    "y": 200,
    "width": 300,
    "height": 100
  },
  "local_rect": {
    "x": 20,
    "y": 30,
    "width": 300,
    "height": 100
  }
}
```

Unity MCP 创建子节点时，应优先使用 `local_rect`。

如果蓝湖原始数据只提供全局坐标，则 Design to Unity 应计算：

```text
local_x = child_global_x - parent_global_x
local_y = child_global_y - parent_global_y
```

再转换为 Unity：

```text
anchoredPosition = (local_x, -local_y)
```

### 4.4 浮点数处理

坐标和尺寸允许保留一位小数。

推荐：

```text
round(value, 1)
```

不要在 Design to Unity 中随意取整到整数，除非原始值本身为整数。

## 5. 节点映射规范

### 5.1 节点类型

Design Node 的 `type` 建议取值：

```text
group
image
text
shape
mask
unknown
```

### 5.2 Unity 组件映射

```text
group -> GameObject + RectTransform
image -> GameObject + RectTransform + Image
text  -> GameObject + RectTransform + TextMeshProUGUI
shape -> GameObject + RectTransform + Image
mask  -> GameObject + RectTransform + Mask / RectMask2D candidate
unknown -> GameObject + RectTransform
```

### 5.3 命名规范

Unity 节点名建议包含稳定序号和设计名称：

```text
node_001_bg
node_002_title
node_003_btn_start
```

Design to Unity 应提供：

```json
{
  "unity_name_hint": "node_003_btn_start"
}
```

命名应避免：

- `/`
- `\`
- `:`
- `*`
- `?`
- `"`
- `<`
- `>`
- `|`

### 5.4 稳定标识

每个节点必须提供稳定标识，用于重导入和 diff：

```json
{
  "id": "lanhu_layer_id",
  "stable_key": "design_id/version_id/layer_id",
  "path": "Root/Footer/btn_start",
  "content_hash": "sha1_of_rect_style_asset_text"
}
```

Unity MCP 可以将这些信息写入自定义组件或 metadata，方便后续增量更新。

## 6. 层级和渲染顺序

### 6.1 z_index

Design to Unity 必须为每个节点提供 `z_index`。

规则：

```text
z_index 表示从源数据读取到的图层遍历顺序。
不同 source adapter 的源数组语义可能不同，Unity MCP 应优先使用 get_unity_plan 返回的 create_nodes 顺序。
```

已验证规则：

- Lanhu：源图层数组更接近“前景到背景”，同父节点内按 `z_index` 从大到小创建。
- PSD：`psd-tools` 遍历在真实 PSD visual diff 中匹配 Photoshop composite，保持同父节点内按 `z_index` 从小到大创建。

### 6.2 Unity sibling index

UGUI 中后面的 sibling 通常渲染在更上层。

Unity MCP 应优先按 `create_nodes` 顺序创建节点。若必须自行排序，需要按 source provider 选择规则：

```text
Lanhu: higher z_index -> lower sibling index, lower z_index -> higher sibling index
PSD:   lower z_index -> lower sibling index, higher z_index -> higher sibling index
```

### 6.3 分组节点

分组节点应尽量保留。

原因：

- 有助于保持设计语义。
- 有助于后续替换为组件。
- 有助于局部更新。

如果某个 group 没有样式，只作为布局容器，也应创建 GameObject + RectTransform。

## 7. 图片资源规范

### 7.1 Asset Manifest 必填字段

每个图片资源必须包含：

```json
{
  "id": "asset_btn_start",
  "name": "btn_start",
  "remote_url": "https://...",
  "local_path": "./data/assets/home/btn_start.png",
  "suggested_unity_path": "Assets/DesignToUnity/Home/Sprites/btn_start.png",
  "format": "png",
  "size": {
    "width": 560,
    "height": 176
  },
  "logical_size": {
    "width": 280,
    "height": 88
  },
  "scale": 2,
  "has_alpha": true,
  "usage": "button_candidate"
}
```

### 7.2 Unity 导入设置建议

```json
{
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

### 7.3 九宫格建议

Design to Unity 不强制为所有按钮/面板自动决定九宫格，但应提供候选信息。Photoshop/UXP 导出物可以显式声明 `nine_slice` / `nineSlice` / `spriteBorder` / `sprite_border`，一旦提供 border，direct YAML writer 会把它写入 Unity Sprite `.meta` 的 `spriteBorder`。

```json
{
  "nine_slice_hint": {
    "candidate": true,
    "reason": "节点名称包含 panel/bg/button，且图片存在明显圆角边框。",
    "border": {
      "left": 16,
      "right": 16,
      "top": 16,
      "bottom": 16
    },
    "requires_review": false
  }
}
```

如果无法判断 border，可返回：

```json
{
  "nine_slice_hint": {
    "candidate": true,
    "border": null,
    "requires_manual_review": true
  }
}
```

### 7.4 资源路径规则

推荐 Unity 资源路径：

```text
Assets/DesignToUnity/{ProjectName}/{DesignName}/Sprites/{asset_name}.png
```

如果用户指定项目资源目录，应优先使用用户目录。

Design to Unity 只提供建议路径，最终复制到 Unity 项目的动作由 Unity MCP 执行。

## 8. Image 组件规范

### 8.1 普通图片

默认：

```text
Image.sprite = asset sprite
Image.type = Simple
Image.preserveAspect = false
Image.raycastTarget = false
```

### 8.2 九宫格图片

当 `nine_slice_hint.candidate=true` 且 border 可用：

```text
Image.type = Sliced
Image.fillCenter = true
Image.raycastTarget = false
Sprite.meta.spriteBorder = {left, bottom, right, top}
```

静态验证器必须检查 source map 中的 `nine_slice_hint.border` 和实际 `.png.meta` 的 `spriteBorder` 是否一致。只有 candidate 但没有 border 的资源不强行写 Sliced，继续作为 review hint。

### 8.3 按钮候选图片

当节点 `semantic_type=button_candidate`：

```text
默认 Unity MCP 流：是否添加 Button 由执行器或用户意图决定。
直接 YAML 流：默认添加 Button，并将 Image / TextMeshProUGUI 作为 targetGraphic。
如果节点本身没有可点击 Graphic，直接 YAML 流可以添加透明 Image 作为 hit area。
```

### 8.4 透明度

如果节点 `style.opacity < 1`：

优先规则：

```text
如果节点有 Image 或 TMP，设置组件 color alpha。
如果 group 需要整体透明，Unity MCP / Direct YAML writer 应添加 CanvasGroup。
```

Design to Unity 应明确：

```json
{
  "opacity_application": "component_alpha|canvas_group_candidate"
}
```

## 9. 文本 TMP 规范

### 9.1 必填文本字段

```json
{
  "text": {
    "content": "开始游戏",
    "font_family": "PingFangSC-Semibold",
    "font_size": 32,
    "font_weight": 600,
    "color": "rgba(255,255,255,1)",
    "align": "center",
    "line_height": 38,
    "letter_spacing": 0,
    "overflow": "clip",
    "wrap": false
  }
}
```

### 9.2 TMP 映射

```text
content -> TMP.text
font_size -> TMP.fontSize
color -> TMP.color
align -> TMP.alignment
wrap=false -> TMP.enableWordWrapping=false
wrap=true -> TMP.enableWordWrapping=true
overflow=clip -> TMP.overflowMode=Masking or Truncate
enableAutoSizing=false
raycastTarget=false
```

### 9.3 字体映射

Design to Unity 不直接提供 Unity TMP FontAsset，但应提供字体候选：

```json
{
  "font_hint": {
    "source_font_family": "PingFangSC-Semibold",
    "weight": 600,
    "unity_preferred_font_asset": null,
    "fallback_policy": "use_project_default_tmp_font"
  }
}
```

如果用户项目提供字体映射表，后续可以扩展：

```json
{
  "font_map": {
    "PingFangSC-Regular": "Assets/Fonts/PingFang-Regular SDF.asset",
    "PingFangSC-Semibold": "Assets/Fonts/PingFang-Semibold SDF.asset"
  }
}
```

### 9.4 字重

TMP 字重处理建议：

```text
如果项目存在对应 FontAsset，使用对应 FontAsset。
否则仅记录 font_weight，不强制模拟。
不要用 scale 或 outline 冒充字重。
```

### 9.5 行高和字间距

Design to Unity 应保留：

- `line_height`
- `letter_spacing`

Unity MCP 可以按项目能力映射到：

- TMP `lineSpacing`
- TMP `characterSpacing`

如果无法精确映射，应记录 warning。

### 9.6 文本超框风险

Design to Unity 应检测：

- 文本长度明显超过节点宽度。
- 字号大于节点高度。
- 多行文本但节点高度不足。

示例 warning：

```json
{
  "node_id": "layer_title",
  "code": "text_overflow_risk",
  "message": "文本可能超出设计框，Unity 中需要检查 TMP overflow/wrapping。"
}
```

## 10. 形状和颜色规范

### 10.1 纯色形状

纯色矩形可映射为：

```text
GameObject + RectTransform + Image
Image.color = fill_color
Image.sprite = default white sprite or generated rounded sprite
```

### 10.2 圆角

UGUI 默认 Image 不支持程序化圆角。

处理策略：

```text
如果形状有圆角且对应蓝湖有切图，优先使用切图。
如果没有切图，标记 rounded_rect_requires_custom_solution。
Unity MCP 可选择项目已有圆角 Image 组件、Shader、或生成 Sprite。
```

warning 示例：

```json
{
  "node_id": "layer_panel",
  "code": "rounded_rect_requires_custom_solution",
  "message": "该节点为圆角纯色形状，UGUI Image 默认无法直接表现圆角。建议使用项目圆角组件或生成切图。"
}
```

### 10.3 渐变

渐变处理策略：

```text
如果蓝湖提供渐变参数，完整保留。
Unity MCP 不应默认用纯色替代渐变。
如项目无渐变组件，建议使用切图兜底。
```

### 10.4 阴影

阴影处理策略：

```text
保留 offset、blur、spread、color、opacity。
Unity UGUI Shadow 不能完整表达 blur/spread。
如果阴影较复杂，建议切图兜底或项目自定义 Shadow 组件。
```

## 11. Mask 和裁剪规范

### 11.1 裁剪候选

如果节点存在：

- `overflow: hidden`
- mask 图层
- clip group
- 明确遮罩层

Design to Unity 应标记：

```json
{
  "semantic_type": "mask_candidate",
  "unity_mask_hint": {
    "can_add_rect_mask_2d": true,
    "default_add_rect_mask_2d": true,
    "recommended_unity_component": "RectMask2D"
  }
}
```

### 11.2 RectMask2D 优先

矩形裁剪优先建议：

```text
RectMask2D
```

Alpha 蒙版或不规则蒙版建议：

```text
Mask + Image
```

如果无法确定，标记 warning，由 Unity MCP 或用户决定。

Direct YAML 当前只自动写入矩形 `RectMask2D`。Photoshop bitmap mask、vector mask、clipping mask 或不规则 alpha mask 不直接转成 Unity Mask；应使用 rasterized group、flattened reference overlay 或 visual diff 做保真校验。

## 12. 交互候选规范

### 12.1 button_candidate

识别依据可包括：

- 名称包含 `btn`、`button`、`按钮`。
- 图片像按钮背景。
- 节点包含短文本且位于明显点击区域。
- 蓝湖图层路径包含 Button。

输出示例：

```json
{
  "semantic_type": "button_candidate",
  "semantic_confidence": 0.82,
  "semantic_reasons": [
    "节点名称包含 btn",
    "节点包含一个背景图片和一个居中文本"
  ],
  "unity_interaction_hint": {
    "can_add_button": true,
    "default_add_button": true,
    "raycast_target_if_interactive": true
  }
}
```

### 12.2 progress_candidate / slider_candidate

识别依据可包括：

- 名称包含 `progress`、`progressbar`、`进度条`、`loading`、`hp`、`exp`、`energy` 等。
- 名称包含 `slider`、`thumb`、`handle`、`滑块` 等。
- 节点是横向细长条。

输出示例：

```json
{
  "semantic_type": "slider_candidate",
  "semantic_confidence": 0.84,
  "semantic_reasons": [
    "name/text suggests slider",
    "rect has horizontal control-like proportions"
  ],
  "unity_interaction_hint": {
    "can_add_slider": true,
    "default_add_slider": true,
    "interactable": true,
    "requires_fill_handle_review": false
  },
  "unity_slider_hint": {
    "direction": "horizontal",
    "track_node_id": "track_bg_node_id",
    "fill_node_id": "fill_node_id",
    "handle_node_id": "handle_node_id",
    "value": 0.75,
    "requires_review": false
  }
}
```

直接 YAML 流默认添加 `Slider`：

- `progress_candidate` -> `Slider.interactable = false`。
- `slider_candidate` -> `Slider.interactable = true`。
- 如果能从名称或文本中解析 `75%` 或 `0.75`，写入 `Slider.value`。
- 如果 PSD 子图层可识别为 `track` / `fill` / `handle`，直接写入 `Slider.m_FillRect` 和 `Slider.m_HandleRect`。
- 如果是扁平进度条，或者无法安全识别子节点，保留空引用并设置 `requires_review=true`。

### 12.3 toggle_candidate

识别条件：

- 名称包含 `toggle`、`switch`、`checkbox`、`开关`、`复选`。
- Photoshop/UXP 导出中显式声明 `role: "toggle_candidate"`。
- track、checkmark、knob、handle、thumb 等子图层只作为状态图形候选，不应被重复识别为 Toggle host。

输出规则：

- host 节点添加 `UnityEngine.UI.Toggle`。
- `Toggle.targetGraphic` 指向 host 自身的 Image / Text graphic。
- `Toggle.graphic` 优先绑定 `unity_toggle_hint.graphic_node_id` 对应子图层；若无法推断，回退 host graphic。
- `Toggle.isOn` 根据 `on`、`checked`、`selected`、`开`、`选中` 等命名或 UXP `checked/isOn/value` 字段推断。
- `Toggle.onValueChanged` 留空，业务事件由后续 Unity MCP 或人工绑定。

### 12.4 tab_group_candidate / tab_candidate

识别条件：

- 分组名称包含 `tabs`、`tabbar`、`tab_group`、`页签`、`标签栏` 等。
- 子节点名称包含 `tab`、`页签`、`标签`，或 Photoshop/UXP 导出中显式声明 `role: "tab_candidate"`。
- 名称包含 `selected`、`active`、`current`、`on`、`checked`、`选中`、`当前`、`激活` 的 tab 作为默认选中项；如果没有明显选中项，默认第一个 tab 选中。

输出规则：

- tab group host 添加 `UnityEngine.UI.ToggleGroup`。
- 每个 tab item 添加 `UnityEngine.UI.Toggle`。
- `Toggle.group` 指向父级 tab group 的 `ToggleGroup`。
- `Toggle.isOn` 使用 `unity_tab_hint.value`，并保持默认只有一个 tab 打开。
- `Toggle.onValueChanged` 留空，业务切页逻辑由后续 Unity MCP 或人工绑定。

### 12.5 radio_group_candidate / radio_candidate

识别条件：

- 分组名称包含 `radiogroup`、`radio_group`、`radio options`、`choice_group`、`单选组`、`选项组` 等。
- 子节点名称包含 `radio`、`choice`、`单选`，或位于明确的 radio group 下。
- Photoshop/UXP 导出中显式声明 `role: "radio_group_candidate"` / `role: "radio_candidate"`。
- 名称包含 `selected`、`active`、`current`、`on`、`checked`、`true`、`选中`、`当前`、`激活` 的 radio 作为默认选中项；如果没有明显选中项，默认第一个 radio 选中。

输出规则：

- radio group host 添加 `UnityEngine.UI.ToggleGroup`。
- 每个 radio option 添加 `UnityEngine.UI.Toggle`。
- `Toggle.group` 指向父级 radio group 的 `ToggleGroup`。
- `Toggle.isOn` 使用 `unity_radio_hint.value`，并保持默认只有一个 radio 打开。
- `Toggle.onValueChanged` 留空，业务选项值由后续 Unity MCP 或人工绑定。

### 12.6 input_candidate

识别条件：

- 名称包含 `input`、`textfield`、`search`、`username`、`password`、`email`、`输入`、`文本框`、`搜索` 等。
- Photoshop/UXP 导出中显式声明 `role: "input_candidate"`。
- 尺寸接近单行输入框，且拥有文本子图层时优先作为 TMP 输入框 host。

输出规则：

- host 节点添加 `TMPro.TMP_InputField`。
- `TMP_InputField.targetGraphic` 指向 host 的 Image / Text graphic。
- `TMP_InputField.textComponent` 优先绑定 `unity_input_hint.text_component_node_id` 对应的 `TextMeshProUGUI`。
- `TMP_InputField.placeholder` 优先绑定 placeholder / hint / 请输入 等文本子图层；无法区分时回退到 textComponent。
- `TMP_InputField.text` 使用识别到的占位或初始文本。
- `onValueChanged`、`onEndEdit`、`onSubmit` 留空，业务校验和提交逻辑由后续 Unity MCP 或人工绑定。

### 12.7 dropdown_candidate

识别条件：

- 名称包含 `dropdown`、`selectbox`、`picker`、`combo`、`下拉`、`选择器` 等。
- Photoshop/UXP 导出中显式声明 `role: "dropdown_candidate"`。
- 拥有 caption 文本子图层，且可选地拥有 Template / Menu / Options / List 子组。

输出规则：

- host 节点添加 `TMPro.TMP_Dropdown`。
- `TMP_Dropdown.targetGraphic` 指向 host 的 Image / Text graphic。
- `TMP_Dropdown.captionText` 绑定 caption 文本子图层。
- `TMP_Dropdown.template` 优先绑定 Template / Menu / Options 子组的 RectTransform；该节点在 prefab 中默认 inactive，符合 Unity TMP_Dropdown 模板习惯。
- `TMP_Dropdown.itemText` 绑定 template 内第一个 option 文本。
- `TMP_Dropdown.options` 从 template 内文本子图层提取；没有展开模板时至少保留 caption 文本作为 best-effort option，并输出 review hint。
- `onValueChanged` 留空，业务选择逻辑由后续 Unity MCP 或人工绑定。

### 12.8 不自动绑定业务

即使识别为按钮，也不自动指定：

- 点击函数名。
- 脚本类型。
- 跳转页面。
- 业务事件。

这些必须由用户、AI 和目标项目上下文决定。

## 13. 组件化候选规范

### 13.1 list_item_candidate

如果多个节点结构重复，可以标记：

```json
{
  "semantic_type": "list_item_candidate",
  "repeat_group_id": "repeat_001",
  "repeat_index": 0,
  "repeat_count": 5
}
```

第一版仍保留所有静态子节点；如果父容器可以从直接子节点几何关系推断出重复排列，则额外写入 `unity_layout_hint`，direct YAML 可在父容器上添加 LayoutGroup，方便 Unity 后续编辑。

后续 Unity MCP 可根据用户要求继续替换为：

- ScrollRect
- GridLayoutGroup
- VerticalLayoutGroup
- 自定义 Item prefab

LayoutGroup 推断字段示例：

```json
{
  "unity_layout_hint": {
    "can_add_layout_group": true,
    "default_add_layout_group": true,
    "component": "GridLayoutGroup",
    "direction": "grid",
    "item_node_ids": ["slot_01", "slot_02", "slot_03", "slot_04"],
    "cell_size": {"width": 54, "height": 40},
    "spacing": {"x": 16, "y": 12},
    "padding": {"left": 0, "right": 26, "top": 0, "bottom": 12},
    "constraint": "fixed_column_count",
    "constraint_count": 2,
    "child_control_width": false,
    "child_control_height": false,
    "child_force_expand_width": false,
    "child_force_expand_height": false,
    "requires_review": false
  }
}
```

当前 direct YAML 写入规则：

- 单列重复项 -> `VerticalLayoutGroup`。
- 单行重复项 -> `HorizontalLayoutGroup`。
- 多行多列重复项 -> `GridLayoutGroup`，默认 `FixedColumnCount`。
- 默认不让 LayoutGroup 改写子节点尺寸，`childControl` / `forceExpand` 均为 false；它主要表达排列语义，并为 Unity 后续调整提供组件锚点。

### 13.2 scroll_area_candidate

PSD 或蓝湖分组可标记为：

```json
{
  "semantic_type": "scroll_area_candidate",
  "unity_interaction_hint": {
    "can_add_scroll_rect": true,
    "default_add_scroll_rect": true,
    "requires_content_viewport_review": true
  },
  "unity_scroll_hint": {
    "direction": "vertical",
    "viewport_node_id": "psd_layer_viewport",
    "content_node_id": "psd_layer_content",
    "item_node_ids": ["psd_layer_item_01", "psd_layer_item_02"],
    "requires_review": false
  }
}
```

直接 YAML 流默认添加：

- `ScrollRect` 到 `scroll_area_candidate` 节点。
- `RectMask2D` 到 `viewport_node_id` 指向的节点；没有 viewport 时暂挂到自身并输出 warning。
- `RectMask2D` 到 `mask_candidate` 节点，作为通用矩形裁剪容器。
- `ScrollRect.m_Content` 和 `ScrollRect.m_Viewport` 引用已推断的 RectTransform。
- `ScrollRect.m_HorizontalScrollbar` / `m_VerticalScrollbar` 在识别到 scrollbar 子图层时写入对应 `Scrollbar`。
- `Scrollbar.m_HandleRect` 在识别到 handle / thumb / 滑块子图层时写入对应 RectTransform。

### 13.3 dialog_candidate

弹窗候选应提供：

- 遮罩节点。
- 面板节点。
- 标题节点。
- 关闭按钮候选。
- 主按钮候选。

不自动替换为项目弹窗基类。

## 14. 重导入和人工修改保护

### 14.1 必须提供稳定 metadata

每个节点必须包含：

```json
{
  "source_provider": "lanhu",
  "source_design_id": "xxx",
  "source_version_id": "xxx",
  "source_node_id": "xxx",
  "source_path": "Root/Footer/btn_start",
  "content_hash": "xxx"
}
```

### 14.2 Unity MCP 写入建议

Unity MCP 可以将 metadata 写入：

- 自定义 `DesignToUnityNode` 组件。
- GameObject name 后缀。
- prefab 外部 manifest。

如果使用 direct YAML writer，默认会在 prefab 同目录写入 `*.design-to-unity.json` source map。该 JSON 包含：

- `node_id`、`parent_id`、`children`。
- `source_metadata.source_path` 和 `content_hash`。
- `semantic_type`、`unity_slider_hint`、`unity_toggle_hint`、`unity_tab_group_hint`、`unity_tab_hint`、`unity_radio_group_hint`、`unity_radio_hint`、`unity_mask_hint`、`unity_scroll_hint`。
- 直接 YAML 中的 `GameObject`、`RectTransform`、`Image`、`TextMeshProUGUI`、`Button`、`Slider`、`Toggle`、`ToggleGroup`、`ScrollRect` 等 `fileID`。
- 关联 sprite 的 Unity guid。
- `unity_import_manifest`：给 Unity MCP / Unity Editor 的导入清单、预期组件数量、静态验证 gate 和视觉 diff gate。
- `update_policy_hint`：重导入时可安全覆盖字段、默认保留字段和身份匹配字段。

如果需要 Unity 导入后的自动校验，可调用 `psd_design_install_unity_editor_validator` 安装 Editor 脚本。该脚本会在 Unity 内加载 prefab 和 source map，并输出 `*.unity-import-report.json`。

Unity Editor API / Unity MCP 生产链路仍推荐自定义组件：

```csharp
public class DesignToUnityNode : MonoBehaviour
{
    public string SourceProvider;
    public string SourceDesignId;
    public string SourceVersionId;
    public string SourceNodeId;
    public string SourcePath;
    public string ContentHash;
}
```

### 14.3 更新策略建议

重导入时：

```text
source_node_id 相同 -> 更新可安全覆盖字段。
source_node_id 不存在 -> 新增节点。
Unity 中存在但新 packet 不存在 -> 标记 orphan，不直接删除。
用户添加的组件或脚本 -> 默认保留。
用户修改过的节点 -> 需要 diff 或用户确认。
```

Design to Unity 应提供：

```json
{
  "update_policy_hint": {
    "safe_to_overwrite": [
      "RectTransform",
      "Image.sprite",
      "Image.color",
      "TMP.text",
      "TMP.fontSize",
      "TMP.color"
    ],
    "preserve_by_default": [
      "custom_scripts",
      "event_bindings",
      "user_added_children",
      "animation",
      "prefab_variant_overrides"
    ]
  }
}
```

## 15. Warnings 规范

Design to Unity 应将不确定或无法直接还原的点放入 warnings。

常见 warning code：

```text
missing_asset
unsupported_gradient
unsupported_shadow
rounded_rect_requires_custom_solution
text_overflow_risk
font_asset_missing
mask_requires_manual_review
nine_slice_requires_manual_review
semantic_low_confidence
safe_area_possible
psd_mask_requires_review
psd_clipping_mask_requires_review
psd_blend_mode_requires_review
psd_smart_object_rasterized
psd_adjustment_layer_requires_review
psd_layer_effect_requires_review
```

PSD 专用 warning 的处理策略：

- 不应自动绑定业务脚本。
- 不应假设 Unity Image 默认混合能复现 Photoshop 效果。
- 优先读取 `source_metadata.unsupported_psd_features` 和 `recommended_fidelity_mode`。
- 当 `recommended_fidelity_mode=group_or_document_rasterize` 时，优先使用整组切图、flattened reference 或 Photoshop UXP 导出。
- 完成 prefab 后调用 `psd_design_compare_unity_screenshot` 做 visual diff。

warning 示例：

```json
{
  "node_id": "layer_panel",
  "code": "unsupported_shadow",
  "severity": "medium",
  "message": "该节点存在复杂阴影，Unity UGUI 默认 Shadow 无法完整还原，建议使用切图或项目自定义阴影组件。"
}
```

## 16. Unity Handoff Profile 输出示例

```json
{
  "target": "unity",
  "ui_system": "UGUI",
  "text_system": "TextMeshPro",
  "coordinate_mapping": {
    "source": "top-left",
    "anchorMin": [0, 1],
    "anchorMax": [0, 1],
    "pivot": [0, 1],
    "anchoredPosition": ["local_rect.x", "-local_rect.y"],
    "sizeDelta": ["local_rect.width", "local_rect.height"]
  },
  "component_mapping": {
    "group": ["GameObject", "RectTransform"],
    "image": ["GameObject", "RectTransform", "Image"],
    "text": ["GameObject", "RectTransform", "TextMeshProUGUI"],
    "shape": ["GameObject", "RectTransform", "Image"],
    "mask": ["GameObject", "RectTransform", "RectMask2D candidate"],
    "mask_candidate": ["GameObject", "RectTransform", "RectMask2D"],
    "button_candidate": ["Image or Text", "Button"],
    "progress_candidate": ["Image", "Slider"],
    "slider_candidate": ["Image", "Slider"],
    "toggle_candidate": ["Image or Text", "Toggle"],
    "tab_group_candidate": ["GameObject", "RectTransform", "ToggleGroup"],
    "tab_candidate": ["Image or Text", "Toggle"],
    "tab_label_candidate": ["Text", "TextMeshProUGUI"],
    "radio_group_candidate": ["GameObject", "RectTransform", "ToggleGroup"],
    "radio_candidate": ["Image or Text", "Toggle"],
    "radio_label_candidate": ["Text", "TextMeshProUGUI"],
    "input_candidate": ["Image or Text", "TMP_InputField"],
    "dropdown_candidate": ["Image or Group", "TMP_Dropdown"],
    "dropdown_template_candidate": ["GameObject", "RectTransform"],
    "dropdown_caption_candidate": ["Text", "TextMeshProUGUI"],
    "dropdown_item_text_candidate": ["Text", "TextMeshProUGUI"],
    "scroll_area_candidate": ["GameObject", "RectTransform", "ScrollRect"],
    "scrollbar_candidate": ["Image or Group", "Scrollbar"],
    "scrollbar_handle_candidate": ["Image", "RectTransform"],
    "scroll_viewport_candidate": ["GameObject", "RectTransform", "RectMask2D"],
    "scroll_content_candidate": ["GameObject", "RectTransform"],
    "unity_layout_hint": ["VerticalLayoutGroup", "HorizontalLayoutGroup", "GridLayoutGroup"]
  },
  "image_defaults": {
    "type": "Simple",
    "preserveAspect": false,
    "raycastTarget": false
  },
  "text_defaults": {
    "enableAutoSizing": false,
    "raycastTarget": false,
    "enableWordWrapping": false
  },
  "asset_import_defaults": {
    "textureType": "Sprite",
    "spriteMode": "Single",
    "alphaIsTransparency": true,
    "sRGBTexture": true,
    "mipmapEnabled": false,
    "wrapMode": "Clamp",
    "filterMode": "Bilinear",
    "compression": "None",
    "pixelsPerUnit": 100
  },
  "rules": [
    "Current milestone default flow: use lanhu_design_write_unity_prefab_yaml or psd_design_write_unity_prefab_yaml for static UGUI prefab snapshots.",
    "Use Unity MCP and Unity-side validator to import, inspect, smoke test, and continue editing generated prefabs.",
    "Import all sprites before assigning Image.sprite.",
    "Create nodes in create_nodes order; sibling z_index direction is source-provider specific.",
    "Use local_rect for child RectTransform positioning.",
    "Direct YAML can add Button for button_candidate, Slider for progress_candidate/slider_candidate, Toggle for toggle_candidate, ToggleGroup + Toggle for tab_group_candidate/tab_candidate and radio_group_candidate/radio_candidate, TMP_InputField for input_candidate, TMP_Dropdown for dropdown_candidate, RectMask2D for mask_candidate, LayoutGroup components for repeated child geometry, and ScrollRect/Scrollbar/RectMask2D for scroll_area_candidate.",
    "Do not treat direct YAML as a production replacement for project-specific scripts, animation binding, or a full Unity Editor API importer."
  ]
}
```

## 17. AI 调用 Unity MCP 推荐流程

```text
1. 读取 Design Implementation Packet。
2. 读取 Unity Handoff Profile。
3. 读取 Asset Manifest。
4. 调 Design to Unity direct YAML writer 生成 prefab、Sprite meta、source map 和 copied assets。
5. 运行 `psd_design_verify_unity_prefab_yaml` 做 Unity 外静态检查。
6. 打开 Unity 或通过 Unity MCP 触发资源导入。
7. 运行 `DesignToUnityPrefabValidator.ValidateFromCommandLine` 做 Unity 内组件和引用检查。
8. 通过 Unity MCP 实例化 prefab、检查 Button / Slider / Toggle / ToggleGroup / TMP_InputField / TMP_Dropdown / ScrollRect / Scrollbar / RectMask2D / LayoutGroup 等组件。
9. 截图验证。
10. 根据 warnings、source map 和截图继续微调。
```

如果需要让 Unity MCP 继续加工 prefab，应优先读取 direct YAML writer 生成的 `*.design-to-unity.json` source map，而不是重新猜测图层含义。

推荐检查顺序：

```text
psd_design_verify_unity_prefab_yaml
DesignToUnityPrefabValidator.ValidateFromCommandLine
```

前者在 Unity 外做 YAML/source map 静态检查，后者在 Unity 内做导入后的组件和引用检查。

## 18. 最小可用字段清单

第一版为了让 Unity MCP 能稳定工作，每个 packet 至少要提供：

```text
design.width
design.height
design.scale
nodes[].id
nodes[].name
nodes[].type
nodes[].path
nodes[].z_index
nodes[].global_rect
nodes[].local_rect
nodes[].unity_rect_hint
nodes[].style.opacity
nodes[].asset_ref
nodes[].text
assets[].id
assets[].local_path
assets[].suggested_unity_path
assets[].size
assets[].logical_size
assets[].unity_import_hints
handoff_profiles.unity
warnings[]
```

## 19. 总结

Unity 导出规范的当前核心是让 Design to Unity 生成可导入、可校验、可继续加工的静态 UGUI prefab，同时保留足够精确的 Unity 执行说明。

最终协作关系是：

```text
Design to Unity:
  负责说明设计图中有什么、资源在哪里、坐标怎么换、哪些效果有风险，并输出 prefab snapshot、Sprite meta、source map。

Unity MCP:
  负责导入、实例化、检查组件引用、截图验证和继续加工 prefab。

AI:
  负责理解用户要求，在 Design to Unity 和 Unity MCP 之间做调度。
```

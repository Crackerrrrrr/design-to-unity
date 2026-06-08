# Unity 导出规范

## 1. 文档目标

本文档定义 Design Handoff MCP 面向 Unity MCP 输出信息时应遵循的规则。

本规范不要求 Design Handoff MCP 直接创建 Unity 预制体或场景。实际创建、修改、保存 prefab / scene 的动作由 Unity MCP 或 Unity Editor 插件完成。

本规范的目标是：

- 让 AI 能稳定理解蓝湖设计稿如何映射到 Unity UGUI。
- 让 Unity MCP 能根据 Design Implementation Packet 创建可还原的 UI 层级。
- 避免坐标、层级、资源、文本、交互候选等信息产生歧义。
- 为后续重导入、局部更新、组件化替换保留稳定依据。

## 2. 总体原则

### 2.1 职责边界

Design Handoff MCP 负责提供：

- 设计图元数据。
- 标准化节点树。
- 坐标和尺寸。
- 样式信息。
- 文本信息。
- 图片和切图资源清单。
- Unity 专用 handoff profile。
- 节点语义候选。
- warnings 和不确定项。

Unity MCP 负责执行：

- 创建或打开 prefab。
- 创建 GameObject 层级。
- 添加 RectTransform、Image、TextMeshProUGUI、Button 等组件。
- 导入 Sprite 资源。
- 设置 RectTransform。
- 设置 Image / TMP 参数。
- 保存 prefab / scene。
- 截图和验证。

### 2.2 不直接手写 Unity YAML

禁止 Design Handoff MCP 直接手写 `.prefab`、`.unity`、`.asset` 等 Unity YAML 文件。

原因：

- Unity 文件依赖 `fileID`、`guid`、序列化版本和内部引用关系。
- 直接写 YAML 容易造成引用损坏。
- 应由 Unity Editor API 生成最终文件。

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

如果设计图中存在明显状态栏、刘海、安全区标注，Design Handoff MCP 应在 warnings 中提示：

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

Design Handoff MCP 应直接在 Unity Profile 中提供转换结果：

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

Design Handoff MCP 必须明确每个节点坐标是：

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

如果蓝湖原始数据只提供全局坐标，则 Design Handoff MCP 应计算：

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

不要在 Design Handoff MCP 中随意取整到整数，除非原始值本身为整数。

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

Design Handoff MCP 应提供：

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

Design Handoff MCP 必须为每个节点提供 `z_index`。

规则：

```text
z_index 表示从蓝湖源数据读取到的图层顺序。
在已验证的蓝湖页面中，源图层数组更接近“前景到背景”的顺序。
因此 z_index 越小通常越靠前，z_index 越大通常越靠后。
```

### 6.2 Unity sibling index

UGUI 中后面的 sibling 通常渲染在更上层。

Unity MCP 应在同一个父节点下按 `z_index` 从大到小创建节点，或创建后设置 sibling index：

```text
higher z_index -> lower sibling index
lower z_index -> higher sibling index
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
  "suggested_unity_path": "Assets/DesignHandoff/Home/Sprites/btn_start.png",
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

Design Handoff MCP 不强制决定是否使用九宫格，但应提供候选信息：

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
    }
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
Assets/DesignHandoff/{ProjectName}/{DesignName}/Sprites/{asset_name}.png
```

如果用户指定项目资源目录，应优先使用用户目录。

Design Handoff MCP 只提供建议路径，最终复制到 Unity 项目的动作由 Unity MCP 执行。

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
Sprite.border = provided border
```

### 8.3 按钮候选图片

当节点 `semantic_type=button_candidate`：

```text
Image.raycastTarget = true only if Unity MCP decides to add Button.
Do not add Button automatically unless user request or implementation plan says so.
```

### 8.4 透明度

如果节点 `style.opacity < 1`：

优先规则：

```text
如果节点有 Image 或 TMP，设置组件 color alpha。
如果 group 需要整体透明，建议 Unity MCP 添加 CanvasGroup。
```

Design Handoff MCP 应明确：

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

Design Handoff MCP 不直接提供 Unity TMP FontAsset，但应提供字体候选：

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

Design Handoff MCP 应保留：

- `line_height`
- `letter_spacing`

Unity MCP 可以按项目能力映射到：

- TMP `lineSpacing`
- TMP `characterSpacing`

如果无法精确映射，应记录 warning。

### 9.6 文本超框风险

Design Handoff MCP 应检测：

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

Design Handoff MCP 应标记：

```json
{
  "mask_hint": {
    "candidate": true,
    "type": "rect|alpha|unknown",
    "recommended_unity_component": "RectMask2D|Mask"
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
    "default_add_button": false,
    "raycast_target_if_interactive": true
  }
}
```

### 12.2 不自动绑定业务

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

第一版落地仍按静态节点创建。

后续 Unity MCP 可根据用户要求替换为：

- ScrollRect
- GridLayoutGroup
- VerticalLayoutGroup
- 自定义 Item prefab

### 13.2 dialog_candidate

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

- 自定义 `DesignHandoffNode` 组件。
- GameObject name 后缀。
- prefab 外部 manifest。

推荐自定义组件：

```csharp
public class DesignHandoffNode : MonoBehaviour
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

Design Handoff MCP 应提供：

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

Design Handoff MCP 应将不确定或无法直接还原的点放入 warnings。

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
```

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
    "mask": ["GameObject", "RectTransform", "RectMask2D candidate"]
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
    "Do not write prefab YAML directly.",
    "Use Unity Editor API through Unity MCP.",
    "Import all sprites before assigning Image.sprite.",
    "Create same-parent siblings by descending z_index.",
    "Use local_rect for child RectTransform positioning.",
    "Do not add Button automatically unless requested.",
    "Preserve custom scripts and event bindings during reimport."
  ]
}
```

## 17. AI 调用 Unity MCP 推荐流程

```text
1. 读取 Design Implementation Packet。
2. 读取 Unity Handoff Profile。
3. 读取 Asset Manifest。
4. 调 Unity MCP 导入或复制 Sprite 资源。
5. 调 Unity MCP 创建或打开 prefab。
6. 创建 ViewRoot。
7. 按 create_nodes 顺序创建节点；同父节点内按 z_index 从大到小。
8. 对 group 创建 RectTransform。
9. 对 image 创建 Image 并绑定 Sprite。
10. 对 text 创建 TextMeshProUGUI 并设置文本样式。
11. 对 shape 创建 Image 或记录需要项目自定义方案。
12. 对 semantic candidate 只做标记，不擅自绑定业务。
13. 写入 source metadata。
14. 保存 prefab。
15. 截图验证。
16. 根据 warnings 和截图继续微调。
```

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

Unity 导出规范的核心不是让 Design Handoff MCP 直接创建 prefab，而是让它提供一份足够精确的 Unity 执行说明。

最终协作关系是：

```text
Design Handoff MCP:
  负责说明设计图中有什么、资源在哪里、坐标怎么换、哪些效果有风险。

Unity MCP:
  负责根据这些说明调用 Unity Editor API 创建、修改、保存 prefab 或 scene。

AI:
  负责理解用户要求，在 Design Handoff MCP 和 Unity MCP 之间做调度。
```

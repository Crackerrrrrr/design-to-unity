# Design to Unity

[GitHub 仓库](https://github.com/Crackerrrrrr/design-to-unity) · `Crackerrrrrr/design-to-unity`

Design to Unity 是一个面向游戏 UI 落地的 MCP 服务。它可以把蓝湖设计稿、PSD / PSB 文件，以及 Photoshop / UXP 导出物转换成结构化的设计实现数据包、资源清单和 Unity 可导入的 UGUI 预制体 YAML 快照。

它的核心目标不是替代 Unity 编辑器，而是给 AI 和 Unity MCP 提供足够完整、低歧义的设计信息，让设计稿可以更稳定地复原为可检查、可继续加工的 Unity UI。

## 主要能力

- 解析蓝湖项目和设计页
- 读取本地 PSD / PSB 文件
- 读取 Photoshop UXP 导出的 `design.json`、`preview.png` 和图层资源
- 输出设计节点树、坐标、文本、样式、资源和语义提示
- 下载和整理设计资源、切图资源
- 生成 Unity handoff plan
- 直接写出静态 UGUI prefab YAML
- 生成 prefab source map，保留设计节点到 Unity 组件的映射
- 提供静态 prefab YAML 校验
- 可安装 Unity Editor validator 脚本做导入后检查
- 支持 Unity 截图和设计参考图的视觉差异比较

## 支持的 Unity UI 组件提示

- `Image`
- `TextMeshProUGUI`
- `Outline`
- `Shadow`
- `Button`
- `Slider`
- `Toggle`
- `ToggleGroup`
- `TMP_InputField`
- `TMP_Dropdown`
- `ScrollRect`
- `Scrollbar`
- `RectMask2D`
- `VerticalLayoutGroup`
- `HorizontalLayoutGroup`
- `GridLayoutGroup`
- `CanvasGroup`

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

如果需要访问蓝湖，在 `.env` 中配置：

```bash
LANHU_COOKIE=你的蓝湖 Cookie
```

启动 HTTP MCP 服务：

```bash
DesignToUnity
```

如果 MCP 客户端使用 stdio：

```bash
MCP_TRANSPORT=stdio DesignToUnity
```

## 蓝湖工具

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
- `lanhu_design_write_unity_prefab_yaml`
- `lanhu_design_verify_unity_prefab_yaml`

## PSD / Photoshop 工具

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

## Photoshop UXP 导出器

仓库内置一个 Photoshop UXP 导出器模板：

```text
templates/photoshop-uxp-exporter
```

它可以导出：

- `design.json`
- `preview.png`
- 图层 PNG 资源
- Photoshop 可暴露的可编辑文本信息
- 复杂分组的 rasterize 标记

导出后可以通过 `psd_design_prepare_export_packet` 读取，也可以通过 `psd_design_convert_export_to_unity_prefab` 直接转换为 Unity prefab。

## Direct Unity Prefab YAML

直接写 prefab 时会生成：

- Unity `Assets/...` 目录下的资源副本
- 稳定 GUID 的 `.png.meta`
- `.prefab` YAML 文件
- 同目录 `*.design-to-unity.json` source map
- 必要的 `.prefab.meta`

这条路径适合静态 UI 还原、prefab review 和 AI 后续加工。业务脚本、动画绑定、运行时数据绑定和项目自定义逻辑应继续在 Unity 中完成。

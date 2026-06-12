# lanhu-unity-handoff-mcp

[English](README.md) | 中文

`lanhu-unity-handoff-mcp` 是一个 MCP Server，用来读取蓝湖设计稿，并生成适合 Unity 落地的 Design Implementation Packet。

默认流程是“先给完整设计上下文”：它会提取结构化设计信息、下载切图资源、生成节点树、整理 Unity 落地计划，让 AI 助手继续调用 Unity MCP 或 Unity 编辑器侧工具完成 UI 还原。

项目里也提供了一个实验能力：直接写出静态 UGUI prefab YAML 快照。这个能力适合快速预览、对比 prefab、生成一个可检查的初稿；如果要接入项目脚本、动画、精确 TMP 字体、项目自定义导入规则，建议继续使用 Unity MCP 或 Unity Editor API 链路。

## 这个 MCP 的优势

- 可以配合 Unity MCP 使用：本 MCP 负责把蓝湖设计稿整理成干净的设计事实、资源路径、RectTransform 提示、节点层级和有顺序的 Unity 创建计划，再交给 Unity MCP 或 Unity Editor API 在真实项目里创建最终 UI。
- 也可以自己直接生成预制体：当你只需要快速得到一个静态结果时，`lanhu_design_write_unity_prefab_yaml` 可以直接写出 sprite、`.meta` 文件和 UGUI `.prefab` YAML 快照，不需要打开 Unity。
- 能识别常见 UI 组件：标准化流程会标记可能的按钮、文本、图标、背景、面板、列表项、标题、进度条、滑条等语义，让 AI 不只是看到原始图层名，而是能拿到更接近实现意图的提示。
- 输出面向落地的 packet：每个 packet 都包含标准化节点、已下载资源、资源角色、本地路径和 Unity 建议路径、坐标、样式和文本信息、警告以及目标平台 handoff profile。
- 适合 AI 分阶段读取：AI 可以先看摘要，再按需要读取节点树、指定节点详情、切图列表或 Unity plan，避免一次性把整份设计稿塞进上下文。
- 默认不破坏项目工程：默认链路只提供设计上下文和落地计划，不直接修改 Unity 项目，所以项目脚本、动画、prefab 变体、事件绑定和导入规则仍然由你的工程流水线控制。

## 你需要准备什么

- Python 3.10 或更高版本。
- 一个能访问目标设计稿的蓝湖账号。
- 要处理的蓝湖设计稿链接。
- 从你自己已经登录的浏览器里复制出来的蓝湖 Cookie。
- 可选：如果要直接导出 prefab YAML，需要一个 Unity 项目。

真实 Cookie 不要提交到 Git。Cookie 只放在本地 `.env` 文件里。

## 1. 获取蓝湖 Cookie

这个 MCP 会用你的蓝湖 Cookie 请求设计稿数据。它相当于复用你浏览器登录后的访问权限。

1. 用 Chrome 或 Chromium 内核浏览器打开 [蓝湖](https://lanhuapp.com)。
2. 登录能访问目标项目的账号。
3. 打开目标设计稿或项目页面。
4. 打开开发者工具：
   - macOS：`Option + Command + I`
   - Windows/Linux：`Ctrl + Shift + I`
5. 切到 `Network` 面板。
6. 保持开发者工具打开，刷新蓝湖页面。
7. 点击一个域名是 `lanhuapp.com` 或 `dds.lanhuapp.com` 的请求。
8. 在 `Headers` 里找到 `Request Headers`。
9. 复制 `Cookie` 请求头的完整值。

复制出来通常是一整行，里面有很多用分号分隔的 `key=value`：

```text
key1=value1; key2=value2; key3=value3
```

注意：不要只复制某一个 cookie 项，要复制完整的 `Cookie:` 请求头值。

如果后续设计数据能读取，但图片或切图下载失败，再找一个 `dds.lanhuapp.com` 的请求，按同样方式复制它的 `Cookie` 值，填到 `DDS_COOKIE`。多数情况下只填 `LANHU_COOKIE` 就够。

## 2. 安装

克隆仓库并创建虚拟环境：

```bash
gh repo clone Crackerrrrrr/lanhu-unity-handoff-mcp
cd lanhu-unity-handoff-mcp

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

如果不用 GitHub CLI，也可以用普通 `git clone`：

```bash
git clone https://github.com/Crackerrrrrr/lanhu-unity-handoff-mcp.git
cd lanhu-unity-handoff-mcp

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 3. 配置 `.env`

创建本地配置文件：

```bash
cp .env.example .env
```

打开 `.env`，把完整 Cookie 粘进去：

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

只有当蓝湖图片资源需要不同 Cookie 时，才额外设置 `DDS_COOKIE`：

```bash
DDS_COOKIE="key1=value1; key2=value2; key3=value3"
```

建议：不确定时不要设置 `DDS_COOKIE`。

## 4. 以 HTTP MCP Server 方式运行

启动服务：

```bash
lanhu-unity-handoff-mcp
```

默认地址是：

```text
http://127.0.0.1:8125/mcp
```

MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "LanhuUnityHandoffMcp": {
      "url": "http://localhost:8125/mcp"
    }
  }
}
```

## 5. 以 stdio MCP Server 方式运行

如果你的 MCP 客户端是直接启动本地命令，使用仓库里的脚本：

```bash
./run-stdio.sh
```

MCP 客户端配置示例：

```json
{
  "mcpServers": {
    "LanhuUnityHandoffMcp": {
      "command": "/absolute/path/to/lanhu-unity-handoff-mcp/run-stdio.sh"
    }
  }
}
```

Codex CLI 常见注册方式：

```bash
codex mcp add lanhu-unity-handoff-mcp -- /absolute/path/to/lanhu-unity-handoff-mcp/run-stdio.sh
```

修改 MCP 配置后，记得重启对应客户端。

## 6. 基本使用流程

推荐按下面顺序调用工具。

1. 列出蓝湖项目里的设计稿：

```text
lanhu_design_list(url="<蓝湖项目或设计稿链接>")
```

2. 生成 Design Implementation Packet：

```text
lanhu_design_prepare_packet(
  url="<蓝湖项目或设计稿链接>",
  design_name_or_index="<设计稿名称或列表序号>",
  target="unity"
)
```

这个步骤会读取蓝湖数据，把节点标准化，并把资源下载到 `DATA_DIR`，最后返回 `packet_id`。

3. 查看实现摘要：

```text
lanhu_design_get_summary(packet_id="<packet_id>")
```

4. 查看 Unity 执行计划：

```text
lanhu_design_get_unity_plan(packet_id="<packet_id>")
```

5. 查看切图资源和坐标：

```text
lanhu_design_get_slices(packet_id="<packet_id>")
```

6. 让 Unity MCP 或 Unity 编辑器侧工具按计划导入资源、创建 UI。

## 7. 直接导出 Unity Prefab YAML

直接写 YAML 是实验功能。它适合快速生成静态 UGUI 快照、做 prefab diff、做视觉检查。正式生产 UI 如果涉及项目脚本、动画、精确 TMP 字体、自定义导入规则，建议使用 Unity MCP 或 Unity Editor API。

调用示例：

```text
lanhu_design_write_unity_prefab_yaml(
  packet_id="<packet_id>",
  unity_project_path="/absolute/path/to/YourUnityProject",
  asset_root="Assets/DesignHandoff/LanhuUnityHandoffMcp",
  prefab_name="LanhuGenerated.prefab",
  overwrite=true
)
```

它会写出：

- 复制到 Unity `Assets/...` 目录下的 sprite 图片。
- 带确定性 GUID 的 `.png.meta` 文件。
- 一个包含 UGUI 对象和组件的 `.prefab` YAML 文件。
- 必要时生成 `.prefab.meta` 文件。

生成的 prefab 可能包含 `GameObject`、`RectTransform`、`CanvasRenderer`、`Image`、`TextMeshProUGUI`、`Button`、`Slider` 等组件。

## 工具说明

- `lanhu_design_list`：列出蓝湖项目里的设计稿。
- `lanhu_design_prepare_packet`：获取设计数据、标准化节点、下载资源并生成 packet。
- `lanhu_design_get_packet`：返回完整 packet。
- `lanhu_design_get_summary`：返回适合 AI 阅读的紧凑实现摘要。
- `lanhu_design_get_node_tree`：返回裁剪后的节点层级树。
- `lanhu_design_get_node_detail`：返回指定节点的完整详情。
- `lanhu_design_get_asset_manifest`：返回已下载资源和 Unity 导入提示。
- `lanhu_design_get_slices`：返回有图片资源的设计节点、资源路径和坐标提示。
- `lanhu_design_get_unity_plan`：返回有顺序的 Unity 创建和导入计划。
- `lanhu_design_write_unity_prefab_yaml`：实验性写出静态 Unity UGUI prefab YAML。
- `lanhu_design_get_handoff_profile`：返回目标平台落地规则。

## 常见问题

如果蓝湖请求报登录或权限错误：

- 确认复制的是完整 `Cookie` 请求头值。
- 确认浏览器登录账号有目标项目权限。
- 刷新蓝湖页面，复制新的 Cookie，更新 `.env`。
- 修改 `.env` 后重启 MCP Server。

如果图片或切图资源缺失：

- 从 `dds.lanhuapp.com` 请求里复制 Cookie。
- 在 `.env` 里设置 `DDS_COOKIE="..."`。
- 重新调用 `lanhu_design_prepare_packet`。

如果 MCP 客户端看不到工具：

- 确认服务已经启动。
- HTTP 模式确认地址是 `http://localhost:8125/mcp`。
- stdio 模式确认 `run-stdio.sh` 使用的是绝对路径。
- 修改 MCP 配置后重启客户端。

如果 Unity prefab 导出失败：

- 确认 `unity_project_path` 指向 Unity 项目根目录，且里面有 `Assets` 文件夹。
- 确认 `asset_root` 以 `Assets/` 开头。
- 文件写入后关闭 Unity，或等待 Unity 自动重新导入资源。

## 已验证案例

`-h-海报分享` 设计稿已成功生成过 packet：

- 77 个标准化节点。
- 77 个已下载资源，包括完整设计参考图。
- 76 个带切图资源和坐标的节点。
- 0 个下载失败。
- Unity plan 能输出资源导入、父子节点、组件提示和 RectTransform 提示。
- 直接 prefab YAML 写出冒烟测试结果：77 个 GameObject、65 个 Image、11 个 TextMeshProUGUI、10 个 Button、65 个复制 sprite。
- Summary 能输出语义数量、资源角色、警告数量和 Unity 就绪信息。
- 资源角色包括 `background`、`button_sprite`、`icon`、`text_sprite`、`panel`、`design_reference`。

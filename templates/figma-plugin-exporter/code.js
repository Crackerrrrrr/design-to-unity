figma.showUI(__html__, { width: 320, height: 180 });

const TAG_DATA_KEYS = ["manualTags", "tags", "designToUnityTags"];
const SHARED_DATA_NAMESPACES = ["design-to-unity", "design_to_unity"];

figma.ui.onmessage = async (message) => {
  if (!message || message.type !== "export") return;
  try {
    figma.ui.postMessage({ type: "status", message: "Collecting selected nodes..." });
    const root = figma.currentPage.selection[0] || figma.currentPage;
    const exportRoot = normalizeNode(root);
    const exportNodes = collectExportNodes(root);

    figma.ui.postMessage({ type: "status", message: `Rendering preview and ${exportNodes.length} asset(s)...` });
    const previewBytes = await root.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
    const assets = [];
    for (const node of exportNodes) {
      try {
        const bytes = await node.exportAsync({ format: "PNG", constraint: { type: "SCALE", value: 1 } });
        assets.push({
          node_id: node.id,
          file_name: `${safeFileName(node.name || node.id)}_${safeFileName(node.id)}.png`,
          usage: usageForNode(node),
          mime_type: "image/png",
          data: `data:image/png;base64,${bytesToBase64(bytes)}`
        });
      } catch (error) {
        assets.push({
          node_id: node.id,
          file_name: `${safeFileName(node.name || node.id)}_${safeFileName(node.id)}.png`,
          usage: usageForNode(node),
          error: String(error && error.message ? error.message : error)
        });
      }
    }

    const manifest = {
      schema: "design-to-unity.figma-export",
      schema_version: 1,
      plugin_version: "0.2.0",
      exported_at: new Date().toISOString(),
      file_key: "",
      file_name: figma.root.name || "Figma File",
      page_id: figma.currentPage.id,
      page_name: figma.currentPage.name,
      root_node_id: root.id,
      root_node_name: root.name,
      image_scale: 1,
      image_format: "png",
      root: exportRoot,
      preview: {
        file_name: "preview.png",
        mime_type: "image/png",
        data: `data:image/png;base64,${bytesToBase64(previewBytes)}`
      },
      assets
    };

    figma.ui.postMessage({
      type: "download",
      fileName: `${safeFileName(root.name || "figma")}-design-to-unity.json`,
      assetCount: assets.filter((asset) => asset.data).length,
      manifest
    });
  } catch (error) {
    figma.ui.postMessage({ type: "error", message: String(error && error.message ? error.message : error) });
  }
};

function normalizeNode(node) {
  const result = {
    id: node.id,
    name: node.name,
    type: node.type,
    visible: node.visible,
    locked: node.locked,
    absoluteBoundingBox: clone(node.absoluteBoundingBox),
    absoluteRenderBounds: clone(node.absoluteRenderBounds),
    relativeTransform: clone(node.relativeTransform),
    constraints: clone(node.constraints),
    opacity: "opacity" in node ? node.opacity : undefined,
    blendMode: "blendMode" in node ? node.blendMode : undefined,
    fills: clonePaints("fills" in node ? node.fills : undefined),
    strokes: clonePaints("strokes" in node ? node.strokes : undefined),
    strokeWeight: "strokeWeight" in node ? node.strokeWeight : undefined,
    strokeAlign: "strokeAlign" in node ? node.strokeAlign : undefined,
    cornerRadius: "cornerRadius" in node ? cloneMixed(node.cornerRadius) : undefined,
    rectangleCornerRadii: "rectangleCornerRadii" in node ? clone(node.rectangleCornerRadii) : undefined,
    effects: clone("effects" in node ? node.effects : undefined),
    clipsContent: "clipsContent" in node ? node.clipsContent : undefined,
    layoutMode: "layoutMode" in node ? node.layoutMode : undefined,
    layoutWrap: "layoutWrap" in node ? node.layoutWrap : undefined,
    itemSpacing: "itemSpacing" in node ? cloneMixed(node.itemSpacing) : undefined,
    paddingLeft: "paddingLeft" in node ? node.paddingLeft : undefined,
    paddingRight: "paddingRight" in node ? node.paddingRight : undefined,
    paddingTop: "paddingTop" in node ? node.paddingTop : undefined,
    paddingBottom: "paddingBottom" in node ? node.paddingBottom : undefined,
    primaryAxisAlignItems: "primaryAxisAlignItems" in node ? node.primaryAxisAlignItems : undefined,
    counterAxisAlignItems: "counterAxisAlignItems" in node ? node.counterAxisAlignItems : undefined,
    primaryAxisSizingMode: "primaryAxisSizingMode" in node ? node.primaryAxisSizingMode : undefined,
    counterAxisSizingMode: "counterAxisSizingMode" in node ? node.counterAxisSizingMode : undefined,
    layoutGrow: "layoutGrow" in node ? node.layoutGrow : undefined,
    layoutAlign: "layoutAlign" in node ? node.layoutAlign : undefined,
    layoutPositioning: "layoutPositioning" in node ? node.layoutPositioning : undefined,
    layoutSizingHorizontal: "layoutSizingHorizontal" in node ? node.layoutSizingHorizontal : undefined,
    layoutSizingVertical: "layoutSizingVertical" in node ? node.layoutSizingVertical : undefined,
    minWidth: "minWidth" in node ? node.minWidth : undefined,
    maxWidth: "maxWidth" in node ? node.maxWidth : undefined,
    minHeight: "minHeight" in node ? node.minHeight : undefined,
    maxHeight: "maxHeight" in node ? node.maxHeight : undefined,
    isMask: "isMask" in node ? node.isMask : undefined,
    maskType: "maskType" in node ? node.maskType : undefined,
    reactions: "reactions" in node ? clone(node.reactions) : undefined,
    componentId: node.type === "INSTANCE" && node.mainComponent ? node.mainComponent.id : undefined,
    componentProperties: "componentProperties" in node ? clone(node.componentProperties) : undefined,
    componentPropertyDefinitions: "componentPropertyDefinitions" in node ? clone(node.componentPropertyDefinitions) : undefined,
    styles: clone("styles" in node ? node.styles : undefined)
  };
  const manualTags = extractManualTags(node);
  if (manualTags.length) result.manualTags = manualTags;
  const pluginData = pluginDataForNode(node);
  if (Object.keys(pluginData).length) result.pluginData = pluginData;

  if (node.type === "TEXT") {
    result.characters = node.characters;
    result.style = {
      fontFamily: cloneMixed(node.fontName && node.fontName.family),
      fontPostScriptName: cloneMixed(node.fontName && node.fontName.style),
      fontSize: cloneMixed(node.fontSize),
      fontWeight: cloneMixed(node.fontWeight),
      textAlignHorizontal: node.textAlignHorizontal,
      textAlignVertical: node.textAlignVertical,
      lineHeightPx: cloneLineHeight(node.lineHeight),
      letterSpacing: cloneLetterSpacing(node.letterSpacing)
    };
    result.styleOverrideTable = clone("styleOverrideTable" in node ? node.styleOverrideTable : undefined);
    result.characterStyleOverrides = clone("characterStyleOverrides" in node ? node.characterStyleOverrides : undefined);
  }

  if ("children" in node) {
    result.children = node.children.map((child) => normalizeNode(child));
  }
  return dropUndefined(result);
}

function extractManualTags(node) {
  const tags = new Set();
  addExplicitTags(tags, String(node.name || ""));
  for (const value of manualTagDataValues(node)) {
    addDelimitedTags(tags, value);
  }
  return Array.from(tags).sort();
}

function pluginDataForNode(node) {
  const values = manualTagDataValues(node);
  if (!values.length) return {};
  const tags = new Set();
  for (const value of values) addDelimitedTags(tags, value);
  const manualTags = Array.from(tags).sort();
  return manualTags.length ? { manualTags } : {};
}

function manualTagDataValues(node) {
  const values = [];
  for (const key of TAG_DATA_KEYS) {
    pushPluginDataValue(values, () => node.getPluginData(key));
    for (const namespace of SHARED_DATA_NAMESPACES) {
      pushPluginDataValue(values, () => node.getSharedPluginData(namespace, key));
    }
  }
  return values;
}

function pushPluginDataValue(values, getter) {
  try {
    const value = getter();
    if (value) values.push(String(value));
  } catch (_error) {
    // Some node-like objects in tests or older Figma runtimes may not expose plugin data APIs.
  }
}

function addExplicitTags(tags, value) {
  const text = Array.isArray(value) ? value.join(" ") : String(value || "");
  for (const match of text.matchAll(/[@#]([a-zA-Z][\w-]*)/g)) {
    tags.add(match[1].toLowerCase());
  }
}

function addDelimitedTags(tags, value) {
  const text = Array.isArray(value) ? value.join(" ") : String(value || "");
  addExplicitTags(tags, text);
  for (const raw of text.split(/[,\s]+/g)) {
    const tag = raw.trim().replace(/^[@#]+/, "").toLowerCase();
    if (/^[a-z][\w-]*$/.test(tag)) tags.add(tag);
  }
}

function collectExportNodes(root) {
  const result = [];
  walk(root, (node) => {
    if (node === root) return;
    if (shouldExportNode(node)) result.push(node);
  });
  return result;
}

function walk(node, visit) {
  visit(node);
  if ("children" in node) {
    for (const child of node.children) walk(child, visit);
  }
}

function shouldExportNode(node) {
  if (!node.visible) return false;
  if (["VECTOR", "BOOLEAN_OPERATION", "STAR", "POLYGON", "LINE"].includes(node.type)) return true;
  if ("fills" in node && Array.isArray(node.fills) && node.fills.some((paint) => paint && paint.visible !== false && paint.type === "IMAGE")) return true;
  if ("fills" in node && Array.isArray(node.fills) && node.fills.filter((paint) => paint && paint.visible !== false).length > 1) return true;
  if ("fills" in node && Array.isArray(node.fills) && node.fills.some((paint) => paint && paint.visible !== false && String(paint.type || "").startsWith("GRADIENT"))) return true;
  if ("effects" in node && Array.isArray(node.effects) && node.effects.some((effect) => effect && effect.visible !== false && ["LAYER_BLUR", "BACKGROUND_BLUR"].includes(effect.type))) return true;
  if ("blendMode" in node && !["NORMAL", "PASS_THROUGH"].includes(String(node.blendMode || "").toUpperCase())) return true;
  if ("isMask" in node && node.isMask) return true;
  if ("maskType" in node && node.maskType) return true;
  return false;
}

function usageForNode(node) {
  if (node.type === "TEXT") return "text";
  if (["RECTANGLE", "ELLIPSE", "POLYGON", "STAR", "LINE"].includes(node.type)) return "shape";
  return "image";
}

function clone(value) {
  if (value === undefined || value === null || value === figma.mixed) return undefined;
  try {
    return JSON.parse(JSON.stringify(value));
  } catch (_error) {
    return undefined;
  }
}

function clonePaints(value) {
  if (!Array.isArray(value)) return undefined;
  return value.map((paint) => clone(paint)).filter(Boolean);
}

function cloneMixed(value) {
  return value === figma.mixed ? undefined : clone(value);
}

function cloneLineHeight(value) {
  const cloned = cloneMixed(value);
  if (!cloned || cloned.unit !== "PIXELS") return undefined;
  return cloned.value;
}

function cloneLetterSpacing(value) {
  const cloned = cloneMixed(value);
  if (!cloned) return undefined;
  return cloned.value;
}

function dropUndefined(value) {
  const result = {};
  for (const key of Object.keys(value)) {
    if (value[key] !== undefined) result[key] = value[key];
  }
  return result;
}

function safeFileName(value) {
  return String(value || "node").replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^_+|_+$/g, "") || "node";
}

function bytesToBase64(bytes) {
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

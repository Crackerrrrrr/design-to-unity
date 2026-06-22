/* global require */

const photoshop = require("photoshop");
const uxp = require("uxp");

const { app, action, core } = photoshop;
const { storage } = uxp;
const localFileSystem = storage.localFileSystem;

const EXPORT_SCHEMA = "design-to-unity.photoshop-export";
const EXPORT_SCHEMA_VERSION = 1;

let exportFolder = null;

document.addEventListener("DOMContentLoaded", () => {
  byId("chooseFolderBtn").addEventListener("click", chooseExportFolder);
  byId("exportBtn").addEventListener("click", exportActiveDocument);
});

function byId(id) {
  return document.getElementById(id);
}

function setStatus(message) {
  byId("status").textContent = typeof message === "string" ? message : JSON.stringify(message, null, 2);
}

async function chooseExportFolder() {
  try {
    exportFolder = await localFileSystem.getFolder();
    byId("folderLabel").textContent = exportFolder.nativePath || exportFolder.name || "Folder selected.";
    byId("exportBtn").disabled = false;
    setStatus("Ready to export.");
  } catch (error) {
    setStatus(`Folder selection cancelled or failed:\n${formatError(error)}`);
  }
}

async function exportActiveDocument() {
  if (!exportFolder) {
    setStatus("Choose an export folder first.");
    return;
  }

  const documentRef = app.activeDocument;
  if (!documentRef) {
    setStatus("Open a Photoshop document first.");
    return;
  }

  byId("exportBtn").disabled = true;
  const startedAt = Date.now();
  try {
    const result = await core.executeAsModal(
      async (executionContext) => exportDocument(documentRef, executionContext),
      { commandName: "Export Design to Unity" }
    );
    result.elapsedMs = Date.now() - startedAt;
    setStatus(result);
  } catch (error) {
    setStatus(`Export failed:\n${formatError(error)}`);
  } finally {
    byId("exportBtn").disabled = false;
  }
}

async function exportDocument(documentRef, executionContext) {
  const assetsFolder = await getOrCreateFolder(exportFolder, "assets");
  const designFile = await exportFolder.createFile("design.json", { overwrite: true });
  const previewFile = await exportFolder.createFile("preview.png", { overwrite: true });
  const notes = [];

  await documentRef.saveAs.png(previewFile, { compression: 6 }, true);

  const options = {
    documentRef,
    assetsFolder,
    rasterizeComplexGroups: byId("rasterComplexGroups").checked,
    notes,
    executionContext,
  };
  const layers = await serializeLayers(documentRef.layers, [], options);
  const manifest = {
    schema: EXPORT_SCHEMA,
    schema_version: EXPORT_SCHEMA_VERSION,
    generator: {
      name: "Design to Unity Photoshop UXP Exporter",
      version: "0.1.0",
    },
    document: {
      id: documentRef.id,
      name: documentRef.title || documentRef.name || "PhotoshopDocument",
      width: safeNumber(documentRef.width, 0),
      height: safeNumber(documentRef.height, 0),
      scale: 1,
      preview: "preview.png",
      layers,
    },
    notes,
  };

  await designFile.write(JSON.stringify(manifest, null, 2));
  return {
    status: "exported",
    schema: EXPORT_SCHEMA,
    designFile: designFile.nativePath || "design.json",
    previewFile: previewFile.nativePath || "preview.png",
    layerCount: countLayers(layers),
    assetLayerCount: countAssets(layers),
    notes,
  };
}

async function serializeLayers(layersCollection, parentIndexPath, options) {
  const result = [];
  const layers = layersToArray(layersCollection);
  for (let index = 0; index < layers.length; index += 1) {
    const layer = layers[index];
    const node = await serializeLayer(layer, parentIndexPath.concat(index), options);
    if (node) {
      result.push(node);
    }
  }
  return result;
}

async function serializeLayer(layer, indexPath, options) {
  const descriptor = await readLayerDescriptor(layer);
  const bounds = boundsToRect(layer.bounds || descriptor.bounds);
  const kind = normalizeKind(layer.kind || descriptor.layerKind || descriptor.kind);
  const text = textInfo(layer, descriptor);
  const childLayers = layersToArray(layer.layers);
  const features = featureInfo(layer, descriptor);
  const isGroup = childLayers.length > 0;
  const rasterized = isGroup && options.rasterizeComplexGroups && features.unsupported_psd_features.length > 0;
  const node = {
    id: String(layer.id || descriptor.layerID || indexPath.join("_")),
    name: String(layer.name || descriptor.name || `Layer ${indexPath.join(".")}`),
    kind,
    visible: layer.visible !== false,
    index_path: indexPath,
    bounds,
    opacity: safeNumber(layer.opacity, safeNumber(descriptor.opacity, 100)),
    blendMode: stringValue(layer.blendMode || descriptor.mode || descriptor.blendMode),
    hasMask: features.has_mask,
    hasVectorMask: features.has_vector_mask,
    clipping: features.has_clipping_mask,
    hasLayerEffects: features.has_layer_effects,
    isSmartObject: features.is_smart_object,
    isAdjustmentLayer: features.is_adjustment_layer,
    unsupported_psd_features: features.unsupported_psd_features,
  };

  if (!node.visible) {
    return node;
  }

  if (text) {
    node.text = text;
  }

  if (rasterized) {
    node.rasterized = true;
    node.kind = "pixel";
  } else if (isGroup) {
    node.layers = await serializeLayers(layer.layers, indexPath, options);
  }

  const shouldExportAsset = !text && hasPositiveBounds(bounds) && (!isGroup || rasterized);
  if (shouldExportAsset) {
    const assetName = `${sanitizeFileName(indexPath.join("_"))}_${sanitizeFileName(node.name)}.png`;
    const assetFile = await options.assetsFolder.createFile(assetName, { overwrite: true });
    try {
      await exportBranchPng(options.documentRef, indexPath, assetFile, bounds, options.executionContext);
      node.asset = `assets/${assetName}`;
    } catch (error) {
      node.exportError = formatError(error);
      options.notes.push({
        code: "layer_asset_export_failed",
        layer_id: node.id,
        layer_name: node.name,
        message: node.exportError,
      });
    }
  }

  if (features.recommended_role) {
    node.role = features.recommended_role;
  }
  return node;
}

async function exportBranchPng(sourceDocument, targetIndexPath, assetFile, bounds, executionContext) {
  const duplicate = await sourceDocument.duplicate(`d2u_export_${targetIndexPath.join("_")}`, false);
  if (executionContext && executionContext.hostControl && duplicate.id) {
    await executionContext.hostControl.registerAutoCloseDocument(duplicate.id);
  }
  try {
    await applyBranchVisibility(duplicate.layers, targetIndexPath, []);
    await duplicate.crop({
      left: Math.max(0, bounds.x),
      top: Math.max(0, bounds.y),
      right: Math.max(bounds.x + 1, bounds.x + bounds.width),
      bottom: Math.max(bounds.y + 1, bounds.y + bounds.height),
    });
    await duplicate.saveAs.png(assetFile, { compression: 6 }, true);
  } finally {
    if (executionContext && executionContext.hostControl && duplicate.id) {
      await executionContext.hostControl.unregisterAutoCloseDocument(duplicate.id);
    }
    await duplicate.closeWithoutSaving();
  }
}

async function applyBranchVisibility(layersCollection, targetIndexPath, currentPath) {
  const layers = layersToArray(layersCollection);
  for (let index = 0; index < layers.length; index += 1) {
    const layer = layers[index];
    const path = currentPath.concat(index);
    const visible = isAncestorOrDescendant(path, targetIndexPath);
    try {
      layer.visible = visible;
    } catch (error) {
      // Background layers and some locked layers may reject visibility edits.
    }
    if (layer.layers && layer.layers.length) {
      await applyBranchVisibility(layer.layers, targetIndexPath, path);
    }
  }
}

function isAncestorOrDescendant(path, targetPath) {
  return startsWithPath(path, targetPath) || startsWithPath(targetPath, path);
}

function startsWithPath(path, prefix) {
  if (prefix.length > path.length) {
    return false;
  }
  for (let index = 0; index < prefix.length; index += 1) {
    if (path[index] !== prefix[index]) {
      return false;
    }
  }
  return true;
}

async function readLayerDescriptor(layer) {
  if (!action || !action.batchPlay || layer.id == null) {
    return {};
  }
  try {
    const result = await action.batchPlay(
      [
        {
          _obj: "get",
          _target: [{ _ref: "layer", _id: layer.id }],
          _options: { dialogOptions: "dontDisplay" },
        },
      ],
      {}
    );
    return result && result[0] ? result[0] : {};
  } catch (error) {
    return {};
  }
}

function featureInfo(layer, descriptor) {
  const blendMode = normalizeBlendMode(stringValue(layer.blendMode || descriptor.mode || descriptor.blendMode));
  const kind = normalizeKind(layer.kind || descriptor.layerKind || descriptor.kind);
  const hasMask = boolValue(descriptor.hasUserMask) || boolValue(descriptor.userMaskEnabled) || hasObject(descriptor.userMask);
  const hasVectorMask = boolValue(descriptor.hasVectorMask) || boolValue(descriptor.vectorMaskEnabled) || hasObject(descriptor.vectorMask);
  const hasClippingMask = boolValue(layer.isClippingMask) || boolValue(descriptor.group) || boolValue(descriptor.clipping);
  const hasLayerEffects = hasObject(descriptor.layerEffects) || hasObject(descriptor.effects);
  const isSmartObject = kind.includes("smart") || kind.includes("placed") || hasObject(descriptor.smartObject) || hasObject(descriptor.smartObjectMore);
  const isAdjustmentLayer = isAdjustmentKind(kind);
  const usesBlend = Boolean(blendMode && blendMode !== "normal" && blendMode !== "pass through" && blendMode !== "passthrough");
  const unsupported = [];

  if (hasMask) unsupported.push("mask");
  if (hasVectorMask) unsupported.push("vector_mask");
  if (hasClippingMask) unsupported.push("clipping_mask");
  if (hasLayerEffects) unsupported.push("layer_effects");
  if (usesBlend) unsupported.push("blend_mode");
  if (isSmartObject) unsupported.push("smart_object");
  if (isAdjustmentLayer) unsupported.push("adjustment_layer");

  return {
    has_mask: hasMask,
    has_vector_mask: hasVectorMask,
    has_clipping_mask: hasClippingMask,
    has_layer_effects: hasLayerEffects,
    is_smart_object: isSmartObject,
    is_adjustment_layer: isAdjustmentLayer,
    unsupported_psd_features: unsupported,
    recommended_role: roleFromName(layer.name || descriptor.name || ""),
  };
}

function textInfo(layer, descriptor) {
  const kind = normalizeKind(layer.kind || descriptor.layerKind || descriptor.kind);
  if (!kind.includes("text") && !descriptor.textKey) {
    return null;
  }

  try {
    if (layer.textItem) {
      return {
        content: String(layer.textItem.contents || ""),
        fontFamily: stringValue(layer.textItem.font),
        fontSize: safeNumber(layer.textItem.size || layer.textItem.fontSize, 24),
        color: colorToRgba(layer.textItem.color),
        align: stringValue(layer.textItem.justification || layer.textItem.alignment),
      };
    }
  } catch (error) {
    // Fall through to batchPlay textKey extraction.
  }

  const textKey = descriptor.textKey || {};
  const content = textKey.textKey || descriptor.text || descriptor.contents;
  if (content == null) {
    return null;
  }
  return {
    content: String(content),
    fontSize: 24,
  };
}

function roleFromName(name) {
  const text = String(name).toLowerCase();
  if (/\b(btn|button)\b|按钮|开始|领取|确认|取消/.test(text)) {
    return "button_candidate";
  }
  if (/slider|thumb|滑块/.test(text)) {
    return "slider_candidate";
  }
  if (/progress|fill|bar|进度/.test(text)) {
    return "progress_candidate";
  }
  if (/scroll|list|viewport|content|列表|滚动/.test(text)) {
    return "scroll_area_candidate";
  }
  return null;
}

function boundsToRect(bounds) {
  if (!bounds) {
    return { x: 0, y: 0, width: 0, height: 0 };
  }
  const left = safeNumber(bounds.left, safeNumber(bounds.x, 0));
  const top = safeNumber(bounds.top, safeNumber(bounds.y, 0));
  const right = safeNumber(bounds.right, left + safeNumber(bounds.width, 0));
  const bottom = safeNumber(bounds.bottom, top + safeNumber(bounds.height, 0));
  return {
    x: round(left),
    y: round(top),
    width: round(Math.max(0, right - left)),
    height: round(Math.max(0, bottom - top)),
    left: round(left),
    top: round(top),
    right: round(right),
    bottom: round(bottom),
  };
}

function layersToArray(layersCollection) {
  if (!layersCollection) {
    return [];
  }
  if (Array.isArray(layersCollection)) {
    return layersCollection;
  }
  const result = [];
  for (let index = 0; index < layersCollection.length; index += 1) {
    result.push(layersCollection[index]);
  }
  return result;
}

async function getOrCreateFolder(parent, name) {
  try {
    const existing = await parent.getEntry(name);
    if (existing && existing.isFolder) {
      return existing;
    }
  } catch (error) {
    // Missing folder; create it below.
  }
  return parent.createFolder(name);
}

function countLayers(layers) {
  return layers.reduce((total, layer) => total + 1 + countLayers(layer.layers || []), 0);
}

function countAssets(layers) {
  return layers.reduce((total, layer) => total + (layer.asset ? 1 : 0) + countAssets(layer.layers || []), 0);
}

function hasPositiveBounds(bounds) {
  return bounds && bounds.width > 0 && bounds.height > 0;
}

function normalizeKind(value) {
  return stringValue(value).replace(/.*\./, "").replace(/_/g, "").toLowerCase();
}

function normalizeBlendMode(value) {
  return stringValue(value).replace(/.*\./, "").replace(/_/g, " ").replace(/-/g, " ").trim().toLowerCase();
}

function stringValue(value) {
  if (value == null) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (value._value) {
    return String(value._value);
  }
  if (value.value) {
    return String(value.value);
  }
  return String(value);
}

function numberValue(value) {
  if (value == null) {
    return Number.NaN;
  }
  if (typeof value === "number") {
    return value;
  }
  if (value && typeof value.value === "number") {
    return value.value;
  }
  if (value && typeof value.as === "function") {
    try {
      return value.as("px");
    } catch (error) {
      return Number(value);
    }
  }
  return Number(value);
}

function safeNumber(value, fallback) {
  const number = numberValue(value);
  return Number.isFinite(number) ? number : fallback;
}

function round(value) {
  return Math.round(value * 1000) / 1000;
}

function boolValue(value) {
  if (value == null) {
    return false;
  }
  if (typeof value === "boolean") {
    return value;
  }
  if (typeof value === "object" && value._value != null) {
    return Boolean(value._value);
  }
  return Boolean(value);
}

function hasObject(value) {
  if (!value) {
    return false;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  return typeof value === "object" ? Object.keys(value).length > 0 : Boolean(value);
}

function isAdjustmentKind(kind) {
  return [
    "brightnesscontrast",
    "colorbalance",
    "curves",
    "exposure",
    "gradientmap",
    "huesaturation",
    "levels",
    "posterize",
    "selectivecolor",
    "threshold",
    "vibrance",
  ].includes(kind);
}

function colorToRgba(color) {
  if (!color) {
    return null;
  }
  try {
    if (color.rgb) {
      const rgb = color.rgb;
      return `rgba(${Math.round(rgb.red)},${Math.round(rgb.green)},${Math.round(rgb.blue)},1)`;
    }
  } catch (error) {
    return null;
  }
  return null;
}

function sanitizeFileName(value) {
  const safe = String(value || "layer")
    .replace(/[\\/:*?"<>|]+/g, "_")
    .replace(/\s+/g, "_")
    .replace(/_+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 80);
  return safe || "layer";
}

function formatError(error) {
  if (!error) {
    return "Unknown error";
  }
  return error.stack || error.message || String(error);
}

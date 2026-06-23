#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

public static class DesignToUnityPrefabImporter
{
    private const string MenuPath = "Tools/Design To Unity/Import Prefab From Source Map";

    [MenuItem(MenuPath)]
    public static void ImportFromMenu()
    {
        string sourceMapPath = EditorUtility.OpenFilePanel("Design to Unity Source Map", Application.dataPath, "json");
        if (string.IsNullOrEmpty(sourceMapPath))
        {
            return;
        }

        string assetPath = ToAssetPath(sourceMapPath);
        string outputPath = EditorUtility.SaveFilePanelInProject("Save Imported Prefab", "DesignToUnityImported", "prefab", "Choose output prefab path");
        if (string.IsNullOrEmpty(outputPath))
        {
            return;
        }

        Import(assetPath, outputPath);
    }

    public static void ImportFromCommandLine()
    {
        if (!string.IsNullOrEmpty(ReadArg("-d2uSourceMaps"))
            || !string.IsNullOrEmpty(ReadArg("-d2uSourceMapList"))
            || !string.IsNullOrEmpty(ReadArg("-d2uSourceMapDir")))
        {
            ImportBatchFromCommandLine();
            return;
        }

        string sourceMapPath = ReadArg("-d2uSourceMap");
        string outputPrefabPath = ReadArg("-d2uOutputPrefab");
        if (string.IsNullOrEmpty(sourceMapPath))
        {
            throw new ArgumentException("Missing -d2uSourceMap Assets/... source map path.");
        }
        if (string.IsNullOrEmpty(outputPrefabPath))
        {
            throw new ArgumentException("Missing -d2uOutputPrefab Assets/... prefab path.");
        }

        bool incremental = ReadBoolArg("-d2uIncremental", false);
        string reportPath = ReadArg("-d2uReport");
        string savedPath = Import(sourceMapPath, outputPrefabPath, incremental, reportPath);
        Debug.Log("Design to Unity imported prefab: " + savedPath);
    }

    public static void ImportBatchFromCommandLine()
    {
        string[] sourceMapPaths = ResolveBatchSourceMaps(ReadArg("-d2uSourceMaps"), ReadArg("-d2uSourceMapList"), ReadArg("-d2uSourceMapDir"));
        string[] outputPrefabPaths = SplitList(ReadArg("-d2uOutputPrefabs"));
        string outputDir = ReadArg("-d2uOutputDir");
        bool incremental = ReadBoolArg("-d2uIncremental", false);
        string reportPath = FirstNonEmpty(ReadArg("-d2uBatchReport"), ReadArg("-d2uReport"));
        BatchImportReport report = ImportBatch(sourceMapPaths, outputPrefabPaths, outputDir, incremental, reportPath);
        Debug.Log("Design to Unity batch import finished: " + report.success_count + " succeeded, " + report.failure_count + " failed.");
        if (report.failure_count > 0)
        {
            throw new InvalidOperationException("Design to Unity batch import failed. See batch report for details.");
        }
    }

    public static string Import(string sourceMapAssetPath, string outputPrefabAssetPath)
    {
        return Import(sourceMapAssetPath, outputPrefabAssetPath, false, null);
    }

    public static string Import(string sourceMapAssetPath, string outputPrefabAssetPath, bool incremental, string reportPath = null)
    {
        sourceMapAssetPath = NormalizeAssetPath(sourceMapAssetPath);
        outputPrefabAssetPath = NormalizeAssetPath(outputPrefabAssetPath);
        TextAsset sourceMapAsset = AssetDatabase.LoadAssetAtPath<TextAsset>(sourceMapAssetPath);
        if (sourceMapAsset == null)
        {
            throw new FileNotFoundException("Source map TextAsset not found.", sourceMapAssetPath);
        }

        SourceMap sourceMap = JsonUtility.FromJson<SourceMap>(sourceMapAsset.text);
        if (sourceMap == null || sourceMap.nodes == null || sourceMap.nodes.Length == 0)
        {
            throw new InvalidOperationException("Source map has no nodes.");
        }

        ImportStats stats = new ImportStats();
        stats.Mode = incremental && AssetDatabase.LoadAssetAtPath<GameObject>(outputPrefabAssetPath) != null ? "incremental" : "rebuild";
        string saved = stats.Mode == "incremental"
            ? ImportIncremental(sourceMap, outputPrefabAssetPath, stats)
            : ImportRebuild(sourceMap, outputPrefabAssetPath, stats);
        WriteReport(sourceMap, sourceMapAssetPath, outputPrefabAssetPath, reportPath, stats);
        AssetDatabase.SaveAssets();
        AssetDatabase.Refresh();
        return saved;
    }

    public static BatchImportReport ImportBatch(string[] sourceMapAssetPaths, string[] outputPrefabAssetPaths, string outputDir, bool incremental, string batchReportPath = null)
    {
        if (sourceMapAssetPaths == null || sourceMapAssetPaths.Length == 0)
        {
            throw new ArgumentException("Batch import requires at least one source map.");
        }
        if ((outputPrefabAssetPaths == null || outputPrefabAssetPaths.Length == 0) && string.IsNullOrEmpty(outputDir))
        {
            throw new ArgumentException("Batch import requires -d2uOutputPrefabs or -d2uOutputDir.");
        }
        if (outputPrefabAssetPaths != null && outputPrefabAssetPaths.Length > 0 && outputPrefabAssetPaths.Length != sourceMapAssetPaths.Length)
        {
            throw new ArgumentException("-d2uOutputPrefabs count must match -d2uSourceMaps count.");
        }

        List<BatchImportItem> items = new List<BatchImportItem>();
        int successCount = 0;
        int failureCount = 0;
        for (int i = 0; i < sourceMapAssetPaths.Length; i++)
        {
            string sourceMapPath = NormalizeAssetPath(sourceMapAssetPaths[i]);
            string outputPrefabPath = outputPrefabAssetPaths != null && outputPrefabAssetPaths.Length > 0
                ? NormalizeAssetPath(outputPrefabAssetPaths[i])
                : OutputPrefabPathForSourceMap(sourceMapPath, outputDir);
            string itemReportPath = DefaultReportPath(outputPrefabPath);
            BatchImportItem item = new BatchImportItem();
            item.source_map_asset_path = sourceMapPath;
            item.output_prefab_asset_path = outputPrefabPath;
            item.report_asset_path = itemReportPath;
            try
            {
                Import(sourceMapPath, outputPrefabPath, incremental, itemReportPath);
                item.status = "success";
                successCount++;
            }
            catch (Exception exc)
            {
                item.status = "error";
                item.error = exc.Message;
                failureCount++;
            }
            items.Add(item);
        }

        BatchImportReport report = new BatchImportReport();
        report.status = failureCount > 0 ? "error" : "success";
        report.mode = incremental ? "incremental_or_rebuild" : "rebuild";
        report.source_map_count = sourceMapAssetPaths.Length;
        report.success_count = successCount;
        report.failure_count = failureCount;
        report.items = items.ToArray();
        if (!string.IsNullOrEmpty(batchReportPath))
        {
            WriteBatchReport(report, batchReportPath);
        }
        return report;
    }

    private static string ImportRebuild(SourceMap sourceMap, string outputPrefabAssetPath, ImportStats stats)
    {
        GameObject root = null;
        Dictionary<string, GameObject> byNodeId = new Dictionary<string, GameObject>();
        try
        {
            foreach (NodeEntry node in sourceMap.nodes)
            {
                GameObject go = CreateNode(node, sourceMap);
                stats.CreatedCount++;
                byNodeId[node.node_id] = go;
                if (string.IsNullOrEmpty(node.parent_id) || node.parent_id == "null")
                {
                    root = go;
                }
                else if (byNodeId.TryGetValue(node.parent_id, out GameObject parent))
                {
                    go.transform.SetParent(parent.transform, false);
                }
                else if (root != null)
                {
                    go.transform.SetParent(root.transform, false);
                }
            }

            if (root == null)
            {
                root = byNodeId[sourceMap.nodes[0].node_id];
            }

            BindComponentReferences(sourceMap, byNodeId, stats);
            SaveReusableDefinitions(sourceMap, byNodeId, stats);
            SavePrefabVariants(sourceMap, byNodeId, stats);
            ApplyReusableInstances(sourceMap, byNodeId, stats);
            BindComponentReferences(sourceMap, byNodeId, stats);
            EnsureDirectoryForAsset(outputPrefabAssetPath);
            PrefabUtility.SaveAsPrefabAsset(root, outputPrefabAssetPath);
            return outputPrefabAssetPath;
        }
        finally
        {
            if (root != null)
            {
                UnityEngine.Object.DestroyImmediate(root);
            }
        }
    }

    private static string ImportIncremental(SourceMap sourceMap, string outputPrefabAssetPath, ImportStats stats)
    {
        GameObject root = PrefabUtility.LoadPrefabContents(outputPrefabAssetPath);
        if (root == null)
        {
            stats.Warnings.Add("Existing prefab could not be loaded; falling back to rebuild.");
            return ImportRebuild(sourceMap, outputPrefabAssetPath, stats);
        }

        Dictionary<string, GameObject> byNodeId = new Dictionary<string, GameObject>();
        Dictionary<string, GameObject> byPath = BuildPathLookup(root);
        try
        {
            foreach (NodeEntry node in sourceMap.nodes)
            {
                GameObject go = ResolveExistingNode(node, root, byNodeId, byPath);
                if (go == null)
                {
                    go = new GameObject(SafeName(string.IsNullOrEmpty(node.unity_name_hint) ? node.name : node.unity_name_hint), typeof(RectTransform));
                    stats.CreatedCount++;
                }
                else
                {
                    stats.UpdatedCount++;
                }

                ApplyNodeFields(go, node, sourceMap);
                byNodeId[node.node_id] = go;

                if (string.IsNullOrEmpty(node.parent_id) || node.parent_id == "null")
                {
                    if (go != root)
                    {
                        stats.Warnings.Add("Root node matched a non-root object; existing prefab root was preserved.");
                    }
                    root.name = go.name;
                }
                else if (byNodeId.TryGetValue(node.parent_id, out GameObject parent) && go.transform.parent != parent.transform)
                {
                    go.transform.SetParent(parent.transform, false);
                }
            }

            BindComponentReferences(sourceMap, byNodeId, stats);
            SaveReusableDefinitions(sourceMap, byNodeId, stats);
            SavePrefabVariants(sourceMap, byNodeId, stats);
            ApplyReusableInstances(sourceMap, byNodeId, stats);
            BindComponentReferences(sourceMap, byNodeId, stats);
            EnsureDirectoryForAsset(outputPrefabAssetPath);
            PrefabUtility.SaveAsPrefabAsset(root, outputPrefabAssetPath);
            stats.PreservedExistingCount = CountUnmatchedTransforms(root.transform, byNodeId);
            return outputPrefabAssetPath;
        }
        finally
        {
            PrefabUtility.UnloadPrefabContents(root);
        }
    }

    private static GameObject CreateNode(NodeEntry node, SourceMap sourceMap)
    {
        GameObject go = new GameObject(SafeName(string.IsNullOrEmpty(node.unity_name_hint) ? node.name : node.unity_name_hint), typeof(RectTransform));
        ApplyNodeFields(go, node, sourceMap);
        return go;
    }

    private static void ApplyNodeFields(GameObject go, NodeEntry node, SourceMap sourceMap)
    {
        go.name = SafeName(string.IsNullOrEmpty(node.unity_name_hint) ? node.name : node.unity_name_hint);
        RectTransform rect = go.GetComponent<RectTransform>() ?? go.AddComponent<RectTransform>();
        ApplyRect(rect, node.local_rect, node.unity_anchor_hint);

        bool hasText = node.text != null && !string.IsNullOrEmpty(node.text.content);
        bool hasAsset = node.asset != null && !string.IsNullOrEmpty(node.asset.unity_guid);
        if (hasAsset)
        {
            Image image = EnsureGraphic<Image>(go);
            image.sprite = LoadSprite(node.asset);
            image.type = HasNineSliceBorder(node.asset) ? Image.Type.Sliced : Image.Type.Simple;
            image.preserveAspect = false;
            image.raycastTarget = IsInteractive(node);
        }
        else if (!hasText && node.style != null && !string.IsNullOrEmpty(node.style.fill_color))
        {
            Image image = EnsureGraphic<Image>(go);
            image.color = ParseColor(node.style.fill_color, Color.white);
            image.raycastTarget = IsInteractive(node);
        }

        if (hasText)
        {
            TextMeshProUGUI tmp = EnsureGraphic<TextMeshProUGUI>(go);
            tmp.text = node.text.content;
            tmp.fontSize = node.text.font_size > 0 ? node.text.font_size : 24;
            tmp.color = ParseColor(node.text.color, Color.white);
            tmp.raycastTarget = false;
            tmp.alignment = TextAlignmentFor(node.text);
            TMP_FontAsset fontAsset = LoadTmpFont(node.text);
            if (fontAsset != null)
            {
                tmp.font = fontAsset;
            }
        }

        AddSemanticComponents(go, node);
        AddLayoutElement(go, node);
        AddLayout(go, node);
    }

    private static void AddSemanticComponents(GameObject go, NodeEntry node)
    {
        switch (node.semantic_type)
        {
            case "button_candidate":
                Button button = go.GetComponent<Button>() ?? go.AddComponent<Button>();
                button.targetGraphic = go.GetComponent<Graphic>();
                break;
            case "slider_candidate":
            case "progress_candidate":
                Slider slider = go.GetComponent<Slider>() ?? go.AddComponent<Slider>();
                slider.targetGraphic = go.GetComponent<Graphic>();
                break;
            case "toggle_candidate":
            case "tab_candidate":
            case "radio_candidate":
                Toggle toggle = go.GetComponent<Toggle>() ?? go.AddComponent<Toggle>();
                toggle.targetGraphic = go.GetComponent<Graphic>();
                break;
            case "scroll_area_candidate":
                if (go.GetComponent<ScrollRect>() == null)
                {
                    go.AddComponent<ScrollRect>();
                }
                if (go.GetComponent<RectMask2D>() == null)
                {
                    go.AddComponent<RectMask2D>();
                }
                break;
            case "tab_group_candidate":
            case "radio_group_candidate":
                if (go.GetComponent<ToggleGroup>() == null)
                {
                    go.AddComponent<ToggleGroup>();
                }
                break;
            case "input_candidate":
                TMP_InputField input = go.GetComponent<TMP_InputField>() ?? go.AddComponent<TMP_InputField>();
                input.targetGraphic = go.GetComponent<Graphic>();
                break;
            case "dropdown_candidate":
                TMP_Dropdown dropdown = go.GetComponent<TMP_Dropdown>() ?? go.AddComponent<TMP_Dropdown>();
                dropdown.targetGraphic = go.GetComponent<Graphic>();
                break;
            case "scrollbar_candidate":
                Scrollbar scrollbar = go.GetComponent<Scrollbar>() ?? go.AddComponent<Scrollbar>();
                scrollbar.targetGraphic = go.GetComponent<Graphic>();
                break;
            case "mask_candidate":
            case "scroll_viewport_candidate":
                if (go.GetComponent<RectMask2D>() == null)
                {
                    go.AddComponent<RectMask2D>();
                }
                break;
        }
    }

    private static void AddLayout(GameObject go, NodeEntry node)
    {
        if (node.unity_layout_hint == null || !node.unity_layout_hint.can_add_layout_group)
        {
            return;
        }

        LayoutGroup group = null;
        HorizontalOrVerticalLayoutGroup axisGroup = null;
        if (node.unity_layout_hint.component == "HorizontalLayoutGroup")
        {
            HorizontalLayoutGroup layout = go.GetComponent<HorizontalLayoutGroup>() ?? go.AddComponent<HorizontalLayoutGroup>();
            layout.spacing = node.unity_layout_hint.spacing != null ? node.unity_layout_hint.spacing.x : 0;
            group = layout;
            axisGroup = layout;
        }
        else if (node.unity_layout_hint.component == "VerticalLayoutGroup")
        {
            VerticalLayoutGroup layout = go.GetComponent<VerticalLayoutGroup>() ?? go.AddComponent<VerticalLayoutGroup>();
            layout.spacing = node.unity_layout_hint.spacing != null ? node.unity_layout_hint.spacing.y : 0;
            group = layout;
            axisGroup = layout;
        }

        if (group != null && node.unity_layout_hint.padding != null)
        {
            group.padding = new RectOffset(
                Mathf.RoundToInt(node.unity_layout_hint.padding.left),
                Mathf.RoundToInt(node.unity_layout_hint.padding.right),
                Mathf.RoundToInt(node.unity_layout_hint.padding.top),
                Mathf.RoundToInt(node.unity_layout_hint.padding.bottom)
            );
        }
        if (group != null)
        {
            group.childAlignment = TextAnchorFromLayoutHint(node.unity_layout_hint.child_alignment);
        }
        if (axisGroup != null)
        {
            axisGroup.childControlWidth = node.unity_layout_hint.child_control_width;
            axisGroup.childControlHeight = node.unity_layout_hint.child_control_height;
            axisGroup.childForceExpandWidth = node.unity_layout_hint.child_force_expand_width;
            axisGroup.childForceExpandHeight = node.unity_layout_hint.child_force_expand_height;
        }
    }

    private static void AddLayoutElement(GameObject go, NodeEntry node)
    {
        if (node.unity_layout_element_hint == null || !node.unity_layout_element_hint.can_add_layout_element)
        {
            return;
        }

        LayoutElement element = go.GetComponent<LayoutElement>() ?? go.AddComponent<LayoutElement>();
        LayoutElementHint hint = node.unity_layout_element_hint;
        element.ignoreLayout = hint.ignore_layout;
        element.minWidth = hint.min_width;
        element.minHeight = hint.min_height;
        element.preferredWidth = hint.preferred_width;
        element.preferredHeight = hint.preferred_height;
        element.flexibleWidth = hint.flexible_width;
        element.flexibleHeight = hint.flexible_height;
        element.layoutPriority = hint.layout_priority > 0 ? hint.layout_priority : 1;
    }

    private static TextAnchor TextAnchorFromLayoutHint(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return TextAnchor.UpperLeft;
        }
        try
        {
            return (TextAnchor)Enum.Parse(typeof(TextAnchor), value, true);
        }
        catch
        {
            return TextAnchor.UpperLeft;
        }
    }

    private static void BindComponentReferences(SourceMap sourceMap, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        if (sourceMap.nodes == null)
        {
            return;
        }

        foreach (NodeEntry node in sourceMap.nodes)
        {
            if (string.IsNullOrEmpty(node.node_id) || !byNodeId.TryGetValue(node.node_id, out GameObject go) || go == null)
            {
                continue;
            }

            BindButton(go, node, byNodeId, stats);
            BindSlider(go, node, byNodeId, stats);
            BindToggle(go, node, byNodeId, stats);
            BindInputField(go, node, byNodeId, stats);
            BindDropdown(go, node, byNodeId, stats);
            BindScrollRect(go, node, byNodeId, stats);
            BindScrollbar(go, node, byNodeId, stats);
        }
    }

    private static void BindButton(GameObject go, NodeEntry node, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        Button button = go.GetComponent<Button>();
        if (button == null)
        {
            return;
        }

        Graphic target = GraphicForNode(byNodeId, FirstNonEmpty(node.unity_button_hint != null ? node.unity_button_hint.target_graphic_node_id : null, node.unity_button_hint != null ? node.unity_button_hint.hit_node_id : null))
            ?? go.GetComponent<Graphic>()
            ?? FirstChildGraphic(go);
        button.targetGraphic = target;
        if (target == null)
        {
            stats.Warnings.Add("button_target_graphic_unbound:" + node.node_id);
        }
    }

    private static void BindSlider(GameObject go, NodeEntry node, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        Slider slider = go.GetComponent<Slider>();
        if (slider == null)
        {
            return;
        }

        SliderHint hint = node.unity_slider_hint;
        if (hint != null)
        {
            slider.fillRect = RectForNode(byNodeId, hint.fill_node_id);
            slider.handleRect = RectForNode(byNodeId, hint.handle_node_id);
            slider.value = Mathf.Clamp01(hint.value);
            slider.interactable = hint.interactable;
            slider.direction = string.Equals(hint.direction, "vertical", StringComparison.OrdinalIgnoreCase)
                ? Slider.Direction.BottomToTop
                : Slider.Direction.LeftToRight;
        }
        if (slider.fillRect == null)
        {
            stats.Warnings.Add("slider_fill_unbound:" + node.node_id);
        }
    }

    private static void BindToggle(GameObject go, NodeEntry node, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        Toggle toggle = go.GetComponent<Toggle>();
        if (toggle == null)
        {
            return;
        }

        ToggleHint hint = FirstNonNull(node.unity_toggle_hint, node.unity_tab_hint, node.unity_radio_hint);
        if (hint != null)
        {
            toggle.graphic = GraphicForNode(byNodeId, hint.graphic_node_id) ?? toggle.graphic;
            toggle.isOn = hint.value;
            ToggleGroup group = ToggleGroupForNode(byNodeId, hint.group_node_id);
            if (group != null)
            {
                toggle.group = group;
            }
        }
        toggle.targetGraphic = toggle.targetGraphic ?? go.GetComponent<Graphic>() ?? FirstChildGraphic(go);
        if (toggle.targetGraphic == null)
        {
            stats.Warnings.Add("toggle_target_graphic_unbound:" + node.node_id);
        }
    }

    private static void BindInputField(GameObject go, NodeEntry node, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        TMP_InputField input = go.GetComponent<TMP_InputField>();
        if (input == null)
        {
            return;
        }

        InputHint hint = node.unity_input_hint;
        if (hint != null)
        {
            input.textComponent = TmpTextForNode(byNodeId, hint.text_component_node_id);
            input.placeholder = GraphicForNode(byNodeId, hint.placeholder_node_id);
            input.text = hint.text ?? input.text;
            input.lineType = TMP_InputField.LineType.SingleLine;
        }
        input.targetGraphic = input.targetGraphic ?? go.GetComponent<Graphic>() ?? FirstChildGraphic(go);
        if (input.textComponent == null)
        {
            stats.Warnings.Add("input_text_component_unbound:" + node.node_id);
        }
    }

    private static void BindDropdown(GameObject go, NodeEntry node, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        TMP_Dropdown dropdown = go.GetComponent<TMP_Dropdown>();
        if (dropdown == null)
        {
            return;
        }

        DropdownHint hint = node.unity_dropdown_hint;
        if (hint != null)
        {
            dropdown.template = RectForNode(byNodeId, hint.template_node_id);
            dropdown.captionText = TmpTextForNode(byNodeId, hint.caption_text_node_id);
            dropdown.itemText = TmpTextForNode(byNodeId, hint.item_text_node_id);
            dropdown.value = Mathf.Max(0, hint.value);
            if (hint.options != null && hint.options.Length > 0)
            {
                dropdown.options.Clear();
                foreach (string option in hint.options)
                {
                    dropdown.options.Add(new TMP_Dropdown.OptionData(option));
                }
            }
        }
        dropdown.targetGraphic = dropdown.targetGraphic ?? go.GetComponent<Graphic>() ?? FirstChildGraphic(go);
        if (dropdown.captionText == null)
        {
            stats.Warnings.Add("dropdown_caption_unbound:" + node.node_id);
        }
    }

    private static void BindScrollRect(GameObject go, NodeEntry node, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        ScrollRect scrollRect = go.GetComponent<ScrollRect>();
        if (scrollRect == null)
        {
            return;
        }

        ScrollHint hint = node.unity_scroll_hint;
        if (hint != null)
        {
            scrollRect.viewport = RectForNode(byNodeId, hint.viewport_node_id);
            scrollRect.content = RectForNode(byNodeId, hint.content_node_id);
            scrollRect.horizontalScrollbar = ScrollbarForNode(byNodeId, hint.horizontal_scrollbar_node_id);
            scrollRect.verticalScrollbar = ScrollbarForNode(byNodeId, hint.vertical_scrollbar_node_id);
            scrollRect.horizontal = string.Equals(hint.direction, "horizontal", StringComparison.OrdinalIgnoreCase) || string.Equals(hint.direction, "both", StringComparison.OrdinalIgnoreCase);
            scrollRect.vertical = !string.Equals(hint.direction, "horizontal", StringComparison.OrdinalIgnoreCase);
        }
        if (scrollRect.content == null)
        {
            stats.Warnings.Add("scroll_content_unbound:" + node.node_id);
        }
    }

    private static void BindScrollbar(GameObject go, NodeEntry node, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        Scrollbar scrollbar = go.GetComponent<Scrollbar>();
        if (scrollbar == null)
        {
            return;
        }

        ScrollbarHint hint = node.unity_scrollbar_hint;
        if (hint != null)
        {
            scrollbar.handleRect = RectForNode(byNodeId, hint.handle_node_id);
            scrollbar.value = Mathf.Clamp01(hint.value);
            scrollbar.size = hint.size > 0 ? Mathf.Clamp01(hint.size) : scrollbar.size;
            scrollbar.direction = string.Equals(hint.direction, "horizontal", StringComparison.OrdinalIgnoreCase)
                ? Scrollbar.Direction.LeftToRight
                : Scrollbar.Direction.BottomToTop;
        }
        scrollbar.targetGraphic = scrollbar.targetGraphic ?? go.GetComponent<Graphic>() ?? FirstChildGraphic(go);
        if (scrollbar.handleRect == null)
        {
            stats.Warnings.Add("scrollbar_handle_unbound:" + node.node_id);
        }
    }

    private static void SaveReusableDefinitions(SourceMap sourceMap, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        if (sourceMap.reusable_prefabs == null)
        {
            return;
        }

        foreach (ReusablePrefabEntry entry in sourceMap.reusable_prefabs)
        {
            if (string.IsNullOrEmpty(entry.definition_node_id) || string.IsNullOrEmpty(entry.suggested_prefab_asset_path))
            {
                continue;
            }
            if (!byNodeId.TryGetValue(entry.definition_node_id, out GameObject definition))
            {
                continue;
            }
            EnsureDirectoryForAsset(entry.suggested_prefab_asset_path);
            PrefabUtility.SaveAsPrefabAsset(definition, NormalizeAssetPath(entry.suggested_prefab_asset_path));
            stats.ReusableDefinitionCount++;
        }
    }

    private static void SavePrefabVariants(SourceMap sourceMap, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        if (sourceMap.prefab_variant_groups == null || sourceMap.nodes == null)
        {
            return;
        }

        Dictionary<string, NodeEntry> nodesById = BuildNodeLookup(sourceMap);
        Dictionary<string, List<NodeEntry>> childrenByParent = BuildChildrenLookup(sourceMap);
        foreach (PrefabVariantGroupEntry group in sourceMap.prefab_variant_groups)
        {
            if (group == null || group.variants == null || string.IsNullOrEmpty(group.base_prefab_asset_path) || string.IsNullOrEmpty(group.definition_node_id))
            {
                continue;
            }

            GameObject prefabAsset = AssetDatabase.LoadAssetAtPath<GameObject>(NormalizeAssetPath(group.base_prefab_asset_path));
            if (prefabAsset == null)
            {
                stats.Warnings.Add("prefab_variant_base_missing:" + group.base_prefab_asset_path);
                continue;
            }
            if (!nodesById.TryGetValue(group.definition_node_id, out NodeEntry definitionRootNode) || !byNodeId.TryGetValue(group.definition_node_id, out GameObject definitionRootObject))
            {
                stats.Warnings.Add("prefab_variant_definition_missing:" + group.definition_node_id);
                continue;
            }

            bool countedGroup = false;
            foreach (PrefabVariantEntry variant in group.variants)
            {
                if (variant == null || string.IsNullOrEmpty(variant.node_id) || string.IsNullOrEmpty(variant.suggested_prefab_asset_path))
                {
                    continue;
                }
                if (!nodesById.TryGetValue(variant.node_id, out NodeEntry variantRootNode) || !byNodeId.TryGetValue(variant.node_id, out GameObject originalRoot))
                {
                    stats.Warnings.Add("prefab_variant_node_missing:" + variant.node_id);
                    continue;
                }

                GameObject instanceRoot = PrefabUtility.InstantiatePrefab(prefabAsset) as GameObject;
                if (instanceRoot == null)
                {
                    stats.Warnings.Add("prefab_variant_create_failed:" + variant.node_id);
                    continue;
                }

                try
                {
                    Dictionary<string, GameObject> tempNodeMap = new Dictionary<string, GameObject>(byNodeId);
                    instanceRoot.name = string.IsNullOrEmpty(variant.suggested_prefab_name) ? originalRoot.name : variant.suggested_prefab_name;
                    ApplyReusableInstanceOverrides(definitionRootNode, definitionRootObject, variantRootNode, originalRoot, instanceRoot, sourceMap, childrenByParent, tempNodeMap, stats);
                    EnsureDirectoryForAsset(variant.suggested_prefab_asset_path);
                    PrefabUtility.SaveAsPrefabAsset(instanceRoot, NormalizeAssetPath(variant.suggested_prefab_asset_path));
                    stats.PrefabVariantAssetCount++;
                    countedGroup = true;
                }
                finally
                {
                    UnityEngine.Object.DestroyImmediate(instanceRoot);
                }
            }

            if (countedGroup)
            {
                stats.PrefabVariantGroupCount++;
            }
        }
    }

    private static void ApplyReusableInstances(SourceMap sourceMap, Dictionary<string, GameObject> byNodeId, ImportStats stats)
    {
        if (sourceMap.reusable_prefabs == null || sourceMap.nodes == null)
        {
            return;
        }

        Dictionary<string, NodeEntry> nodesById = BuildNodeLookup(sourceMap);
        Dictionary<string, List<NodeEntry>> childrenByParent = BuildChildrenLookup(sourceMap);

        foreach (ReusablePrefabEntry entry in sourceMap.reusable_prefabs)
        {
            if (entry.instance_node_ids == null || string.IsNullOrEmpty(entry.suggested_prefab_asset_path))
            {
                continue;
            }

            nodesById.TryGetValue(entry.definition_node_id, out NodeEntry definitionRootNode);
            byNodeId.TryGetValue(entry.definition_node_id, out GameObject definitionRootObject);

            string prefabPath = NormalizeAssetPath(entry.suggested_prefab_asset_path);
            GameObject prefabAsset = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            if (prefabAsset == null)
            {
                stats.Warnings.Add("reusable_prefab_asset_missing:" + prefabPath);
                continue;
            }

            foreach (string nodeId in entry.instance_node_ids)
            {
                if (string.IsNullOrEmpty(nodeId) || nodeId == entry.definition_node_id)
                {
                    continue;
                }
                if (!nodesById.TryGetValue(nodeId, out NodeEntry rootNode) || !byNodeId.TryGetValue(nodeId, out GameObject originalRoot))
                {
                    stats.Warnings.Add("reusable_instance_missing:" + nodeId);
                    continue;
                }
                if (PrefabUtility.IsPartOfPrefabInstance(originalRoot))
                {
                    stats.ReusedPrefabInstanceCount++;
                    continue;
                }
                if (stats.Mode == "incremental" && HasProtectedUserState(rootNode, childrenByParent, byNodeId, stats))
                {
                    stats.ProtectedReusableInstanceCount++;
                    stats.Warnings.Add("reusable_instance_preserved_user_state:" + nodeId);
                    continue;
                }

                Transform parent = originalRoot.transform.parent;
                int siblingIndex = originalRoot.transform.GetSiblingIndex();
                GameObject instanceRoot = PrefabUtility.InstantiatePrefab(prefabAsset) as GameObject;
                if (instanceRoot == null)
                {
                    stats.Warnings.Add("reusable_instance_create_failed:" + nodeId);
                    continue;
                }

                instanceRoot.name = originalRoot.name;
                if (parent != null)
                {
                    instanceRoot.transform.SetParent(parent, false);
                }
                instanceRoot.transform.SetSiblingIndex(siblingIndex);

                Dictionary<Transform, string> sourceTransformToNodeId = BuildSourceTransformNodeMap(rootNode, childrenByParent, byNodeId);
                ApplyReusableInstanceOverrides(definitionRootNode, definitionRootObject, rootNode, originalRoot, instanceRoot, sourceMap, childrenByParent, byNodeId, stats);
                MoveUserOwnedChildren(originalRoot, instanceRoot, sourceTransformToNodeId, byNodeId, stats);
                UnityEngine.Object.DestroyImmediate(originalRoot);
                stats.ReusedPrefabInstanceCount++;
            }
        }
    }

    private static bool HasProtectedUserState(
        NodeEntry rootNode,
        Dictionary<string, List<NodeEntry>> childrenByParent,
        Dictionary<string, GameObject> byNodeId,
        ImportStats stats)
    {
        bool hasProtectedState = false;
        foreach (KeyValuePair<Transform, string> item in BuildSourceTransformNodeMap(rootNode, childrenByParent, byNodeId))
        {
            Transform transform = item.Key;
            if (transform == null)
            {
                continue;
            }
            foreach (Component component in transform.GetComponents<Component>())
            {
                if (component == null)
                {
                    continue;
                }
                if (!IsDesignOwnedComponent(component))
                {
                    stats.ProtectedUserComponentCount++;
                    stats.ProtectedUserStatePaths.Add(PathFor(transform) + ":" + component.GetType().Name);
                    hasProtectedState = true;
                }
                int eventCount = PersistentEventCount(component);
                if (eventCount > 0)
                {
                    stats.ProtectedEventBindingCount += eventCount;
                    stats.ProtectedUserStatePaths.Add(PathFor(transform) + ":" + component.GetType().Name + ".events");
                    hasProtectedState = true;
                }
            }
        }
        return hasProtectedState;
    }

    private static void MoveUserOwnedChildren(
        GameObject originalRoot,
        GameObject instanceRoot,
        Dictionary<Transform, string> sourceTransformToNodeId,
        Dictionary<string, GameObject> byNodeId,
        ImportStats stats)
    {
        if (originalRoot == null || instanceRoot == null || sourceTransformToNodeId == null)
        {
            return;
        }

        HashSet<Transform> sourceTransforms = new HashSet<Transform>(sourceTransformToNodeId.Keys);
        List<Transform> userChildren = new List<Transform>();
        foreach (Transform child in originalRoot.GetComponentsInChildren<Transform>(true))
        {
            if (child == originalRoot.transform || sourceTransforms.Contains(child))
            {
                continue;
            }
            Transform oldParent = child.parent;
            if (oldParent == originalRoot.transform || sourceTransforms.Contains(oldParent))
            {
                userChildren.Add(child);
            }
        }

        foreach (Transform child in userChildren)
        {
            if (child == null)
            {
                continue;
            }
            string oldPath = RelativeTransformPath(originalRoot.transform, child);
            Transform oldParent = child.parent;
            Transform newParent = instanceRoot.transform;
            if (oldParent != null && sourceTransformToNodeId.TryGetValue(oldParent, out string parentNodeId) && byNodeId.TryGetValue(parentNodeId, out GameObject mappedParent) && mappedParent != null)
            {
                newParent = mappedParent.transform;
            }
            child.SetParent(newParent, false);
            stats.PreservedUserChildCount++;
            stats.PreservedUserChildPaths.Add(string.IsNullOrEmpty(oldPath) ? child.name : oldPath);
        }
    }

    private static Dictionary<Transform, string> BuildSourceTransformNodeMap(
        NodeEntry rootNode,
        Dictionary<string, List<NodeEntry>> childrenByParent,
        Dictionary<string, GameObject> byNodeId)
    {
        Dictionary<Transform, string> result = new Dictionary<Transform, string>();
        foreach (NodeEntry node in EnumerateSubtree(rootNode, childrenByParent))
        {
            if (node == null || string.IsNullOrEmpty(node.node_id) || !byNodeId.TryGetValue(node.node_id, out GameObject go) || go == null)
            {
                continue;
            }
            result[go.transform] = node.node_id;
        }
        return result;
    }

    private static bool IsDesignOwnedComponent(Component component)
    {
        return component is Transform
            || component is RectTransform
            || component is CanvasRenderer
            || component is Graphic
            || component is Selectable
            || component is ToggleGroup
            || component is TMP_Text
            || component is TMP_InputField
            || component is TMP_Dropdown
            || component is ScrollRect
            || component is RectMask2D
            || component is LayoutGroup
            || component is LayoutElement
            || component is ContentSizeFitter
            || component is CanvasGroup
            || component is Shadow;
    }

    private static int PersistentEventCount(Component component)
    {
        if (component is Button button)
        {
            return button.onClick.GetPersistentEventCount();
        }
        if (component is Toggle toggle)
        {
            return toggle.onValueChanged.GetPersistentEventCount();
        }
        if (component is Slider slider)
        {
            return slider.onValueChanged.GetPersistentEventCount();
        }
        if (component is Scrollbar scrollbar)
        {
            return scrollbar.onValueChanged.GetPersistentEventCount();
        }
        if (component is ScrollRect scrollRect)
        {
            return scrollRect.onValueChanged.GetPersistentEventCount();
        }
        if (component is TMP_InputField input)
        {
            return input.onValueChanged.GetPersistentEventCount()
                + input.onEndEdit.GetPersistentEventCount()
                + input.onSubmit.GetPersistentEventCount();
        }
        if (component is TMP_Dropdown dropdown)
        {
            return dropdown.onValueChanged.GetPersistentEventCount();
        }
        return 0;
    }

    private static void ApplyReusableInstanceOverrides(
        NodeEntry definitionRootNode,
        GameObject definitionRootObject,
        NodeEntry rootNode,
        GameObject originalRoot,
        GameObject instanceRoot,
        SourceMap sourceMap,
        Dictionary<string, List<NodeEntry>> childrenByParent,
        Dictionary<string, GameObject> byNodeId,
        ImportStats stats)
    {
        Dictionary<string, GameObject> instanceByRelativePath = BuildRelativePathLookup(instanceRoot.transform);
        Dictionary<string, GameObject> instanceByReusablePath = BuildReusableInstanceTargetLookup(
            definitionRootNode,
            definitionRootObject,
            instanceRoot,
            childrenByParent,
            byNodeId);
        Dictionary<string, string> reusablePathByNodeId = BuildReusablePathByNodeId(rootNode, childrenByParent);
        foreach (NodeEntry node in EnumerateSubtree(rootNode, childrenByParent))
        {
            string relativePath = "";
            if (node != rootNode && byNodeId.TryGetValue(node.node_id, out GameObject originalNode))
            {
                relativePath = RelativeTransformPath(originalRoot.transform, originalNode.transform);
            }
            if (string.IsNullOrEmpty(relativePath) && node != rootNode)
            {
                relativePath = RelativeUnityPath(rootNode.unity_path, node.unity_path);
            }

            if (!instanceByRelativePath.TryGetValue(relativePath, out GameObject target))
            {
                string reusablePath = "";
                if (reusablePathByNodeId.TryGetValue(node.node_id, out reusablePath))
                {
                    instanceByReusablePath.TryGetValue(reusablePath, out target);
                }
                if (target == null)
                {
                    stats.Warnings.Add("reusable_instance_child_unmatched:" + node.node_id);
                    byNodeId.Remove(node.node_id);
                    continue;
                }
            }

            ApplyNodeFields(target, node, sourceMap);
            byNodeId[node.node_id] = target;
        }
    }

    private static Dictionary<string, GameObject> BuildReusableInstanceTargetLookup(
        NodeEntry definitionRootNode,
        GameObject definitionRootObject,
        GameObject instanceRoot,
        Dictionary<string, List<NodeEntry>> childrenByParent,
        Dictionary<string, GameObject> byNodeId)
    {
        Dictionary<string, GameObject> result = new Dictionary<string, GameObject>();
        if (definitionRootNode == null || definitionRootObject == null || instanceRoot == null)
        {
            return result;
        }

        Dictionary<string, GameObject> instanceByRelativePath = BuildRelativePathLookup(instanceRoot.transform);
        AddReusableInstanceTarget(result, definitionRootNode, definitionRootNode, "", definitionRootObject, instanceByRelativePath, childrenByParent, byNodeId);
        return result;
    }

    private static void AddReusableInstanceTarget(
        Dictionary<string, GameObject> result,
        NodeEntry definitionRootNode,
        NodeEntry node,
        string reusablePath,
        GameObject definitionRootObject,
        Dictionary<string, GameObject> instanceByRelativePath,
        Dictionary<string, List<NodeEntry>> childrenByParent,
        Dictionary<string, GameObject> byNodeId)
    {
        string relativePath = "";
        if (node != definitionRootNode && byNodeId.TryGetValue(node.node_id, out GameObject definitionNode) && definitionNode != null)
        {
            relativePath = RelativeTransformPath(definitionRootObject.transform, definitionNode.transform);
        }
        if (instanceByRelativePath.TryGetValue(relativePath, out GameObject target))
        {
            result[reusablePath] = target;
        }

        if (string.IsNullOrEmpty(node.node_id) || !childrenByParent.TryGetValue(node.node_id, out List<NodeEntry> children))
        {
            return;
        }

        Dictionary<string, int> segmentCounts = new Dictionary<string, int>();
        foreach (NodeEntry child in children)
        {
            string segment = ReusablePathSegment(child);
            segmentCounts.TryGetValue(segment, out int index);
            segmentCounts[segment] = index + 1;
            string childSegment = segment + "#" + index;
            string childPath = string.IsNullOrEmpty(reusablePath) ? childSegment : reusablePath + "/" + childSegment;
            AddReusableInstanceTarget(result, definitionRootNode, child, childPath, definitionRootObject, instanceByRelativePath, childrenByParent, byNodeId);
        }
    }

    private static Dictionary<string, string> BuildReusablePathByNodeId(NodeEntry rootNode, Dictionary<string, List<NodeEntry>> childrenByParent)
    {
        Dictionary<string, string> result = new Dictionary<string, string>();
        if (rootNode == null)
        {
            return result;
        }
        AddReusablePathByNodeId(result, rootNode, "", childrenByParent);
        return result;
    }

    private static void AddReusablePathByNodeId(
        Dictionary<string, string> result,
        NodeEntry node,
        string reusablePath,
        Dictionary<string, List<NodeEntry>> childrenByParent)
    {
        if (!string.IsNullOrEmpty(node.node_id))
        {
            result[node.node_id] = reusablePath;
        }
        if (string.IsNullOrEmpty(node.node_id) || !childrenByParent.TryGetValue(node.node_id, out List<NodeEntry> children))
        {
            return;
        }

        Dictionary<string, int> segmentCounts = new Dictionary<string, int>();
        foreach (NodeEntry child in children)
        {
            string segment = ReusablePathSegment(child);
            segmentCounts.TryGetValue(segment, out int index);
            segmentCounts[segment] = index + 1;
            string childSegment = segment + "#" + index;
            string childPath = string.IsNullOrEmpty(reusablePath) ? childSegment : reusablePath + "/" + childSegment;
            AddReusablePathByNodeId(result, child, childPath, childrenByParent);
        }
    }

    private static string ReusablePathSegment(NodeEntry node)
    {
        string value = node == null ? "" : node.name;
        if (string.IsNullOrEmpty(value) && node != null)
        {
            value = node.unity_name_hint;
        }
        if (string.IsNullOrEmpty(value) && node != null)
        {
            value = node.node_id;
        }
        value = SafeName(value);
        return string.IsNullOrEmpty(value) ? "node" : value;
    }

    private static Dictionary<string, NodeEntry> BuildNodeLookup(SourceMap sourceMap)
    {
        Dictionary<string, NodeEntry> result = new Dictionary<string, NodeEntry>();
        if (sourceMap.nodes == null)
        {
            return result;
        }
        foreach (NodeEntry node in sourceMap.nodes)
        {
            if (!string.IsNullOrEmpty(node.node_id))
            {
                result[node.node_id] = node;
            }
        }
        return result;
    }

    private static Dictionary<string, List<NodeEntry>> BuildChildrenLookup(SourceMap sourceMap)
    {
        Dictionary<string, List<NodeEntry>> result = new Dictionary<string, List<NodeEntry>>();
        if (sourceMap.nodes == null)
        {
            return result;
        }
        foreach (NodeEntry node in sourceMap.nodes)
        {
            if (string.IsNullOrEmpty(node.parent_id) || node.parent_id == "null")
            {
                continue;
            }
            if (!result.TryGetValue(node.parent_id, out List<NodeEntry> children))
            {
                children = new List<NodeEntry>();
                result[node.parent_id] = children;
            }
            children.Add(node);
        }
        return result;
    }

    private static IEnumerable<NodeEntry> EnumerateSubtree(NodeEntry root, Dictionary<string, List<NodeEntry>> childrenByParent)
    {
        yield return root;
        if (root == null || string.IsNullOrEmpty(root.node_id) || !childrenByParent.TryGetValue(root.node_id, out List<NodeEntry> children))
        {
            yield break;
        }
        foreach (NodeEntry child in children)
        {
            foreach (NodeEntry descendant in EnumerateSubtree(child, childrenByParent))
            {
                yield return descendant;
            }
        }
    }

    private static Dictionary<string, GameObject> BuildRelativePathLookup(Transform root)
    {
        Dictionary<string, GameObject> result = new Dictionary<string, GameObject>();
        AddRelativePath(result, root, "");
        return result;
    }

    private static void AddRelativePath(Dictionary<string, GameObject> result, Transform transform, string path)
    {
        result[path] = transform.gameObject;
        foreach (Transform child in transform)
        {
            string childPath = string.IsNullOrEmpty(path) ? PathSegmentFor(child) : path + "/" + PathSegmentFor(child);
            AddRelativePath(result, child, childPath);
        }
    }

    private static string RelativeTransformPath(Transform root, Transform target)
    {
        if (root == null || target == null || root == target)
        {
            return "";
        }

        List<string> segments = new List<string>();
        Transform current = target;
        while (current != null && current != root)
        {
            segments.Add(PathSegmentFor(current));
            current = current.parent;
        }
        if (current != root)
        {
            return "";
        }
        segments.Reverse();
        return string.Join("/", segments.ToArray());
    }

    private static string RelativeUnityPath(string rootPath, string childPath)
    {
        if (string.IsNullOrEmpty(rootPath) || string.IsNullOrEmpty(childPath) || rootPath == childPath)
        {
            return "";
        }
        string prefix = rootPath + "/";
        return childPath.StartsWith(prefix, StringComparison.Ordinal) ? childPath.Substring(prefix.Length) : "";
    }

    private static Dictionary<string, GameObject> BuildPathLookup(GameObject root)
    {
        Dictionary<string, GameObject> result = new Dictionary<string, GameObject>();
        foreach (Transform transform in root.GetComponentsInChildren<Transform>(true))
        {
            result[PathFor(transform)] = transform.gameObject;
        }
        return result;
    }

    private static GameObject ResolveExistingNode(NodeEntry node, GameObject root, Dictionary<string, GameObject> byNodeId, Dictionary<string, GameObject> byPath)
    {
        if (!string.IsNullOrEmpty(node.unity_path) && byPath.TryGetValue(node.unity_path, out GameObject byUnityPath))
        {
            return byUnityPath;
        }

        if (string.IsNullOrEmpty(node.parent_id) || node.parent_id == "null")
        {
            return root;
        }

        if (byNodeId.TryGetValue(node.parent_id, out GameObject parent))
        {
            string childName = SafeName(string.IsNullOrEmpty(node.unity_name_hint) ? node.name : node.unity_name_hint);
            Transform existingChild = FindChildBySegment(parent.transform, LastPathSegment(node.unity_path), childName);
            if (existingChild != null)
            {
                return existingChild.gameObject;
            }
        }

        return null;
    }

    private static Transform FindChildBySegment(Transform parent, string pathSegment, string fallbackName)
    {
        string targetName = fallbackName;
        int targetOccurrence = 1;
        if (!string.IsNullOrEmpty(pathSegment) && pathSegment.EndsWith("]", StringComparison.Ordinal))
        {
            int open = pathSegment.LastIndexOf("[", StringComparison.Ordinal);
            if (open > 0 && int.TryParse(pathSegment.Substring(open + 1, pathSegment.Length - open - 2), out int parsed))
            {
                targetName = pathSegment.Substring(0, open);
                targetOccurrence = Mathf.Max(1, parsed);
            }
        }

        int occurrence = 0;
        for (int i = 0; i < parent.childCount; i++)
        {
            Transform child = parent.GetChild(i);
            if (child.name != targetName)
            {
                continue;
            }
            occurrence++;
            if (occurrence == targetOccurrence)
            {
                return child;
            }
        }
        return parent.Find(fallbackName);
    }

    private static string LastPathSegment(string path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return null;
        }
        int index = path.LastIndexOf("/", StringComparison.Ordinal);
        return index >= 0 ? path.Substring(index + 1) : path;
    }

    private static string PathFor(Transform transform)
    {
        Stack<string> names = new Stack<string>();
        Transform current = transform;
        while (current != null)
        {
            names.Push(PathSegmentFor(current));
            current = current.parent;
        }
        return string.Join("/", names.ToArray());
    }

    private static string PathSegmentFor(Transform transform)
    {
        if (transform.parent == null)
        {
            return transform.name;
        }

        int total = 0;
        int occurrence = 0;
        for (int i = 0; i < transform.parent.childCount; i++)
        {
            Transform sibling = transform.parent.GetChild(i);
            if (sibling.name != transform.name)
            {
                continue;
            }
            total++;
            if (sibling == transform)
            {
                occurrence = total;
            }
        }
        return total > 1 ? transform.name + "[" + occurrence + "]" : transform.name;
    }

    private static int CountTransforms(Transform root)
    {
        int count = 0;
        foreach (Transform ignored in root.GetComponentsInChildren<Transform>(true))
        {
            count++;
        }
        return count;
    }

    private static int CountUnmatchedTransforms(Transform root, Dictionary<string, GameObject> byNodeId)
    {
        HashSet<GameObject> sourceObjects = new HashSet<GameObject>();
        foreach (GameObject go in byNodeId.Values)
        {
            if (go != null)
            {
                sourceObjects.Add(go);
            }
        }

        int count = 0;
        foreach (Transform transform in root.GetComponentsInChildren<Transform>(true))
        {
            if (!sourceObjects.Contains(transform.gameObject))
            {
                count++;
            }
        }
        return count;
    }

    private static T EnsureGraphic<T>(GameObject go) where T : Graphic
    {
        CanvasRenderer renderer = go.GetComponent<CanvasRenderer>();
        if (renderer == null)
        {
            go.AddComponent<CanvasRenderer>();
        }
        T graphic = go.GetComponent<T>();
        return graphic != null ? graphic : go.AddComponent<T>();
    }

    private static Sprite LoadSprite(AssetRef asset)
    {
        if (asset == null)
        {
            return null;
        }
        string guid = asset != null ? asset.unity_guid : null;
        string path = string.IsNullOrEmpty(guid) ? null : AssetDatabase.GUIDToAssetPath(guid);
        if (string.IsNullOrEmpty(path))
        {
            path = FirstNonEmpty(asset.deduped_unity_asset_path, asset.suggested_unity_path);
        }
        return string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<Sprite>(NormalizeAssetPath(path));
    }

    private static TMP_FontAsset LoadTmpFont(TextData text)
    {
        if (text == null)
        {
            return null;
        }
        string guid = FirstNonEmpty(text.tmp_font_asset_guid, text.unity_font_asset_guid);
        string path = string.IsNullOrEmpty(guid) ? null : AssetDatabase.GUIDToAssetPath(guid);
        if (string.IsNullOrEmpty(path))
        {
            path = FirstNonEmpty(text.tmp_font_asset_path, text.unity_font_asset_path);
        }
        return string.IsNullOrEmpty(path) ? null : AssetDatabase.LoadAssetAtPath<TMP_FontAsset>(NormalizeAssetPath(path));
    }

    private static bool HasNineSliceBorder(AssetRef asset)
    {
        if (asset == null || asset.nine_slice_hint == null)
        {
            return false;
        }
        BorderData border = asset.nine_slice_hint.border;
        if (border == null)
        {
            return asset.nine_slice_hint.candidate;
        }
        return border.left > 0 || border.right > 0 || border.top > 0 || border.bottom > 0;
    }

    private static TextAlignmentOptions TextAlignmentFor(TextData text)
    {
        string horizontal = (text != null ? text.align : null) ?? "";
        string vertical = (text != null ? text.vertical_align : null) ?? "";
        bool top = vertical.Equals("top", StringComparison.OrdinalIgnoreCase);
        bool bottom = vertical.Equals("bottom", StringComparison.OrdinalIgnoreCase);
        bool right = horizontal.Equals("right", StringComparison.OrdinalIgnoreCase);
        bool left = horizontal.Equals("left", StringComparison.OrdinalIgnoreCase);
        if (top && right) return TextAlignmentOptions.TopRight;
        if (top && left) return TextAlignmentOptions.TopLeft;
        if (top) return TextAlignmentOptions.Top;
        if (bottom && right) return TextAlignmentOptions.BottomRight;
        if (bottom && left) return TextAlignmentOptions.BottomLeft;
        if (bottom) return TextAlignmentOptions.Bottom;
        if (right) return TextAlignmentOptions.Right;
        if (left) return TextAlignmentOptions.Left;
        return TextAlignmentOptions.Center;
    }

    private static Graphic GraphicForNode(Dictionary<string, GameObject> byNodeId, string nodeId)
    {
        if (string.IsNullOrEmpty(nodeId) || !byNodeId.TryGetValue(nodeId, out GameObject go) || go == null)
        {
            return null;
        }
        return go.GetComponent<Graphic>() ?? FirstChildGraphic(go);
    }

    private static Graphic FirstChildGraphic(GameObject go)
    {
        return go != null ? go.GetComponentInChildren<Graphic>(true) : null;
    }

    private static RectTransform RectForNode(Dictionary<string, GameObject> byNodeId, string nodeId)
    {
        if (string.IsNullOrEmpty(nodeId) || !byNodeId.TryGetValue(nodeId, out GameObject go) || go == null)
        {
            return null;
        }
        return go.GetComponent<RectTransform>();
    }

    private static ToggleGroup ToggleGroupForNode(Dictionary<string, GameObject> byNodeId, string nodeId)
    {
        if (string.IsNullOrEmpty(nodeId) || !byNodeId.TryGetValue(nodeId, out GameObject go) || go == null)
        {
            return null;
        }
        return go.GetComponent<ToggleGroup>();
    }

    private static TMP_Text TmpTextForNode(Dictionary<string, GameObject> byNodeId, string nodeId)
    {
        if (string.IsNullOrEmpty(nodeId) || !byNodeId.TryGetValue(nodeId, out GameObject go) || go == null)
        {
            return null;
        }
        return go.GetComponent<TMP_Text>() ?? go.GetComponentInChildren<TMP_Text>(true);
    }

    private static Scrollbar ScrollbarForNode(Dictionary<string, GameObject> byNodeId, string nodeId)
    {
        if (string.IsNullOrEmpty(nodeId) || !byNodeId.TryGetValue(nodeId, out GameObject go) || go == null)
        {
            return null;
        }
        return go.GetComponent<Scrollbar>();
    }

    private static ToggleHint FirstNonNull(params ToggleHint[] hints)
    {
        foreach (ToggleHint hint in hints)
        {
            if (hint != null)
            {
                return hint;
            }
        }
        return null;
    }

    private static void ApplyRect(RectTransform rect, RectData data, AnchorHint anchorHint = null)
    {
        rect.anchorMin = Vector2FromArray(anchorHint != null ? anchorHint.anchorMin : null, new Vector2(0, 1));
        rect.anchorMax = Vector2FromArray(anchorHint != null ? anchorHint.anchorMax : null, new Vector2(0, 1));
        rect.pivot = Vector2FromArray(anchorHint != null ? anchorHint.pivot : null, new Vector2(0, 1));
        if (data == null)
        {
            rect.anchoredPosition = Vector2FromArray(anchorHint != null ? anchorHint.anchoredPosition : null, Vector2.zero);
            rect.sizeDelta = Vector2FromArray(anchorHint != null ? anchorHint.sizeDelta : null, Vector2.zero);
            return;
        }
        rect.anchoredPosition = Vector2FromArray(anchorHint != null ? anchorHint.anchoredPosition : null, new Vector2(data.x, -data.y));
        rect.sizeDelta = Vector2FromArray(anchorHint != null ? anchorHint.sizeDelta : null, new Vector2(Mathf.Max(0, data.width), Mathf.Max(0, data.height)));
        rect.localScale = Vector3.one;
    }

    private static Vector2 Vector2FromArray(float[] values, Vector2 fallback)
    {
        if (values == null || values.Length < 2)
        {
            return fallback;
        }
        return new Vector2(values[0], values[1]);
    }

    private static bool IsInteractive(NodeEntry node)
    {
        return node.semantic_type == "button_candidate"
            || node.semantic_type == "slider_candidate"
            || node.semantic_type == "toggle_candidate"
            || node.semantic_type == "tab_candidate"
            || node.semantic_type == "radio_candidate"
            || node.semantic_type == "input_candidate"
            || node.semantic_type == "dropdown_candidate"
            || node.semantic_type == "scrollbar_candidate";
    }

    private static Color ParseColor(string value, Color fallback)
    {
        if (string.IsNullOrEmpty(value))
        {
            return fallback;
        }
        if (ColorUtility.TryParseHtmlString(value, out Color html))
        {
            return html;
        }
        if (value.StartsWith("rgba(", StringComparison.OrdinalIgnoreCase))
        {
            string inner = value.Substring(5, value.Length - 6);
            string[] parts = inner.Split(',');
            if (parts.Length >= 3)
            {
                float r = ParseFloat(parts[0]) / 255f;
                float g = ParseFloat(parts[1]) / 255f;
                float b = ParseFloat(parts[2]) / 255f;
                float a = parts.Length >= 4 ? ParseFloat(parts[3]) : 1f;
                return new Color(r, g, b, a);
            }
        }
        return fallback;
    }

    private static float ParseFloat(string value)
    {
        return float.TryParse(value, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out float parsed)
            ? parsed
            : 0;
    }

    private static string ReadArg(string name)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == name)
            {
                return args[i + 1];
            }
        }
        return null;
    }

    private static string[] SplitList(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return new string[0];
        }
        string[] rawItems = value.Split(new[] { ';', ',', '\n', '\r' }, StringSplitOptions.RemoveEmptyEntries);
        List<string> result = new List<string>();
        foreach (string raw in rawItems)
        {
            string item = raw.Trim();
            if (!string.IsNullOrEmpty(item))
            {
                result.Add(item);
            }
        }
        return result.ToArray();
    }

    private static string[] ResolveBatchSourceMaps(string sourceMapsArg, string sourceMapListArg, string sourceMapDir)
    {
        string[] explicitMaps = SplitList(FirstNonEmpty(sourceMapsArg, sourceMapListArg));
        if (explicitMaps.Length > 0)
        {
            for (int i = 0; i < explicitMaps.Length; i++)
            {
                explicitMaps[i] = NormalizeAssetPath(explicitMaps[i]);
            }
            return explicitMaps;
        }
        if (string.IsNullOrEmpty(sourceMapDir))
        {
            return new string[0];
        }
        string absoluteDir = ToAbsolutePath(NormalizeAssetPath(sourceMapDir));
        if (!Directory.Exists(absoluteDir))
        {
            throw new DirectoryNotFoundException("Source map directory not found: " + sourceMapDir);
        }
        string[] files = Directory.GetFiles(absoluteDir, "*.design-to-unity.json", SearchOption.AllDirectories);
        Array.Sort(files, StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i < files.Length; i++)
        {
            files[i] = NormalizeAssetPath(ToAssetPath(files[i]));
        }
        return files;
    }

    private static string OutputPrefabPathForSourceMap(string sourceMapAssetPath, string outputDir)
    {
        string normalizedDir = NormalizeAssetPath(outputDir).TrimEnd('/');
        string stem = Path.GetFileNameWithoutExtension(sourceMapAssetPath);
        if (stem.EndsWith(".design-to-unity", StringComparison.OrdinalIgnoreCase))
        {
            stem = stem.Substring(0, stem.Length - ".design-to-unity".Length);
        }
        return normalizedDir + "/" + SafeName(stem) + ".editor-imported.prefab";
    }

    private static bool ReadBoolArg(string name, bool fallback)
    {
        string value = ReadArg(name);
        if (string.IsNullOrEmpty(value))
        {
            return fallback;
        }
        return value == "1"
            || value.Equals("true", StringComparison.OrdinalIgnoreCase)
            || value.Equals("yes", StringComparison.OrdinalIgnoreCase);
    }

    private static void WriteReport(SourceMap sourceMap, string sourceMapAssetPath, string outputPrefabAssetPath, string reportPath, ImportStats stats)
    {
        ImportReport report = new ImportReport();
        report.status = "success";
        report.mode = stats.Mode;
        report.packet_id = sourceMap.packet_id;
        report.source_map_asset_path = sourceMapAssetPath;
        report.output_prefab_asset_path = outputPrefabAssetPath;
        report.node_count = sourceMap.nodes != null ? sourceMap.nodes.Length : 0;
        report.created_count = stats.CreatedCount;
        report.updated_count = stats.UpdatedCount;
        report.preserved_existing_count = Mathf.Max(0, stats.PreservedExistingCount);
        report.reusable_definition_count = stats.ReusableDefinitionCount;
        report.reused_prefab_instance_count = stats.ReusedPrefabInstanceCount;
        report.prefab_variant_group_count = stats.PrefabVariantGroupCount;
        report.prefab_variant_count = stats.PrefabVariantAssetCount;
        report.protected_reusable_instance_count = stats.ProtectedReusableInstanceCount;
        report.protected_user_component_count = stats.ProtectedUserComponentCount;
        report.protected_event_binding_count = stats.ProtectedEventBindingCount;
        report.preserved_user_child_count = stats.PreservedUserChildCount;
        report.protected_user_state_paths = stats.ProtectedUserStatePaths.ToArray();
        report.preserved_user_child_paths = stats.PreservedUserChildPaths.ToArray();
        report.identity_keys = sourceMap.incremental_update_plan != null ? sourceMap.incremental_update_plan.identity_keys : null;
        report.preserve_by_default = sourceMap.incremental_update_plan != null ? sourceMap.incremental_update_plan.preserve_by_default : null;
        report.node_update_fields = sourceMap.incremental_update_plan != null ? sourceMap.incremental_update_plan.node_update_fields : null;
        report.warnings = stats.Warnings.ToArray();
        report.reusable_prefabs = sourceMap.reusable_prefabs;
        report.prefab_variant_groups = sourceMap.prefab_variant_groups;

        string finalReportPath = string.IsNullOrEmpty(reportPath) ? DefaultReportPath(outputPrefabAssetPath) : reportPath;
        string absoluteReportPath = ToAbsolutePath(finalReportPath);
        string directory = Path.GetDirectoryName(absoluteReportPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
        File.WriteAllText(absoluteReportPath, JsonUtility.ToJson(report, true));
    }

    private static void WriteBatchReport(BatchImportReport report, string reportPath)
    {
        string absoluteReportPath = ToAbsolutePath(reportPath);
        string directory = Path.GetDirectoryName(absoluteReportPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
        File.WriteAllText(absoluteReportPath, JsonUtility.ToJson(report, true));
    }

    private static int CountPrefabVariants(PrefabVariantGroupEntry[] groups)
    {
        if (groups == null)
        {
            return 0;
        }
        int count = 0;
        foreach (PrefabVariantGroupEntry group in groups)
        {
            if (group != null && group.variants != null)
            {
                count += group.variants.Length;
            }
        }
        return count;
    }

    private static string DefaultReportPath(string outputPrefabAssetPath)
    {
        string normalized = NormalizeAssetPath(outputPrefabAssetPath);
        return normalized.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase)
            ? normalized.Substring(0, normalized.Length - ".prefab".Length) + ".import-report.json"
            : normalized + ".import-report.json";
    }

    private static string NormalizeAssetPath(string path)
    {
        if (string.IsNullOrEmpty(path))
        {
            return path;
        }
        path = path.Replace("\\", "/");
        int assetsIndex = path.IndexOf("Assets/", StringComparison.OrdinalIgnoreCase);
        return assetsIndex >= 0 ? path.Substring(assetsIndex) : path;
    }

    private static string ToAssetPath(string absolutePath)
    {
        string normalized = absolutePath.Replace("\\", "/");
        string project = Application.dataPath.Replace("\\", "/");
        if (normalized.StartsWith(project, StringComparison.OrdinalIgnoreCase))
        {
            return "Assets" + normalized.Substring(project.Length);
        }
        return normalized;
    }

    private static string ToAbsolutePath(string path)
    {
        string normalized = path.Replace("\\", "/");
        if (normalized.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
        {
            return Path.Combine(Directory.GetCurrentDirectory(), normalized);
        }
        return normalized;
    }

    private static void EnsureDirectoryForAsset(string assetPath)
    {
        string normalized = NormalizeAssetPath(assetPath);
        string absolute = Path.Combine(Directory.GetCurrentDirectory(), normalized);
        string directory = Path.GetDirectoryName(absolute);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }
    }

    private static string SafeName(string value)
    {
        if (string.IsNullOrEmpty(value))
        {
            return "Node";
        }
        foreach (char c in Path.GetInvalidFileNameChars())
        {
            value = value.Replace(c, '_');
        }
        return value;
    }

    private static string FirstNonEmpty(params string[] values)
    {
        foreach (string value in values)
        {
            if (!string.IsNullOrEmpty(value))
            {
                return value;
            }
        }
        return null;
    }

    [Serializable]
    private class SourceMap
    {
        public string packet_id;
        public NodeEntry[] nodes;
        public ReusablePrefabEntry[] reusable_prefabs;
        public PrefabVariantGroupEntry[] prefab_variant_groups;
        public IncrementalUpdatePlan incremental_update_plan;
    }

    [Serializable]
    private class NodeEntry
    {
        public string node_id;
        public string parent_id;
        public string name;
        public string unity_name_hint;
        public string unity_path;
        public string type;
        public string semantic_type;
        public RectData local_rect;
        public AnchorHint unity_anchor_hint;
        public StyleData style;
        public TextData text;
        public AssetRef asset;
        public LayoutHint unity_layout_hint;
        public LayoutElementHint unity_layout_element_hint;
        public ButtonHint unity_button_hint;
        public SliderHint unity_slider_hint;
        public ToggleHint unity_toggle_hint;
        public ToggleHint unity_tab_hint;
        public ToggleHint unity_radio_hint;
        public InputHint unity_input_hint;
        public DropdownHint unity_dropdown_hint;
        public ScrollHint unity_scroll_hint;
        public ScrollbarHint unity_scrollbar_hint;
        public IncrementalNodeUpdate incremental_update;
    }

    [Serializable]
    private class RectData
    {
        public float x;
        public float y;
        public float width;
        public float height;
    }

    [Serializable]
    private class AnchorHint
    {
        public float[] anchorMin;
        public float[] anchorMax;
        public float[] pivot;
        public float[] anchoredPosition;
        public float[] sizeDelta;
        public string anchor_mode;
        public string source;
        public bool requires_review;
    }

    [Serializable]
    private class StyleData
    {
        public string fill_color;
    }

    [Serializable]
    private class TextData
    {
        public string content;
        public float font_size;
        public string color;
        public string align;
        public string vertical_align;
        public string font_family;
        public string font_style;
        public string font_weight;
        public string tmp_font_asset_guid;
        public string unity_font_asset_guid;
        public string tmp_font_asset_path;
        public string unity_font_asset_path;
    }

    [Serializable]
    private class AssetRef
    {
        public string unity_guid;
        public string suggested_unity_path;
        public string deduped_unity_asset_path;
        public NineSliceHint nine_slice_hint;
    }

    [Serializable]
    private class NineSliceHint
    {
        public bool candidate;
        public BorderData border;
    }

    [Serializable]
    private class BorderData
    {
        public float left;
        public float right;
        public float top;
        public float bottom;
    }

    [Serializable]
    private class ButtonHint
    {
        public bool can_add_button;
        public string target_graphic_node_id;
        public string hit_node_id;
        public string label_node_id;
    }

    [Serializable]
    private class SliderHint
    {
        public bool can_add_slider;
        public string track_node_id;
        public string fill_node_id;
        public string handle_node_id;
        public string direction;
        public float value;
        public bool interactable;
    }

    [Serializable]
    private class ToggleHint
    {
        public bool can_add_toggle;
        public string graphic_node_id;
        public string group_node_id;
        public string label_node_id;
        public bool value;
    }

    [Serializable]
    private class InputHint
    {
        public bool can_add_tmp_input_field;
        public string text_component_node_id;
        public string placeholder_node_id;
        public string text;
        public string line_type;
    }

    [Serializable]
    private class DropdownHint
    {
        public bool can_add_tmp_dropdown;
        public string template_node_id;
        public string caption_text_node_id;
        public string item_text_node_id;
        public string[] options;
        public int value;
    }

    [Serializable]
    private class ScrollHint
    {
        public bool can_add_scroll_rect;
        public string direction;
        public string viewport_node_id;
        public string content_node_id;
        public string horizontal_scrollbar_node_id;
        public string vertical_scrollbar_node_id;
    }

    [Serializable]
    private class ScrollbarHint
    {
        public bool can_add_scrollbar;
        public string direction;
        public string handle_node_id;
        public float value;
        public float size;
    }

    [Serializable]
    private class LayoutHint
    {
        public bool can_add_layout_group;
        public string component;
        public string child_alignment;
        public int child_alignment_enum;
        public bool child_control_width;
        public bool child_control_height;
        public bool child_force_expand_width;
        public bool child_force_expand_height;
        public Spacing spacing;
        public Padding padding;
    }

    [Serializable]
    private class LayoutElementHint
    {
        public bool can_add_layout_element;
        public bool ignore_layout;
        public float min_width = -1;
        public float min_height = -1;
        public float preferred_width = -1;
        public float preferred_height = -1;
        public float flexible_width = -1;
        public float flexible_height = -1;
        public int layout_priority = 1;
        public string layout_align;
        public float layout_grow;
        public string layout_positioning;
        public string parent_layout_mode;
    }

    [Serializable]
    private class Spacing
    {
        public float x;
        public float y;
    }

    [Serializable]
    private class Padding
    {
        public float left;
        public float right;
        public float top;
        public float bottom;
    }

    [Serializable]
    private class ReusablePrefabEntry
    {
        public string key;
        public string definition_node_id;
        public string[] instance_node_ids;
        public int instance_count;
        public string suggested_prefab_asset_path;
    }

    [Serializable]
    private class PrefabVariantGroupEntry
    {
        public string key;
        public string reusable_prefab_key;
        public string definition_node_id;
        public string component_id;
        public string component_set_id;
        public string base_prefab_asset_path;
        public string suggested_variant_dir;
        public int variant_count;
        public string unity_strategy;
        public PrefabVariantEntry[] variants;
    }

    [Serializable]
    private class PrefabVariantEntry
    {
        public string key;
        public string node_id;
        public string source_node_id;
        public string signature;
        public string suggested_prefab_name;
        public string suggested_prefab_asset_path;
        public string base_prefab_asset_path;
    }

    [Serializable]
    private class IncrementalUpdatePlan
    {
        public string status;
        public string source_provider;
        public string[] identity_keys;
        public string[] node_update_fields;
        public string[] preserve_by_default;
    }

    [Serializable]
    private class IncrementalNodeUpdate
    {
        public string stable_id;
        public string source_node_id;
        public string ownership;
        public string[] identity_keys;
        public string[] owned_fields;
        public string[] preserve_fields;
        public string delete_policy;
    }

    private class ImportStats
    {
        public string Mode = "rebuild";
        public int CreatedCount;
        public int UpdatedCount;
        public int PreservedExistingCount;
        public int ReusableDefinitionCount;
        public int ReusedPrefabInstanceCount;
        public int PrefabVariantGroupCount;
        public int PrefabVariantAssetCount;
        public int ProtectedReusableInstanceCount;
        public int ProtectedUserComponentCount;
        public int ProtectedEventBindingCount;
        public int PreservedUserChildCount;
        public readonly List<string> ProtectedUserStatePaths = new List<string>();
        public readonly List<string> PreservedUserChildPaths = new List<string>();
        public readonly List<string> Warnings = new List<string>();
    }

    [Serializable]
    private class ImportReport
    {
        public string status;
        public string mode;
        public string packet_id;
        public string source_map_asset_path;
        public string output_prefab_asset_path;
        public int node_count;
        public int created_count;
        public int updated_count;
        public int preserved_existing_count;
        public int reusable_definition_count;
        public int reused_prefab_instance_count;
        public int prefab_variant_group_count;
        public int prefab_variant_count;
        public int protected_reusable_instance_count;
        public int protected_user_component_count;
        public int protected_event_binding_count;
        public int preserved_user_child_count;
        public string[] protected_user_state_paths;
        public string[] preserved_user_child_paths;
        public string[] identity_keys;
        public string[] preserve_by_default;
        public string[] node_update_fields;
        public string[] warnings;
        public ReusablePrefabEntry[] reusable_prefabs;
        public PrefabVariantGroupEntry[] prefab_variant_groups;
    }

    [Serializable]
    public class BatchImportReport
    {
        public string status;
        public string mode;
        public int source_map_count;
        public int success_count;
        public int failure_count;
        public BatchImportItem[] items;
    }

    [Serializable]
    public class BatchImportItem
    {
        public string status;
        public string source_map_asset_path;
        public string output_prefab_asset_path;
        public string report_asset_path;
        public string error;
    }
}
#endif

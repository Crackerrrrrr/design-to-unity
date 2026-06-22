#if UNITY_EDITOR
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using TMPro;
using UnityEditor;
using UnityEngine;
using UnityEngine.UI;

public static class DesignToUnityPrefabValidator
{
    private const string MenuPath = "Tools/Design To Unity/Validate Selected Prefab";

    [MenuItem(MenuPath)]
    public static void ValidateSelectedPrefab()
    {
        string prefabAssetPath = AssetDatabase.GetAssetPath(Selection.activeObject);
        if (string.IsNullOrEmpty(prefabAssetPath) || !prefabAssetPath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
        {
            Debug.LogError("Select a generated Design to Unity prefab first.");
            return;
        }

        Validate(prefabAssetPath, null, null);
    }

    [MenuItem(MenuPath, true)]
    public static bool ValidateSelectedPrefabEnabled()
    {
        string prefabAssetPath = AssetDatabase.GetAssetPath(Selection.activeObject);
        return !string.IsNullOrEmpty(prefabAssetPath) && prefabAssetPath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase);
    }

    public static void ValidateFromCommandLine()
    {
        string prefabAssetPath = ReadArg("-d2uPrefab");
        string sourceMapAssetPath = ReadArg("-d2uSourceMap");
        string reportPath = ReadArg("-d2uReport");
        if (string.IsNullOrEmpty(prefabAssetPath))
        {
            throw new ArgumentException("Missing -d2uPrefab Assets/... prefab path.");
        }

        string writtenReportPath = Validate(prefabAssetPath, sourceMapAssetPath, reportPath);
        Debug.Log("Design to Unity prefab validation report: " + writtenReportPath);
    }

    public static void CapturePrefabFromCommandLine()
    {
        string prefabAssetPath = ReadArg("-d2uPrefab");
        string screenshotPath = ReadArg("-d2uScreenshot");
        int width = ReadIntArg("-d2uWidth", 0);
        int height = ReadIntArg("-d2uHeight", 0);
        if (string.IsNullOrEmpty(prefabAssetPath))
        {
            throw new ArgumentException("Missing -d2uPrefab Assets/... prefab path.");
        }

        string writtenScreenshotPath = CapturePrefab(prefabAssetPath, screenshotPath, width, height);
        Debug.Log("Design to Unity prefab screenshot: " + writtenScreenshotPath);
    }

    public static string Validate(string prefabAssetPath, string sourceMapAssetPath = null, string reportPath = null)
    {
        ValidationReport report = BuildReport(prefabAssetPath, sourceMapAssetPath);
        string finalReportPath = string.IsNullOrEmpty(reportPath)
            ? DefaultReportPath(prefabAssetPath, report.SourceMapAssetPath)
            : reportPath;
        string absoluteReportPath = ToAbsolutePath(finalReportPath);
        string directory = Path.GetDirectoryName(absoluteReportPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllText(absoluteReportPath, ToJson(report), Encoding.UTF8);
        AssetDatabase.Refresh();

        if (report.Errors.Count > 0)
        {
            Debug.LogError("Design to Unity prefab validation failed. Report: " + absoluteReportPath);
        }
        else if (report.Warnings.Count > 0)
        {
            Debug.LogWarning("Design to Unity prefab validation passed with warnings. Report: " + absoluteReportPath);
        }
        else
        {
            Debug.Log("Design to Unity prefab validation passed. Report: " + absoluteReportPath);
        }

        return absoluteReportPath;
    }

    public static string CapturePrefab(string prefabAssetPath, string screenshotPath = null, int width = 0, int height = 0)
    {
        string normalizedPrefabPath = NormalizeAssetPath(prefabAssetPath);
        GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(normalizedPrefabPath);
        if (prefab == null)
        {
            throw new FileNotFoundException("Unity could not load the prefab asset.", normalizedPrefabPath);
        }

        Vector2 designSize = ResolvePrefabSize(prefab);
        int captureWidth = width > 0 ? width : Mathf.Max(1, Mathf.RoundToInt(designSize.x));
        int captureHeight = height > 0 ? height : Mathf.Max(1, Mathf.RoundToInt(designSize.y));
        string finalScreenshotPath = string.IsNullOrEmpty(screenshotPath)
            ? DefaultScreenshotPath(normalizedPrefabPath)
            : screenshotPath;
        string absoluteScreenshotPath = ToAbsolutePath(finalScreenshotPath);
        string directory = Path.GetDirectoryName(absoluteScreenshotPath);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        RenderTexture renderTexture = null;
        Texture2D screenshot = null;
        GameObject cameraObject = null;
        GameObject canvasObject = null;
        GameObject frameObject = null;
        GameObject instance = null;
        RenderTexture previousActive = RenderTexture.active;
        try
        {
            cameraObject = new GameObject("DesignToUnityCaptureCamera", typeof(Camera));
            Camera camera = cameraObject.GetComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0, 0, 0, 0);
            camera.orthographic = true;
            camera.orthographicSize = 1;
            camera.nearClipPlane = 0.01f;
            camera.farClipPlane = 100;
            camera.transform.position = new Vector3(0, 0, -10);

            canvasObject = new GameObject("DesignToUnityCaptureCanvas", typeof(RectTransform), typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            Canvas canvas = canvasObject.GetComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceCamera;
            canvas.worldCamera = camera;
            canvas.planeDistance = 10;
            CanvasScaler scaler = canvasObject.GetComponent<CanvasScaler>();
            scaler.uiScaleMode = CanvasScaler.ScaleMode.ConstantPixelSize;
            scaler.scaleFactor = 1;
            scaler.referencePixelsPerUnit = 100;

            frameObject = new GameObject("DesignToUnityCaptureFrame", typeof(RectTransform));
            RectTransform frameRect = frameObject.GetComponent<RectTransform>();
            frameRect.SetParent(canvasObject.transform, false);
            frameRect.anchorMin = new Vector2(0.5f, 0.5f);
            frameRect.anchorMax = new Vector2(0.5f, 0.5f);
            frameRect.pivot = new Vector2(0.5f, 0.5f);
            frameRect.anchoredPosition = Vector2.zero;
            frameRect.sizeDelta = new Vector2(designSize.x, designSize.y);

            instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            if (instance == null)
            {
                instance = UnityEngine.Object.Instantiate(prefab);
            }
            RectTransform instanceRect = instance.GetComponent<RectTransform>();
            if (instanceRect == null)
            {
                throw new InvalidOperationException("Generated prefab root has no RectTransform.");
            }
            instanceRect.SetParent(frameRect, false);
            instanceRect.anchorMin = new Vector2(0, 1);
            instanceRect.anchorMax = new Vector2(0, 1);
            instanceRect.pivot = new Vector2(0, 1);
            instanceRect.anchoredPosition = Vector2.zero;
            instanceRect.sizeDelta = designSize;
            instanceRect.localScale = Vector3.one;

            renderTexture = new RenderTexture(captureWidth, captureHeight, 24, RenderTextureFormat.ARGB32);
            camera.targetTexture = renderTexture;
            Canvas.ForceUpdateCanvases();
            camera.Render();

            RenderTexture.active = renderTexture;
            screenshot = new Texture2D(captureWidth, captureHeight, TextureFormat.RGBA32, false);
            screenshot.ReadPixels(new Rect(0, 0, captureWidth, captureHeight), 0, 0);
            screenshot.Apply();
            File.WriteAllBytes(absoluteScreenshotPath, screenshot.EncodeToPNG());
        }
        finally
        {
            RenderTexture.active = previousActive;
            if (renderTexture != null)
            {
                renderTexture.Release();
                UnityEngine.Object.DestroyImmediate(renderTexture);
            }
            if (screenshot != null)
            {
                UnityEngine.Object.DestroyImmediate(screenshot);
            }
            if (instance != null)
            {
                UnityEngine.Object.DestroyImmediate(instance);
            }
            if (frameObject != null)
            {
                UnityEngine.Object.DestroyImmediate(frameObject);
            }
            if (canvasObject != null)
            {
                UnityEngine.Object.DestroyImmediate(canvasObject);
            }
            if (cameraObject != null)
            {
                UnityEngine.Object.DestroyImmediate(cameraObject);
            }
        }

        AssetDatabase.Refresh();
        return absoluteScreenshotPath;
    }

    private static ValidationReport BuildReport(string prefabAssetPath, string sourceMapAssetPath)
    {
        ValidationReport report = new ValidationReport();
        report.PrefabAssetPath = NormalizeAssetPath(prefabAssetPath);
        report.SourceMapAssetPath = string.IsNullOrEmpty(sourceMapAssetPath)
            ? SourceMapPathFor(report.PrefabAssetPath)
            : NormalizeAssetPath(sourceMapAssetPath);

        GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(report.PrefabAssetPath);
        if (prefab == null)
        {
            report.Errors.Add(new ValidationMessage("prefab_not_imported", "Unity could not load the prefab asset: " + report.PrefabAssetPath));
            report.FinalizeStatus();
            return report;
        }

        TextAsset sourceMap = AssetDatabase.LoadAssetAtPath<TextAsset>(report.SourceMapAssetPath);
        if (sourceMap == null)
        {
            report.Errors.Add(new ValidationMessage("source_map_not_imported", "Unity could not load the source map TextAsset: " + report.SourceMapAssetPath));
        }
        else
        {
            report.ExpectedComponents = ParseExpectedComponents(sourceMap.text);
            if (report.ExpectedComponents.Count == 0)
            {
                report.Warnings.Add(new ValidationMessage("expected_components_missing", "Source map does not contain unity_import_manifest.expected_components."));
            }
        }

        CountComponents(prefab, report);
        CompareExpectedComponents(report);
        CheckBindings(prefab, report);
        report.FinalizeStatus();
        return report;
    }

    private static void CountComponents(GameObject prefab, ValidationReport report)
    {
        report.ActualComponents["GameObject"] = prefab.GetComponentsInChildren<Transform>(true).Length;
        report.ActualComponents["RectTransform"] = prefab.GetComponentsInChildren<RectTransform>(true).Length;
        report.ActualComponents["Image"] = prefab.GetComponentsInChildren<Image>(true).Length;
        report.ActualComponents["TextMeshProUGUI"] = prefab.GetComponentsInChildren<TextMeshProUGUI>(true).Length;
        report.ActualComponents["TMP_InputField"] = prefab.GetComponentsInChildren<TMP_InputField>(true).Length;
        report.ActualComponents["TMP_Dropdown"] = prefab.GetComponentsInChildren<TMP_Dropdown>(true).Length;
        report.ActualComponents["Button"] = prefab.GetComponentsInChildren<Button>(true).Length;
        report.ActualComponents["Slider"] = prefab.GetComponentsInChildren<Slider>(true).Length;
        report.ActualComponents["Toggle"] = prefab.GetComponentsInChildren<Toggle>(true).Length;
        report.ActualComponents["ToggleGroup"] = prefab.GetComponentsInChildren<ToggleGroup>(true).Length;
        report.ActualComponents["ScrollRect"] = prefab.GetComponentsInChildren<ScrollRect>(true).Length;
        report.ActualComponents["Scrollbar"] = prefab.GetComponentsInChildren<Scrollbar>(true).Length;
        report.ActualComponents["RectMask2D"] = prefab.GetComponentsInChildren<RectMask2D>(true).Length;
        report.ActualComponents["VerticalLayoutGroup"] = prefab.GetComponentsInChildren<VerticalLayoutGroup>(true).Length;
        report.ActualComponents["HorizontalLayoutGroup"] = prefab.GetComponentsInChildren<HorizontalLayoutGroup>(true).Length;
        report.ActualComponents["GridLayoutGroup"] = prefab.GetComponentsInChildren<GridLayoutGroup>(true).Length;
        report.ActualComponents["CanvasGroup"] = prefab.GetComponentsInChildren<CanvasGroup>(true).Length;
    }

    private static void CompareExpectedComponents(ValidationReport report)
    {
        foreach (KeyValuePair<string, int> expected in report.ExpectedComponents)
        {
            int actual = report.ActualComponents.ContainsKey(expected.Key) ? report.ActualComponents[expected.Key] : 0;
            if (actual != expected.Value)
            {
                report.Errors.Add(
                    new ValidationMessage(
                        "component_count_mismatch",
                        expected.Key + " expected " + expected.Value + " but Unity imported " + actual + "."
                    )
                );
            }
        }
    }

    private static void CheckBindings(GameObject prefab, ValidationReport report)
    {
        int unexpectedNullSprites = 0;
        Image[] images = prefab.GetComponentsInChildren<Image>(true);
        for (int i = 0; i < images.Length; i += 1)
        {
            if (images[i].sprite == null && !IsExpectedTransparentHitArea(images[i]))
            {
                unexpectedNullSprites += 1;
            }
        }
        if (unexpectedNullSprites > 0)
        {
            report.Warnings.Add(new ValidationMessage("image_sprite_unbound", unexpectedNullSprites + " Image components have no Sprite and are not transparent Button/Slider/Toggle hit areas."));
        }

        int buttonsWithoutGraphic = 0;
        Button[] buttons = prefab.GetComponentsInChildren<Button>(true);
        for (int i = 0; i < buttons.Length; i += 1)
        {
            if (buttons[i].targetGraphic == null)
            {
                buttonsWithoutGraphic += 1;
            }
        }
        if (buttonsWithoutGraphic > 0)
        {
            report.Warnings.Add(new ValidationMessage("button_target_graphic_unbound", buttonsWithoutGraphic + " Button components have no targetGraphic."));
        }

        int slidersWithoutFill = 0;
        int slidersWithoutHandle = 0;
        Slider[] sliders = prefab.GetComponentsInChildren<Slider>(true);
        for (int i = 0; i < sliders.Length; i += 1)
        {
            if (sliders[i].fillRect == null)
            {
                slidersWithoutFill += 1;
            }
            if (sliders[i].interactable && sliders[i].handleRect == null)
            {
                slidersWithoutHandle += 1;
            }
        }
        if (slidersWithoutFill > 0)
        {
            report.Warnings.Add(new ValidationMessage("slider_fill_rect_unbound", slidersWithoutFill + " Slider components have no fillRect."));
        }
        if (slidersWithoutHandle > 0)
        {
            report.Warnings.Add(new ValidationMessage("slider_handle_rect_unbound", slidersWithoutHandle + " interactive Slider components have no handleRect."));
        }

        int togglesWithoutTargetGraphic = 0;
        int togglesWithoutGraphic = 0;
        Toggle[] toggles = prefab.GetComponentsInChildren<Toggle>(true);
        for (int i = 0; i < toggles.Length; i += 1)
        {
            if (toggles[i].targetGraphic == null)
            {
                togglesWithoutTargetGraphic += 1;
            }
            if (toggles[i].graphic == null)
            {
                togglesWithoutGraphic += 1;
            }
        }
        if (togglesWithoutTargetGraphic > 0)
        {
            report.Warnings.Add(new ValidationMessage("toggle_target_graphic_unbound", togglesWithoutTargetGraphic + " Toggle components have no targetGraphic."));
        }
        if (togglesWithoutGraphic > 0)
        {
            report.Warnings.Add(new ValidationMessage("toggle_graphic_unbound", togglesWithoutGraphic + " Toggle components have no state graphic."));
        }

        int emptyToggleGroups = 0;
        ToggleGroup[] toggleGroups = prefab.GetComponentsInChildren<ToggleGroup>(true);
        for (int i = 0; i < toggleGroups.Length; i += 1)
        {
            bool hasBoundToggle = false;
            for (int j = 0; j < toggles.Length; j += 1)
            {
                if (toggles[j].group == toggleGroups[i])
                {
                    hasBoundToggle = true;
                    break;
                }
            }
            if (!hasBoundToggle)
            {
                emptyToggleGroups += 1;
            }
        }
        if (emptyToggleGroups > 0)
        {
            report.Warnings.Add(new ValidationMessage("toggle_group_empty", emptyToggleGroups + " ToggleGroup components have no Toggle referencing them."));
        }

        int inputsWithoutTextComponent = 0;
        int inputsWithoutGraphic = 0;
        TMP_InputField[] inputFields = prefab.GetComponentsInChildren<TMP_InputField>(true);
        for (int i = 0; i < inputFields.Length; i += 1)
        {
            if (inputFields[i].textComponent == null)
            {
                inputsWithoutTextComponent += 1;
            }
            if (inputFields[i].targetGraphic == null)
            {
                inputsWithoutGraphic += 1;
            }
        }
        if (inputsWithoutTextComponent > 0)
        {
            report.Warnings.Add(new ValidationMessage("input_text_component_unbound", inputsWithoutTextComponent + " TMP_InputField components have no textComponent."));
        }
        if (inputsWithoutGraphic > 0)
        {
            report.Warnings.Add(new ValidationMessage("input_target_graphic_unbound", inputsWithoutGraphic + " TMP_InputField components have no targetGraphic."));
        }

        int dropdownsWithoutTemplate = 0;
        int dropdownsWithoutCaption = 0;
        int dropdownsWithoutItem = 0;
        int dropdownsWithoutGraphic = 0;
        TMP_Dropdown[] dropdowns = prefab.GetComponentsInChildren<TMP_Dropdown>(true);
        for (int i = 0; i < dropdowns.Length; i += 1)
        {
            if (dropdowns[i].template == null)
            {
                dropdownsWithoutTemplate += 1;
            }
            if (dropdowns[i].captionText == null)
            {
                dropdownsWithoutCaption += 1;
            }
            if (dropdowns[i].itemText == null)
            {
                dropdownsWithoutItem += 1;
            }
            if (dropdowns[i].targetGraphic == null)
            {
                dropdownsWithoutGraphic += 1;
            }
        }
        if (dropdownsWithoutTemplate > 0)
        {
            report.Warnings.Add(new ValidationMessage("dropdown_template_unbound", dropdownsWithoutTemplate + " TMP_Dropdown components have no template RectTransform."));
        }
        if (dropdownsWithoutCaption > 0)
        {
            report.Warnings.Add(new ValidationMessage("dropdown_caption_text_unbound", dropdownsWithoutCaption + " TMP_Dropdown components have no captionText."));
        }
        if (dropdownsWithoutItem > 0)
        {
            report.Warnings.Add(new ValidationMessage("dropdown_item_text_unbound", dropdownsWithoutItem + " TMP_Dropdown components have no itemText."));
        }
        if (dropdownsWithoutGraphic > 0)
        {
            report.Warnings.Add(new ValidationMessage("dropdown_target_graphic_unbound", dropdownsWithoutGraphic + " TMP_Dropdown components have no targetGraphic."));
        }

        int scrollsWithoutContent = 0;
        int scrollsWithoutViewport = 0;
        ScrollRect[] scrollRects = prefab.GetComponentsInChildren<ScrollRect>(true);
        for (int i = 0; i < scrollRects.Length; i += 1)
        {
            if (scrollRects[i].content == null)
            {
                scrollsWithoutContent += 1;
            }
            if (scrollRects[i].viewport == null)
            {
                scrollsWithoutViewport += 1;
            }
        }
        if (scrollsWithoutContent > 0)
        {
            report.Warnings.Add(new ValidationMessage("scroll_content_unbound", scrollsWithoutContent + " ScrollRect components have no content RectTransform."));
        }
        if (scrollsWithoutViewport > 0)
        {
            report.Warnings.Add(new ValidationMessage("scroll_viewport_unbound", scrollsWithoutViewport + " ScrollRect components have no viewport RectTransform."));
        }

        int scrollbarsWithoutHandle = 0;
        int scrollbarsWithoutGraphic = 0;
        Scrollbar[] scrollbars = prefab.GetComponentsInChildren<Scrollbar>(true);
        for (int i = 0; i < scrollbars.Length; i += 1)
        {
            if (scrollbars[i].handleRect == null)
            {
                scrollbarsWithoutHandle += 1;
            }
            if (scrollbars[i].targetGraphic == null)
            {
                scrollbarsWithoutGraphic += 1;
            }
        }
        if (scrollbarsWithoutHandle > 0)
        {
            report.Warnings.Add(new ValidationMessage("scrollbar_handle_unbound", scrollbarsWithoutHandle + " Scrollbar components have no handleRect."));
        }
        if (scrollbarsWithoutGraphic > 0)
        {
            report.Warnings.Add(new ValidationMessage("scrollbar_target_graphic_unbound", scrollbarsWithoutGraphic + " Scrollbar components have no targetGraphic."));
        }

        int tmpWithoutFont = 0;
        TextMeshProUGUI[] texts = prefab.GetComponentsInChildren<TextMeshProUGUI>(true);
        for (int i = 0; i < texts.Length; i += 1)
        {
            if (texts[i].font == null)
            {
                tmpWithoutFont += 1;
            }
        }
        if (tmpWithoutFont > 0)
        {
            report.Warnings.Add(new ValidationMessage("tmp_font_unbound", tmpWithoutFont + " TextMeshProUGUI components have no font asset."));
        }
    }

    private static bool IsExpectedTransparentHitArea(Image image)
    {
        if (image == null)
        {
            return false;
        }

        bool transparent = image.color.a <= 0.001f;
        bool controlHost = image.GetComponent<Button>() != null || image.GetComponent<Slider>() != null || image.GetComponent<Toggle>() != null || image.GetComponent<TMP_InputField>() != null || image.GetComponent<TMP_Dropdown>() != null || image.GetComponent<Scrollbar>() != null;
        return transparent && controlHost;
    }

    private static Dictionary<string, int> ParseExpectedComponents(string sourceMapJson)
    {
        Dictionary<string, int> result = new Dictionary<string, int>();
        Match objectMatch = Regex.Match(sourceMapJson, "\\\"expected_components\\\"\\s*:\\s*\\{(?<body>.*?)\\}", RegexOptions.Singleline);
        if (!objectMatch.Success)
        {
            return result;
        }

        MatchCollection entries = Regex.Matches(objectMatch.Groups["body"].Value, "\\\"(?<key>[^\\\"]+)\\\"\\s*:\\s*(?<value>\\d+)");
        foreach (Match entry in entries)
        {
            int value;
            if (int.TryParse(entry.Groups["value"].Value, out value))
            {
                result[entry.Groups["key"].Value] = value;
            }
        }
        return result;
    }

    private static string SourceMapPathFor(string prefabAssetPath)
    {
        if (prefabAssetPath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
        {
            return prefabAssetPath.Substring(0, prefabAssetPath.Length - ".prefab".Length) + ".design-to-unity.json";
        }
        return prefabAssetPath + ".design-to-unity.json";
    }

    private static string DefaultReportPath(string prefabAssetPath, string sourceMapAssetPath)
    {
        string basePath = string.IsNullOrEmpty(sourceMapAssetPath) ? prefabAssetPath : sourceMapAssetPath;
        if (basePath.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
        {
            return basePath.Substring(0, basePath.Length - ".json".Length) + ".unity-import-report.json";
        }
        return basePath + ".unity-import-report.json";
    }

    private static string DefaultScreenshotPath(string prefabAssetPath)
    {
        if (prefabAssetPath.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase))
        {
            return prefabAssetPath.Substring(0, prefabAssetPath.Length - ".prefab".Length) + ".unity-screenshot.png";
        }
        return prefabAssetPath + ".unity-screenshot.png";
    }

    private static string ReadArg(string key)
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i += 1)
        {
            if (args[i] == key)
            {
                return args[i + 1];
            }
        }
        return null;
    }

    private static int ReadIntArg(string key, int fallback)
    {
        string raw = ReadArg(key);
        int value;
        if (string.IsNullOrEmpty(raw) || !int.TryParse(raw, out value))
        {
            return fallback;
        }
        return value;
    }

    private static Vector2 ResolvePrefabSize(GameObject prefab)
    {
        RectTransform rectTransform = prefab.GetComponent<RectTransform>();
        if (rectTransform == null)
        {
            return new Vector2(1024, 1024);
        }

        float width = Mathf.Abs(rectTransform.sizeDelta.x);
        float height = Mathf.Abs(rectTransform.sizeDelta.y);
        if (width <= 0.01f)
        {
            width = Mathf.Abs(rectTransform.rect.width);
        }
        if (height <= 0.01f)
        {
            height = Mathf.Abs(rectTransform.rect.height);
        }
        return new Vector2(Mathf.Max(1, width), Mathf.Max(1, height));
    }

    private static string NormalizeAssetPath(string path)
    {
        return (path ?? string.Empty).Replace("\\", "/").TrimStart('/');
    }

    private static string ToAbsolutePath(string path)
    {
        string raw = (path ?? string.Empty).Replace("\\", "/");
        if (Path.IsPathRooted(raw))
        {
            return raw;
        }
        string normalized = raw.TrimStart('/');
        string projectRoot = Directory.GetParent(Application.dataPath).FullName;
        return Path.Combine(projectRoot, normalized);
    }

    private static string ToJson(ValidationReport report)
    {
        StringBuilder builder = new StringBuilder();
        builder.Append("{\n");
        AppendString(builder, "status", report.Status, 1, true);
        AppendString(builder, "prefab_asset_path", report.PrefabAssetPath, 1, true);
        AppendString(builder, "source_map_asset_path", report.SourceMapAssetPath, 1, true);
        AppendMap(builder, "expected_components", report.ExpectedComponents, 1, true);
        AppendMap(builder, "actual_components", report.ActualComponents, 1, true);
        AppendMessages(builder, "errors", report.Errors, 1, true);
        AppendMessages(builder, "warnings", report.Warnings, 1, false);
        builder.Append("\n}\n");
        return builder.ToString();
    }

    private static void AppendString(StringBuilder builder, string key, string value, int indent, bool comma)
    {
        builder.Append(Indent(indent)).Append("\"").Append(Escape(key)).Append("\": \"").Append(Escape(value)).Append("\"");
        if (comma)
        {
            builder.Append(",");
        }
        builder.Append("\n");
    }

    private static void AppendMap(StringBuilder builder, string key, Dictionary<string, int> map, int indent, bool comma)
    {
        builder.Append(Indent(indent)).Append("\"").Append(Escape(key)).Append("\": {");
        int index = 0;
        foreach (KeyValuePair<string, int> item in map)
        {
            builder.Append(index == 0 ? "\n" : ",\n");
            builder.Append(Indent(indent + 1)).Append("\"").Append(Escape(item.Key)).Append("\": ").Append(item.Value);
            index += 1;
        }
        if (index > 0)
        {
            builder.Append("\n").Append(Indent(indent));
        }
        builder.Append("}");
        if (comma)
        {
            builder.Append(",");
        }
        builder.Append("\n");
    }

    private static void AppendMessages(StringBuilder builder, string key, List<ValidationMessage> messages, int indent, bool comma)
    {
        builder.Append(Indent(indent)).Append("\"").Append(Escape(key)).Append("\": [");
        for (int i = 0; i < messages.Count; i += 1)
        {
            builder.Append(i == 0 ? "\n" : ",\n");
            builder.Append(Indent(indent + 1)).Append("{\"code\": \"").Append(Escape(messages[i].Code)).Append("\", \"message\": \"").Append(Escape(messages[i].Message)).Append("\"}");
        }
        if (messages.Count > 0)
        {
            builder.Append("\n").Append(Indent(indent));
        }
        builder.Append("]");
        if (comma)
        {
            builder.Append(",");
        }
    }

    private static string Escape(string value)
    {
        return (value ?? string.Empty).Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", "\\n").Replace("\r", "\\r");
    }

    private static string Indent(int count)
    {
        return new string(' ', count * 2);
    }

    private sealed class ValidationReport
    {
        public string Status = "fail";
        public string PrefabAssetPath;
        public string SourceMapAssetPath;
        public Dictionary<string, int> ExpectedComponents = new Dictionary<string, int>();
        public Dictionary<string, int> ActualComponents = new Dictionary<string, int>();
        public List<ValidationMessage> Errors = new List<ValidationMessage>();
        public List<ValidationMessage> Warnings = new List<ValidationMessage>();

        public void FinalizeStatus()
        {
            Status = Errors.Count > 0 ? "fail" : Warnings.Count > 0 ? "pass_with_warnings" : "pass";
        }
    }

    private sealed class ValidationMessage
    {
        public readonly string Code;
        public readonly string Message;

        public ValidationMessage(string code, string message)
        {
            Code = code;
            Message = message;
        }
    }
}
#endif

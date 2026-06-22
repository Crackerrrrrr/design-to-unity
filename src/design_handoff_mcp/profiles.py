from __future__ import annotations

from typing import Any


def build_unity_profile(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": "unity",
        "ui_system": "UGUI",
        "text_system": "TextMeshPro",
        "direct_yaml_text_system": "TextMeshProUGUI",
        "reference_resolution": {
            "width": design.get("width"),
            "height": design.get("height"),
        },
        "coordinate_mapping": {
            "source": "top-left",
            "anchorMin": [0, 1],
            "anchorMax": [0, 1],
            "pivot": [0, 1],
            "anchoredPosition": ["local_rect.x", "-local_rect.y"],
            "sizeDelta": ["local_rect.width", "local_rect.height"],
        },
        "component_mapping": {
            "group": ["GameObject", "RectTransform", "CanvasGroup when opacity < 1"],
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
            "unity_layout_hint": ["VerticalLayoutGroup", "HorizontalLayoutGroup", "GridLayoutGroup"],
            "unknown": ["GameObject", "RectTransform"],
        },
        "image_defaults": {
            "type": "Simple",
            "preserveAspect": False,
            "raycastTarget": False,
        },
        "text_defaults": {
            "enableAutoSizing": False,
            "raycastTarget": False,
            "enableWordWrapping": False,
        },
        "asset_import_defaults": {
            "textureType": "Sprite",
            "spriteMode": "Single",
            "alphaIsTransparency": True,
            "sRGBTexture": True,
            "mipmapEnabled": False,
            "wrapMode": "Clamp",
            "filterMode": "Bilinear",
            "compression": "None",
            "pixelsPerUnit": 100,
        },
        "rules": [
            "Current milestone default flow: use lanhu_design_write_unity_prefab_yaml or psd_design_write_unity_prefab_yaml for static UGUI prefab snapshots.",
            "Use Unity MCP and Unity-side validator to import, inspect, smoke test, and continue editing generated prefabs.",
            "Import all sprites before assigning Image.sprite.",
            "Create nodes in the order returned by get_unity_plan.create_nodes; sibling z_index direction is source-provider specific.",
            "Use local_rect for child RectTransform positioning.",
            "Direct YAML can add Button for button_candidate, Slider for progress_candidate/slider_candidate, Toggle for toggle_candidate, ToggleGroup + Toggle for tab_group_candidate/tab_candidate and radio_group_candidate/radio_candidate, TMP_InputField for input_candidate, TMP_Dropdown for dropdown_candidate, RectMask2D for mask_candidate, LayoutGroup components for repeated child geometry, and ScrollRect/Scrollbar/RectMask2D for scroll_area_candidate.",
            "Direct YAML can add CanvasGroup for semi-transparent groups.",
            "Tab groups should bind each tab_candidate Toggle.group to the parent tab_group_candidate ToggleGroup and keep exactly one default selected tab unless allowSwitchOff is explicitly true.",
            "Radio groups should bind each radio_candidate Toggle.group to the parent radio_group_candidate ToggleGroup and keep exactly one default selected radio unless allowSwitchOff is explicitly true.",
            "ScrollRect content/viewport/scrollbar bindings must be confirmed when unity_scroll_hint.requires_review is true.",
            "Preserve custom scripts and event bindings during reimport.",
        ],
        "update_policy_hint": {
            "safe_to_overwrite": [
                "RectTransform",
                "Image.sprite",
                "Image.color",
                "TextMeshProUGUI.text",
                "TextMeshProUGUI.fontSize",
                "TextMeshProUGUI.color",
                "Button.targetGraphic",
                "Slider.value",
                "Toggle.isOn",
                "Toggle.group",
                "ToggleGroup.allowSwitchOff",
                "TMP_InputField.text",
                "TMP_InputField.textComponent",
                "TMP_Dropdown.template",
                "TMP_Dropdown.captionText",
                "TMP_Dropdown.itemText",
                "TMP_Dropdown.options",
                "TMP_Dropdown.value",
                "CanvasGroup.alpha",
            ],
            "preserve_by_default": [
                "custom_scripts",
                "event_bindings",
                "user_added_children",
                "animation",
                "prefab_variant_overrides",
            ],
        },
    }


def build_web_profile(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": "web",
        "layout": "absolute",
        "root_style": {
            "position": "relative",
            "width": f"{design.get('width')}px",
            "height": f"{design.get('height')}px",
        },
        "coordinate_mapping": {
            "source": "top-left",
            "left": "global_rect.x",
            "top": "global_rect.y",
            "width": "global_rect.width",
            "height": "global_rect.height",
        },
        "component_mapping": {
            "group": "div",
            "image": "img",
            "text": "div",
            "shape": "div",
            "button_candidate": "button candidate",
        },
    }


def build_handoff_profiles(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "unity": build_unity_profile(design),
        "web": build_web_profile(design),
    }

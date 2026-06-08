from __future__ import annotations

from typing import Any


def build_unity_profile(design: dict[str, Any]) -> dict[str, Any]:
    return {
        "target": "unity",
        "ui_system": "UGUI",
        "text_system": "TextMeshPro",
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
            "group": ["GameObject", "RectTransform"],
            "image": ["GameObject", "RectTransform", "Image"],
            "text": ["GameObject", "RectTransform", "TextMeshProUGUI"],
            "shape": ["GameObject", "RectTransform", "Image"],
            "mask": ["GameObject", "RectTransform", "RectMask2D candidate"],
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
            "Do not write prefab YAML directly.",
            "Use Unity Editor API through Unity MCP.",
            "Import all sprites before assigning Image.sprite.",
            "Create same-parent siblings by descending z_index; observed Lanhu layer arrays are front-to-back, while Unity UGUI renders later siblings on top.",
            "Use local_rect for child RectTransform positioning.",
            "Do not add Button automatically unless requested.",
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

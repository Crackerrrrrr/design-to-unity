from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from PIL import Image
    import psd_tools
except Exception:  # pragma: no cover
    Image = None
    psd_tools = None

from design_handoff_mcp.psd_adapter import make_psd_packet
from design_handoff_mcp.photoshop_export_adapter import make_photoshop_export_packet, photoshop_export_schema, validate_photoshop_export
from design_handoff_mcp.server import _unity_plan_response, _unity_readiness_report
from design_handoff_mcp.unity_editor_validator import install_unity_editor_validator
from design_handoff_mcp.unity_prefab_verifier import verify_unity_prefab_yaml
from design_handoff_mcp.unity_yaml_writer import write_unity_prefab_yaml
from design_handoff_mcp.visual_diff import compare_packet_reference_to_screenshot


class FakeLayer:
    def __init__(
        self,
        name: str,
        kind: str,
        bbox: tuple[int, int, int, int],
        children: list["FakeLayer"] | None = None,
        text: str | None = None,
        color: tuple[int, int, int, int] = (255, 255, 255, 255),
        opacity: int = 255,
        blend_mode: str | None = None,
        has_mask: bool = False,
        clipping: bool = False,
        effects: list | None = None,
        visible: bool = True,
    ) -> None:
        self.name = name
        self.kind = kind
        self.bbox = bbox
        self._children = children or []
        self.text = text
        self.opacity = opacity
        self.blend_mode = blend_mode
        self._has_mask = has_mask
        self.clipping = clipping
        self.effects = effects or []
        self._color = color
        self.visible = visible

    def __iter__(self):
        return iter(self._children)

    def is_visible(self) -> bool:
        return self.visible

    def is_group(self) -> bool:
        return bool(self._children) or self.kind == "group"

    def has_mask(self) -> bool:
        return self._has_mask

    def topil(self):
        if self.kind == "type":
            return None
        width = max(1, self.bbox[2] - self.bbox[0])
        height = max(1, self.bbox[3] - self.bbox[1])
        return Image.new("RGBA", (width, height), self._color)

    def composite(self, *args, **kwargs):
        return self.topil()


class FakePSD:
    width = 400
    height = 300
    size = (400, 300)

    def __init__(self) -> None:
        items = [
            FakeLayer("Item_01", "group", (30, 90, 350, 130), [FakeLayer("item_icon_01", "pixel", (40, 96, 76, 124))]),
            FakeLayer("Item_02", "group", (30, 140, 350, 180), [FakeLayer("item_icon_02", "pixel", (40, 146, 76, 174))]),
            FakeLayer("Item_03", "group", (30, 190, 350, 230), [FakeLayer("item_icon_03", "pixel", (40, 196, 76, 224))]),
        ]
        content = FakeLayer("Content", "group", (20, 80, 380, 260), items)
        viewport = FakeLayer("Viewport", "group", (20, 80, 380, 190), [content])
        vertical_scrollbar = FakeLayer(
            "Vertical Scrollbar",
            "group",
            (362, 80, 378, 190),
            [
                FakeLayer("Scrollbar Handle", "pixel", (364, 92, 376, 140), color=(180, 180, 180, 255)),
            ],
        )
        dropdown_template = FakeLayer(
            "Dropdown Template",
            "group",
            (270, 92, 370, 152),
            [
                FakeLayer("Item Option A", "type", (282, 98, 360, 118), text="Easy"),
                FakeLayer("Item Option B", "type", (282, 124, 360, 144), text="Hard"),
            ],
        )
        tabs = FakeLayer(
            "Tabs",
            "group",
            (40, 32, 250, 58),
            [
                FakeLayer(
                    "tab_home_selected",
                    "group",
                    (40, 32, 140, 58),
                    [FakeLayer("Home Label", "type", (52, 36, 130, 54), text="Home")],
                ),
                FakeLayer(
                    "tab_shop",
                    "group",
                    (150, 32, 250, 58),
                    [FakeLayer("Shop Label", "type", (162, 36, 240, 54), text="Shop")],
                ),
            ],
        )
        radio_group = FakeLayer(
            "RadioGroup",
            "group",
            (270, 32, 390, 58),
            [
                FakeLayer(
                    "radio_easy_selected",
                    "group",
                    (270, 32, 325, 58),
                    [FakeLayer("Easy Radio Label", "type", (278, 36, 318, 54), text="Easy")],
                ),
                FakeLayer(
                    "radio_hard",
                    "group",
                    (330, 32, 390, 58),
                    [FakeLayer("Hard Radio Label", "type", (338, 36, 382, 54), text="Hard")],
                ),
            ],
        )
        self._children = [
            FakeLayer("bg", "pixel", (0, 0, 400, 300)),
            tabs,
            radio_group,
            FakeLayer(
                "AvatarMask",
                "group",
                (292, 94, 352, 154),
                [FakeLayer("avatar_icon", "pixel", (298, 100, 346, 148), color=(120, 160, 220, 255))],
            ),
            FakeLayer(
                "input_player_name",
                "group",
                (40, 62, 260, 92),
                [
                    FakeLayer("placeholder_text", "type", (54, 67, 245, 87), text="Player Name"),
                ],
            ),
            FakeLayer(
                "dropdown_difficulty",
                "group",
                (270, 62, 370, 92),
                [
                    FakeLayer("Caption Text", "type", (282, 67, 350, 87), text="Easy"),
                    dropdown_template,
                ],
            ),
            FakeLayer("ScrollView", "group", (20, 80, 380, 190), [viewport, vertical_scrollbar], opacity=128),
            FakeLayer("progress_bar_75%", "pixel", (40, 215, 260, 235)),
            FakeLayer(
                "slider_volume_75%",
                "group",
                (40, 210, 260, 240),
                [
                    FakeLayer("track_bg", "pixel", (40, 215, 260, 235)),
                    FakeLayer("fill_75%", "pixel", (40, 215, 205, 235)),
                    FakeLayer("handle_thumb", "pixel", (195, 210, 217, 240)),
                ],
            ),
            FakeLayer(
                "toggle_music_on",
                "group",
                (275, 210, 360, 240),
                [
                    FakeLayer("toggle_track", "pixel", (275, 215, 360, 235), color=(80, 80, 80, 255)),
                    FakeLayer("checkmark_on", "pixel", (332, 211, 358, 239), color=(120, 220, 120, 255)),
                ],
            ),
            FakeLayer("btn_start", "smartobject", (90, 245, 250, 290), blend_mode="multiply", has_mask=True, clipping=True),
            FakeLayer("Color_Adjustment", "levels", (0, 0, 400, 300), color=(0, 0, 0, 0)),
            FakeLayer("TitleText", "type", (80, 20, 320, 60), text="Start Game"),
        ]

    def __iter__(self):
        return iter(self._children)

    def composite(self, *args, **kwargs):
        image = Image.new("RGBA", (400, 300), (10, 10, 10, 255))
        image.paste((20, 10, 10, 255), (0, 150, 400, 300))
        image.paste((10, 20, 10, 255), (0, 0, 200, 150))
        return image


class FakeHiddenPSD:
    width = 180
    height = 120
    size = (180, 120)

    def __init__(self) -> None:
        self._children = [
            FakeLayer("hidden_bg", "pixel", (0, 0, 180, 120), visible=False, color=(30, 40, 50, 255)),
            FakeLayer("hidden_btn_start", "pixel", (40, 70, 140, 105), visible=False, color=(80, 120, 200, 255)),
        ]

    def __iter__(self):
        return iter(self._children)

    def composite(self, *args, **kwargs):
        image = Image.new("RGBA", (180, 120), (30, 40, 50, 255))
        image.paste((80, 120, 200, 255), (40, 70, 140, 105))
        return image


class FakeHiddenCompositeFailPSD(FakeHiddenPSD):
    def composite(self, *args, **kwargs):
        raise RuntimeError("composite dependency missing")


@unittest.skipIf(psd_tools is None or Image is None, "psd-tools/Pillow are not installed")
class PsdPipelineTest(unittest.TestCase):
    def test_psd_packet_plan_and_prefab_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_path = tmp_path / "fake.psd"
            fake_path.write_bytes(b"fake psd bytes")

            old_open = psd_tools.PSDImage.open
            psd_tools.PSDImage.open = staticmethod(lambda path: FakePSD())
            try:
                packet = make_psd_packet(
                    str(fake_path),
                    asset_output_dir=tmp_path / "psd_assets",
                    data_dir=tmp_path / "data",
                    include_reference=True,
                )
            finally:
                psd_tools.PSDImage.open = old_open

            self.assertIn("scroll_area_candidate", packet["semantic_map"])
            self.assertIn("scroll_content_candidate", packet["semantic_map"])
            self.assertIn("scroll_viewport_candidate", packet["semantic_map"])
            self.assertIn("button_candidate", packet["semantic_map"])
            self.assertIn("progress_candidate", packet["semantic_map"])
            self.assertIn("slider_candidate", packet["semantic_map"])
            self.assertIn("slider_fill_candidate", packet["semantic_map"])
            self.assertIn("slider_handle_candidate", packet["semantic_map"])
            self.assertIn("toggle_candidate", packet["semantic_map"])
            self.assertIn("input_candidate", packet["semantic_map"])
            self.assertIn("dropdown_candidate", packet["semantic_map"])
            self.assertIn("dropdown_template_candidate", packet["semantic_map"])
            self.assertIn("dropdown_item_text_candidate", packet["semantic_map"])
            self.assertIn("scrollbar_candidate", packet["semantic_map"])
            self.assertIn("scrollbar_handle_candidate", packet["semantic_map"])
            self.assertIn("tab_group_candidate", packet["semantic_map"])
            self.assertIn("tab_candidate", packet["semantic_map"])
            self.assertIn("tab_label_candidate", packet["semantic_map"])
            self.assertIn("radio_group_candidate", packet["semantic_map"])
            self.assertIn("radio_candidate", packet["semantic_map"])
            self.assertIn("radio_label_candidate", packet["semantic_map"])
            self.assertIn("mask_candidate", packet["semantic_map"])
            btn_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "btn_start")
            btn_metadata = btn_node["source_metadata"]
            self.assertTrue(btn_metadata["has_mask"])
            self.assertTrue(btn_metadata["has_clipping_mask"])
            self.assertTrue(btn_metadata["uses_non_normal_blend_mode"])
            self.assertTrue(btn_metadata["is_smart_object"])
            self.assertEqual(btn_metadata["recommended_fidelity_mode"], "group_or_document_rasterize")
            warning_codes = {warning["code"] for warning in packet["warnings"]}
            self.assertIn("psd_mask_requires_review", warning_codes)
            self.assertIn("psd_clipping_mask_requires_review", warning_codes)
            self.assertIn("psd_blend_mode_requires_review", warning_codes)
            self.assertIn("psd_smart_object_rasterized", warning_codes)
            self.assertIn("psd_adjustment_layer_requires_review", warning_codes)

            slider_node = next(
                node
                for node in _walk_packet_nodes(packet)
                if node.get("semantic_type") == "slider_candidate"
            )
            slider_hint = slider_node.get("unity_slider_hint") or {}
            nodes_by_id = {node.get("id"): node for node in _walk_packet_nodes(packet)}
            self.assertEqual(nodes_by_id[slider_hint["fill_node_id"]]["name"], "fill_75%")
            self.assertEqual(nodes_by_id[slider_hint["handle_node_id"]]["name"], "handle_thumb")
            self.assertAlmostEqual(slider_hint["value"], 0.75)
            toggle_node = next(
                node
                for node in _walk_packet_nodes(packet)
                if node.get("semantic_type") == "toggle_candidate"
            )
            toggle_hint = toggle_node.get("unity_toggle_hint") or {}
            self.assertTrue(toggle_hint["can_add_toggle"])
            self.assertTrue(toggle_hint["value"])
            self.assertEqual(nodes_by_id[toggle_hint["graphic_node_id"]]["name"], "checkmark_on")
            input_node = next(
                node
                for node in _walk_packet_nodes(packet)
                if node.get("semantic_type") == "input_candidate"
            )
            input_hint = input_node.get("unity_input_hint") or {}
            self.assertTrue(input_hint["can_add_tmp_input_field"])
            self.assertEqual(nodes_by_id[input_hint["text_component_node_id"]]["name"], "placeholder_text")
            dropdown_node = next(
                node
                for node in _walk_packet_nodes(packet)
                if node.get("semantic_type") == "dropdown_candidate"
            )
            dropdown_hint = dropdown_node.get("unity_dropdown_hint") or {}
            self.assertTrue(dropdown_hint["can_add_tmp_dropdown"])
            self.assertEqual(nodes_by_id[dropdown_hint["template_node_id"]]["name"], "Dropdown Template")
            self.assertEqual(nodes_by_id[dropdown_hint["caption_text_node_id"]]["name"], "Caption Text")
            self.assertEqual(nodes_by_id[dropdown_hint["item_text_node_id"]]["name"], "Item Option A")
            self.assertEqual(dropdown_hint["options"], ["Easy", "Hard"])
            tab_group_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "Tabs")
            tab_home_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "tab_home_selected")
            tab_shop_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "tab_shop")
            tab_group_hint = tab_group_node.get("unity_tab_group_hint") or {}
            self.assertEqual(tab_group_hint["tab_node_ids"], [tab_home_node["id"], tab_shop_node["id"]])
            self.assertEqual(tab_group_hint["selected_tab_node_id"], tab_home_node["id"])
            self.assertEqual(tab_home_node["unity_tab_hint"]["group_node_id"], tab_group_node["id"])
            self.assertTrue(tab_home_node["unity_tab_hint"]["value"])
            self.assertFalse(tab_shop_node["unity_tab_hint"]["value"])
            radio_group_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "RadioGroup")
            radio_easy_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "radio_easy_selected")
            radio_hard_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "radio_hard")
            radio_group_hint = radio_group_node.get("unity_radio_group_hint") or {}
            self.assertEqual(radio_group_hint["radio_node_ids"], [radio_easy_node["id"], radio_hard_node["id"]])
            self.assertEqual(radio_group_hint["selected_radio_node_id"], radio_easy_node["id"])
            self.assertEqual(radio_easy_node["unity_radio_hint"]["group_node_id"], radio_group_node["id"])
            self.assertTrue(radio_easy_node["unity_radio_hint"]["value"])
            self.assertFalse(radio_hard_node["unity_radio_hint"]["value"])
            mask_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "AvatarMask")
            self.assertEqual(mask_node["semantic_type"], "mask_candidate")
            self.assertTrue(mask_node["unity_mask_hint"]["can_add_rect_mask_2d"])
            scroll_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "ScrollView")
            content_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "Content")
            scrollbar_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "Vertical Scrollbar")
            scrollbar_handle_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "Scrollbar Handle")
            first_item_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "Item_01")
            self.assertEqual(scroll_node["semantic_type"], "scroll_area_candidate")
            self.assertEqual(scroll_node["unity_scroll_hint"]["content_node_id"], content_node["id"])
            self.assertEqual(scroll_node["unity_scroll_hint"]["vertical_scrollbar_node_id"], scrollbar_node["id"])
            self.assertEqual(content_node["semantic_type"], "scroll_content_candidate")
            self.assertNotIn("unity_scroll_hint", content_node)
            self.assertEqual(content_node["unity_layout_hint"]["component"], "VerticalLayoutGroup")
            self.assertEqual(content_node["unity_layout_hint"]["direction"], "vertical")
            self.assertEqual(scrollbar_node["semantic_type"], "scrollbar_candidate")
            self.assertEqual(scrollbar_node["unity_scrollbar_hint"]["handle_node_id"], scrollbar_handle_node["id"])
            self.assertEqual(scrollbar_node["unity_scrollbar_hint"]["direction"], "vertical")
            self.assertGreater(scrollbar_node["unity_scrollbar_hint"]["size"], 0)
            self.assertEqual(first_item_node["semantic_type"], "list_item_candidate")
            self.assertNotIn("unity_scroll_hint", first_item_node)

            plan = _unity_plan_response(packet, packet["packet_id"], include_reference=True)
            self.assertIn("ascending z_index", plan["unity_sibling_order"]["rule"])
            self.assertEqual(plan["create_nodes"][0]["source_name"], "bg")
            self.assertEqual(len(plan["semantic_candidates"]["scroll_area_candidate"]), 1)
            self.assertEqual(plan["semantic_candidates"]["slider_candidate"][0]["unity_slider_hint"]["value"], 0.75)
            scroll_step = next(step for step in plan["create_nodes"] if step["source_name"] == "ScrollView")
            self.assertEqual(scroll_step["canvas_group_settings"]["alpha"], 0.502)

            readiness = _unity_readiness_report(packet)
            self.assertEqual(readiness["status"], "ready_with_review")
            self.assertGreaterEqual(readiness["readiness_score"], 60)
            self.assertEqual(readiness["counts"]["component_candidates"]["button"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["slider"], 2)
            self.assertEqual(readiness["counts"]["component_candidates"]["toggle"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["tab_group"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["tab"], 2)
            self.assertEqual(readiness["counts"]["component_candidates"]["radio_group"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["radio"], 2)
            self.assertEqual(readiness["counts"]["component_candidates"]["mask"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["input_field"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["dropdown"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["scroll_rect"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["scrollbar"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["layout_group"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["canvas_group"], 1)
            self.assertTrue(any(item["code"] == "psd_text_style_best_effort" for item in readiness["review_items"]))
            readiness_codes = {item["code"] for item in readiness["review_items"]}
            self.assertIn("psd_mask_requires_review", readiness_codes)
            self.assertIn("psd_clipping_mask_requires_review", readiness_codes)
            self.assertIn("psd_blend_mode_requires_review", readiness_codes)
            self.assertIn("psd_smart_object_rasterized", readiness_codes)
            self.assertIn("psd_adjustment_layer_requires_review", readiness_codes)

            assets_by_id = {asset["id"]: asset for asset in packet["assets"]}
            reference_path = Path(assets_by_id[packet["design"]["reference_asset_ref"]]["local_path"])
            matching_screenshot = tmp_path / "unity_matching.png"
            Image.open(reference_path).save(matching_screenshot)
            pass_diff = compare_packet_reference_to_screenshot(
                packet,
                str(matching_screenshot),
                output_dir=tmp_path / "visual_diffs",
            )
            self.assertEqual(pass_diff["status"], "pass")
            self.assertEqual(pass_diff["metrics"]["mean_abs_delta"], 0)
            self.assertEqual(pass_diff["orientation"]["used"], "normal")
            self.assertTrue(Path(pass_diff["diff_image_path"]).exists())
            self.assertTrue(Path(pass_diff["report_path"]).exists())

            flipped_screenshot = tmp_path / "unity_flipped.png"
            Image.open(reference_path).transpose(Image.Transpose.FLIP_TOP_BOTTOM).save(flipped_screenshot)
            flipped_diff = compare_packet_reference_to_screenshot(
                packet,
                str(flipped_screenshot),
                output_dir=tmp_path / "visual_diffs",
            )
            self.assertEqual(flipped_diff["status"], "pass")
            self.assertEqual(flipped_diff["orientation"]["used"], "flip_y")
            self.assertTrue(any(warning["code"] == "screenshot_orientation_adjusted" for warning in flipped_diff["warnings"]))

            changed_screenshot = tmp_path / "unity_changed.png"
            Image.new("RGBA", (400, 300), (255, 0, 0, 255)).save(changed_screenshot)
            fail_diff = compare_packet_reference_to_screenshot(
                packet,
                str(changed_screenshot),
                output_dir=tmp_path / "visual_diffs",
                max_mean_delta=0.001,
                max_mismatch_ratio=0.001,
            )
            self.assertEqual(fail_diff["status"], "fail")
            self.assertGreater(fail_diff["metrics"]["mismatch_ratio"], 0.9)

            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(packet, str(unity_root), prefab_name="PSD_Test")
            prefab_readiness = _unity_readiness_report(packet, prefab_result=result)
            prefab_verification = verify_unity_prefab_yaml(
                str(unity_root),
                result["prefab_asset_path"],
                result["source_map_asset_path"],
            )
            prefab_text = Path(result["prefab_path"]).read_text(encoding="utf-8")
            source_map = json.loads(Path(result["source_map_path"]).read_text(encoding="utf-8"))

            self.assertEqual(prefab_verification["status"], "pass")
            self.assertEqual(result["prefab_visual_mode"], "layered")
            self.assertEqual(prefab_verification["error_count"], 0)
            self.assertEqual(prefab_verification["counts"]["prefab_yaml"]["node_count"], result["node_count"])
            self.assertEqual(prefab_verification["counts"]["prefab_yaml"]["image_node_count"], result["image_node_count"])
            self.assertEqual(prefab_verification["warning_count"], 0)
            self.assertGreaterEqual(result["tmp_text_node_count"], 1)
            self.assertGreaterEqual(result["button_node_count"], 1)
            self.assertGreaterEqual(result["slider_node_count"], 1)
            self.assertEqual(result["toggle_node_count"], 5)
            self.assertEqual(result["toggle_group_node_count"], 2)
            self.assertEqual(result["tab_node_count"], 2)
            self.assertEqual(result["radio_node_count"], 2)
            self.assertEqual(result["input_field_node_count"], 1)
            self.assertEqual(result["dropdown_node_count"], 1)
            self.assertEqual(result["dropdown_template_bound_count"], 1)
            self.assertEqual(result["dropdown_caption_bound_count"], 1)
            self.assertEqual(result["dropdown_item_bound_count"], 1)
            self.assertGreaterEqual(result["slider_fill_bound_count"], 1)
            self.assertGreaterEqual(result["slider_handle_bound_count"], 1)
            self.assertGreaterEqual(result["scroll_rect_node_count"], 1)
            self.assertEqual(result["scrollbar_node_count"], 1)
            self.assertEqual(result["scrollbar_handle_bound_count"], 1)
            self.assertGreaterEqual(result["rect_mask_2d_node_count"], 2)
            self.assertEqual(result["vertical_layout_group_node_count"], 1)
            self.assertEqual(result["horizontal_layout_group_node_count"], 0)
            self.assertEqual(result["grid_layout_group_node_count"], 0)
            self.assertGreaterEqual(result["canvas_group_node_count"], 1)
            self.assertEqual(result["source_map_node_count"], result["node_count"])
            self.assertEqual(prefab_readiness["counts"]["prefab_stats"]["button_node_count"], result["button_node_count"])
            self.assertEqual(prefab_readiness["counts"]["prefab_stats"]["source_map_node_count"], result["source_map_node_count"])
            self.assertIn("Open the generated prefab in Unity and capture a screenshot for visual diff.", prefab_readiness["next_actions"])
            self.assertTrue(Path(result["source_map_meta_path"]).exists())
            self.assertIn("guid: f4688fdb7df04437aeb418b961361dc5", prefab_text)
            self.assertIn("guid: 4e29b1a8efbd4b44bb3f3716e73f07ff", prefab_text)
            self.assertIn("guid: 67db9e8f0e2ae9c40bc1e2b64352a6b4", prefab_text)
            self.assertIn("guid: 9085046f02f69544eb97fd06b6048fe2", prefab_text)
            self.assertIn("guid: 2fafe2cfe61f6974895a912c3755e8f1", prefab_text)
            self.assertIn("guid: 2da0c512f12947e489f739169773d7ca", prefab_text)
            self.assertIn("guid: 7b743370ac3e4ec2a1668f5455a8ef8a", prefab_text)
            self.assertIn("guid: 1aa08ab6e0800fa44ae55d278d1423e3", prefab_text)
            self.assertIn("guid: 2a4db7a114972834c8e4117be1d82ba3", prefab_text)
            self.assertIn("guid: 3312d7739989d2b4e91e6319e9a96d76", prefab_text)
            self.assertIn("--- !u!225", prefab_text)
            self.assertIn("m_Alpha: 0.502", prefab_text)
            self.assertRegex(prefab_text, r"m_FillRect: \{fileID: [1-9]\d*\}")
            self.assertRegex(prefab_text, r"m_HandleRect: \{fileID: [1-9]\d*\}")
            self.assertRegex(prefab_text, r"m_VerticalScrollbar: \{fileID: [1-9]\d*\}")
            self.assertRegex(prefab_text, r"m_Template: \{fileID: [1-9]\d*\}")
            self.assertRegex(prefab_text, r"m_CaptionText: \{fileID: [1-9]\d*\}")
            self.assertRegex(prefab_text, r"m_ItemText: \{fileID: [1-9]\d*\}")
            self.assertRegex(prefab_text, r"m_Group: \{fileID: [1-9]\d*\}")
            self.assertIn("m_Text: \"Hard\"", prefab_text)
            self.assertRegex(prefab_text, r"graphic: \{fileID: [1-9]\d*\}")
            self.assertIn("m_IsOn: 1", prefab_text)
            self.assertIn("DesignToUnityView_", prefab_text)
            self.assertNotIn("LanhuView_", prefab_text)
            self.assertEqual(source_map["schema"], "design-to-unity.prefab-source-map")
            self.assertEqual(source_map["prefab_visual_mode"], "layered")
            self.assertEqual(source_map["visual_strategy"]["visible_baseline"], "source_layers")
            self.assertEqual(source_map["prefab_asset_path"], result["prefab_asset_path"])
            self.assertEqual(source_map["stats"]["slider_fill_bound_count"], result["slider_fill_bound_count"])
            self.assertEqual(source_map["stats"]["canvas_group_node_count"], result["canvas_group_node_count"])
            self.assertEqual(source_map["stats"]["toggle_group_node_count"], 2)
            self.assertEqual(source_map["stats"]["tab_node_count"], 2)
            self.assertEqual(source_map["stats"]["radio_node_count"], 2)
            self.assertEqual(source_map["unity_import_manifest"]["target"], "unity")
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["Button"], result["button_node_count"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["Slider"], result["slider_node_count"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["Toggle"], result["toggle_node_count"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["ToggleGroup"], result["toggle_group_node_count"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["TMP_InputField"], result["input_field_node_count"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["TMP_Dropdown"], result["dropdown_node_count"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["Scrollbar"], result["scrollbar_node_count"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["VerticalLayoutGroup"], 1)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["HorizontalLayoutGroup"], 0)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["GridLayoutGroup"], 0)
            self.assertTrue(any(gate["id"] == "static_prefab_verify" for gate in source_map["unity_import_manifest"]["import_gates"]))
            self.assertTrue(any(gate["id"] == "unity_prefab_screenshot" for gate in source_map["unity_import_manifest"]["import_gates"]))
            self.assertTrue(
                any(
                    "Capture a prefab screenshot" in step
                    for step in source_map["unity_import_manifest"]["recommended_sequence"]
                )
            )
            self.assertIn("Image.sprite", source_map["update_policy_hint"]["safe_to_overwrite"])
            self.assertIn("Toggle.group", source_map["update_policy_hint"]["safe_to_overwrite"])
            self.assertIn("event_bindings", source_map["update_policy_hint"]["preserve_by_default"])
            mapped_slider = next(
                node
                for node in source_map["nodes"]
                if node.get("semantic_type") == "slider_candidate"
            )
            self.assertEqual(mapped_slider["unity_slider_hint"]["value"], 0.75)
            self.assertIn("slider", mapped_slider["component_file_ids"])
            self.assertIn("rect", mapped_slider["component_file_ids"])
            mapped_fill = next(
                node
                for node in source_map["nodes"]
                if node.get("semantic_type") == "slider_fill_candidate"
            )
            self.assertEqual(mapped_fill["source_metadata"]["source_provider"], "psd")
            self.assertTrue(mapped_fill["content_hash"])
            mapped_scroll = next(
                node
                for node in source_map["nodes"]
                if node.get("name") == "ScrollView"
            )
            self.assertIn("canvas_group", mapped_scroll["component_file_ids"])
            self.assertEqual(mapped_scroll["style"]["opacity"], 0.502)
            mapped_content = next(node for node in source_map["nodes"] if node.get("name") == "Content")
            self.assertIn("vertical_layout_group", mapped_content["component_file_ids"])
            self.assertEqual(mapped_content["unity_layout_hint"]["component"], "VerticalLayoutGroup")
            mapped_toggle = next(
                node
                for node in source_map["nodes"]
                if node.get("name") == "toggle_music_on"
            )
            self.assertIn("toggle", mapped_toggle["component_file_ids"])
            self.assertTrue(mapped_toggle["unity_toggle_hint"]["value"])
            mapped_mask = next(node for node in source_map["nodes"] if node.get("name") == "AvatarMask")
            self.assertEqual(mapped_mask["unity_mask_hint"]["recommended_unity_component"], "RectMask2D")
            self.assertIn("rect_mask_2d", mapped_mask["component_file_ids"])
            mapped_radio_group = next(node for node in source_map["nodes"] if node.get("name") == "RadioGroup")
            mapped_radio_easy = next(node for node in source_map["nodes"] if node.get("name") == "radio_easy_selected")
            mapped_radio_hard = next(node for node in source_map["nodes"] if node.get("name") == "radio_hard")
            self.assertIn("toggle_group", mapped_radio_group["component_file_ids"])
            self.assertEqual(mapped_radio_group["unity_radio_group_hint"]["selected_radio_node_id"], mapped_radio_easy["node_id"])
            self.assertEqual(mapped_radio_easy["unity_radio_hint"]["group_node_id"], mapped_radio_group["node_id"])
            self.assertTrue(mapped_radio_easy["unity_radio_hint"]["value"])
            self.assertFalse(mapped_radio_hard["unity_radio_hint"]["value"])
            self.assertIn(f"m_Group: {{fileID: {mapped_radio_group['component_file_ids']['toggle_group']}}}", prefab_text)
            mapped_input = next(
                node
                for node in source_map["nodes"]
                if node.get("name") == "input_player_name"
            )
            mapped_placeholder = next(
                node
                for node in source_map["nodes"]
                if node.get("name") == "placeholder_text"
            )
            self.assertIn("tmp_input_field", mapped_input["component_file_ids"])
            self.assertEqual(mapped_input["unity_input_hint"]["text_component_node_id"], mapped_placeholder["node_id"])
            self.assertIn(f"m_TextComponent: {{fileID: {mapped_placeholder['component_file_ids']['tmp_text']}}}", prefab_text)
            mapped_button = next(
                node
                for node in source_map["nodes"]
                if node.get("name") == "btn_start"
            )
            self.assertIn("mask", mapped_button["source_metadata"]["unsupported_psd_features"])
            self.assertIn("blend_mode", mapped_button["source_metadata"]["unsupported_psd_features"])
            self.assertEqual(mapped_button["source_metadata"]["recommended_fidelity_mode"], "group_or_document_rasterize")

            overlay_result = write_unity_prefab_yaml(
                packet,
                str(unity_root),
                asset_root="Assets/DesignToUnityOverlay",
                prefab_name="PSD_Overlay_Test",
                prefab_visual_mode="flattened_reference_overlay",
            )
            overlay_verification = verify_unity_prefab_yaml(
                str(unity_root),
                overlay_result["prefab_asset_path"],
                overlay_result["source_map_asset_path"],
            )
            overlay_prefab_text = Path(overlay_result["prefab_path"]).read_text(encoding="utf-8")
            overlay_source_map = json.loads(Path(overlay_result["source_map_path"]).read_text(encoding="utf-8"))
            self.assertEqual(overlay_result["prefab_visual_mode"], "flattened_reference_overlay")
            self.assertEqual(overlay_verification["status"], "pass")
            self.assertEqual(overlay_result["copied_asset_count"], 1)
            self.assertLess(overlay_result["image_node_count"], result["image_node_count"])
            self.assertEqual(overlay_source_map["visual_strategy"]["visible_baseline"], "design_reference")
            self.assertEqual(overlay_source_map["visual_strategy"]["reference_asset_ref"], packet["design"]["reference_asset_ref"])
            reference_node = next(node for node in overlay_source_map["nodes"] if node["node_id"] == "__design_reference_overlay")
            self.assertEqual(reference_node["asset"]["usage"], "design_reference")
            source_button = next(node for node in overlay_source_map["nodes"] if node.get("name") == "btn_start")
            self.assertTrue(source_button["visual_suppressed"])
            self.assertIn("m_fontColor: {r: 1.0, g: 1.0, b: 1.0, a: 0.0}", overlay_prefab_text)

    def test_psd_all_hidden_layers_auto_include_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_path = tmp_path / "hidden.psd"
            fake_path.write_bytes(b"hidden psd bytes")

            old_open = psd_tools.PSDImage.open
            psd_tools.PSDImage.open = staticmethod(lambda path: FakeHiddenPSD())
            try:
                packet = make_psd_packet(
                    str(fake_path),
                    asset_output_dir=tmp_path / "psd_assets",
                    data_dir=tmp_path / "data",
                    include_reference=True,
                )
            finally:
                psd_tools.PSDImage.open = old_open

            self.assertTrue(packet["source"]["include_hidden"])
            self.assertTrue(packet["source"]["auto_included_hidden_layers"])
            warning_codes = {warning["code"] for warning in packet["warnings"]}
            self.assertIn("psd_no_visible_layers_auto_include_hidden", warning_codes)
            self.assertIn("psd_reference_auto_include_hidden", warning_codes)
            root = packet["nodes"][0]
            self.assertEqual(len(root["children"]), 2)
            self.assertGreaterEqual(len(packet["assets"]), 3)
            assets = {asset["id"]: asset for asset in packet["assets"]}
            reference_path = Path(assets[packet["design"]["reference_asset_ref"]]["local_path"])
            self.assertEqual(Image.open(reference_path).convert("RGBA").getextrema()[3], (255, 255))

            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(packet, str(unity_root), prefab_name="HiddenPSD_Test")
            verification = verify_unity_prefab_yaml(
                str(unity_root),
                result["prefab_asset_path"],
                result["source_map_asset_path"],
            )
            self.assertEqual(result["image_node_count"], 2)
            self.assertEqual(verification["status"], "pass")

    def test_psd_reference_falls_back_to_exported_layer_composite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_path = tmp_path / "hidden-composite-fail.psd"
            fake_path.write_bytes(b"hidden composite fail psd bytes")

            old_open = psd_tools.PSDImage.open
            psd_tools.PSDImage.open = staticmethod(lambda path: FakeHiddenCompositeFailPSD())
            try:
                packet = make_psd_packet(
                    str(fake_path),
                    asset_output_dir=tmp_path / "psd_assets",
                    data_dir=tmp_path / "data",
                    include_reference=True,
                )
            finally:
                psd_tools.PSDImage.open = old_open

            warning_codes = {warning["code"] for warning in packet["warnings"]}
            self.assertIn("psd_reference_export_failed", warning_codes)
            self.assertIn("psd_reference_composed_from_exported_layers", warning_codes)
            self.assertIn("reference_asset_ref", packet["design"])
            assets = {asset["id"]: asset for asset in packet["assets"]}
            reference_path = Path(assets[packet["design"]["reference_asset_ref"]]["local_path"])
            image = Image.open(reference_path).convert("RGBA")
            self.assertEqual(image.size, (180, 120))
            self.assertEqual(image.getextrema()[3], (255, 255))
            packet["warnings"].append(
                {
                    "code": "psd_blend_mode_requires_review",
                    "severity": "medium",
                    "message": "Synthetic complex blend warning for visual diff status.",
                }
            )
            changed_screenshot = tmp_path / "changed.png"
            Image.new("RGBA", (180, 120), (255, 0, 0, 255)).save(changed_screenshot)
            diff = compare_packet_reference_to_screenshot(
                packet,
                str(changed_screenshot),
                output_dir=tmp_path / "fallback_visual_diffs",
                max_mean_delta=0.001,
                max_mismatch_ratio=0.001,
            )
            self.assertEqual(diff["status"], "needs_review")
            self.assertTrue(any(warning["code"] == "visual_diff_needs_human_review" for warning in diff["warnings"]))

    def test_psd_external_reference_image_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_path = tmp_path / "hidden.psd"
            fake_path.write_bytes(b"hidden psd bytes")
            external_reference = tmp_path / "photoshop-preview.png"
            Image.new("RGBA", (180, 120), (12, 34, 56, 255)).save(external_reference)

            old_open = psd_tools.PSDImage.open
            psd_tools.PSDImage.open = staticmethod(lambda path: FakeHiddenCompositeFailPSD())
            try:
                packet = make_psd_packet(
                    str(fake_path),
                    asset_output_dir=tmp_path / "psd_assets",
                    data_dir=tmp_path / "data",
                    include_reference=True,
                    reference_image_path=external_reference,
                )
            finally:
                psd_tools.PSDImage.open = old_open

            warning_codes = {warning["code"] for warning in packet["warnings"]}
            self.assertIn("psd_external_reference_used", warning_codes)
            self.assertNotIn("psd_reference_composed_from_exported_layers", warning_codes)
            assets = {asset["id"]: asset for asset in packet["assets"]}
            reference_path = Path(assets[packet["design"]["reference_asset_ref"]]["local_path"])
            self.assertEqual(Image.open(reference_path).convert("RGBA").getpixel((0, 0)), (12, 34, 56, 255))

    def test_photoshop_export_packet_plan_and_prefab_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_dir = tmp_path / "uxp_export"
            assets_dir = export_dir / "assets"
            assets_dir.mkdir(parents=True)
            _save_image(export_dir / "preview.png", (400, 300), (20, 30, 40, 255))
            _save_image(assets_dir / "bg.png", (400, 300), (20, 30, 40, 255))
            _save_image(assets_dir / "btn_start.png", (160, 45), (80, 120, 200, 255))
            _save_image(assets_dir / "track.png", (220, 20), (50, 50, 50, 255))
            _save_image(assets_dir / "fill.png", (165, 20), (80, 180, 120, 255))
            _save_image(assets_dir / "handle.png", (22, 30), (240, 240, 240, 255))
            _save_image(assets_dir / "toggle_track.png", (85, 20), (70, 70, 70, 255))
            _save_image(assets_dir / "toggle_check.png", (26, 28), (120, 220, 120, 255))
            manifest = {
                "document": {
                    "name": "UXPPanel",
                    "width": 400,
                    "height": 300,
                    "scale": 1,
                    "preview": "preview.png",
                    "layers": [
                        {
                            "id": "bg",
                            "name": "bg",
                            "kind": "pixel",
                            "bounds": {"x": 0, "y": 0, "width": 400, "height": 300},
                            "asset": "assets/bg.png",
                        },
                        {
                            "id": "tabs",
                            "name": "Tabs",
                            "kind": "group",
                            "role": "tab_group_candidate",
                            "bounds": {"x": 40, "y": 32, "width": 210, "height": 26},
                            "layers": [
                                {
                                    "id": "tab_home",
                                    "name": "tab_home_selected",
                                    "kind": "group",
                                    "role": "tab_candidate",
                                    "bounds": {"x": 40, "y": 32, "width": 100, "height": 26},
                                    "layers": [
                                        {
                                            "id": "tab_home_label",
                                            "name": "Home Label",
                                            "kind": "type",
                                            "bounds": {"x": 52, "y": 36, "width": 78, "height": 18},
                                            "text": {"content": "Home", "fontSize": 14, "color": "rgba(255,255,255,1)"},
                                        },
                                    ],
                                },
                                {
                                    "id": "tab_shop",
                                    "name": "tab_shop",
                                    "kind": "group",
                                    "role": "tab_candidate",
                                    "bounds": {"x": 150, "y": 32, "width": 100, "height": 26},
                                    "layers": [
                                        {
                                            "id": "tab_shop_label",
                                            "name": "Shop Label",
                                            "kind": "type",
                                            "bounds": {"x": 162, "y": 36, "width": 78, "height": 18},
                                            "text": {"content": "Shop", "fontSize": 14, "color": "rgba(255,255,255,1)"},
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            "id": "radio_group",
                            "name": "RadioGroup",
                            "kind": "group",
                            "role": "radio_group_candidate",
                            "bounds": {"x": 270, "y": 32, "width": 120, "height": 26},
                            "layers": [
                                {
                                    "id": "radio_easy",
                                    "name": "radio_easy_selected",
                                    "kind": "group",
                                    "role": "radio_candidate",
                                    "bounds": {"x": 270, "y": 32, "width": 55, "height": 26},
                                    "layers": [
                                        {
                                            "id": "radio_easy_label",
                                            "name": "Easy Radio Label",
                                            "kind": "type",
                                            "bounds": {"x": 278, "y": 36, "width": 40, "height": 18},
                                            "text": {"content": "Easy", "fontSize": 14, "color": "rgba(255,255,255,1)"},
                                        },
                                    ],
                                },
                                {
                                    "id": "radio_hard",
                                    "name": "radio_hard",
                                    "kind": "group",
                                    "role": "radio_candidate",
                                    "bounds": {"x": 330, "y": 32, "width": 60, "height": 26},
                                    "layers": [
                                        {
                                            "id": "radio_hard_label",
                                            "name": "Hard Radio Label",
                                            "kind": "type",
                                            "bounds": {"x": 338, "y": 36, "width": 44, "height": 18},
                                            "text": {"content": "Hard", "fontSize": 14, "color": "rgba(255,255,255,1)"},
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            "id": "slider",
                            "name": "slider_volume_75%",
                            "kind": "group",
                            "bounds": {"x": 40, "y": 210, "width": 220, "height": 30},
                            "layers": [
                                {
                                    "id": "track",
                                    "name": "track_bg",
                                    "kind": "pixel",
                                    "bounds": {"x": 40, "y": 215, "width": 220, "height": 20},
                                    "asset": "assets/track.png",
                                },
                                {
                                    "id": "fill",
                                    "name": "fill_75%",
                                    "kind": "pixel",
                                    "bounds": {"x": 40, "y": 215, "width": 165, "height": 20},
                                    "asset": "assets/fill.png",
                                },
                                {
                                    "id": "handle",
                                    "name": "handle_thumb",
                                    "kind": "pixel",
                                    "bounds": {"x": 195, "y": 210, "width": 22, "height": 30},
                                    "asset": "assets/handle.png",
                                },
                            ],
                        },
                        {
                            "id": "toggle",
                            "name": "toggle_music_on",
                            "kind": "group",
                            "role": "toggle_candidate",
                            "checked": True,
                            "graphic_node_id": "toggle_check",
                            "bounds": {"x": 275, "y": 210, "width": 85, "height": 30},
                            "layers": [
                                {
                                    "id": "toggle_track",
                                    "name": "toggle_track",
                                    "kind": "pixel",
                                    "bounds": {"x": 275, "y": 215, "width": 85, "height": 20},
                                    "asset": "assets/toggle_track.png",
                                },
                                {
                                    "id": "toggle_check",
                                    "name": "checkmark_on",
                                    "kind": "pixel",
                                    "bounds": {"x": 332, "y": 211, "width": 26, "height": 28},
                                    "asset": "assets/toggle_check.png",
                                },
                            ],
                        },
                        {
                            "id": "input",
                            "name": "input_player_name",
                            "kind": "group",
                            "role": "input_candidate",
                            "bounds": {"x": 40, "y": 62, "width": 220, "height": 30},
                            "layers": [
                                {
                                    "id": "input_placeholder",
                                    "name": "placeholder_text",
                                    "kind": "type",
                                    "bounds": {"x": 54, "y": 67, "width": 190, "height": 20},
                                    "text": {"content": "Player Name", "fontSize": 16, "color": "rgba(255,255,255,0.6)"},
                                }
                            ],
                        },
                        {
                            "id": "dropdown",
                            "name": "dropdown_difficulty",
                            "kind": "group",
                            "role": "dropdown_candidate",
                            "bounds": {"x": 270, "y": 62, "width": 100, "height": 30},
                            "layers": [
                                {
                                    "id": "dropdown_caption",
                                    "name": "Caption Text",
                                    "kind": "type",
                                    "bounds": {"x": 282, "y": 67, "width": 70, "height": 20},
                                    "text": {"content": "Easy", "fontSize": 16, "color": "rgba(255,255,255,1)"},
                                },
                                {
                                    "id": "dropdown_template",
                                    "name": "Dropdown Template",
                                    "kind": "group",
                                    "bounds": {"x": 270, "y": 92, "width": 100, "height": 60},
                                    "layers": [
                                        {
                                            "id": "dropdown_item_easy",
                                            "name": "Item Option A",
                                            "kind": "type",
                                            "bounds": {"x": 282, "y": 98, "width": 70, "height": 20},
                                            "text": {"content": "Easy", "fontSize": 16, "color": "rgba(255,255,255,1)"},
                                        },
                                        {
                                            "id": "dropdown_item_hard",
                                            "name": "Item Option B",
                                            "kind": "type",
                                            "bounds": {"x": 282, "y": 124, "width": 70, "height": 20},
                                            "text": {"content": "Hard", "fontSize": 16, "color": "rgba(255,255,255,1)"},
                                        },
                                    ],
                                },
                            ],
                        },
                        {
                            "id": "btn",
                            "name": "btn_start",
                            "kind": "pixel",
                            "role": "button_candidate",
                            "bounds": {"x": 90, "y": 245, "width": 160, "height": 45},
                            "asset": "assets/btn_start.png",
                            "nine_slice": {"border": {"left": 16, "right": 16, "top": 8, "bottom": 8}},
                            "opacity": 100,
                            "hasMask": True,
                            "blendMode": "multiply",
                        },
                        {
                            "id": "title",
                            "name": "TitleText",
                            "kind": "type",
                            "bounds": {"x": 80, "y": 20, "width": 240, "height": 40},
                            "text": {"content": "Start Game", "fontSize": 24, "color": "rgba(255,255,255,1)"},
                        },
                    ],
                }
            }
            (export_dir / "design.json").write_text(json.dumps(manifest), encoding="utf-8")

            schema = photoshop_export_schema()
            self.assertEqual(schema["schema"], "design-to-unity.photoshop-export")
            validation = validate_photoshop_export(str(export_dir))
            self.assertEqual(validation["status"], "valid_with_warnings")
            self.assertEqual(validation["counts"]["layer_count"], 27)
            self.assertEqual(validation["counts"]["asset_layer_count"], 7)
            self.assertEqual(validation["counts"]["missing_asset_count"], 0)
            self.assertTrue(any(warning["code"] == "complex_psd_feature" for warning in validation["warnings"]))

            packet = make_photoshop_export_packet(str(export_dir))
            self.assertEqual(packet["source"]["schema_source"], "photoshop-uxp")
            self.assertEqual(packet["source"]["provider"], "psd")
            self.assertEqual(packet["design"]["name"], "UXPPanel")
            self.assertIn("button_candidate", packet["semantic_map"])
            self.assertIn("slider_candidate", packet["semantic_map"])
            self.assertIn("toggle_candidate", packet["semantic_map"])
            self.assertIn("tab_group_candidate", packet["semantic_map"])
            self.assertIn("tab_candidate", packet["semantic_map"])
            self.assertIn("radio_group_candidate", packet["semantic_map"])
            self.assertIn("radio_candidate", packet["semantic_map"])
            self.assertIn("input_candidate", packet["semantic_map"])
            self.assertIn("dropdown_candidate", packet["semantic_map"])
            button = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "btn_start")
            self.assertEqual(button["source_metadata"]["source_provider"], "photoshop_export")
            self.assertEqual(button["style"]["opacity"], 1)
            self.assertIn("mask", button["source_metadata"]["unsupported_psd_features"])
            self.assertIn("blend_mode", button["source_metadata"]["unsupported_psd_features"])
            readiness = _unity_readiness_report(packet)
            readiness_codes = {item["code"] for item in readiness["review_items"]}
            self.assertIn("psd_mask_requires_review", readiness_codes)
            self.assertIn("psd_blend_mode_requires_review", readiness_codes)
            self.assertEqual(readiness["counts"]["component_candidates"]["tab_group"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["tab"], 2)
            self.assertEqual(readiness["counts"]["component_candidates"]["radio_group"], 1)
            self.assertEqual(readiness["counts"]["component_candidates"]["radio"], 2)
            plan = _unity_plan_response(packet, packet["packet_id"], include_reference=True)
            self.assertIn("photoshop-uxp", packet["source"]["schema_source"])
            self.assertEqual(plan["create_nodes"][0]["source_name"], "bg")

            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(packet, str(unity_root), prefab_name="UXP_Test")
            prefab_verification = verify_unity_prefab_yaml(
                str(unity_root),
                result["prefab_asset_path"],
                result["source_map_asset_path"],
            )
            source_map = json.loads(Path(result["source_map_path"]).read_text(encoding="utf-8"))
            prefab_text = Path(result["prefab_path"]).read_text(encoding="utf-8")
            self.assertEqual(prefab_verification["status"], "pass")
            self.assertEqual(prefab_verification["error_count"], 0)
            self.assertEqual(prefab_verification["counts"]["source_map"]["tmp_text_node_count"], 9)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["TextMeshProUGUI"], 9)
            self.assertGreaterEqual(result["button_node_count"], 1)
            self.assertGreaterEqual(result["slider_fill_bound_count"], 1)
            self.assertEqual(result["toggle_node_count"], 5)
            self.assertEqual(result["toggle_group_node_count"], 2)
            self.assertEqual(result["tab_node_count"], 2)
            self.assertEqual(result["radio_node_count"], 2)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["Toggle"], 5)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["ToggleGroup"], 2)
            self.assertEqual(result["input_field_node_count"], 1)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["TMP_InputField"], 1)
            self.assertEqual(result["dropdown_node_count"], 1)
            self.assertEqual(result["dropdown_template_bound_count"], 1)
            self.assertEqual(result["dropdown_caption_bound_count"], 1)
            self.assertEqual(result["dropdown_item_bound_count"], 1)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["TMP_Dropdown"], 1)
            self.assertGreaterEqual(result["tmp_text_node_count"], 1)
            mapped_button = next(node for node in source_map["nodes"] if node.get("name") == "btn_start")
            self.assertEqual(mapped_button["source_metadata"]["source_provider"], "photoshop_export")
            self.assertEqual(mapped_button["asset"]["nine_slice_hint"]["border"]["left"], 16)
            self.assertIn("m_Type: 1", prefab_text)
            button_meta = Path(result["sprite_dir"]) / f"{mapped_button['asset']['file_name']}.meta"
            button_meta_text = button_meta.read_text(encoding="utf-8")
            self.assertIn("spriteBorder: {x: 16.0, y: 8.0, z: 16.0, w: 8.0}", button_meta_text)
            button_meta.write_text(button_meta_text.replace("spriteBorder: {x: 16.0, y: 8.0, z: 16.0, w: 8.0}", "spriteBorder: {x: 0, y: 0, z: 0, w: 0}"), encoding="utf-8")
            border_verification = verify_unity_prefab_yaml(
                str(unity_root),
                result["prefab_asset_path"],
                result["source_map_asset_path"],
            )
            self.assertEqual(border_verification["status"], "fail")
            self.assertTrue(any(error["code"] == "sprite_border_mismatch" for error in border_verification["errors"]))
            button_meta.write_text(button_meta_text, encoding="utf-8")
            mapped_toggle = next(node for node in source_map["nodes"] if node.get("name") == "toggle_music_on")
            mapped_check = next(node for node in source_map["nodes"] if node.get("name") == "checkmark_on")
            self.assertTrue(mapped_toggle["unity_toggle_hint"]["value"])
            self.assertEqual(mapped_toggle["unity_toggle_hint"]["graphic_node_id"], mapped_check["node_id"])
            self.assertIn("toggle", mapped_toggle["component_file_ids"])
            self.assertIn(f"m_TargetGraphic: {{fileID: {mapped_toggle['component_file_ids']['image']}}}", prefab_text)
            self.assertIn(f"graphic: {{fileID: {mapped_check['component_file_ids']['image']}}}", prefab_text)
            mapped_tab_group = next(node for node in source_map["nodes"] if node.get("name") == "Tabs")
            mapped_tab_home = next(node for node in source_map["nodes"] if node.get("name") == "tab_home_selected")
            mapped_tab_shop = next(node for node in source_map["nodes"] if node.get("name") == "tab_shop")
            self.assertIn("toggle_group", mapped_tab_group["component_file_ids"])
            self.assertEqual(mapped_tab_group["unity_tab_group_hint"]["selected_tab_node_id"], mapped_tab_home["node_id"])
            self.assertEqual(mapped_tab_home["unity_tab_hint"]["group_node_id"], mapped_tab_group["node_id"])
            self.assertTrue(mapped_tab_home["unity_tab_hint"]["value"])
            self.assertFalse(mapped_tab_shop["unity_tab_hint"]["value"])
            self.assertIn(f"m_Group: {{fileID: {mapped_tab_group['component_file_ids']['toggle_group']}}}", prefab_text)
            mapped_radio_group = next(node for node in source_map["nodes"] if node.get("name") == "RadioGroup")
            mapped_radio_easy = next(node for node in source_map["nodes"] if node.get("name") == "radio_easy_selected")
            mapped_radio_hard = next(node for node in source_map["nodes"] if node.get("name") == "radio_hard")
            self.assertIn("toggle_group", mapped_radio_group["component_file_ids"])
            self.assertEqual(mapped_radio_group["unity_radio_group_hint"]["selected_radio_node_id"], mapped_radio_easy["node_id"])
            self.assertEqual(mapped_radio_easy["unity_radio_hint"]["group_node_id"], mapped_radio_group["node_id"])
            self.assertTrue(mapped_radio_easy["unity_radio_hint"]["value"])
            self.assertFalse(mapped_radio_hard["unity_radio_hint"]["value"])
            self.assertIn(f"m_Group: {{fileID: {mapped_radio_group['component_file_ids']['toggle_group']}}}", prefab_text)
            mapped_input = next(node for node in source_map["nodes"] if node.get("name") == "input_player_name")
            mapped_placeholder = next(node for node in source_map["nodes"] if node.get("name") == "placeholder_text")
            self.assertEqual(mapped_input["unity_input_hint"]["text_component_node_id"], mapped_placeholder["node_id"])
            self.assertIn("tmp_input_field", mapped_input["component_file_ids"])
            self.assertIn(f"m_TextComponent: {{fileID: {mapped_placeholder['component_file_ids']['tmp_text']}}}", prefab_text)
            mapped_dropdown = next(node for node in source_map["nodes"] if node.get("name") == "dropdown_difficulty")
            mapped_template = next(node for node in source_map["nodes"] if node.get("name") == "Dropdown Template")
            mapped_caption = next(node for node in source_map["nodes"] if node.get("name") == "Caption Text")
            mapped_item = next(node for node in source_map["nodes"] if node.get("name") == "Item Option A")
            self.assertEqual(mapped_dropdown["unity_dropdown_hint"]["template_node_id"], mapped_template["node_id"])
            self.assertEqual(mapped_dropdown["unity_dropdown_hint"]["caption_text_node_id"], mapped_caption["node_id"])
            self.assertEqual(mapped_dropdown["unity_dropdown_hint"]["item_text_node_id"], mapped_item["node_id"])
            self.assertIn("tmp_dropdown", mapped_dropdown["component_file_ids"])
            self.assertIn(f"m_Template: {{fileID: {mapped_template['component_file_ids']['rect']}}}", prefab_text)
            self.assertIn(f"m_CaptionText: {{fileID: {mapped_caption['component_file_ids']['tmp_text']}}}", prefab_text)
            self.assertIn(f"m_ItemText: {{fileID: {mapped_item['component_file_ids']['tmp_text']}}}", prefab_text)
            pass_diff = compare_packet_reference_to_screenshot(
                packet,
                str(export_dir / "preview.png"),
                output_dir=tmp_path / "uxp_visual_diffs",
            )
            self.assertEqual(pass_diff["status"], "pass")

            bad_manifest = {
                "document": {
                    "name": "BrokenExport",
                    "width": 400,
                    "height": 300,
                    "preview": "missing_preview.png",
                    "layers": [
                        {
                            "id": "missing_asset",
                            "name": "missing_asset",
                            "kind": "pixel",
                            "bounds": {"x": 0, "y": 0, "width": 10, "height": 10},
                            "asset": "assets/nope.png",
                        },
                        {
                            "id": "bad_bounds",
                            "name": "bad_bounds",
                            "kind": "pixel",
                            "bounds": {"x": 0, "y": 0, "width": 0, "height": 0},
                        },
                    ],
                }
            }
            bad_dir = tmp_path / "bad_export"
            bad_dir.mkdir()
            (bad_dir / "design.json").write_text(json.dumps(bad_manifest), encoding="utf-8")
            bad_validation = validate_photoshop_export(str(bad_dir))
            self.assertEqual(bad_validation["status"], "invalid")
            bad_codes = {error["code"] for error in bad_validation["errors"]}
            self.assertIn("preview_reference_not_found", bad_codes)
            self.assertIn("layer_asset_not_found", bad_codes)
            self.assertIn("missing_layer_bounds", bad_codes)

    def test_photoshop_export_scroll_content_keeps_single_scroll_area(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_dir = tmp_path / "uxp_scroll"
            assets_dir = export_dir / "assets"
            assets_dir.mkdir(parents=True)
            _save_image(export_dir / "preview.png", (320, 240), (20, 30, 40, 255))
            for index in range(1, 5):
                _save_image(assets_dir / f"item_{index}.png", (240, 40), (40 + index * 20, 80, 120, 255))
            _save_image(assets_dir / "scrollbar_handle.png", (12, 48), (190, 190, 190, 255))
            manifest = {
                "document": {
                    "name": "ScrollPanel",
                    "width": 320,
                    "height": 240,
                    "preview": "preview.png",
                    "layers": [
                        {
                            "id": "scroll",
                            "name": "ScrollView",
                            "kind": "group",
                            "bounds": {"x": 40, "y": 30, "width": 240, "height": 120},
                            "layers": [
                                {
                                    "id": "viewport",
                                    "name": "Viewport",
                                    "kind": "group",
                                    "bounds": {"x": 40, "y": 30, "width": 240, "height": 120},
                                    "layers": [
                                        {
                                            "id": "content",
                                            "name": "Content",
                                            "kind": "group",
                                            "bounds": {"x": 40, "y": 30, "width": 240, "height": 190},
                                            "layers": [
                                                {
                                                    "id": f"item_{index}",
                                                    "name": f"Item_{index:02d}",
                                                    "kind": "pixel",
                                                    "bounds": {"x": 40, "y": 30 + (index - 1) * 48, "width": 240, "height": 40},
                                                    "asset": f"assets/item_{index}.png",
                                                }
                                                for index in range(1, 5)
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "id": "scrollbar_vertical",
                                    "name": "Vertical Scrollbar",
                                    "kind": "group",
                                    "bounds": {"x": 284, "y": 30, "width": 14, "height": 120},
                                    "layers": [
                                        {
                                            "id": "scrollbar_handle",
                                            "name": "Scrollbar Handle",
                                            "kind": "pixel",
                                            "bounds": {"x": 285, "y": 42, "width": 12, "height": 48},
                                            "asset": "assets/scrollbar_handle.png",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            }
            (export_dir / "design.json").write_text(json.dumps(manifest), encoding="utf-8")

            packet = make_photoshop_export_packet(str(export_dir))
            nodes = {node["name"]: node for node in _walk_packet_nodes(packet)}
            self.assertEqual(packet["semantic_map"]["scroll_area_candidate"], [nodes["ScrollView"]["id"]])
            self.assertEqual(nodes["ScrollView"]["unity_scroll_hint"]["content_node_id"], nodes["Content"]["id"])
            self.assertEqual(nodes["ScrollView"]["unity_scroll_hint"]["vertical_scrollbar_node_id"], nodes["Vertical Scrollbar"]["id"])
            self.assertEqual(nodes["Content"]["semantic_type"], "scroll_content_candidate")
            self.assertNotIn("unity_scroll_hint", nodes["Content"])
            self.assertEqual(nodes["Content"]["unity_layout_hint"]["component"], "VerticalLayoutGroup")
            self.assertEqual(nodes["Vertical Scrollbar"]["semantic_type"], "scrollbar_candidate")
            self.assertEqual(nodes["Vertical Scrollbar"]["unity_scrollbar_hint"]["handle_node_id"], nodes["Scrollbar Handle"]["id"])
            self.assertEqual(nodes["Item_01"]["semantic_type"], "list_item_candidate")
            self.assertNotIn("unity_scroll_hint", nodes["Item_01"])

            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(packet, str(unity_root), prefab_name="UXP_Scroll_Test")
            verification = verify_unity_prefab_yaml(str(unity_root), result["prefab_asset_path"], result["source_map_asset_path"])
            self.assertEqual(result["scroll_rect_node_count"], 1)
            self.assertEqual(result["scrollbar_node_count"], 1)
            self.assertEqual(result["scrollbar_handle_bound_count"], 1)
            self.assertEqual(result["rect_mask_2d_node_count"], 1)
            self.assertEqual(result["vertical_layout_group_node_count"], 1)
            self.assertEqual(verification["status"], "pass")

    def test_photoshop_export_mask_candidate_writes_rect_mask(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_dir = tmp_path / "uxp_mask"
            assets_dir = export_dir / "assets"
            assets_dir.mkdir(parents=True)
            _save_image(export_dir / "preview.png", (180, 120), (20, 30, 40, 255))
            _save_image(assets_dir / "avatar.png", (48, 48), (120, 160, 220, 255))
            manifest = {
                "document": {
                    "name": "MaskPanel",
                    "width": 180,
                    "height": 120,
                    "preview": "preview.png",
                    "layers": [
                        {
                            "id": "avatar_mask",
                            "name": "AvatarMask",
                            "kind": "group",
                            "role": "mask_candidate",
                            "bounds": {"x": 48, "y": 28, "width": 64, "height": 64},
                            "layers": [
                                {
                                    "id": "avatar",
                                    "name": "avatar_icon",
                                    "kind": "pixel",
                                    "bounds": {"x": 56, "y": 36, "width": 48, "height": 48},
                                    "asset": "assets/avatar.png",
                                }
                            ],
                        }
                    ],
                }
            }
            (export_dir / "design.json").write_text(json.dumps(manifest), encoding="utf-8")

            packet = make_photoshop_export_packet(str(export_dir))
            mask = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "AvatarMask")
            self.assertEqual(mask["semantic_type"], "mask_candidate")
            self.assertTrue(mask["unity_mask_hint"]["can_add_rect_mask_2d"])

            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(packet, str(unity_root), prefab_name="UXP_Mask_Test")
            verification = verify_unity_prefab_yaml(str(unity_root), result["prefab_asset_path"], result["source_map_asset_path"])
            source_map = json.loads(Path(result["source_map_path"]).read_text(encoding="utf-8"))
            mapped_mask = next(node for node in source_map["nodes"] if node.get("name") == "AvatarMask")
            self.assertEqual(result["rect_mask_2d_node_count"], 1)
            self.assertIn("rect_mask_2d", mapped_mask["component_file_ids"])
            self.assertEqual(mapped_mask["unity_mask_hint"]["recommended_unity_component"], "RectMask2D")
            self.assertEqual(verification["status"], "pass")

    def test_photoshop_export_repeated_items_write_layout_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_dir = tmp_path / "uxp_layout"
            export_dir.mkdir(parents=True)
            _save_image(export_dir / "preview.png", (320, 220), (20, 30, 40, 255))
            manifest = {
                "document": {
                    "name": "LayoutPanel",
                    "width": 320,
                    "height": 220,
                    "preview": "preview.png",
                    "layers": [
                        {
                            "id": "horizontal_content",
                            "name": "HorizontalContent",
                            "kind": "group",
                            "role": "scroll_content_candidate",
                            "bounds": {"x": 20, "y": 24, "width": 210, "height": 48},
                            "layers": [
                                {
                                    "id": f"chip_{index}",
                                    "name": f"Chip_{index}",
                                    "kind": "shape",
                                    "bounds": {"x": 20 + index * 70, "y": 24, "width": 54, "height": 40},
                                }
                                for index in range(3)
                            ],
                        },
                        {
                            "id": "grid_content",
                            "name": "GridContent",
                            "kind": "group",
                            "role": "scroll_content_candidate",
                            "bounds": {"x": 20, "y": 92, "width": 150, "height": 104},
                            "layers": [
                                {
                                    "id": f"slot_{index}",
                                    "name": f"Slot_{index}",
                                    "kind": "shape",
                                    "bounds": {
                                        "x": 20 + (index % 2) * 70,
                                        "y": 92 + (index // 2) * 52,
                                        "width": 54,
                                        "height": 40,
                                    },
                                }
                                for index in range(4)
                            ],
                        },
                    ],
                }
            }
            (export_dir / "design.json").write_text(json.dumps(manifest), encoding="utf-8")

            packet = make_photoshop_export_packet(str(export_dir))
            nodes = {node["name"]: node for node in _walk_packet_nodes(packet)}
            self.assertEqual(nodes["HorizontalContent"]["unity_layout_hint"]["component"], "HorizontalLayoutGroup")
            self.assertEqual(nodes["GridContent"]["unity_layout_hint"]["component"], "GridLayoutGroup")
            self.assertEqual(nodes["GridContent"]["unity_layout_hint"]["constraint_count"], 2)

            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(packet, str(unity_root), prefab_name="UXP_Layout_Test")
            verification = verify_unity_prefab_yaml(str(unity_root), result["prefab_asset_path"], result["source_map_asset_path"])
            source_map = json.loads(Path(result["source_map_path"]).read_text(encoding="utf-8"))
            mapped_horizontal = next(node for node in source_map["nodes"] if node.get("name") == "HorizontalContent")
            mapped_grid = next(node for node in source_map["nodes"] if node.get("name") == "GridContent")
            self.assertEqual(result["horizontal_layout_group_node_count"], 1)
            self.assertEqual(result["grid_layout_group_node_count"], 1)
            self.assertIn("horizontal_layout_group", mapped_horizontal["component_file_ids"])
            self.assertIn("grid_layout_group", mapped_grid["component_file_ids"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["HorizontalLayoutGroup"], 1)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["GridLayoutGroup"], 1)
            self.assertEqual(verification["status"], "pass")

    def test_photoshop_export_complex_text_writes_tmp_effects_and_rich_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_dir = tmp_path / "uxp_text"
            export_dir.mkdir(parents=True)
            _save_image(export_dir / "preview.png", (260, 120), (20, 30, 40, 255))
            manifest = {
                "document": {
                    "name": "TextPanel",
                    "width": 260,
                    "height": 120,
                    "preview": "preview.png",
                    "layers": [
                        {
                            "id": "headline",
                            "name": "Headline",
                            "kind": "type",
                            "bounds": {"x": 20, "y": 24, "width": 220, "height": 48},
                            "text": {
                                "content": "Gold VIP",
                                "fontFamily": "Inter-Bold",
                                "fontStyle": "Bold Italic",
                                "fontSize": 28,
                                "lineHeight": 34,
                                "letterSpacing": 1.5,
                                "color": "#FFE680",
                                "alignment": "center",
                                "tmpFontAssetGuid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                                "spans": [
                                    {"start": 0, "length": 4, "color": "#FFE680", "fontStyle": "Bold"},
                                    {"start": 5, "length": 3, "color": "#80D8FF", "fontStyle": "Italic", "fontSize": 24},
                                ],
                                "stroke": {"width": 2, "color": "#3A1600"},
                                "dropShadow": {"color": "rgba(0,0,0,0.65)", "offset": {"x": 2, "y": -3}},
                            },
                        },
                        {
                            "id": "mapped_label",
                            "name": "MappedLabel",
                            "kind": "type",
                            "bounds": {"x": 20, "y": 78, "width": 220, "height": 24},
                            "text": {
                                "content": "Mapped",
                                "fontFamily": "Inter-Bold",
                                "fontStyle": "Bold Italic",
                                "fontSize": 18,
                                "color": "#FFFFFF",
                            },
                        }
                    ],
                }
            }
            (export_dir / "design.json").write_text(json.dumps(manifest), encoding="utf-8")

            packet = make_photoshop_export_packet(str(export_dir))
            text_node = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "Headline")
            self.assertTrue(text_node["unity_text_hint"]["rich_text_enabled"])
            self.assertTrue(text_node["unity_text_hint"]["uses_outline_component"])
            self.assertTrue(text_node["unity_text_hint"]["uses_shadow_component"])
            self.assertEqual(text_node["text"]["font_hint"]["tmp_font_asset_guid"], "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")

            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(
                packet,
                str(unity_root),
                prefab_name="UXP_Text_Test",
                tmp_font_asset_map={"Inter-Bold Bold Italic": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
            )
            verification = verify_unity_prefab_yaml(str(unity_root), result["prefab_asset_path"], result["source_map_asset_path"])
            prefab_text = Path(result["prefab_path"]).read_text(encoding="utf-8")
            source_map = json.loads(Path(result["source_map_path"]).read_text(encoding="utf-8"))
            mapped_text = next(node for node in source_map["nodes"] if node.get("name") == "Headline")
            self.assertEqual(result["tmp_font_asset_map_count"], 1)
            self.assertEqual(result["outline_node_count"], 1)
            self.assertEqual(result["shadow_node_count"], 1)
            self.assertIn("outline", mapped_text["component_file_ids"])
            self.assertIn("shadow", mapped_text["component_file_ids"])
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["Outline"], 1)
            self.assertEqual(source_map["unity_import_manifest"]["expected_components"]["Shadow"], 1)
            self.assertIn("guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", prefab_text)
            self.assertIn("guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", prefab_text)
            self.assertIn("<color=#FFE680><b>Gold</b></color> ", prefab_text)
            self.assertIn("<color=#80D8FF><size=24.0><i>VIP</i></size></color>", prefab_text)
            self.assertIn("m_fontStyle: 3", prefab_text)
            self.assertIn("m_characterSpacing: 1.5", prefab_text)
            self.assertIn("guid: e19747de3f5aca642ab2be37e372fb86", prefab_text)
            self.assertIn("guid: cfabb0440166ab443bba8876756fdfa9", prefab_text)
            self.assertIn("m_EffectDistance: {x: 2.0, y: -2.0}", prefab_text)
            self.assertIn("m_EffectDistance: {x: 2.0, y: -3.0}", prefab_text)
            self.assertEqual(verification["status"], "pass")

    def test_unity_prefab_verifier_detects_broken_sprite_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_dir = tmp_path / "uxp_export"
            assets_dir = export_dir / "assets"
            assets_dir.mkdir(parents=True)
            _save_image(export_dir / "preview.png", (120, 80), (20, 30, 40, 255))
            _save_image(assets_dir / "bg.png", (120, 80), (20, 30, 40, 255))
            manifest = {
                "document": {
                    "name": "VerifierPanel",
                    "width": 120,
                    "height": 80,
                    "preview": "preview.png",
                    "layers": [
                        {
                            "id": "bg",
                            "name": "bg",
                            "kind": "pixel",
                            "bounds": {"x": 0, "y": 0, "width": 120, "height": 80},
                            "asset": "assets/bg.png",
                        }
                    ],
                }
            }
            (export_dir / "design.json").write_text(json.dumps(manifest), encoding="utf-8")
            packet = make_photoshop_export_packet(str(export_dir))
            unity_root = tmp_path / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)
            result = write_unity_prefab_yaml(packet, str(unity_root), prefab_name="Verifier_Test")
            verification = verify_unity_prefab_yaml(str(unity_root), result["prefab_asset_path"], result["source_map_asset_path"])
            self.assertEqual(verification["status"], "pass")

            source_map_path = Path(result["source_map_path"])
            source_map = json.loads(source_map_path.read_text(encoding="utf-8"))
            source_map["unity_import_manifest"]["expected_components"]["Image"] += 1
            source_map_path.write_text(json.dumps(source_map), encoding="utf-8")
            mismatched = verify_unity_prefab_yaml(str(unity_root), result["prefab_asset_path"], result["source_map_asset_path"])
            self.assertEqual(mismatched["status"], "fail")
            self.assertTrue(any(error["code"] == "unity_import_manifest_count_mismatch" for error in mismatched["errors"]))
            source_map["unity_import_manifest"]["expected_components"]["Image"] -= 1
            source_map_path.write_text(json.dumps(source_map), encoding="utf-8")

            first_sprite_meta = next((unity_root / result["sprite_asset_dir"]).glob("*.png.meta"))
            first_sprite_meta.write_text(first_sprite_meta.read_text(encoding="utf-8").replace("guid: ", "guid: 00000000000000000000000000000000 # "), encoding="utf-8")
            broken = verify_unity_prefab_yaml(str(unity_root), result["prefab_asset_path"], result["source_map_asset_path"])
            self.assertEqual(broken["status"], "fail")
            self.assertTrue(any(error["code"] == "sprite_meta_guid_mismatch" for error in broken["errors"]))

    def test_photoshop_export_rasterized_group_skips_children(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            export_dir = tmp_path / "uxp_rasterized_group"
            assets_dir = export_dir / "assets"
            assets_dir.mkdir(parents=True)
            _save_image(export_dir / "preview.png", (120, 80), (20, 30, 40, 255))
            _save_image(assets_dir / "complex_group.png", (80, 40), (80, 120, 200, 255))
            manifest = {
                "document": {
                    "name": "RasterizedGroup",
                    "width": 120,
                    "height": 80,
                    "preview": "preview.png",
                    "layers": [
                        {
                            "id": "group",
                            "name": "btn_complex_group",
                            "kind": "group",
                            "role": "button_candidate",
                            "rasterized": True,
                            "bounds": {"x": 20, "y": 20, "width": 80, "height": 40},
                            "asset": "assets/complex_group.png",
                            "hasLayerEffects": True,
                            "layers": [
                                {
                                    "id": "child_without_asset",
                                    "name": "child_without_asset",
                                    "kind": "pixel",
                                    "bounds": {"x": 20, "y": 20, "width": 10, "height": 10},
                                }
                            ],
                        }
                    ],
                }
            }
            (export_dir / "design.json").write_text(json.dumps(manifest), encoding="utf-8")

            validation = validate_photoshop_export(str(export_dir))
            self.assertEqual(validation["status"], "valid_with_warnings")
            self.assertEqual(validation["counts"]["layer_count"], 1)
            self.assertEqual(validation["counts"]["group_layer_count"], 1)
            self.assertEqual(validation["counts"]["asset_layer_count"], 1)
            self.assertFalse(any(warning["code"] == "image_layer_without_asset" for warning in validation["warnings"]))

            packet = make_photoshop_export_packet(str(export_dir))
            group = next(node for node in _walk_packet_nodes(packet) if node.get("name") == "btn_complex_group")
            self.assertEqual(group["type"], "image")
            self.assertEqual(group["semantic_type"], "button_candidate")
            self.assertTrue(group["asset_ref"])
            self.assertEqual(group["children"], [])
            self.assertTrue(group["source_metadata"]["rasterized_export"])


def _walk_packet_nodes(packet: dict) -> list[dict]:
    nodes = []

    def walk(node: dict) -> None:
        nodes.append(node)
        for child in node.get("children") or []:
            walk(child)

    for root in packet.get("nodes") or []:
        walk(root)
    return nodes


def _save_image(path: Path, size: tuple[int, int], color: tuple[int, int, int, int]) -> None:
    Image.new("RGBA", size, color).save(path)


class PhotoshopUxpTemplateTest(unittest.TestCase):
    def test_template_manifest_and_script_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        template_dir = root / "templates" / "photoshop-uxp-exporter"
        manifest = json.loads((template_dir / "manifest.json").read_text(encoding="utf-8"))
        index_js = (template_dir / "index.js").read_text(encoding="utf-8")
        sample = json.loads((template_dir / "sample-design.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["manifestVersion"], 5)
        self.assertEqual(manifest["main"], "index.html")
        self.assertEqual(manifest["host"]["app"], "PS")
        self.assertEqual(manifest["requiredPermissions"]["localFileSystem"], "request")
        self.assertEqual(sample["schema"], "design-to-unity.photoshop-export")
        self.assertIn("design-to-unity.photoshop-export", index_js)
        self.assertIn("saveAs.png", index_js)
        self.assertIn("rasterized", index_js)
        self.assertIn("batchPlay", index_js)


class UnityEditorValidatorTemplateTest(unittest.TestCase):
    def test_install_unity_editor_validator_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            unity_root = Path(tmp) / "UnityProject"
            (unity_root / "Assets").mkdir(parents=True)

            result = install_unity_editor_validator(str(unity_root))
            script_path = Path(result["script_path"])
            script_text = script_path.read_text(encoding="utf-8")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["script_asset_path"], "Assets/Editor/DesignToUnity/DesignToUnityPrefabValidator.cs")
            self.assertTrue(script_path.exists())
            self.assertIn("ValidateFromCommandLine", script_text)
            self.assertIn("CapturePrefabFromCommandLine", script_text)
            self.assertIn("CapturePrefab", script_text)
            self.assertIn("expected_components", script_text)
            self.assertIn("TextMeshProUGUI", script_text)
            self.assertIn("Toggle", script_text)
            self.assertIn("ToggleGroup", script_text)
            self.assertIn("toggle_target_graphic_unbound", script_text)
            self.assertIn("toggle_group_empty", script_text)
            self.assertIn("component_count_mismatch", script_text)
            self.assertIn("IsExpectedTransparentHitArea", script_text)
            self.assertIn("-d2uPrefab", result["command_line"]["arguments"])
            self.assertEqual(
                result["screenshot_command_line"]["execute_method"],
                "DesignToUnityPrefabValidator.CapturePrefabFromCommandLine",
            )
            self.assertIn("-d2uScreenshot", result["screenshot_command_line"]["arguments"])

            with self.assertRaises(FileExistsError):
                install_unity_editor_validator(str(unity_root), overwrite=False)


if __name__ == "__main__":
    unittest.main()

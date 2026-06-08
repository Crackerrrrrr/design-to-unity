from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import Settings


class PacketStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.data_dir / "packets"
        self.root.mkdir(parents=True, exist_ok=True)

    def packet_path(self, packet_id: str) -> Path:
        return self.root / f"{packet_id}.json"

    def save(self, packet: dict[str, Any]) -> Path:
        path = self.packet_path(packet["packet_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, packet_id: str) -> dict[str, Any]:
        path = self.packet_path(packet_id)
        if not path.exists():
            raise FileNotFoundError(f"Packet not found: {packet_id}")
        return json.loads(path.read_text(encoding="utf-8"))


def trim_node_tree(node: dict[str, Any], max_depth: int, include_style: bool, depth: int = 0) -> dict[str, Any]:
    keys = [
        "id",
        "parent_id",
        "name",
        "path",
        "type",
        "semantic_type",
        "semantic_candidates",
        "semantic_confidence",
        "requires_semantic_review",
        "z_index",
        "global_rect",
        "local_rect",
        "unity_rect_hint",
        "asset_ref",
    ]
    if include_style:
        keys.extend(["style", "text", "warnings"])
    result = {key: node.get(key) for key in keys if key in node and node.get(key) is not None}
    children = node.get("children") or []
    if depth < max_depth:
        result["children"] = [trim_node_tree(child, max_depth, include_style, depth + 1) for child in children]
    else:
        result["children_count"] = len(children)
    return result


def collect_nodes(node: dict[str, Any]) -> list[dict[str, Any]]:
    result = [node]
    for child in node.get("children") or []:
        result.extend(collect_nodes(child))
    return result

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any


class VisualDiffError(RuntimeError):
    pass


def compare_packet_reference_to_screenshot(
    packet: dict[str, Any],
    screenshot_path: str,
    output_dir: str | Path,
    max_mean_delta: float = 0.03,
    max_mismatch_ratio: float = 0.08,
    per_pixel_threshold: float = 0.08,
    resize_screenshot: bool = True,
    orientation: str = "auto",
) -> dict[str, Any]:
    try:
        from PIL import Image, ImageChops, ImageStat
    except ImportError as exc:  # pragma: no cover
        raise VisualDiffError("Visual diff requires Pillow.") from exc

    reference_asset = _reference_asset(packet)
    provider_label = _provider_label(packet)
    reference_path = Path(str(reference_asset.get("local_path") or "")).expanduser()
    screenshot = Path(screenshot_path).expanduser()
    if not reference_path.exists():
        raise FileNotFoundError(f"{provider_label} reference image not found: {reference_path}")
    if not screenshot.exists():
        raise FileNotFoundError(f"Unity screenshot not found: {screenshot}")

    reference_image = Image.open(reference_path).convert("RGBA")
    screenshot_image = Image.open(screenshot).convert("RGBA")
    reference_size = reference_image.size
    screenshot_size = screenshot_image.size
    warnings = []
    orientation = str(orientation or "auto").strip().lower()
    if orientation not in {"auto", "normal", "flip_y"}:
        raise ValueError("orientation must be one of: auto, normal, flip_y")

    if screenshot_image.size != reference_image.size:
        if not resize_screenshot:
            raise ValueError(
                f"Screenshot size {screenshot_image.size} does not match reference size {reference_image.size}."
            )
        screenshot_image = screenshot_image.resize(reference_image.size, Image.Resampling.LANCZOS)
        warnings.append(
            {
                "code": "screenshot_resized",
                "severity": "low",
                "message": f"Unity screenshot size differed from the {provider_label} reference and was resized before comparison.",
                "reference_size": {"width": reference_size[0], "height": reference_size[1]},
                "screenshot_size": {"width": screenshot_size[0], "height": screenshot_size[1]},
            }
        )

    candidates = []
    if orientation in {"auto", "normal"}:
        candidates.append(("normal", screenshot_image))
    if orientation in {"auto", "flip_y"}:
        candidates.append(("flip_y", screenshot_image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)))
    measured = [
        (name, _measure_diff(reference_image, image, per_pixel_threshold, ImageChops, ImageStat))
        for name, image in candidates
    ]
    used_orientation, chosen = min(
        measured,
        key=lambda item: (item[1]["mean_abs_delta"], item[1]["mismatch_ratio"], item[1]["rmse"]),
    )
    if orientation == "auto" and used_orientation != "normal":
        warnings.append(
            {
                "code": "screenshot_orientation_adjusted",
                "severity": "low",
                "message": "The visual diff auto-selected a vertically flipped screenshot because it matched the PSD reference better.",
                "used_orientation": used_orientation,
            }
        )

    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(packet, screenshot)
    diff_path = output_root / f"{stem}.diff.png"
    report_path = output_root / f"{stem}.visual-diff.json"
    heatmap = chosen["diff"].point(lambda value: min(255, value * 4))
    heatmap.save(diff_path, "PNG")

    passed = chosen["mean_abs_delta"] <= max_mean_delta and chosen["mismatch_ratio"] <= max_mismatch_ratio
    review_reason = None if passed else _needs_review_reason(packet, reference_asset)
    if review_reason:
        warnings.append(
            {
                "code": "visual_diff_needs_human_review",
                "severity": "medium",
                "message": review_reason,
            }
        )
    result = {
        "status": "pass" if passed else "needs_review" if review_reason else "fail",
        "status_reason": "within_thresholds" if passed else review_reason or "outside_thresholds",
        "packet_id": packet.get("packet_id"),
        "source": packet.get("source"),
        "design": packet.get("design"),
        "reference_image_path": str(reference_path),
        "screenshot_path": str(screenshot.resolve()),
        "diff_image_path": str(diff_path.resolve()),
        "report_path": str(report_path.resolve()),
        "sizes": {
            "reference": {"width": reference_size[0], "height": reference_size[1]},
            "screenshot_original": {"width": screenshot_size[0], "height": screenshot_size[1]},
            "compared": {"width": reference_size[0], "height": reference_size[1]},
        },
        "thresholds": {
            "max_mean_delta": max_mean_delta,
            "max_mismatch_ratio": max_mismatch_ratio,
            "per_pixel_threshold": per_pixel_threshold,
        },
        "orientation": {
            "requested": orientation,
            "used": used_orientation,
            "candidates": [
                _rounded_metrics(name, metrics)
                for name, metrics in measured
            ],
        },
        "metrics": {
            "mean_abs_delta": round(chosen["mean_abs_delta"], 6),
            "rmse": round(chosen["rmse"], 6),
            "max_delta": round(chosen["max_delta"], 6),
            "mismatch_pixel_count": chosen["mismatch_pixel_count"],
            "total_pixel_count": chosen["total_pixel_count"],
            "mismatch_ratio": round(chosen["mismatch_ratio"], 6),
        },
        "warnings": warnings,
        "usage_note": f"Use this after Unity MCP captures the generated prefab or scene. Fail does not always mean the prefab is unusable; inspect the diff image and review {provider_label} warnings.",
    }
    report_path.write_text(_json_dumps(result), encoding="utf-8")
    return result


def _measure_diff(reference_image: Any, screenshot_image: Any, per_pixel_threshold: float, image_chops: Any, image_stat: Any) -> dict[str, Any]:
    diff = image_chops.difference(reference_image, screenshot_image)
    stat = image_stat.Stat(diff)
    means = [value / 255 for value in stat.mean]
    mean_abs_delta = sum(means) / len(means)
    width, height = reference_image.size
    squared = sum(stat.sum2) / (255 * 255 * width * height * len(stat.sum2))
    rmse = math.sqrt(squared)
    extrema = diff.getextrema()
    max_delta = max(channel_max for _, channel_max in extrema) / 255
    threshold = max(0, min(1, float(per_pixel_threshold))) * 255
    diff_channels = diff.split()
    max_channel_diff = diff_channels[0]
    for channel in diff_channels[1:]:
        max_channel_diff = image_chops.lighter(max_channel_diff, channel)
    mismatch_mask = max_channel_diff.point(lambda value: 255 if value > threshold else 0, mode="1")
    mismatch_bbox = mismatch_mask.getbbox()
    mismatch_count = 0
    if mismatch_bbox:
        mismatch_count = int(image_stat.Stat(mismatch_mask.convert("L")).sum[0] / 255)
    total_pixels = width * height
    mismatch_ratio = mismatch_count / total_pixels if total_pixels else 0
    return {
        "diff": diff,
        "mean_abs_delta": mean_abs_delta,
        "rmse": rmse,
        "max_delta": max_delta,
        "mismatch_pixel_count": mismatch_count,
        "total_pixel_count": total_pixels,
        "mismatch_ratio": mismatch_ratio,
    }


def _rounded_metrics(name: str, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "orientation": name,
        "mean_abs_delta": round(metrics["mean_abs_delta"], 6),
        "rmse": round(metrics["rmse"], 6),
        "max_delta": round(metrics["max_delta"], 6),
        "mismatch_pixel_count": metrics["mismatch_pixel_count"],
        "mismatch_ratio": round(metrics["mismatch_ratio"], 6),
    }


def _reference_asset(packet: dict[str, Any]) -> dict[str, Any]:
    reference_asset_ref = (packet.get("design") or {}).get("reference_asset_ref")
    assets = {asset.get("id"): asset for asset in packet.get("assets") or [] if asset.get("id")}
    if reference_asset_ref and reference_asset_ref in assets:
        return assets[reference_asset_ref]
    for asset in packet.get("assets") or []:
        if asset.get("usage") == "design_reference":
            return asset
    raise VisualDiffError(f"Packet has no {_provider_label(packet)} reference image. Prepare the packet with a preview/reference asset before running visual diff.")


def _provider_label(packet: dict[str, Any]) -> str:
    provider = str((packet.get("source") or {}).get("provider") or "design").strip().lower()
    if provider == "psd":
        return "PSD"
    if provider == "figma":
        return "Figma"
    if provider == "lanhu":
        return "Lanhu"
    if provider == "photoshop_export":
        return "Photoshop export"
    return "design"


def _needs_review_reason(packet: dict[str, Any], reference_asset: dict[str, Any]) -> str | None:
    warning_codes = {str(warning.get("code") or "") for warning in packet.get("warnings") or []}
    complex_codes = {
        "psd_mask_requires_review",
        "psd_clipping_mask_requires_review",
        "psd_blend_mode_requires_review",
        "psd_smart_object_rasterized",
        "psd_adjustment_layer_requires_review",
        "psd_layer_effect_requires_review",
    }
    if "psd_reference_composed_from_exported_layers" in warning_codes and warning_codes.intersection(complex_codes):
        return (
            "Visual diff is outside thresholds, but the packet reference was composed from exported layer PNGs "
            "for a complex PSD. Use a Photoshop/UXP-rendered preview or flattened_reference_overlay prefab mode for strict QA."
        )
    if reference_asset.get("source_node_id") is None and "psd_reference_export_failed" in warning_codes:
        return (
            "Visual diff is outside thresholds and the PSD reference export was best-effort. "
            "Use a Photoshop-rendered reference image before treating this as a prefab failure."
        )
    return None


def _safe_stem(packet: dict[str, Any], screenshot: Path) -> str:
    packet_id = str(packet.get("packet_id") or "packet")
    raw = f"{packet_id}:{screenshot.resolve()}:{screenshot.stat().st_mtime_ns}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    screenshot_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in screenshot.stem)[:40] or "screenshot"
    return f"{packet_id[:8]}_{screenshot_stem}_{digest}"


def _json_dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)

from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any


DEFAULT_VALIDATOR_ASSET_PATH = "Assets/Editor/DesignToUnity/DesignToUnityPrefabValidator.cs"


def install_unity_editor_validator(
    unity_project_path: str,
    asset_path: str = DEFAULT_VALIDATOR_ASSET_PATH,
    overwrite: bool = True,
) -> dict[str, Any]:
    project_root = Path(unity_project_path).expanduser().resolve()
    assets_dir = project_root / "Assets"
    if not assets_dir.is_dir():
        raise FileNotFoundError(f"Unity project Assets folder not found: {assets_dir}")

    asset_path = asset_path.replace("\\", "/").strip("/")
    if not asset_path.startswith("Assets/"):
        raise ValueError("asset_path must start with Assets/")
    if not asset_path.endswith(".cs"):
        raise ValueError("asset_path must end with .cs")

    target_path = project_root / asset_path
    if target_path.exists() and not overwrite:
        raise FileExistsError(f"Unity validator script already exists: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    template = (
        resources.files("design_handoff_mcp")
        .joinpath("templates/unity_editor/DesignToUnityPrefabValidator.cs")
        .read_text(encoding="utf-8")
    )
    target_path.write_text(template, encoding="utf-8")

    return {
        "status": "success",
        "unity_project_path": str(project_root),
        "script_asset_path": asset_path,
        "script_path": str(target_path),
        "overwrite": overwrite,
        "menu_path": "Tools/Design To Unity/Validate Selected Prefab",
        "command_line": {
            "execute_method": "DesignToUnityPrefabValidator.ValidateFromCommandLine",
            "arguments": [
                "-d2uPrefab",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.prefab",
                "-d2uSourceMap",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.design-to-unity.json",
                "-d2uReport",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.unity-import-report.json",
            ],
        },
        "screenshot_command_line": {
            "execute_method": "DesignToUnityPrefabValidator.CapturePrefabFromCommandLine",
            "arguments": [
                "-d2uPrefab",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.prefab",
                "-d2uScreenshot",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.unity-screenshot.png",
                "-d2uWidth",
                "<optional width>",
                "-d2uHeight",
                "<optional height>",
            ],
        },
        "next_steps": [
            "Refresh or open the Unity project so the Editor script compiles.",
            "Select a generated prefab and run Tools/Design To Unity/Validate Selected Prefab.",
            "Or run Unity in batchmode with -executeMethod DesignToUnityPrefabValidator.ValidateFromCommandLine and the -d2uPrefab/-d2uSourceMap arguments.",
            "Optionally run DesignToUnityPrefabValidator.CapturePrefabFromCommandLine to write a PNG for psd_design_compare_unity_screenshot.",
            "Use the generated unity-import-report JSON before final visual diff QA.",
        ],
    }

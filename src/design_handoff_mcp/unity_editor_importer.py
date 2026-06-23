from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any


DEFAULT_IMPORTER_ASSET_PATH = "Assets/Editor/DesignToUnity/DesignToUnityPrefabImporter.cs"


def install_unity_editor_importer(
    unity_project_path: str,
    asset_path: str = DEFAULT_IMPORTER_ASSET_PATH,
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
        raise FileExistsError(f"Unity importer script already exists: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    template = (
        resources.files("design_handoff_mcp")
        .joinpath("templates/unity_editor/DesignToUnityPrefabImporter.cs")
        .read_text(encoding="utf-8")
    )
    target_path.write_text(template, encoding="utf-8")

    return {
        "status": "success",
        "unity_project_path": str(project_root),
        "script_asset_path": asset_path,
        "script_path": str(target_path),
        "overwrite": overwrite,
        "menu_path": "Tools/Design To Unity/Import Prefab From Source Map",
        "command_line": {
            "execute_method": "DesignToUnityPrefabImporter.ImportFromCommandLine",
            "arguments": [
                "-d2uSourceMap",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.design-to-unity.json",
                "-d2uOutputPrefab",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.editor-imported.prefab",
                "-d2uIncremental",
                "true",
                "-d2uReport",
                "Assets/DesignToUnity/<packet>/Prefabs/<name>.import-report.json",
            ],
        },
        "batch_command_line": {
            "execute_method": "DesignToUnityPrefabImporter.ImportFromCommandLine",
            "arguments": [
                "-d2uSourceMaps",
                "Assets/DesignToUnity/<packet-a>/Prefabs/<a>.design-to-unity.json;Assets/DesignToUnity/<packet-b>/Prefabs/<b>.design-to-unity.json",
                "-d2uOutputDir",
                "Assets/DesignToUnity/ImportedPrefabs",
                "-d2uIncremental",
                "true",
                "-d2uBatchReport",
                "Assets/DesignToUnity/import-batch-report.json",
            ],
            "alternatives": [
                "Use -d2uOutputPrefabs with a semicolon-separated prefab list when each source map needs an explicit output path.",
                "Use -d2uSourceMapDir Assets/DesignToUnity to import every *.design-to-unity.json source map under a folder.",
            ],
        },
        "next_steps": [
            "Refresh or open the Unity project so the Editor script compiles.",
            "Run Tools/Design To Unity/Import Prefab From Source Map or Unity batchmode -executeMethod DesignToUnityPrefabImporter.ImportFromCommandLine.",
            "The importer creates UGUI nodes from the source map, saves reusable prefab definitions, creates prefab variant assets from prefab_variant_groups, and instantiates reused nodes.",
            "For page/component-library batches, pass -d2uSourceMaps or -d2uSourceMapDir plus -d2uOutputDir; inspect the generated batch report.",
            "Pass -d2uIncremental true to update an existing prefab by source-map unity_path while preserving user-owned fields, custom components, event bindings, and extra children by default.",
            "Read the generated *.import-report.json file to inspect created, updated, preserved, protected, reusable definition, reused instance, and prefab variant counts.",
            "Use the validator and visual diff after importer output is generated.",
        ],
    }

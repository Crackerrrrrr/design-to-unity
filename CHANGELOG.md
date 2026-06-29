# Changelog

All notable changes to Design to Unity will be documented in this file.

The format follows Keep a Changelog, and this project uses semantic versioning.

## [0.1.0] - 2026-06-29

### Added

- Initial public MCP server for converting design sources into Unity-ready handoff packets and prefabs.
- Lanhu project and design-page extraction, including slices, node tree, asset manifest, Unity plan, handoff profile, static prefab YAML writing, and prefab YAML verification.
- Figma REST, snapshot, and plugin-export workflows, including page/frame/component listing, batch packet preparation, asset export, component usage reporting, readiness reports, visual diff, static prefab YAML writing, and Unity prefab conversion.
- PSD / PSB and Photoshop UXP export workflows, including packet preparation, schema validation, asset manifests, readiness reports, visual diff, static prefab YAML writing, and Unity prefab conversion.
- Unity Editor importer and validator templates for source-map based UGUI prefab import, incremental updates, reusable prefab definitions, nested instances, and prefab variants.
- Unified Design Implementation Packet metadata for geometry, text, assets, render strategy, source semantics, reusable prefabs, variant groups, 9-slice hints, and TMP font mapping.

### Packaging

- Added MCP Registry metadata through `server.json`.
- Added AI-readable project index through `llms.txt`.
- Added MIT license and release changelog.

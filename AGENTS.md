# Agent Guidelines & Repository Architecture: College Debt SMP Resource Pack

This document provides context, architectural details, and operational conventions for AI coding assistants working in this repository.

## Repository Overview

This repository maintains the server-wide Minecraft Resource Pack (`resource-pack/`) and Datapack (`data-pack/`) for the **College Debt SMP**. It includes custom assets from third-party datapacks (such as *Dungeons and Taverns*, *Portfolio*, and *Vanilla+*) as well as a fully automated custom painting submission system powered by GitHub Actions and Python scripts.

## Core Architecture & Directory Layout

- **`resource-pack/`**: Contains Minecraft textures, models, language files, shaders, and painting textures (`assets/minecraft/textures/painting/`).
- **`data-pack/`**: Contains datapack definitions and painting variant JSONs:
  - `data/cdsmp/painting_variant/*.json`: Individual painting definitions under the `cdsmp` namespace.
  - `data/minecraft/tags/painting_variant/placeable.json`: List of all placeable paintings.
- **`.submission_state/`**: Stores JSON state files (`<issue_number>.json`) tracking uploaded paintings per GitHub Issue submission for undo/resubmit capabilities.
- **`scripts/`**: Python automation scripts:
  - `process_paintings.py`: Validates uploaded `.zip` files from [mc-tools.net](https://mc-tools.net/paintings), extracts textures, parses dimensions, generates datapack variant JSONs and resource pack assets, updates placeable tag files, and tracks state.
  - `handle_comment.py`: Parses commands from issue comment threads (`help`, `list`, `rename`, `author`, `undo`, zip re-submissions).
  - `check_pack_format.py`: Verifies pack format compliance across updates.
- **`.github/workflows/`**:
  - `process-paintings.yml`: Automated processing when an issue with label `painting-submission` is created or updated with a `.zip` file.
  - `handle-comments.yml`: Handles user commands posted in issue comments (works on both open and closed issues).
  - `release.yml`: Creates GitHub releases with `resource-pack.zip` and `datapack.zip`.
  - `auto-bump-format.yml`: Scheduled workflow to check pack format compatibility.

## MCTools Export & Painting Processing Rules

When modifying or debugging `scripts/process_paintings.py` or painting processing:
1. **JSON Parsing (`mctools.json`)**:
   - Primary array key: `items` (fallback to `paintings` for legacy exports).
   - In-game ID: Derived from `name` (sanitized slug format).
   - Dimensions: Must be parsed from `sizeLabel` (e.g., `"4x2"` or `"4×2"` in blocks). **Do not use `sizeW` and `sizeH` for block dimensions**, as those represent pixel dimensions which change when users scale texture resolution.
   - Texture mapping: Locate `{slotName}.png` (or `{name}.png`) inside the zip and extract it to `resource-pack/assets/minecraft/textures/painting/{name}.png`.
2. **Datapack Registration**:
   - Variant JSON format: `data/cdsmp/painting_variant/{name}.json` referencing `cdsmp:{name}` texture assets and width/height dimensions.
   - Tag Registration: Add `cdsmp:{name}` to `data/minecraft/tags/painting_variant/placeable.json`.

## Issue Comment Commands (`scripts/handle_comment.py`)

- **`help`**: Replies with command usage documentation.
- **`list`**: Lists all paintings submitted in the current issue thread with their slug, title, author, and dimensions.
- **`rename [<slug>] <new_title>`**: Changes the painting's display title in the stonecutter UI without altering the `cdsmp:` ID.
- **`author [<slug>] <new_author>`**: Changes the author attribution in the tooltip.
- **`undo`**: Completely reverts and cleans up all generated datapack entries, textures, and state for the issue.
- **Zip re-upload**: Reverts old submission state and processes the newly attached `.zip` file.

## Development & Verification Guidelines

- **Dependencies**: Use standard Python 3 library modules only (`zipfile`, `json`, `re`, `os`, `sys`, `pathlib`, `urllib`).
- **Syntax Verification**: Run `python3 -m py_compile scripts/*.py` after editing Python files.
- **Release Workflow**: The release workflow (`release.yml`) builds zip files directly without third-party optimizer actions to avoid texture dimension limits (e.g. animated sprite sheets).

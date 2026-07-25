import os
import re
import sys
import json
import zipfile
import shutil
import urllib.request
import subprocess

ISSUE_NUMBER = os.environ.get("ISSUE_NUMBER")
REPO = os.environ.get("GITHUB_REPOSITORY")

MAX_ZIP_SIZE_MB = 50
MAX_ZIP_SIZE_BYTES = MAX_ZIP_SIZE_MB * 1024 * 1024


def post_comment(message):
    print(f"Posting comment: {message}")
    subprocess.run(["gh", "issue", "comment", ISSUE_NUMBER, "--repo", REPO, "--body", message])


def sanitize_name(name):
    """Sanitize a painting name to a valid Minecraft resource identifier (a-z, 0-9, _, -, .)."""
    name = name.lower().replace(" ", "_")
    name = re.sub(r"[^a-z0-9_\-.]", "", name)
    name = name.strip("_-.")
    return name if name else "unnamed"


def find_in_zip(file_list, filename_suffix_lower):
    """Case-insensitive search for a filename suffix within a zip's file list."""
    for f in file_list:
        if f.lower().endswith(filename_suffix_lower):
            return f
    return None


def main():
    if not ISSUE_NUMBER or not REPO:
        print("Missing ISSUE_NUMBER or REPO environment variables.")
        sys.exit(1)

    # Read issue body to find attachments
    result = subprocess.run(
        ["gh", "issue", "view", ISSUE_NUMBER, "--repo", REPO, "--json", "body"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Failed to fetch issue body.")
        sys.exit(1)

    issue_data = json.loads(result.stdout)
    # body can be None if the user opened an issue with no description text
    body = issue_data.get("body") or ""

    # Find zip URLs attached to the issue.
    # GitHub attachment URLs appear as: [filename.zip](https://github.com/user-attachments/...)
    zip_links = re.findall(
        r'\[.*?\.zip\]\((https://github\.com/(?:[^/]+)/(?:[^/]+)/files/[^\)]+|https://github\.com/user-attachments/[^\)]+)\)',
        body
    )

    if not zip_links:
        print("No zip files found in the issue body.")
        post_comment(
            "I couldn't find any `.zip` file attached to this issue. "
            "Please ensure you upload the zip file directly into the issue description."
        )
        sys.exit(1)

    extracted_any_valid = False
    added_variants = []

    os.makedirs("temp_downloads", exist_ok=True)

    try:
        for idx, url in enumerate(zip_links):
            zip_path = f"temp_downloads/upload_{idx}.zip"
            print(f"Downloading {url}...")

            # Bug 1 fix: wrap download in try/except so a failed download skips cleanly
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req) as response:
                    # Bug 6 fix: reject files over MAX_ZIP_SIZE_MB before and during download
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_ZIP_SIZE_BYTES:
                        print(f"Zip exceeds {MAX_ZIP_SIZE_MB} MB size limit. Skipping.")
                        continue

                    downloaded = 0
                    size_exceeded = False
                    with open(zip_path, "wb") as out_file:
                        while True:
                            chunk = response.read(65536)
                            if not chunk:
                                break
                            downloaded += len(chunk)
                            if downloaded > MAX_ZIP_SIZE_BYTES:
                                print(f"Zip exceeded {MAX_ZIP_SIZE_MB} MB size limit during download. Skipping.")
                                size_exceeded = True
                                break
                            out_file.write(chunk)

                    if size_exceeded:
                        continue

            except Exception as e:
                print(f"Failed to download {url}: {e}")
                continue

            try:
                with zipfile.ZipFile(zip_path, "r") as z:
                    file_list = z.namelist()

                    # Bug 3 fix: case-insensitive search for mctools.json
                    mctools_path = find_in_zip(file_list, "mctools.json")
                    if not mctools_path:
                        print(f"mctools.json missing in zip from {url}")
                        continue

                    with z.open(mctools_path) as f:
                        try:
                            mctools_data = json.load(f)
                        except json.JSONDecodeError as e:
                            print(f"Failed to parse mctools.json: {e}")
                            continue

                    paintings = mctools_data.get("paintings", [])

                    if not paintings:
                        print("No paintings entries found in mctools.json")
                        continue

                    for p in paintings:
                        # Bug 5 fix: use sanitize_name for valid resource identifiers
                        original_name = sanitize_name(p.get("name", "unnamed"))
                        width = p.get("width", 1)
                        height = p.get("height", 1)

                        # Bug 3 fix: case-insensitive PNG search
                        png_path = find_in_zip(file_list, f"{original_name}.png")
                        if not png_path:
                            print(f"Could not find texture PNG for '{original_name}'")
                            continue

                        # Target locations
                        target_texture_dir = "resource-pack/assets/cdsmp/textures/painting"
                        os.makedirs(target_texture_dir, exist_ok=True)

                        target_data_dir = "data-pack/data/cdsmp/painting_variant"
                        os.makedirs(target_data_dir, exist_ok=True)

                        # Bug 4 fix: collision detection checks BOTH .png and .json
                        final_name = original_name
                        counter = 1
                        while (
                            os.path.exists(os.path.join(target_texture_dir, f"{final_name}.png")) or
                            os.path.exists(os.path.join(target_data_dir, f"{final_name}.json"))
                        ):
                            final_name = f"{original_name}-{counter}"
                            counter += 1

                        target_png_file = os.path.join(target_texture_dir, f"{final_name}.png")

                        # Extract PNG
                        with z.open(png_path) as source_png, open(target_png_file, "wb") as target_png:
                            shutil.copyfileobj(source_png, target_png)

                        # Generate datapack painting_variant JSON
                        variant_json = {
                            "asset_id": f"cdsmp:{final_name}",
                            "width": width,
                            "height": height
                        }

                        target_json_file = os.path.join(target_data_dir, f"{final_name}.json")
                        with open(target_json_file, "w") as f:
                            json.dump(variant_json, f, indent=2)

                        print(f"Processed painting: {final_name}")
                        extracted_any_valid = True
                        added_variants.append(f"cdsmp:{final_name}")

            except zipfile.BadZipFile:
                print(f"Bad zip file from {url}")
                continue

    finally:
        # Bug 1 fix: always clean up temp dir, even if an exception occurred
        shutil.rmtree("temp_downloads", ignore_errors=True)

    # Update placeable.json tag, appending only new entries
    if added_variants:
        tag_file = "data-pack/data/minecraft/tags/painting_variant/placeable.json"
        os.makedirs(os.path.dirname(tag_file), exist_ok=True)

        if os.path.exists(tag_file):
            with open(tag_file, "r") as f:
                try:
                    tag_data = json.load(f)
                except json.JSONDecodeError:
                    tag_data = {"replace": False, "values": []}
        else:
            tag_data = {"replace": False, "values": []}

        # Bug 4 fix: ensure values key exists regardless of what was in the file
        existing_values = tag_data.setdefault("values", [])
        for variant in added_variants:
            if variant not in existing_values:
                existing_values.append(variant)

        with open(tag_file, "w") as f:
            json.dump(tag_data, f, indent=2)

    if not extracted_any_valid:
        post_comment(
            "The uploaded zip file(s) did not appear to be a valid MCTools painting pack. "
            "Please make sure the zip contains a `mctools.json` file and valid painting PNGs, then try again."
        )
        sys.exit(1)

    print("Successfully processed paintings.")


if __name__ == "__main__":
    main()

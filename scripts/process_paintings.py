import os
import re
import sys
import json
import zipfile
import shutil
import urllib.request
import subprocess

MAX_ZIP_SIZE_MB = 50
MAX_ZIP_SIZE_BYTES = MAX_ZIP_SIZE_MB * 1024 * 1024

def post_comment(issue_number, repo, message):
    print(f"Posting comment: {message}")
    subprocess.run(["gh", "issue", "comment", issue_number, "--repo", repo, "--body", message])

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

def extract_zip_links(body):
    """Extract all zip links from markdown body."""
    return re.findall(
        r'\[.*?\.zip\]\((https://github\.com/(?:[^/]+)/(?:[^/]+)/files/[^\)]+|https://github\.com/user-attachments/[^\)]+)\)',
        body
    )

def process_zips(zip_links, issue_number, repo):
    """Downloads zips, extracts them, handles state, and returns state dict or None on failure."""
    extracted_any_valid = False
    
    state = {
        "variants": [],
        "pngs": [],
        "jsons": []
    }

    os.makedirs("temp_downloads", exist_ok=True)

    try:
        for idx, url in enumerate(zip_links):
            zip_path = f"temp_downloads/upload_{idx}.zip"
            print(f"Downloading {url}...")

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req) as response:
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
                        original_name = sanitize_name(p.get("name", "unnamed"))
                        width = p.get("width", 1)
                        height = p.get("height", 1)

                        png_path = find_in_zip(file_list, f"{original_name}.png")
                        if not png_path:
                            print(f"Could not find texture PNG for '{original_name}'")
                            continue

                        target_texture_dir = "resource-pack/assets/cdsmp/textures/painting"
                        os.makedirs(target_texture_dir, exist_ok=True)

                        target_data_dir = "data-pack/data/cdsmp/painting_variant"
                        os.makedirs(target_data_dir, exist_ok=True)

                        final_name = original_name
                        counter = 1
                        while (
                            os.path.exists(os.path.join(target_texture_dir, f"{final_name}.png")) or
                            os.path.exists(os.path.join(target_data_dir, f"{final_name}.json"))
                        ):
                            final_name = f"{original_name}-{counter}"
                            counter += 1

                        target_png_file = os.path.join(target_texture_dir, f"{final_name}.png")

                        with z.open(png_path) as source_png, open(target_png_file, "wb") as target_png:
                            shutil.copyfileobj(source_png, target_png)

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
                        
                        # Add to state tracking
                        variant_str = f"cdsmp:{final_name}"
                        state["variants"].append(variant_str)
                        state["pngs"].append(target_png_file)
                        state["jsons"].append(target_json_file)

            except zipfile.BadZipFile:
                print(f"Bad zip file from {url}")
                continue

    finally:
        shutil.rmtree("temp_downloads", ignore_errors=True)

    if not extracted_any_valid:
        return None

    # Update placeable.json tag
    if state["variants"]:
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

        existing_values = tag_data.setdefault("values", [])
        for variant in state["variants"]:
            if variant not in existing_values:
                existing_values.append(variant)

        with open(tag_file, "w") as f:
            json.dump(tag_data, f, indent=2)

    # Save state file
    state_dir = ".submission_state"
    os.makedirs(state_dir, exist_ok=True)
    state_file = os.path.join(state_dir, f"{issue_number}.json")
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
        
    return state

def main():
    issue_number = os.environ.get("ISSUE_NUMBER")
    repo = os.environ.get("GITHUB_REPOSITORY")
    
    if not issue_number or not repo:
        print("Missing ISSUE_NUMBER or REPO environment variables.")
        sys.exit(1)

    result = subprocess.run(
        ["gh", "issue", "view", issue_number, "--repo", repo, "--json", "body"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("Failed to fetch issue body.")
        sys.exit(1)

    issue_data = json.loads(result.stdout)
    body = issue_data.get("body") or ""

    zip_links = extract_zip_links(body)

    if not zip_links:
        post_comment(
            issue_number, repo,
            "I couldn't find any `.zip` file attached to this issue. "
            "Please ensure you upload the zip file directly into the issue description."
        )
        sys.exit(1)

    state = process_zips(zip_links, issue_number, repo)
    
    if not state:
        post_comment(
            issue_number, repo,
            "The uploaded zip file(s) did not appear to be a valid MCTools painting pack. "
            "Please make sure the zip contains a `mctools.json` file and valid painting PNGs, then try again."
        )
        sys.exit(1)
        
    print("Successfully processed paintings.")

if __name__ == "__main__":
    main()

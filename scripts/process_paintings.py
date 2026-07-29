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
PAINTING_AUTHOR = "College Debt SMP"
TITLE_COLOR = "aqua"
AUTHOR_COLOR = "gray"
RECIPE_DIR = "data-pack/data/cdsmp/recipe/painting_variant"

def colored_title(display_title):
    return {"text": display_title, "color": TITLE_COLOR}

def colored_author(author=PAINTING_AUTHOR):
    return {"text": author, "color": AUTHOR_COLOR}

def title_text(value, fallback=""):
    """Extract plain display text from a string or text-component title/author."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str):
            return text
    return fallback

# Alias for author/title text-component extraction.
component_text = title_text

MANAGE_HINT = (
    "*You can reply with **`help`** for all commands, **`list`** to see your paintings, "
    "**`rename <title>`** / **`author <name>`** (or with a **`<slug>`** prefix) to change "
    "tooltip text, exactly **`undo`** to revert, or upload a **new zip file** to replace "
    "the submission. Put multiple `rename`/`author` commands on separate lines in one comment "
    "to apply them together.*"
)

def painting_entries(state):
    """Return list of dicts: slug, title, author, width, height, json_path."""
    entries = []
    for json_path in state.get("jsons", []):
        slug = os.path.splitext(os.path.basename(json_path))[0]
        title = slug
        author = PAINTING_AUTHOR
        width, height = "?", "?"
        if os.path.exists(json_path):
            try:
                with open(json_path, "r") as f:
                    data = json.load(f)
                title = title_text(data.get("title"), slug)
                author = title_text(data.get("author"), PAINTING_AUTHOR)
                width = data.get("width", "?")
                height = data.get("height", "?")
            except json.JSONDecodeError:
                pass
        entries.append({
            "slug": slug,
            "title": title,
            "author": author,
            "width": width,
            "height": height,
            "json_path": json_path,
        })
    return entries

def format_painting_list(state):
    lines = ["Available paintings in this submission:"]
    for entry in painting_entries(state):
        lines.append(
            f'- `{entry["slug"]}` — "{entry["title"]}" by {entry["author"]} '
            f'({entry["width"]}x{entry["height"]})'
        )
    return "\n".join(lines)

def format_success_comment(state, headline):
    return (
        f"{headline}\n\n"
        f"{format_painting_list(state)}\n\n"
        f"{MANAGE_HINT}"
    )

def build_variant_json(final_name, width, height, display_title):
    return {
        "asset_id": f"cdsmp:{final_name}",
        "width": width,
        "height": height,
        "title": colored_title(display_title),
        "author": colored_author(),
    }

def build_stonecutter_recipe(final_name):
    return {
        "type": "minecraft:stonecutting",
        "ingredient": "minecraft:painting",
        "result": {
            "id": "minecraft:painting",
            "components": {
                "minecraft:painting/variant": f"cdsmp:{final_name}",
            },
            "count": 1,
        },
    }

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
    """
    Extract GitHub zip attachment URLs from an issue or comment body.

    Supports:
    - Markdown links: [name.zip](https://github.com/...)
    - Markdown links where only the URL looks like a GitHub file attachment
      (common when issue templates/forms wrap uploads in labeled fields)
    - Bare GitHub user-attachments / repo files URLs
    """
    if not body:
        return []

    links = []
    seen = set()

    def add(url):
        url = url.strip().rstrip(").,;\"'>")
        if not url or url in seen:
            return
        seen.add(url)
        links.append(url)

    def looks_like_github_upload(url):
        url_l = url.lower()
        return (
            "github.com/user-attachments/" in url_l
            or re.search(r"github\.com/[^/]+/[^/]+/files/\d+", url_l) is not None
        )

    # Markdown links: [label](url)
    for label, url in re.findall(
        r"\[([^\]]*)\]\((https://github\.com/[^)\s]+)\)",
        body,
        flags=re.IGNORECASE,
    ):
        label_l = label.lower()
        url_l = url.lower()
        if label_l.endswith(".zip") or ".zip" in url_l or looks_like_github_upload(url):
            add(url)

    # Bare URLs (no markdown wrapper)
    for url in re.findall(
        r"https://github\.com/(?:user-attachments/[^\s<>\]]+|[^/\s]+/[^/\s]+/files/\d+[^\s<>\]]*)",
        body,
        flags=re.IGNORECASE,
    ):
        url_l = url.lower()
        if ".zip" in url_l or "user-attachments/" in url_l:
            add(url)

    return links

def process_zips(zip_links, issue_number, repo):
    """Downloads zips, extracts them, handles state, and returns state dict or None on failure."""
    extracted_any_valid = False
    
    state = {
        "variants": [],
        "pngs": [],
        "jsons": [],
        "recipes": [],
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

                    items = mctools_data.get("items", [])
                    if not items:
                        print("No 'items' entries found in mctools.json")
                        continue

                    for p in items:
                        # 'name' is the original filename, used for the in-game painting ID
                        raw_name = (p.get("name") or "").strip()
                        original_name = sanitize_name(raw_name or "unnamed")
                        display_title = raw_name or original_name
                        
                        # 'sizeLabel' is the painting dimension in blocks (e.g. "4x2" or "4×2")
                        size_label = p.get("sizeLabel")
                        width, height = 1, 1
                        
                        if size_label:
                            parts = re.split(r'[xX\u00d7]', size_label)
                            if len(parts) == 2:
                                try:
                                    width = int(parts[0].strip())
                                    height = int(parts[1].strip())
                                except ValueError:
                                    pass

                        # 'slotName' is the actual PNG filename inside the uploaded zip
                        slot_name = sanitize_name(p.get("slotName", ""))
                        
                        png_path = None
                        if slot_name:
                            png_path = find_in_zip(file_list, f"{slot_name}.png")
                        if not png_path:
                            # Fallback just in case
                            png_path = find_in_zip(file_list, f"{original_name}.png")
                            
                        if not png_path:
                            print(f"Could not find texture PNG for '{original_name}' (expected '{slot_name}.png')")
                            continue

                        target_texture_dir = "resource-pack/assets/cdsmp/textures/painting"
                        os.makedirs(target_texture_dir, exist_ok=True)

                        target_data_dir = "data-pack/data/cdsmp/painting_variant"
                        os.makedirs(target_data_dir, exist_ok=True)
                        os.makedirs(RECIPE_DIR, exist_ok=True)

                        final_name = original_name
                        counter = 1
                        while (
                            os.path.exists(os.path.join(target_texture_dir, f"{final_name}.png")) or
                            os.path.exists(os.path.join(target_data_dir, f"{final_name}.json")) or
                            os.path.exists(os.path.join(RECIPE_DIR, f"{final_name}.json"))
                        ):
                            final_name = f"{original_name}-{counter}"
                            counter += 1

                        target_png_file = os.path.join(target_texture_dir, f"{final_name}.png")

                        with z.open(png_path) as source_png, open(target_png_file, "wb") as target_png:
                            shutil.copyfileobj(source_png, target_png)

                        variant_json = build_variant_json(final_name, width, height, display_title)

                        target_json_file = os.path.join(target_data_dir, f"{final_name}.json")
                        with open(target_json_file, "w") as f:
                            json.dump(variant_json, f, indent=2)

                        recipe_file = os.path.join(RECIPE_DIR, f"{final_name}.json")
                        with open(recipe_file, "w") as f:
                            json.dump(build_stonecutter_recipe(final_name), f, indent=2)

                        print(f"Processed painting: {final_name}")
                        extracted_any_valid = True
                        
                        # Add to state tracking
                        variant_str = f"cdsmp:{final_name}"
                        state["variants"].append(variant_str)
                        state["pngs"].append(target_png_file)
                        state["jsons"].append(target_json_file)
                        state["recipes"].append(recipe_file)

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
            "Please upload the MCTools zip directly in the issue body "
            "(issue template text around the attachment is fine)."
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

    post_comment(
        issue_number, repo,
        format_success_comment(
            state,
            "✅ Paintings successfully processed and added to the server resource pack! "
            "A new release will be generated shortly.",
        ),
    )
    print("Successfully processed paintings.")

if __name__ == "__main__":
    main()

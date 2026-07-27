import os
import re
import sys
import json

# Ensure the scripts/ directory is on the path so process_paintings can be imported
# regardless of the working directory the runner uses (repo root).
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from process_paintings import extract_zip_links, process_zips, post_comment

MANAGE_HINT = (
    "*You can reply with **`help`** for all commands, **`list`** to see your paintings, "
    "**`rename <title>`** (or **`rename <slug> <title>`**) to change a title, exactly **`undo`** "
    "to revert, or upload a **new zip file** to replace the submission.*"
)

HELP_TEXT = """Available commands for this painting submission:

- `help` — show this command list
- `list` — list paintings in this submission (slug, title, dimensions)
- `rename <title>` — rename the title when this submission has exactly one painting
- `rename <slug> <title>` — rename a specific painting by slug (required when there are multiple)
- `undo` — remove all paintings from this submission
- Upload a **new `.zip` file** — replace this submission with a new MCTools pack

Notes:
- `rename` only changes the display title used in the stonecutter UI. The `cdsmp:` resource ID stays the same.
- If `rename` is missing a slug on a multi-painting submission, or uses an unknown slug, the bot will list available slugs."""


def normalize_comment_body(raw):
    """Decode COMMENT_BODY when the workflow passes it via toJSON(...)."""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(parsed, str):
        return parsed.strip()
    return text

def set_action_type(action_type):
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as f:
            f.write(f"ACTION_TYPE={action_type}\n")

def load_state(issue_number):
    state_file = f".submission_state/{issue_number}.json"
    if not os.path.exists(state_file):
        return None
    with open(state_file, "r") as f:
        return json.load(f)

def variant_slugs(state):
    slugs = []
    for variant in state.get("variants", []):
        if ":" in variant:
            slugs.append(variant.split(":", 1)[1])
        else:
            slugs.append(variant)
    return slugs

def painting_entries(state):
    """Return list of dicts: slug, title, width, height, json_path."""
    entries = []
    for json_path in state.get("jsons", []):
        slug = os.path.splitext(os.path.basename(json_path))[0]
        title = slug
        width, height = "?", "?"
        if os.path.exists(json_path):
            try:
                with open(json_path, "r") as f:
                    data = json.load(f)
                title = data.get("title", slug)
                width = data.get("width", "?")
                height = data.get("height", "?")
            except json.JSONDecodeError:
                pass
        entries.append({
            "slug": slug,
            "title": title,
            "width": width,
            "height": height,
            "json_path": json_path,
        })
    return entries

def format_painting_list(state):
    lines = ["Available paintings in this submission:"]
    for entry in painting_entries(state):
        lines.append(
            f'- `{entry["slug"]}` — "{entry["title"]}" ({entry["width"]}x{entry["height"]})'
        )
    return "\n".join(lines)

def parse_rename(remainder, slugs):
    """
    Parse rename arguments.
    Returns (slug, new_title, error_message).
    error_message is set when the command cannot be applied.
    """
    remainder = (remainder or "").strip()
    if not remainder:
        return None, None, "❌ Missing title. Usage: `rename <title>` or `rename <slug> <title>`"

    if not slugs:
        return None, None, "❌ No paintings found in this submission."

    parts = remainder.split(None, 1)
    first = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""

    if first in slugs:
        if not rest:
            return None, None, (
                f"❌ Missing new title for `{first}`.\n\n"
                f"Usage: `rename {first} <new title>`"
            )
        return first, rest, None

    if len(slugs) == 1:
        return slugs[0], remainder, None

    return None, None, "multiple"

def do_undo(issue_number, repo):
    """Reverts the changes made by a submission using its state file."""
    state_file = f".submission_state/{issue_number}.json"
    
    if not os.path.exists(state_file):
        print("No state file found. Cannot undo.")
        return False
        
    with open(state_file, "r") as f:
        state = json.load(f)
        
    variants = set(state.get("variants", []))
    pngs = state.get("pngs", [])
    jsons = state.get("jsons", [])
    recipes = state.get("recipes", [])
    
    # Delete the generated PNGs, variant JSONs, and stonecutter recipes
    for file_path in pngs + jsons + recipes:
        if os.path.exists(file_path):
            os.remove(file_path)
            
    # Remove the variants from placeable.json
    tag_file = "data-pack/data/minecraft/tags/painting_variant/placeable.json"
    if variants and os.path.exists(tag_file):
        with open(tag_file, "r") as f:
            try:
                tag_data = json.load(f)
            except json.JSONDecodeError:
                tag_data = {"replace": False, "values": []}
                
        existing_values = tag_data.get("values", [])
        new_values = [v for v in existing_values if v not in variants]
        tag_data["values"] = new_values
        
        with open(tag_file, "w") as f:
            json.dump(tag_data, f, indent=2)
            
    # Remove the state file
    os.remove(state_file)
    
    return True

def do_list(issue_number, repo):
    state = load_state(issue_number)
    if not state:
        post_comment(
            issue_number, repo,
            "❌ No submission state found for this issue. Nothing to list."
        )
        return False

    body = format_painting_list(state)
    body += "\n\n" + MANAGE_HINT
    post_comment(issue_number, repo, body)
    return True

def do_help(issue_number, repo):
    post_comment(issue_number, repo, HELP_TEXT)
    return True

def do_rename(issue_number, repo, comment_body):
    state = load_state(issue_number)
    if not state:
        post_comment(
            issue_number, repo,
            "❌ No submission state found for this issue. Nothing to rename."
        )
        return False

    slugs = variant_slugs(state)
    entries = {entry["slug"]: entry for entry in painting_entries(state)}
    if not slugs:
        slugs = list(entries.keys())

    match = re.match(r"^rename\s*(.*)$", comment_body, flags=re.IGNORECASE | re.DOTALL)
    remainder = (match.group(1) if match else "").strip()
    parts = remainder.split(None, 1)

    # For multi-painting submissions, a slug-like first token that isn't in this
    # submission is treated as an unknown target. Single-painting submissions
    # always allow title-only renames (including multi-word titles).
    if (
        len(slugs) > 1
        and parts
        and len(parts) > 1
        and parts[0] not in slugs
        and re.fullmatch(r"[a-z0-9][a-z0-9_\-.]*", parts[0])
    ):
        post_comment(
            issue_number, repo,
            f"❌ Unknown slug `{parts[0]}` for this submission.\n\n"
            f"{format_painting_list(state)}\n\n"
            "Usage: `rename <slug> <new title>`"
        )
        return False

    slug, new_title, error = parse_rename(remainder, slugs)
    if error == "multiple":
        post_comment(
            issue_number, repo,
            "❌ Multiple paintings in this submission — please specify which slug to rename.\n\n"
            f"{format_painting_list(state)}\n\n"
            "Usage: `rename <slug> <new title>`"
        )
        return False
    if error:
        post_comment(issue_number, repo, error)
        return False

    entry = entries.get(slug)
    json_path = entry["json_path"] if entry else f"data-pack/data/cdsmp/painting_variant/{slug}.json"
    if not os.path.exists(json_path):
        post_comment(
            issue_number, repo,
            f"❌ Painting file for `{slug}` was not found.\n\n{format_painting_list(state)}"
        )
        return False

    with open(json_path, "r") as f:
        data = json.load(f)

    old_title = data.get("title", slug)
    data["title"] = new_title

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    post_comment(
        issue_number, repo,
        f'✅ Renamed `{slug}` from "{old_title}" to "{new_title}". '
        "A new release will be generated shortly.\n\n"
        + MANAGE_HINT
    )
    return True

def main():
    issue_number = os.environ.get("ISSUE_NUMBER")
    repo = os.environ.get("GITHUB_REPOSITORY")
    comment_body = normalize_comment_body(os.environ.get("COMMENT_BODY", ""))
    
    if not issue_number or not repo:
        print("Missing ISSUE_NUMBER or REPO environment variables.")
        sys.exit(1)

    # help
    if comment_body.lower() == "help":
        print("Processing HELP request...")
        set_action_type("help")
        if do_help(issue_number, repo):
            sys.exit(0)
        sys.exit(1)

    # list
    if comment_body.lower() == "list":
        print("Processing LIST request...")
        set_action_type("list")
        if do_list(issue_number, repo):
            sys.exit(0)
        sys.exit(1)

    # rename ...
    if re.match(r"^rename(\s|$)", comment_body, flags=re.IGNORECASE):
        print("Processing RENAME request...")
        set_action_type("rename")
        if do_rename(issue_number, repo, comment_body):
            sys.exit(0)
        sys.exit(1)
        
    # Check if this is an UNDO command
    if comment_body.lower() == "undo":
        print("Processing UNDO request...")
        success = do_undo(issue_number, repo)
        if success:
            set_action_type("undo")
            post_comment(
                issue_number, repo,
                "✅ Submission successfully undone. The paintings have been removed from the repository. \n\n"
                "*Note: If you want to submit again, please open a **new issue** instead of commenting here.*"
            )
            sys.exit(0)
        else:
            post_comment(issue_number, repo, "❌ Failed to undo: No previous submission state found for this issue.")
            sys.exit(1)
            
    # Check if this is a RESUBMIT command (contains a zip)
    zip_links = extract_zip_links(comment_body)
    if zip_links:
        print("Processing RESUBMIT request...")
        set_action_type("resubmit")

        # Undo the previous submission to clear the slate
        do_undo(issue_number, repo)
        
        # Process the new zip
        state = process_zips(zip_links, issue_number, repo)
        if state:
            post_comment(
                issue_number, repo,
                "✅ Resubmission successfully processed! The new paintings have replaced your old submission. "
                "A new release will be generated shortly.\n\n"
                + MANAGE_HINT
            )
            sys.exit(0)
        else:
            post_comment(
                issue_number, repo,
                "❌ Resubmission failed. The uploaded zip file(s) did not appear to be a valid MCTools painting pack."
            )
            sys.exit(1)
            
    print("Comment ignored. No recognized command or zip file was detected.")
    # Exit with 1 so we don't accidentally commit or trigger release workflow
    sys.exit(1)

if __name__ == "__main__":
    main()

import os
import re
import sys
import json

# Ensure the scripts/ directory is on the path so process_paintings can be imported
# regardless of the working directory the runner uses (repo root).
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from process_paintings import (
    MANAGE_HINT,
    colored_author,
    colored_title,
    component_text,
    extract_zip_links,
    format_painting_list,
    format_success_comment,
    painting_entries,
    process_zips,
    post_comment,
    title_text,
)

HELP_TEXT = """Available commands for this painting submission:

- `help` — show this command list
- `list` — list paintings in this submission (slug, title, author, dimensions)
- `rename <title>` — rename the title when this submission has exactly one painting
- `rename <slug> <title>` — rename a specific painting's title by slug (required when there are multiple)
- `author <name>` — set the author when this submission has exactly one painting
- `author <slug> <name>` — set a specific painting's author by slug (required when there are multiple)
- `undo` — remove all paintings from this submission
- Upload a **new `.zip` file** — replace this submission with a new MCTools pack

Notes:
- `rename` and `author` only change stonecutter tooltip text. The `cdsmp:` resource ID stays the same.
- If this submission has one painting and you write `rename <slug>` or `author <slug>` with that painting's slug, it is treated as setting the value to that same text.
- If a slug is missing on a multi-painting submission, or an unknown slug is used, the bot will list available slugs.
- You can batch several `rename` / `author` commands in one comment by putting each on its own line."""

FIELD_COMMANDS = {
    "rename": {
        "field": "title",
        "colorize": colored_title,
        "value_label": "title",
        "verb": "Renamed",
    },
    "author": {
        "field": "author",
        "colorize": colored_author,
        "value_label": "author",
        "verb": "Updated author for",
    },
}


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

def parse_targeted_value(remainder, slugs, *, command, value_label):
    """
    Parse `command <value>` / `command <slug> <value>` arguments.
    Returns (slug, new_value, error_message).
    """
    remainder = (remainder or "").strip()
    if not remainder:
        return None, None, (
            f"❌ Missing {value_label}. Usage: `{command} <{value_label}>` or "
            f"`{command} <slug> <{value_label}>`"
        )

    if not slugs:
        return None, None, "❌ No paintings found in this submission."

    parts = remainder.split(None, 1)
    first = parts[0]
    rest = parts[1].strip() if len(parts) > 1 else ""

    if first in slugs:
        if not rest:
            # Single-painting ambiguity: `command <slug>` means set the value to that
            # same string (equivalent to `command <slug> <slug>`).
            if len(slugs) == 1:
                return first, first, None
            return None, None, (
                f"❌ Missing new {value_label} for `{first}`.\n\n"
                f"Usage: `{command} {first} <new {value_label}>`"
            )
        return first, rest, None

    if len(slugs) == 1:
        return slugs[0], remainder, None

    return None, None, "multiple"

def parse_rename(remainder, slugs):
    """Backward-compatible wrapper around parse_targeted_value for titles."""
    return parse_targeted_value(remainder, slugs, command="rename", value_label="title")

def non_empty_lines(comment_body):
    return [line.strip() for line in comment_body.splitlines() if line.strip()]

def classify_update_line(line):
    """Return (command, line) if this is a rename/author command line, else None."""
    for command in FIELD_COMMANDS:
        if re.match(rf"^{command}(\s|$)", line, flags=re.IGNORECASE):
            return command, line
    return None

def collect_update_lines(comment_body):
    """
    Parse a comment into rename/author command lines.
    Returns (commands, invalid_lines) where commands is a list of (command, line).
    """
    commands = []
    invalid = []
    for line in non_empty_lines(comment_body):
        classified = classify_update_line(line)
        if classified:
            commands.append(classified)
        else:
            invalid.append(line)
    return commands, invalid

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

def apply_field_update(issue_number, comment_body, *, command, field, colorize, value_label, verb):
    """
    Apply one rename/author update.
    Returns (ok, message) without posting a GitHub comment.
    """
    state = load_state(issue_number)
    if not state:
        return False, f"❌ No submission state found for this issue. Nothing to {command}."

    slugs = variant_slugs(state)
    entries = {entry["slug"]: entry for entry in painting_entries(state)}
    if not slugs:
        slugs = list(entries.keys())

    match = re.match(rf"^{re.escape(command)}\s*(.*)$", comment_body, flags=re.IGNORECASE | re.DOTALL)
    remainder = (match.group(1) if match else "").strip()
    parts = remainder.split(None, 1)

    # For multi-painting submissions, a slug-like first token that isn't in this
    # submission is treated as an unknown target.
    if (
        len(slugs) > 1
        and parts
        and len(parts) > 1
        and parts[0] not in slugs
        and re.fullmatch(r"[a-z0-9][a-z0-9_\-.]*", parts[0])
    ):
        return False, (
            f"❌ Unknown slug `{parts[0]}` for this submission.\n\n"
            f"{format_painting_list(state)}\n\n"
            f"Usage: `{command} <slug> <new {value_label}>`"
        )

    slug, new_value, error = parse_targeted_value(
        remainder, slugs, command=command, value_label=value_label
    )
    if error == "multiple":
        return False, (
            f"❌ Multiple paintings in this submission — please specify which slug to {command}.\n\n"
            f"{format_painting_list(state)}\n\n"
            f"Usage: `{command} <slug> <new {value_label}>`"
        )
    if error:
        return False, error

    entry = entries.get(slug)
    json_path = entry["json_path"] if entry else f"data-pack/data/cdsmp/painting_variant/{slug}.json"
    if not os.path.exists(json_path):
        return False, (
            f"❌ Painting file for `{slug}` was not found.\n\n{format_painting_list(state)}"
        )

    with open(json_path, "r") as f:
        data = json.load(f)

    old_value = component_text(data.get(field), slug)
    data[field] = colorize(new_value)

    # Keep the sibling tooltip field as a colored text component if it was still plain.
    if field == "title" and isinstance(data.get("author"), str):
        data["author"] = colored_author(data["author"])
    elif field == "author" and isinstance(data.get("title"), str):
        data["title"] = colored_title(data["title"])

    with open(json_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    return True, f'✅ {verb} `{slug}` from "{old_value}" to "{new_value}".'

def do_field_update(issue_number, repo, comment_body, *, command, field, colorize, value_label, verb):
    """Shared handler for a single rename (title) or author update."""
    ok, message = apply_field_update(
        issue_number,
        comment_body,
        command=command,
        field=field,
        colorize=colorize,
        value_label=value_label,
        verb=verb,
    )
    if ok:
        post_comment(
            issue_number, repo,
            f"{message} A new release will be generated shortly.\n\n" + MANAGE_HINT
        )
    else:
        post_comment(issue_number, repo, message)
    return ok

def do_batch_updates(issue_number, repo, command_lines):
    """
    Apply multiple rename/author lines from one comment.
    Returns True if at least one update succeeded.
    """
    results = []
    success_count = 0

    for command, line in command_lines:
        spec = FIELD_COMMANDS[command]
        ok, message = apply_field_update(
            issue_number,
            line,
            command=command,
            field=spec["field"],
            colorize=spec["colorize"],
            value_label=spec["value_label"],
            verb=spec["verb"],
        )
        # Keep batch replies compact: one status line per command when possible.
        first_line = message.splitlines()[0]
        results.append(first_line)
        if ok:
            success_count += 1
        elif "\n" in message:
            # Include slug list / usage details for failures that need them.
            results.extend(message.splitlines()[1:])

    if success_count:
        body = "\n".join(results)
        body += (
            f"\n\n✅ Applied {success_count}/{len(command_lines)} update(s). "
            "A new release will be generated shortly.\n\n"
            + MANAGE_HINT
        )
        post_comment(issue_number, repo, body)
        return True

    body = "\n".join(results) if results else "❌ No updates applied."
    post_comment(issue_number, repo, body)
    return False

def do_rename(issue_number, repo, comment_body):
    return do_field_update(
        issue_number,
        repo,
        comment_body,
        command="rename",
        field="title",
        colorize=colored_title,
        value_label="title",
        verb="Renamed",
    )

def do_author(issue_number, repo, comment_body):
    return do_field_update(
        issue_number,
        repo,
        comment_body,
        command="author",
        field="author",
        colorize=colored_author,
        value_label="author",
        verb="Updated author for",
    )

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

    # undo (exact)
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

    # One or more rename/author lines (supports batching in a single comment)
    command_lines, invalid_lines = collect_update_lines(comment_body)
    if command_lines:
        if invalid_lines:
            preview = "\n".join(f"- `{line}`" for line in invalid_lines[:5])
            post_comment(
                issue_number, repo,
                "❌ Could not process this comment because some lines are not `rename`/`author` commands:\n"
                f"{preview}\n\n"
                "Put each `rename` or `author` command on its own line."
            )
            sys.exit(1)

        if len(command_lines) == 1:
            command = command_lines[0][0]
            print(f"Processing {command.upper()} request...")
            set_action_type(command)
        else:
            print(f"Processing BATCH update ({len(command_lines)} commands)...")
            set_action_type("update")

        if do_batch_updates(issue_number, repo, command_lines):
            sys.exit(0)
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
                format_success_comment(
                    state,
                    "✅ Resubmission successfully processed! The new paintings have replaced your old submission. "
                    "A new release will be generated shortly.",
                ),
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

import os
import sys
import json

# Ensure the scripts/ directory is on the path so process_paintings can be imported
# regardless of the working directory the runner uses (repo root).
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from process_paintings import extract_zip_links, process_zips, post_comment

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
    
    # Delete the generated PNGs and JSONs
    for file_path in pngs + jsons:
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

def main():
    issue_number = os.environ.get("ISSUE_NUMBER")
    repo = os.environ.get("GITHUB_REPOSITORY")
    comment_body = os.environ.get("COMMENT_BODY", "").strip()
    
    if not issue_number or not repo:
        print("Missing ISSUE_NUMBER or REPO environment variables.")
        sys.exit(1)
        
    # Check if this is an UNDO command
    if comment_body.lower() == "undo":
        print("Processing UNDO request...")
        success = do_undo(issue_number, repo)
        if success:
            # Signal to the workflow that this is an undo (skips release trigger)
            github_env = os.environ.get("GITHUB_ENV")
            if github_env:
                with open(github_env, "a") as f:
                    f.write("ACTION_TYPE=undo\n")
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
        # Signal to the workflow that this is a resubmit (triggers release)
        github_env = os.environ.get("GITHUB_ENV")
        if github_env:
            with open(github_env, "a") as f:
                f.write("ACTION_TYPE=resubmit\n")

        # Undo the previous submission to clear the slate
        do_undo(issue_number, repo)
        
        # Process the new zip
        state = process_zips(zip_links, issue_number, repo)
        if state:
            post_comment(
                issue_number, repo,
                "✅ Resubmission successfully processed! The new paintings have replaced your old submission. A new release will be generated shortly. \n\n"
                "*If you made a mistake, you can reply to this issue with exactly **`undo`** to revert your submission, or simply upload a **new zip file** in a comment to replace it.*"
            )
            sys.exit(0)
        else:
            post_comment(
                issue_number, repo,
                "❌ Resubmission failed. The uploaded zip file(s) did not appear to be a valid MCTools painting pack."
            )
            sys.exit(1)
            
    print("Comment ignored. Neither 'undo' nor a zip file was detected.")
    # Exit with 1 so we don't accidentally commit or trigger release workflow
    sys.exit(1)

if __name__ == "__main__":
    main()

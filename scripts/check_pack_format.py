import os
import sys
import json
import urllib.request

API_URL = "https://raw.githubusercontent.com/misode/mcmeta/summary/versions/data.json"

def fetch_latest_formats():
    """Fetches the latest pack formats from misode's mcmeta repository."""
    print("Fetching latest pack formats...")
    req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode("utf-8"))
        
    # Some recent/experimental snapshots might be missing pack_version,
    # so we iterate until we find the most recent valid one.
    pack_version = None
    for entry in data:
        if entry.get("pack_version") is not None:
            pack_version = entry.get("pack_version")
            break
    
    if pack_version is None:
        raise ValueError("Could not find any pack_version in the recent versions list.")
    
    if isinstance(pack_version, dict):
        return {
            "resource": pack_version.get("resource", 0),
            "data": pack_version.get("data", 0)
        }
    elif isinstance(pack_version, int):
        return {
            "resource": pack_version,
            "data": pack_version
        }
    else:
        raise ValueError(f"Unexpected pack_version format: {pack_version}")

def update_mcmeta(file_path, new_max_format):
    """Updates the pack.mcmeta file if the new format is greater than the current max."""
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False
        
    with open(file_path, "r") as f:
        mcmeta = json.load(f)
        
    pack = mcmeta.get("pack", {})
    
    current_max = pack.get("pack_format", 0)
    supported = pack.get("supported_formats")
    
    if isinstance(supported, dict):
        current_max = supported.get("max_inclusive", current_max)
    elif isinstance(supported, list) and len(supported) == 2:
        current_max = supported[1]
        
    if new_max_format <= current_max:
        print(f"[{file_path}] Up to date (Current max: {current_max}, Latest: {new_max_format})")
        return False
        
    print(f"[{file_path}] Update available! Bumping from {current_max} to {new_max_format}")
    
    # Update pack_format (this acts as the fallback for older versions and general indicator)
    pack["pack_format"] = new_max_format
    
    # Update supported_formats range
    if isinstance(supported, dict):
        pack["supported_formats"]["max_inclusive"] = new_max_format
    elif isinstance(supported, list) and len(supported) == 2:
        pack["supported_formats"][1] = new_max_format
    else:
        # If there wasn't a supported_formats block, create one to ensure backwards compatibility
        pack["supported_formats"] = {
            "min_inclusive": current_max,
            "max_inclusive": new_max_format
        }
        
    mcmeta["pack"] = pack
    
    with open(file_path, "w") as f:
        json.dump(mcmeta, f, indent=2)
        # Add a newline at the end of the file for neatness
        f.write("\n")
        
    return True

def main():
    try:
        latest_formats = fetch_latest_formats()
        print(f"Latest formats from API: {latest_formats}")
    except Exception as e:
        print(f"Failed to fetch pack formats: {e}")
        # Exit with an error code so the workflow runner correctly marks this step as failed
        sys.exit(1)
        
    resource_updated = update_mcmeta("resource-pack/pack.mcmeta", latest_formats["resource"])
    data_updated = update_mcmeta("data-pack/pack.mcmeta", latest_formats["data"])
    
    # Write result directly to $GITHUB_OUTPUT to avoid fragile grep-based parsing
    github_output = os.environ.get("GITHUB_OUTPUT")
    changes_made = "true" if (resource_updated or data_updated) else "false"
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"changes_made={changes_made}\n")
    else:
        # Fallback for local testing
        print(f"changes_made={changes_made}")

if __name__ == "__main__":
    main()

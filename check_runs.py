import urllib.request
import json
import os
import subprocess

repo = "College-Debt-SMP/resource-pack"
run_id = 30235114260
job_id = 89881360340

# Get the logs for the run
result = subprocess.run(["gh", "run", "view", str(run_id), "--log-failed"], capture_output=True, text=True)

with open("release_logs.txt", "w") as f:
    f.write(result.stdout)
    f.write(result.stderr)

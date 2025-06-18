import os
import subprocess
import sys

if len(sys.argv) < 2:
    print("Usage: python clone_repo.py <repo_url>")
    sys.exit(1)

repo_url = sys.argv[1]

# determine target directory from repo url
name = os.path.splitext(os.path.basename(repo_url))[0]

# check if 'work' branch exists in remote
check = subprocess.run(["git", "ls-remote", "--heads", repo_url, "work"], capture_output=True, text=True)
branch = "work" if check.stdout.strip() else None

cmd = ["git", "clone"]
if branch:
    cmd.extend(["--branch", branch])
cmd.extend([repo_url, name])
subprocess.check_call(cmd)

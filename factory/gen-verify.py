#!/usr/bin/env python3
"""Generate a repo's ./verify from the shared template + its checks block."""
import sys, pathlib

tpl = pathlib.Path(__file__).parent / "verify.template"
repo, checks_file, out = sys.argv[1], sys.argv[2], sys.argv[3]
body = tpl.read_text()
checks = pathlib.Path(checks_file).read_text().rstrip("\n")
body = body.replace("__REPO__", repo).replace("__CHECKS__", checks)
p = pathlib.Path(out)
p.write_text(body)
p.chmod(0o755)
print(f"wrote {out}")

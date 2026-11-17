#!/usr/bin/env python3
"""Assemble the Firefox and Chromium builds of the extension into extension/dist/."""
import os
import shutil
import sys
import zipfile

here = os.path.dirname(os.path.abspath(__file__))
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "dist")

for target in ("firefox", "chromium"):
    dest = os.path.join(out, target)
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(os.path.join(here, "common"), dest)
    shutil.copy(os.path.join(here, f"manifest.{target}.json"), os.path.join(dest, "manifest.json"))

# An unsigned .xpi, ready to upload for signing or to load in Firefox Developer Edition / ESR.
xpi = os.path.join(out, "focusguard-firefox.xpi")
with zipfile.ZipFile(xpi, "w", zipfile.ZIP_DEFLATED) as z:
    src = os.path.join(out, "firefox")
    for name in sorted(os.listdir(src)):
        z.write(os.path.join(src, name), name)
print("Built", out)

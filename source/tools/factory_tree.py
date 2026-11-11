"""The factory tree of the workshop-owned SD files (SD-LAYOUT.md F.5, decision G12).

`dsf/sd_restore.py` restores ONE workshop-owned file from `dsf/factory/<path under the SD>` (kept by DSF in the plugin folder, off the SD)
and refuses a copy whose sha256 is not the one of `dsf/sd_manifest.json`. This module is the single place that knows how that tree is
made and checked:

  write(files, out)          lays the tree out (called by tools/gen_sd_manifest.py, which has the bytes from the plugin zips)
  dsf_files(paths)           the `dsfFiles` entries of plugin.json for it ("factory/<path>")
  sync_plugin_json(...)      rewrites those entries in plugin.json (the rest of dsfFiles is untouched)
  check_tree(manifest, read) the problems between a manifest and a tree (read(rel) -> bytes or None)
  check_zip(path)            the same on a finished service zip: every workshop-owned file of the manifest INSIDE the zip is in the zip's
                             dsf/factory with the manifest sha, and nothing else is there (used by tools/build_37.py check_release, so by
                             tools/build_release.py --check and by both line builds)

It never touches a machine.
"""
import hashlib
import json
import os
import re
import shutil
import zipfile

CRLF = chr(13) + chr(10)
LF = chr(10)
FACTORY = "factory"
MANIFEST = "sd_manifest.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def owned(manifest):
    """{path: sha256} of the workshop-owned files of a manifest (the only ones that are restored)."""
    return {e["path"]: e["sha256"] for e in manifest["files"] if e["kind"] == "workshop-owned"}


def dsf_files(paths):
    return sorted("%s/%s" % (FACTORY, p) for p in paths)


def write(files, out):
    """files = {sd path: bytes}. Makes `out` hold exactly those files (a stale one is removed). Returns the sorted paths."""
    if os.path.isdir(out):
        shutil.rmtree(out)
    for rel, data in sorted(files.items()):
        dst = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)
    return sorted(files)


def sync_plugin_json(path, paths):
    """Rewrites the factory entries of dsfFiles in plugin.json as TEXT (the rest of the file, one line per hand-written entry, is not
    reformatted): the old factory entries go, the new ones are appended at the end of the array. True when the file changed."""
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    nl = CRLF if CRLF in raw else LF
    m = re.search(r'("dsfFiles"\s*:\s*\[)(.*?)(\])', raw, re.S)
    body = m.group(2)
    items = re.findall(r'"([^"]+)"', body)
    keep = [x for x in items if not x.startswith(FACTORY + "/")]
    # drop the factory entries (and the comma that goes with each) from the text, keeping the layout of the others
    cleaned = re.sub(r'\s*"%s/[^"]*"\s*,?' % FACTORY, "", body)
    cleaned = cleaned.rstrip().rstrip(",")
    tail = "".join(',%s    "%s"' % (nl, x) for x in dsf_files(paths))
    new_body = cleaned + tail + nl + "  "
    new = raw[:m.start(2)] + new_body + raw[m.end(2):]
    if json.loads(new)["dsfFiles"] != keep + dsf_files(paths):
        raise SystemExit("plugin.json dsfFiles rewrite went wrong")
    if new == raw:
        return False
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    return True


def check_tree(manifest, read):
    """Problems (list of text) between the workshop-owned files of `manifest` and a tree: read("factory/<path>") -> bytes or None."""
    problems = []
    for path, want in sorted(owned(manifest).items()):
        data = read("%s/%s" % (FACTORY, path))
        if data is None:
            problems.append("factory copy missing: %s/%s" % (FACTORY, path))
        elif sha(data) != want:
            problems.append("factory copy differs from the manifest sha: %s/%s" % (FACTORY, path))
    return problems


def check_zip(path):
    """Problems of the factory tree inside a finished service zip. A zip with no sd_manifest.json has nothing to check."""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        mname = "dsf/" + MANIFEST
        if mname not in names:
            return []
        manifest = json.loads(z.read(mname).decode("utf-8"))
        problems = check_tree(manifest, lambda rel: z.read("dsf/" + rel) if "dsf/" + rel in names else None)
        expected = {"dsf/%s/%s" % (FACTORY, p) for p in owned(manifest)}
        for n in sorted(names):
            if n.startswith("dsf/%s/" % FACTORY) and n not in expected:
                problems.append("factory copy of a file the manifest does not own: " + n)
    return problems

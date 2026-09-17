#!/usr/bin/env python3
"""Workflow Map installer.

    python install.py                 install to ~/workflow-map, wire the hook, build once
    python install.py --dir PATH      install somewhere else
    python install.py --no-hook       install and build, but do not touch Claude settings
    python install.py --uninstall     remove the hook (and offer to delete the folder)

Requires Python 3.9+ and Claude Code (the desktop app or the terminal CLI).
Nothing leaves your machine. The map only reads local files.
"""
import argparse, json, os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
SETTINGS = HOME / ".claude" / "settings.json"
DEFAULT_DIR = HOME / "workflow-map"

SYSTEM_DIRS = {
    # Windows
    "AppData", "Application Data", "Cookies", "Local Settings", "My Documents", "Recent", "Searches", "Start Menu",
    "Templates", "NetHood", "PrintHood", "SendTo", "CrossDevice", "Links", "Favorites", "Saved Games", "Contacts",
    "3D Objects", "OneDrive", "My Drive", "Dropbox", "iCloudDrive", "Creative Cloud Files",
    # macOS / Linux
    "Library", "Applications", "Public", "Sites", "snap", "go", "bin",
    # generic
    "Music", "Videos", "Movies", "Pictures", "Documents", "Downloads", "Desktop", "node_modules", "source", "workflow-map",
}


def discover(root, exclude):
    out = []
    for d in sorted(root.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and d.name not in exclude:
            out.append(d.name)
    return out


def write_config(dest, root):
    cfg_path = dest / "config.json"
    if cfg_path.exists():
        print(f"  keeping existing {cfg_path}")
        return
    exclude = sorted(SYSTEM_DIRS)
    names = discover(root, set(exclude))
    email = None
    try:
        email = json.load(open(HOME / ".claude.json", encoding="utf-8")).get("oauthAccount", {}).get("emailAddress")
    except Exception:
        pass
    cfg = {
        "_help": "Edit this file to change how the map reads. notes = one line per project folder; group = label used to group cards; "
                 "group_order = the order groups appear; aliases = old folder name -> new folder name; exclude = folders under projects_root "
                 "that are not projects; primary_email = the account that holds your real work (auto-detected if blank); "
                 "mirror_sessions = copy every Code session's sidebar record into every account so any login shows all of them "
                 "(undo with build-map.py --unmirror); backup_transcripts = keep a copy of every transcript under history/.",
        "projects_root": str(root),
        "primary_email": email or "",
        "active_days": 14,
        "min_mentions": 6,
        "mirror_sessions": False,
        "backup_transcripts": False,
        "search_index": True,
        "search_server": False,
        "search_port": 8765,
        "exclude": exclude,
        "aliases": {},
        "group_order": [],
        "group": {n: "" for n in names},
        "notes": {n: "" for n in names},
        "automation_title_patterns": ["heartbeat", "scheduled-task", "reply with exactly"],
        "global_pieces": [
            ["Custom skills", str(HOME / ".claude" / "skills")],
            ["Memory per project", str(HOME / ".claude" / "projects" / "<folder>" / "memory")],
            ["Session transcripts (shared by every account)", str(HOME / ".claude" / "projects")],
            ["This map, its builder and config", str(dest)],
        ],
    }
    json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"  wrote {cfg_path} with {len(names)} projects found under {root}")
    print("  Tip: ask Claude to fill in the notes. With the skill installed: \"describe my projects in the workflow map\".")


def hook_entry(script, event):
    # SessionStart runs in the foreground so its one-line summary reaches the session; SessionEnd runs in the background.
    return {"type": "command", "command": sys.executable, "args": [str(script)], "async": event != "SessionStart", "timeout": 120,
            "statusMessage": "Rebuilding workflow map"}


def add_hook(script):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    st = json.load(open(SETTINGS, encoding="utf-8")) if SETTINGS.exists() else {}
    hooks = st.setdefault("hooks", {})
    added = 0
    for ev in ("SessionStart", "SessionEnd"):
        entries = hooks.setdefault(ev, [])
        present = any(any("build-map.py" in " ".join(h.get("args", [])) for h in e.get("hooks", [])) for e in entries)
        if not present:
            entries.append({"hooks": [hook_entry(script, ev)]})
            added += 1
    json.dump(st, open(SETTINGS, "w", encoding="utf-8"), indent=2)
    print(f"  hook: {added} entries added to {SETTINGS} (SessionStart + SessionEnd)" if added else f"  hook already present in {SETTINGS}")


def remove_hook():
    if not SETTINGS.exists():
        return
    st = json.load(open(SETTINGS, encoding="utf-8"))
    hooks = st.get("hooks", {})
    removed = 0
    for ev in list(hooks):
        keep = []
        for e in hooks[ev]:
            if any("build-map.py" in " ".join(h.get("args", [])) for h in e.get("hooks", [])):
                removed += 1
            else:
                keep.append(e)
        if keep:
            hooks[ev] = keep
        else:
            del hooks[ev]
    if not hooks:
        st.pop("hooks", None)
    json.dump(st, open(SETTINGS, "w", encoding="utf-8"), indent=2)
    print(f"  removed {removed} hook entries from {SETTINGS}")


def keep_transcripts():
    """Claude Code deletes terminal transcripts after 30 days by default. Raise that so the history is real."""
    st = json.load(open(SETTINGS, encoding="utf-8")) if SETTINGS.exists() else {}
    if st.get("cleanupPeriodDays", 30) >= 3650:
        print("  transcript retention already long")
        return
    st["cleanupPeriodDays"] = 3650
    json.dump(st, open(SETTINGS, "w", encoding="utf-8"), indent=2)
    print(f"  transcript retention set to 3650 days in {SETTINGS} (was {st.get('cleanupPeriodDays', 30)} by default)")


def install_skill():
    src = HERE / "skill" / "workflow-map"
    if not src.exists():
        return
    dst = HOME / ".claude" / "skills" / "workflow-map"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src / "SKILL.md", dst / "SKILL.md")
    print(f"  skill installed at {dst} (say \"update my workflow map\" in any Claude session)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(DEFAULT_DIR), help="where to install (default ~/workflow-map)")
    ap.add_argument("--root", default=str(HOME), help="folder whose subfolders are your projects (default: your home folder)")
    ap.add_argument("--no-hook", action="store_true", help="do not add the SessionStart/SessionEnd hook")
    ap.add_argument("--no-skill", action="store_true", help="do not install the Claude skill")
    ap.add_argument("--keep-transcripts", action="store_true", help="raise Claude Code's transcript retention from 30 days to 10 years")
    ap.add_argument("--search", action="store_true", help="keep a local conversation-search server running (127.0.0.1 only) so the map can search inside conversations")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    dest = Path(a.dir).expanduser().resolve()

    if a.uninstall:
        print("Uninstalling Workflow Map")
        remove_hook()
        sk = HOME / ".claude" / "skills" / "workflow-map"
        if sk.exists():
            shutil.rmtree(sk); print(f"  removed {sk}")
        print(f"  Your map folder {dest} was left in place. Delete it yourself if you want it gone.")
        return

    if sys.version_info < (3, 9):
        sys.exit("Python 3.9 or newer is required.")
    print(f"Installing Workflow Map to {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    for fn in ("build-map.py", "search_index.py", "search-server.py", "README.md"):
        shutil.copy2(HERE / fn, dest / fn)
    write_config(dest, Path(a.root).expanduser().resolve())
    if a.search:
        cfg_path = dest / "config.json"
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        cfg["search_server"] = True
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        print("  conversation search server enabled (starts with the first build, restarts with each session)")
    if not a.no_skill:
        install_skill()
    if not a.no_hook:
        add_hook(dest / "build-map.py")
    if a.keep_transcripts:
        keep_transcripts()
    print("  building the first map (the first run scans every transcript once; later runs take under a second)...")
    r = subprocess.run([sys.executable, str(dest / "build-map.py"), "--verbose"], capture_output=True, text=True)
    print("  " + (r.stdout.strip() or r.stderr.strip()))
    print()
    print(f"Done. Open this in a browser:  {dest / '00-WORKFLOW-MAP.html'}")
    print("It rebuilds itself every time a Claude session starts or ends.")


if __name__ == "__main__":
    main()

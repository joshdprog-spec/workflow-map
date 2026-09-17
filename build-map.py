#!/usr/bin/env python3
"""Workflow Map: rebuild 00-WORKFLOW-MAP.html / .md from what is actually on disk.

Nothing leaves your machine. It only reads local files.

Reads:
  - every project folder under the home directory
  - every Claude Desktop session index, for EVERY account signed in on this PC
  - every CLI transcript under ~/.claude/projects
  - scheduled task definitions and which account they are registered to
  - config.json next to this script (notes, groups, aliases)

Writes nothing to stdout unless --verbose (SessionStart hooks feed stdout to
the model, so the default is silent). Errors go to last-run.log.
"""
import json, os, re, sys, glob, datetime, traceback, html, shutil, subprocess, socket
from pathlib import Path

HERE = Path(__file__).resolve().parent
CFG = json.load(open(HERE / "config.json", encoding="utf-8"))
HOME = Path.home()
CLAUDE = HOME / ".claude"
# Where the Claude desktop app keeps its per-account session index, per platform
if sys.platform == "win32":
    APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming")) / "Claude"
elif sys.platform == "darwin":
    APPDATA = HOME / "Library" / "Application Support" / "Claude"
else:
    APPDATA = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "Claude"
ROOT = Path(os.path.expanduser(CFG.get("projects_root", "~"))).resolve()  # the folder whose subfolders are your projects
SESS_ROOT = APPDATA / "claude-code-sessions"
COWORK_ROOT = APPDATA / "local-agent-mode-sessions"
NOW = datetime.datetime.now()
VERBOSE = "--verbose" in sys.argv
UNMIRROR = "--unmirror" in sys.argv
HOOK_EVENT = ""


def _read_hook_event():
    """Claude Code pipes a JSON event on stdin when this runs as a hook. Anywhere else stdin may be a pipe that
    never closes, so read it in a thread and give up after two seconds."""
    global HOOK_EVENT
    import threading
    box = {}

    def reader():
        try:
            box["v"] = json.loads(sys.stdin.read() or "{}").get("hook_event_name", "")
        except Exception:
            box["v"] = ""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return
    except Exception:
        return
    t = threading.Thread(target=reader, daemon=True)
    t.start()
    t.join(2.0)
    HOOK_EVENT = box.get("v", "")


_read_hook_event()
STATE_PAT = re.compile(r"(HANDOFF|STATE|START-HERE|WHERE-WE-ARE|CONTINUITY|-CURRENT|BLUEPRINT|CLAUDE\.md|README\.md|AUDIT-)", re.I)
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".claude"}
AUTOMATION = [p.lower() for p in CFG.get("automation_title_patterns", [])]


def log(msg):
    if VERBOSE:
        print(msg)


def ts(ms):
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000)
    except Exception:
        return None


def fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def slug_for(folder_name):
    """Claude Code names a project's transcript folder after its full path with every non-alphanumeric turned into '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(ROOT / folder_name))


# ---------- accounts ----------
def load_accounts():
    """Map (accountId, orgId) -> {email, org_name, plan, last_active, index_dir}."""
    accts = {}
    if not SESS_ROOT.exists():
        return accts
    for acct_dir in SESS_ROOT.iterdir():
        if not acct_dir.is_dir():
            continue
        for org_dir in acct_dir.iterdir():
            if not org_dir.is_dir():
                continue
            files = [f for f in org_dir.glob("local_*.json") if str(f) not in mirrored_paths()]
            if not files and not (org_dir / "scheduled-tasks.json").exists():
                continue
            info = {"email": "?", "org_name": "?", "plan": "?", "index_dir": org_dir,
                    "last_active": max((f.stat().st_mtime for f in files), default=0),
                    "n_sessions": len(files)}
            # email from any cowork sandbox .claude.json under the same acct/org
            for cj in list((COWORK_ROOT / acct_dir.name / org_dir.name).glob("local_*/.claude/.claude.json"))[:5]:
                try:
                    oa = json.load(open(cj, encoding="utf-8")).get("oauthAccount", {})
                    if oa.get("emailAddress"):
                        info.update(email=oa["emailAddress"], org_name=oa.get("organizationName", "?"),
                                    plan=oa.get("organizationType", "?"))
                        break
                except Exception:
                    pass
            if info["email"] == "?":
                try:
                    oa = json.load(open(HOME / ".claude.json", encoding="utf-8")).get("oauthAccount", {})
                    if oa.get("accountUuid") == acct_dir.name and oa.get("organizationUuid") == org_dir.name:
                        info.update(email=oa["emailAddress"], org_name=oa.get("organizationName", "?"),
                                    plan=oa.get("organizationType", "?"))
                except Exception:
                    pass
            if info["email"] == "?":
                info["email"] = "(unknown account)"
            if info["n_sessions"] or info["email"] != "(unknown account)":
                accts[(acct_dir.name, org_dir.name)] = info
    return accts


# ---------- sessions ----------
def is_automation(title):
    t = (title or "").lower()
    return any(p in t for p in AUTOMATION)


_MIRRORED = None


def mirrored_paths():
    """Paths of sidebar records this tool mirrored (read once per run)."""
    global _MIRRORED
    if _MIRRORED is None:
        try:
            with open(HERE / "mirror-manifest.json", encoding="utf-8") as fh:
                w = json.load(fh).get("written", [])
                _MIRRORED = set(w.keys() if isinstance(w, dict) else w)
        except Exception:
            _MIRRORED = set()
    return _MIRRORED


def load_index_sessions(accts):
    """All desktop sessions from every account, each counted once under the account that created it."""
    out = []
    mirrored = mirrored_paths()
    for key, info in accts.items():
        for f in info["index_dir"].glob("local_*.json"):
            if str(f) in mirrored:
                continue
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            out.append({
                "cwd": d.get("cwd") or "", "title": (d.get("title") or "").removeprefix(CFG.get("mirror_label", "\u21c4 ")), "cli": d.get("cliSessionId") or "",
                "last": ts(d.get("lastActivityAt")), "archived": bool(d.get("isArchived")),
                "email": info["email"], "acct": key, "auto": is_automation(d.get("title")),
            })
    return out


def first_user_text(jsonl_path, max_lines=60):
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > max_lines:
                    break
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if d.get("type") != "user":
                    continue
                c = d.get("message", {}).get("content")
                txt = c if isinstance(c, str) else " ".join(x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text")
                txt = re.sub(r"<[^>]+>", " ", txt or "")
                txt = re.sub(r"\s+", " ", txt).strip()
                if txt:
                    return txt[:70]
    except Exception:
        pass
    return ""


def load_transcript_sessions(known_cli_ids):
    """CLI transcripts not already covered by a desktop index (e.g. terminal sessions)."""
    out = {}
    root = CLAUDE / "projects"
    if not root.exists():
        return out
    for pdir in root.iterdir():
        if not pdir.is_dir() or "scratch-workspaces" in pdir.name or "local-agent-mode" in pdir.name:
            continue
        rows = []
        for j in pdir.glob("*.jsonl"):
            sid = j.stem
            if sid in known_cli_ids:
                continue
            title = first_user_text(j)
            rows.append({"cli": sid, "title": title, "last": datetime.datetime.fromtimestamp(j.stat().st_mtime),
                         "email": "terminal", "auto": is_automation(title) or title.startswith("scheduled-task")})
        if rows:
            out[pdir.name] = rows
    return out


def load_cowork_sessions(accts):
    """Cowork sessions (Claude tab with folders attached). Each carries the list of attached home folders."""
    out = []
    if not COWORK_ROOT.exists():
        return out
    for f in COWORK_ROOT.glob("*/*/local_*.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict) or "userSelectedFolders" not in d:
            continue
        key = (f.parts[-3], f.parts[-2])
        email = accts.get(key, {}).get("email", "(unknown account)")
        folders = []
        for p in d.get("userSelectedFolders") or []:
            try:
                rel = Path(p).relative_to(ROOT).parts
                if rel and rel[0] not in set(CFG.get("exclude", [])):
                    folders.append(rel[0])
            except Exception:
                pass
        tr = list((f.parent / f.stem / ".claude" / "projects").glob("*/*.jsonl"))
        out.append({"cwd": "", "title": d.get("title") or "", "cli": d.get("cliSessionId") or "", "last": ts(d.get("lastActivityAt")),
                    "archived": bool(d.get("isArchived")), "email": email, "acct": key, "auto": is_automation(d.get("title")),
                    "kind": "cowork", "folders": folders, "transcript": tr[0] if tr else None})
    return out


def scan_mentions(files, names):
    """Which project folder names each transcript mentions. Cached by (mtime, size) so only changed files are re-read."""
    cache_path = HERE / "mention-cache.json"
    try:
        cache = json.load(open(cache_path, encoding="utf-8"))
    except Exception:
        cache = {}
    needles = {n: n.encode("utf-8") for n in names if len(n) >= 5}
    result, new_cache = {}, {}
    for fp in files:
        fp = Path(fp)
        try:
            st = fp.stat()
        except Exception:
            continue
        k = str(fp)
        ent = cache.get(k)
        if ent and ent.get("v") == 2 and ent.get("m") == st.st_mtime and ent.get("s") == st.st_size and set(ent.get("names", [])) == set(needles):
            hits = ent["n"]
        else:
            counts = {}
            try:
                with open(fp, "rb") as fh:
                    while True:
                        chunk = fh.read(8 * 1024 * 1024)
                        if not chunk:
                            break
                        for n, b in needles.items():
                            c = chunk.count(b)
                            if c:
                                counts[n] = counts.get(n, 0) + c
            except Exception:
                pass
            hits = counts
        new_cache[k] = {"v": 2, "m": st.st_mtime, "s": st.st_size, "n": hits, "names": sorted(needles)}
        result[k] = hits
    try:
        json.dump(new_cache, open(cache_path, "w", encoding="utf-8"))
    except Exception:
        pass
    return result


# ---------- mirror: make every account's sidebar show every session ----------
def mirror_sessions(accts):
    """Copy each session's newest record file into every account folder that lacks it (or has an older copy).
    Transcripts are shared on disk, so a mirrored record opens normally from either account.
    Skips archived and deleted sessions. Keeps a manifest of what it wrote so --unmirror can undo it exactly."""
    manifest_path = HERE / "mirror-manifest.json"
    try:
        manifest = json.load(open(manifest_path, encoding="utf-8"))
    except Exception:
        manifest = {"written": {}}
    if isinstance(manifest.get("written"), list):  # older manifest form
        manifest["written"] = {w: 0 for w in manifest["written"]}
    if UNMIRROR:
        removed = 0
        for w in list(manifest.get("written", {})):
            try:
                Path(w).unlink(); removed += 1
            except Exception:
                pass
        manifest_path.write_text(json.dumps({"written": {}}, indent=1), encoding="utf-8")
        log(f"unmirror: removed {removed} mirrored records")
        return 0
    if not CFG.get("mirror_sessions"):
        return 0
    dirs = [info["index_dir"] for info in accts.values() if info["email"] not in ("(unknown account)",)]
    if len(dirs) < 2:
        return 0
    deleted = set()
    for d in dirs:
        for m in d.glob("deleted_*"):
            deleted.add(m.name.replace("deleted_", ""))
    newest = {}  # session id -> (mtime, path, record)
    for d in dirs:
        for f in d.glob("local_*.json"):
            try:
                rec = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(rec, dict) or rec.get("isArchived"):
                continue
            sid = f.stem.replace("local_", "")
            if sid in deleted:
                continue
            m = f.stat().st_mtime
            if sid not in newest or m > newest[sid][0]:
                newest[sid] = (m, f, rec)
    written = dict(manifest.get("written", {}))
    n = 0
    for sid, (m, src, rec) in newest.items():
        for d in dirs:
            dst = d / src.name
            if dst == src:
                continue
            if dst.exists() and str(dst) not in written:
                continue  # the other account has its own native copy; leave it alone
            if str(dst) in written and written[str(dst)] >= m:
                continue  # our copy is already from this version of the source
            try:
                shutil.copy2(src, dst)
                written[str(dst)] = m; n += 1
            except Exception:
                pass
    manifest_path.write_text(json.dumps({"written": dict(sorted(written.items()))}, indent=1), encoding="utf-8")
    # label every mirrored copy so the sidebar shows which sessions come from another account
    marker = CFG.get("mirror_label", "\u21c4 ")
    labelled = 0
    if marker:
        for w in written:
            wp = Path(w)
            try:
                rec = json.loads(wp.read_text(encoding="utf-8"))
                t = rec.get("title") or ""
                if t.startswith(marker):
                    continue
                rec["title"] = marker + t
                wp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
                labelled += 1
            except Exception:
                pass
    log(f"mirror: {n} records copied this run, {len(written)} mirrored records in total, {labelled} newly labelled")
    return n


# ---------- history: a ledger that only grows, plus backups ----------
def update_history(accts, sessions, cowork, transcripts_by_slug):
    """history/ledger.json remembers every session ever seen, even after the app or a cleanup deletes it.
    history/records/ keeps the latest copy of every sidebar record file.
    history/transcripts/ (optional, backup_transcripts: true) keeps a copy of every transcript, updated when it changes."""
    hdir = HERE / "history"
    (hdir / "records").mkdir(parents=True, exist_ok=True)
    ledger_path = hdir / "ledger.json"
    try:
        ledger = json.load(open(ledger_path, encoding="utf-8"))
    except Exception:
        ledger = {}
    now = NOW.isoformat(timespec="seconds")

    def note(key, **fields):
        e = ledger.setdefault(key, {"first_seen": now})
        e["last_seen"] = now
        for k, v in fields.items():
            if v not in (None, ""):
                e[k] = v
        e.setdefault("accounts", [])
        if fields.get("account") and fields["account"] not in e["accounts"]:
            e["accounts"].append(fields["account"])

    for s_ in sessions:
        note(s_["cli"] or s_.get("sid", ""), kind="code", title=s_["title"], cwd=s_["cwd"], account=s_["email"],
             last_activity=s_["last"].isoformat(timespec="seconds") if s_["last"] else None, archived=s_.get("archived", False))
    for c in cowork:
        note(c["cli"] or c["title"], kind="cowork", title=c["title"], folders=c["folders"], account=c["email"],
             last_activity=c["last"].isoformat(timespec="seconds") if c["last"] else None,
             transcript=str(c["transcript"]) if c["transcript"] else None)
    for slug, rows in transcripts_by_slug.items():
        for t in rows:
            note(t["cli"], kind="terminal", title=t["title"], project_slug=slug,
                 last_activity=t["last"].isoformat(timespec="seconds") if t["last"] else None)
    ledger_path.write_text(json.dumps(ledger, indent=1, ensure_ascii=False), encoding="utf-8")

    copied = 0
    for key, info in accts.items():
        sub = hdir / "records" / (info["email"].replace("@", "_at_") if info["email"] else "_".join(key))
        sub.mkdir(parents=True, exist_ok=True)
        for f in list(info["index_dir"].glob("local_*.json")) + list(info["index_dir"].glob("scheduled-tasks.json")) + list(info["index_dir"].glob("archived-sessions.idx")):
            dst = sub / f.name
            try:
                if not dst.exists() or dst.stat().st_mtime < f.stat().st_mtime or dst.stat().st_size != f.stat().st_size:
                    shutil.copy2(f, dst); copied += 1
            except Exception:
                pass
    tcopied = 0
    if CFG.get("backup_transcripts"):
        tdir = hdir / "transcripts"
        srcs = []
        root = CLAUDE / "projects"
        if root.exists():
            for pdir in root.iterdir():
                if pdir.is_dir() and "scratch-workspaces" not in pdir.name:
                    for j in pdir.glob("*.jsonl"):
                        srcs.append((j, tdir / pdir.name / j.name))
        for c in cowork:
            if c["transcript"]:
                srcs.append((c["transcript"], tdir / "cowork" / c["transcript"].name))
        for src, dst in srcs:
            try:
                st = src.stat()
                if not dst.exists() or dst.stat().st_size != st.st_size or dst.stat().st_mtime < st.st_mtime:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst); tcopied += 1
            except Exception:
                pass
    log(f"history: {len(ledger)} sessions in ledger, {copied} record files refreshed, {tcopied} transcripts backed up")
    return len(ledger)


# ---------- conversation search ----------
def update_search_index(entries):
    """entries: [{path, session, kind, project, account}] for every transcript. Uses search_index.py next to this script."""
    if not CFG.get("search_index", True):
        return
    try:
        sys.path.insert(0, str(HERE))
        import search_index
        search_index.update_index(HERE / "history" / "search.sqlite", entries, log)
    except Exception as e:
        log(f"search index skipped: {e}")


def ensure_search_server():
    """Start search-server.py detached if nothing answers on the configured port."""
    if not CFG.get("search_server"):
        return False
    port = int(CFG.get("search_port", 27183))
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        pass
    script = HERE / "search-server.py"
    if not script.exists():
        return False
    try:
        kw = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
        if sys.platform == "win32":
            kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
        else:
            kw["start_new_session"] = True
        subprocess.Popen([sys.executable, str(script), "--port", str(port)], **kw)
        log(f"search server started on 127.0.0.1:{port}")
        return True
    except Exception as e:
        log(f"search server not started: {e}")
        return False


# ---------- assets that live per account ----------
JUNK = {"settings.local.json", ".package-lock.json", "package-lock.json", "concat.txt"}
JUNK_DIRS = {"node_modules", "playwright", "playwright-core", "__pycache__", ".claude", ".git"}


def load_claude_projects(accts):
    """Claude Projects (the claude.ai kind, with a description and knowledge docs), from each account's project cache."""
    out = []
    for key, info in accts.items():
        pc = COWORK_ROOT / key[0] / key[1] / ".project-cache"
        if not pc.exists():
            continue
        for d in pc.iterdir():
            meta = d / "metadata.json"
            if not meta.exists():
                continue
            try:
                m = json.load(open(meta, encoding="utf-8"))
            except Exception:
                continue
            docs = sorted([f.name for f in (d / "docs").glob("*") if f.is_file()]) if (d / "docs").exists() else []
            out.append({"name": m.get("name") or d.name, "description": (m.get("description") or "").strip(), "account": info["email"],
                        "docs": docs, "synced": (m.get("synced_at") or "")[:10], "path": str(d)})
    out.sort(key=lambda x: (x["account"], x["name"].lower()))
    return out


def load_cowork_outputs(cowork):
    """Files each Cowork session produced, minus tooling noise."""
    out = []
    for c in cowork:
        if not c.get("transcript"):
            continue
        odir = c["transcript"].parents[3] / "outputs"
        if not odir.exists():
            continue
        files = []
        for root, dirs, names in os.walk(odir):
            dirs[:] = [x for x in dirs if x not in JUNK_DIRS]
            for n in names:
                if n in JUNK or n.startswith("."):
                    continue
                files.append(str(Path(root, n).relative_to(odir)))
        if files:
            files.sort()
            out.append({"title": c["title"], "account": c["email"], "last": c["last"], "folders": c["folders"], "dir": str(odir), "files": files})
    out.sort(key=lambda x: x["last"] or datetime.datetime.min, reverse=True)
    return out


# ---------- projects ----------
def last_touched(folder, max_depth=2):
    best = 0
    base_depth = len(folder.parts)
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if len(Path(root).parts) - base_depth >= max_depth:
            dirs[:] = []
        for fn in files:
            try:
                best = max(best, (Path(root) / fn).stat().st_mtime)
            except Exception:
                pass
    return datetime.datetime.fromtimestamp(best) if best else None


def state_files(folder):
    found = []
    base_depth = len(folder.parts)
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if len(Path(root).parts) - base_depth >= 2:
            dirs[:] = []
        for fn in files:
            if STATE_PAT.search(fn) and fn.lower().endswith((".md", ".html", ".txt")):
                p = Path(root) / fn
                try:
                    found.append((p.stat().st_mtime, str(p.relative_to(folder))))
                except Exception:
                    pass
    found.sort(reverse=True)
    # prefer HANDOFF/STATE/START-HERE over README/AUDIT
    pri = lambda n: (0 if re.search(r"HANDOFF|STATE|START-HERE|WHERE-WE-ARE|CONTINUITY|-CURRENT|CLAUDE\.md", n, re.I) else 1)
    found.sort(key=lambda t: (pri(t[1]), -t[0]))
    return [n for _, n in found[:4]]


def build():
    accts = load_accounts()
    sessions = load_index_sessions(accts)
    known = {s["cli"] for s in sessions if s["cli"]}
    transcripts = load_transcript_sessions(known)

    # which account is the desktop app on right now = most recently written index
    current = max(accts.items(), key=lambda kv: kv[1]["last_active"], default=(None, None))
    current_key, current_info = current
    primary_email = CFG.get("primary_email")
    if not primary_email:  # default to whoever the terminal CLI is signed in as
        try:
            primary_email = json.load(open(HOME / ".claude.json", encoding="utf-8")).get("oauthAccount", {}).get("emailAddress")
        except Exception:
            primary_email = None
    if not primary_email and current_info:
        primary_email = current_info.get("email")

    exclude = set(CFG.get("exclude", []))
    if HERE.parent == ROOT:
        exclude.add(HERE.name)  # never list the map's own folder as a project
    projects = {}
    for d in sorted(ROOT.iterdir()):
        if not d.is_dir() or d.name in exclude or d.name.startswith("."):
            continue
        projects[d.name] = {"folder": d, "exists": True}

    # sessions whose cwd folder no longer exists -> renamed or deleted
    aliases = CFG.get("aliases", {})
    for s in sessions:
        cwd = s["cwd"]
        if not cwd or not cwd.lower().startswith(str(ROOT).lower() + os.sep):
            continue
        rel = Path(cwd).relative_to(ROOT).parts
        if not rel or "AppData" in rel[0]:
            continue
        name = rel[0]
        if name not in projects:
            projects[name] = {"folder": ROOT / name, "exists": False}

    def sessions_for(name):
        target = str(ROOT / name).lower()
        rows = [s for s in sessions if s["cwd"].lower() == target or s["cwd"].lower().startswith(target + os.sep)]
        rows += transcripts.get(slug_for(name), [])
        return rows

    # Cowork sessions, attached to every project folder they had open
    cowork = load_cowork_sessions(accts)

    mirrored = mirror_sessions(accts)
    ledger_n = update_history(accts, sessions, cowork, transcripts)

    # Which sessions (anywhere) mention each project folder by name -> "also worked on from elsewhere"
    names = list(projects.keys())
    by_cli = {s["cli"]: s for s in sessions if s["cli"]}
    scan_files, file_meta = [], {}
    for pdir in (CLAUDE / "projects").iterdir() if (CLAUDE / "projects").exists() else []:
        if not pdir.is_dir() or "scratch-workspaces" in pdir.name or "local-agent-mode" in pdir.name:
            continue
        for j in pdir.glob("*.jsonl"):
            scan_files.append(j)
            s = by_cli.get(j.stem)
            home_folder = ""
            for n in names:
                if pdir.name == slug_for(n):
                    home_folder = n
            file_meta[str(j)] = {"title": (s["title"] if s else "") or "", "last": (s["last"] if s else None) or datetime.datetime.fromtimestamp(j.stat().st_mtime),
                                 "cli": j.stem, "from": home_folder or pdir.name.removeprefix(slug_for("")).lstrip("-"), "email": s["email"] if s else "terminal",
                                 "auto": s["auto"] if s else False, "kind": "code"}
    for c in cowork:
        if c["transcript"]:
            scan_files.append(c["transcript"])
            file_meta[str(c["transcript"])] = {"title": c["title"], "last": c["last"], "cli": c["cli"], "from": "Cowork: " + (", ".join(c["folders"][:2]) or "no folder"),
                                               "email": c["email"], "auto": c["auto"], "kind": "cowork", "folders": c["folders"]}
    mentions = scan_mentions(scan_files, names)
    index_entries = [{"path": fp, "session": m["cli"], "kind": m["kind"], "project": (m["from"] if m["kind"] == "code" else ", ".join(m.get("folders", []))), "account": m["email"]}
                     for fp, m in file_meta.items()]
    # conversations held with no project folder (the desktop app's scratch workspaces) are conversations too
    for pdir in (CLAUDE / "projects").iterdir() if (CLAUDE / "projects").exists() else []:
        if pdir.is_dir() and "scratch-workspaces" in pdir.name:
            for j in pdir.glob("*.jsonl"):
                s_ = by_cli.get(j.stem)
                index_entries.append({"path": str(j), "session": j.stem, "kind": "code", "project": "(no folder)", "account": s_["email"] if s_ else "terminal"})
    update_search_index(index_entries)
    search_up = ensure_search_server()
    elsewhere = {n: [] for n in names}
    min_mentions = int(CFG.get("min_mentions", 6))  # a folder listing mentions a name once or twice; real work mentions it many times
    for fp, hits in mentions.items():
        m = file_meta.get(fp)
        if not m or m["auto"]:
            continue
        for n, c in hits.items():
            if c < min_mentions or m["from"] == n or n in m.get("folders", []):
                continue  # too incidental, or it is the project's own session (already listed)
            elsewhere[n].append(dict(m, mentions=c))
    for n in elsewhere:
        elsewhere[n].sort(key=lambda m: m["last"] or datetime.datetime.min, reverse=True)

    rows = []
    for name, p in projects.items():
        sess = sessions_for(name)
        work = sorted([s for s in sess if not s["auto"] and not s.get("archived")], key=lambda s: s["last"] or datetime.datetime.min, reverse=True)
        auto = [s for s in sess if s["auto"]]
        cw = sorted([c for c in cowork if name in c["folders"] and not c["auto"] and not c["archived"]], key=lambda s: s["last"] or datetime.datetime.min, reverse=True)
        touched = last_touched(p["folder"]) if p["exists"] else None
        last_sess = work[0]["last"] if work else None
        last_cw = cw[0]["last"] if cw else None
        last_any = max([x for x in (touched, last_sess, last_cw) if x], default=None)
        mem = CLAUDE / "projects" / slug_for(name) / "memory"
        n_mem = len([f for f in mem.glob("*.md") if f.name != "MEMORY.md"]) if mem.exists() else 0
        rows.append({
            "name": name, "exists": p["exists"], "touched": touched, "last": last_any,
            "state": state_files(p["folder"]) if p["exists"] else [],
            "work": work[:6], "n_work": len(work), "n_auto": len(auto), "n_mem": n_mem,
            "cowork": cw[:4], "n_cowork": len(cw), "elsewhere": elsewhere.get(name, [])[:4], "n_elsewhere": len(elsewhere.get(name, [])),
            "group": CFG.get("group", {}).get(name, ""), "note": CFG.get("notes", {}).get(name, ""),
            "alias_to": aliases.get(name), "hidden": sum(1 for s in work if s["email"] not in (primary_email, "terminal")),
        })
    rows.sort(key=lambda r: r["last"] or datetime.datetime.min, reverse=True)

    # scheduled tasks
    tasks = []
    for tdir in sorted((CLAUDE / "scheduled-tasks").glob("*/")):
        desc = ""
        sk = tdir / "SKILL.md"
        if sk.exists():
            m = re.search(r"^description:\s*(.+)$", sk.read_text(encoding="utf-8", errors="replace"), re.M)
            desc = m.group(1).strip() if m else ""
        reg = []
        for key, info in accts.items():
            stj = info["index_dir"] / "scheduled-tasks.json"
            if not stj.exists():
                continue
            try:
                for t in json.load(open(stj, encoding="utf-8")).get("scheduledTasks", []):
                    if t.get("id") == tdir.name:
                        reg.append((info["email"], t.get("enabled"), t.get("lastRunAt", ""), os.path.basename(t.get("cwd", ""))))
            except Exception:
                pass
        tasks.append((tdir.name, desc, reg))

    cowork_list = sorted([c for c in cowork if not c["auto"]], key=lambda s: s["last"] or datetime.datetime.min, reverse=True)
    claude_projects = load_claude_projects(accts)
    cowork_outputs = load_cowork_outputs(cowork)
    return dict(accts=accts, current_key=current_key, current_info=current_info, rows=rows, tasks=tasks,
                primary_email=primary_email, n_sessions=len(sessions), n_cowork=len(cowork), cowork=cowork_list,
                mirrored=mirrored, ledger_n=ledger_n, search_up=search_up, search_port=int(CFG.get("search_port", 27183)),
                claude_projects=claude_projects, cowork_outputs=cowork_outputs)


# ---------- render ----------
def render_md(D):
    L = []
    A = L.append
    cur = D["current_info"] or {}
    A(f"# WORKFLOW MAP\n")
    A(f"Rebuilt {NOW.strftime('%Y-%m-%d %H:%M')} by `{HERE / 'build-map.py'}` (runs at every session start and end). "
      f"Edit `{HERE / 'config.json'}` to change notes, groups or rename aliases.\n")
    A("## Accounts on this PC\n")
    A("| Account | Org | Plan | Desktop sessions | Last active | |")
    A("|---|---|---|---|---|---|")
    for key, info in sorted(D["accts"].items(), key=lambda kv: -kv[1]["last_active"]):
        flag = "**<- app was last used as this**" if key == D["current_key"] else ""
        A(f"| {info['email']} | {info['org_name']} | {info['plan']} | {info['n_sessions']} | {fmt(datetime.datetime.fromtimestamp(info['last_active'])) if info['last_active'] else ''} | {flag} |")
    if CFG.get("mirror_sessions"):
        A(f"\n> **Mirrored.** Every Code session is copied into every account's sidebar, so the login does not matter for Code sessions. "
          f"Claude-tab (Cowork) sessions are not mirrored and still need the account shown. App was last used as {cur.get('email')}.\n")
    elif cur and cur.get("email") != D["primary_email"]:
        A(f"\n> **WARNING: the desktop app was last used as {cur.get('email')}, not {D['primary_email']}.** "
          f"The sidebar only shows that account's sessions. Everything else is still on disk. "
          f"Sign out and back in as {D['primary_email']} to see it all.\n")
    A("\nSessions are per account in the sidebar, but every transcript is shared on disk. From a terminal inside the project folder, "
      "any Code session below can be reopened with `claude --resume <id>`. Lines marked COWORK are Claude-tab sessions that had this folder attached "
      "(reopen them from the Claude tab's history on that account). Lines marked FROM are sessions in another folder that read or wrote this project's files.\n")

    active_days = CFG.get("active_days", 14)
    cutoff = NOW - datetime.timedelta(days=active_days)

    def table(rows_):
        A("| Project | Group | Last activity | Read this first | Latest sessions (resume id) | Notes |")
        A("|---|---|---|---|---|---|")
        for r in rows_:
            name = f"**{r['name']}**" if r["exists"] else f"~~{r['name']}~~"
            if r["alias_to"]:
                name += f" is now **{r['alias_to']}**"
            elif not r["exists"]:
                name += " (folder gone: renamed? add it to aliases in config.json)"
            state = "<br>".join(r["state"]) or "-"
            def tag(s):
                return f" *[{s['email']}]*" if s['email'] not in (D['primary_email'], 'terminal') else ""
            parts = [f"{fmt(s['last'])} {html.escape(s['title'][:45]) or '(untitled)'} `{s['cli'][:8]}`" + tag(s) for s in r["work"]]
            parts += [f"{fmt(s['last'])} COWORK: {html.escape(s['title'][:40]) or '(untitled)'}" + tag(s) for s in r["cowork"]]
            parts += [f"{fmt(s['last'])} FROM {html.escape(s['from'][:22])}: {html.escape(s['title'][:32]) or '(untitled)'} `{s['cli'][:8]}`" + tag(s) for s in r["elsewhere"]]
            sess = "<br>".join(parts) or "-"
            extra = []
            if r["n_work"] > 3:
                extra.append(f"+{r['n_work'] - 3} more")
            if r["n_cowork"] > 3:
                extra.append(f"+{r['n_cowork'] - 3} more Cowork")
            if r["n_elsewhere"] > 3:
                extra.append(f"+{r['n_elsewhere'] - 3} more from elsewhere")
            if r["n_auto"]:
                extra.append(f"{r['n_auto']} automation runs")
            if r["n_mem"]:
                extra.append(f"{r['n_mem']} memory files")
            note = r["note"] + (f" _({', '.join(extra)})_" if extra else "")
            A(f"| {name} | {r['group']} | {fmt(r['last'])} | {state} | {sess} | {note} |")

    act = [r for r in D["rows"] if r["last"] and r["last"] >= cutoff]
    rest = [r for r in D["rows"] if r not in act]
    A(f"\n## Active in the last {active_days} days\n")
    table(act)
    A("\n## Everything else\n")
    table(rest)

    A(f"\n## Cowork sessions ({len(D['cowork'])})\n")
    A("Sessions run from the Claude tab with folders attached. They never appear in the Code sidebar. Reopen them from the Claude tab's history while signed in to the account shown.\n")
    A("| When | Session | Folders attached | Account |")
    A("|---|---|---|---|")
    for c in D["cowork"]:
        A(f"| {fmt(c['last'])} | {html.escape(c['title'][:60]) or '(untitled)'} | {', '.join(c['folders']) or '-'} | {c['email']} |")

    A("\n## Scheduled tasks\n")
    A("Definitions live in `~/.claude/scheduled-tasks`. A task only fires while the desktop app is signed in to the account it is registered to.\n")
    A("| Task | What | Registered to | Enabled | Last run | Folder |")
    A("|---|---|---|---|---|---|")
    for name, desc, reg in D["tasks"]:
        if reg:
            for email, en, lr, cwd in reg:
                A(f"| {name} | {desc} | {email} | {en} | {str(lr)[:16]} | {cwd} |")
        else:
            A(f"| {name} | {desc} | (not registered in any account) | | | |")

    if D.get("claude_projects"):
        A(f"\n## Claude Projects ({len(D['claude_projects'])})\n")
        A("The claude.ai kind, with a description and knowledge docs. Each belongs to the account shown.\n")
        A("| Project | Description | Docs | Account |")
        A("|---|---|---|---|")
        for x in D["claude_projects"]:
            A(f"| **{x['name']}** | {html.escape(x['description'][:90])} | {len(x['docs'])}: {', '.join(x['docs'][:4])}{' ...' if len(x['docs']) > 4 else ''} | {x['account']} |")
    if D.get("cowork_outputs"):
        A(f"\n## Cowork deliverables ({len(D['cowork_outputs'])} sessions with files)\n")
        A("| When | Session | Files | Folder | Account |")
        A("|---|---|---|---|---|")
        for o in D["cowork_outputs"]:
            A(f"| {fmt(o['last'])} | {html.escape(o['title'][:50])} | {len(o['files'])}: {', '.join(o['files'][:3])}{' ...' if len(o['files']) > 3 else ''} | `{o['dir']}` | {o['account']} |")

    arts = CFG.get("artifacts", [])
    if arts:
        A(f"\n## Published artifacts ({len(arts)})\n")
        A("Artifacts belong to the account that published them. A shared link opens from any account.\n")
        A("| Updated | Artifact | Project | Account |")
        A("|---|---|---|---|")
        for a in sorted(arts, key=lambda a: a.get("updated", ""), reverse=True):
            A(f"| {a.get('updated', '')} | [{a['title']}]({a['url']}) | {a.get('project', '')} | {a.get('account', '')} |")

    A("\n## Global pieces (shared by every project and every account)\n")
    for label, path in CFG.get("global_pieces", []):
        A(f"- **{label}**: `{path}`")
    A("\n## Renames on record\n")
    for old, new in CFG.get("aliases", {}).items():
        A(f"- {old} is now **{new}**")
    return "\n".join(L) + "\n"


def render_html(D):
    """Page rendering lives in render_v3.py next to this script (an app shell fed by one JSON blob)."""
    sys.path.insert(0, str(HERE))
    import importlib, render_v3
    importlib.reload(render_v3)
    return render_v3.render_html(D, CFG, HERE, NOW, ROOT)


def main():
    try:
        D = build()
        md = render_md(D)
        Path(CFG.get("output_md", HERE / "00-WORKFLOW-MAP.md")).write_text(md, encoding="utf-8")
        Path(CFG.get("output_html", HERE / "00-WORKFLOW-MAP.html")).write_text(render_html(D), encoding="utf-8")
        (HERE / "last-run.log").write_text(f"ok {NOW.isoformat()} projects={len(D['rows'])} sessions={D['n_sessions']} cowork={D['n_cowork']} ledger={D['ledger_n']} mirrored={D['mirrored']} app_as={(D['current_info'] or {}).get('email')}\n", encoding="utf-8")
        if HOOK_EVENT == "SessionStart":
            cur = (D["current_info"] or {}).get("email")
            hidden = sum(1 for r in D["rows"] for s_ in r["work"] if s_["email"] not in (cur, "terminal"))
            recent = ", ".join(r["name"] for r in D["rows"][:4])
            state = "mirrored into every account's sidebar" if CFG.get("mirror_sessions") else (f"{hidden} sessions belong to {D['primary_email']} and are hidden from this account's sidebar" if hidden and cur != D["primary_email"] else "all visible")
            print(f"Workflow Map: {len(D['rows'])} projects, {D['n_sessions']} Code + {D['n_cowork']} Cowork sessions; app on {cur}; {state}. Most recent: {recent}. Full map: {CFG.get('output_md', HERE / '00-WORKFLOW-MAP.md')}")
        log(f"wrote {CFG.get('output_html', HERE / '00-WORKFLOW-MAP.html')}: {len(D['rows'])} projects, {D['n_sessions']} desktop sessions, {D['n_cowork']} cowork sessions")
    except Exception:
        (HERE / "last-run.log").write_text("ERROR " + NOW.isoformat() + "\n" + traceback.format_exc(), encoding="utf-8")
        if VERBOSE:
            raise


if __name__ == "__main__":
    main()

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
import json, os, re, sys, glob, datetime, traceback, html
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
            files = list(org_dir.glob("local_*.json"))
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


def load_index_sessions(accts):
    """All desktop sessions from every account. Returns list of dicts."""
    out = []
    for key, info in accts.items():
        for f in info["index_dir"].glob("local_*.json"):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            out.append({
                "cwd": d.get("cwd") or "", "title": d.get("title") or "", "cli": d.get("cliSessionId") or "",
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
    return dict(accts=accts, current_key=current_key, current_info=current_info, rows=rows, tasks=tasks,
                primary_email=primary_email, n_sessions=len(sessions), n_cowork=len(cowork), cowork=cowork_list)


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
    if cur and cur.get("email") != D["primary_email"]:
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

    A("\n## Global pieces (shared by every project and every account)\n")
    for label, path in CFG.get("global_pieces", []):
        A(f"- **{label}**: `{path}`")
    A("\n## Renames on record\n")
    for old, new in CFG.get("aliases", {}).items():
        A(f"- {old} is now **{new}**")
    return "\n".join(L) + "\n"


def render_html(D):
    E = lambda s: html.escape(str(s), quote=True)
    cur = D["current_info"] or {}
    cur_email = cur.get("email")
    on_primary = cur_email == D["primary_email"]
    hidden_total = sum(1 for r in D["rows"] for s in r["work"] if s["email"] not in (cur_email, "terminal"))
    hidden_cw = sum(1 for c in D["cowork"] if c["email"] != cur_email)

    def ago(dt):
        if not dt:
            return "never"
        d = (NOW - dt).days
        if d <= 0:
            return "today"
        if d == 1:
            return "yesterday"
        if d < 14:
            return f"{d} days ago"
        if d < 60:
            return f"{d // 7} weeks ago"
        return f"{d // 30} months ago"

    def acct_note(email):
        if email in (cur_email, "terminal"):
            return ""
        return f'<span class="needs">needs {E(email)}</span>'

    def sess_line(s, kind="code"):
        if kind == "cowork":
            how = '<span class="k k-cw">Claude tab</span>'
        elif kind == "elsewhere":
            how = f'<span class="k k-from">opened in {E(s["from"][:24])}</span>'
        else:
            how = ""
        can_resume = kind != "cowork" and s.get("kind", "code") == "code" and s.get("cli")
        cmd = f'<button class="copy" data-copy="claude --resume {E(s["cli"])}" title="Copy the resume command">copy resume</button>' if can_resume else ""
        return (f'<li><span class="when">{E(ago(s["last"]))}</span><span class="what">{how}{E(s["title"][:70]) or "(untitled)"}</span>'
                f'<span class="act">{cmd}{acct_note(s["email"])}</span></li>')

    order = CFG.get("group_order", [])
    groups, renamed = {}, []
    for r in D["rows"]:
        if r["alias_to"]:
            renamed.append(r)
            continue
        groups.setdefault(r["group"] or "Other", []).append(r)
    group_names = [g for g in order if g in groups] + [g for g in groups if g not in order]

    def card(r):
        pick = r["work"][0] if r["work"] else (r["cowork"][0] if r["cowork"] else None)
        pick_kind = "code" if r["work"] else "cowork"
        folder = ROOT / r["name"]
        if not r["exists"]:
            head = f'<h3><s>{E(r["name"])}</s></h3><p class="desc warn-inline">Folder is gone and no rename is recorded. If you renamed it, add it to aliases in config.json.</p>'
        else:
            head = f'<h3>{E(r["name"])}</h3><p class="desc">{E(r["note"]) or "No description yet. Add one in config.json."}</p>'
        if pick:
            btn = ""
            if pick_kind == "code" and pick.get("cli"):
                cmd = f'cd "{folder}" && claude --resume {pick["cli"]}'
                btn = f'<button class="copy primary" data-copy="{E(cmd)}">Copy resume command</button>'
            tag = "" if pick_kind == "code" else ' <span class="k-cw-inline">Claude tab</span>'
            resume = (f'<div class="pickup"><div class="lbl">Pick up here</div><div class="pick-title">{E(pick["title"][:80]) or "(untitled)"}{tag}</div>'
                      f'<div class="pick-meta">{E(ago(pick["last"]))}{acct_note(pick["email"])}</div>{btn}</div>')
        else:
            resume = '<div class="pickup"><div class="lbl">Pick up here</div><div class="pick-meta">No session has been opened in this folder yet. Start one from New session.</div></div>'
        files = "".join(f'<div class="file">{E(f)}</div>' for f in r["state"][:3]) or '<div class="dim">no state file</div>'
        read = f'<div class="read"><div class="lbl">Read first</div>{files}</div>'
        n_all = r["n_work"] + r["n_cowork"] + r["n_elsewhere"]
        details = ""
        if n_all:
            items = ("".join(sess_line(s) for s in r["work"]) + "".join(sess_line(s, "cowork") for s in r["cowork"])
                     + "".join(sess_line(s, "elsewhere") for s in r["elsewhere"]))
            more = []
            if r["n_work"] > len(r["work"]): more.append(f'{r["n_work"] - len(r["work"])} more in this folder')
            if r["n_cowork"] > len(r["cowork"]): more.append(f'{r["n_cowork"] - len(r["cowork"])} more Claude-tab')
            if r["n_elsewhere"] > len(r["elsewhere"]): more.append(f'{r["n_elsewhere"] - len(r["elsewhere"])} more from other folders')
            more_html = f'<div class="dim">and {", ".join(more)}</div>' if more else ""
            details = f'<details><summary>All sessions <span class="cnt">{n_all}</span></summary><ul class="sess-list">{items}</ul>{more_html}</details>'
        meta_bits = [b for b in [f'{r["n_mem"]} memory notes' if r["n_mem"] else "", f'{r["n_auto"]} automation runs' if r["n_auto"] else ""] if b]
        meta = f'<div class="meta">{E(" · ".join(meta_bits))}</div>' if meta_bits else ""
        search = (r["name"] + " " + r["note"] + " " + " ".join(s["title"] for s in r["work"] + r["cowork"])).lower()
        return (f'<article class="card" data-search="{E(search)}">'
                f'<div class="card-top"><span class="ago">{E(ago(r["last"]))}</span><span class="path" title="{E(str(folder))}">{E(str(folder))}</span></div>'
                f'{head}<div class="card-body">{resume}{read}</div>{details}{meta}</article>')

    sections = "".join(
        f'<section><h2>{E(g)} <small>{len(groups[g])}</small></h2><div class="grid">{"".join(card(r) for r in groups[g])}</div></section>'
        for g in group_names)

    if on_primary:
        banner = (f'<div class="banner ok"><div class="banner-k">You are set</div><div class="banner-v">The app was last used as <b>{E(cur_email)}</b>. '
                  f'Every session below is reachable from the sidebar.</div></div>')
    else:
        banner = (f'<div class="banner bad"><div class="banner-k">Wrong account</div><div class="banner-v">The app was last used as <b>{E(cur_email or "?")}</b>. '
                  f'{hidden_total} Code sessions and {hidden_cw} Claude-tab sessions below belong to <b>{E(D["primary_email"])}</b> and will not show in the sidebar '
                  f'until you sign in as that account. Nothing is deleted. Anything marked <span class="needs">needs {E(D["primary_email"])}</span> is one of those.</div></div>')

    acct_cards = ""
    for key, info in sorted(D["accts"].items(), key=lambda kv: -kv[1]["last_active"]):
        n_cw = sum(1 for c in D["cowork"] if c["acct"] == key)
        if not info["n_sessions"] and not n_cw:
            continue
        last = ago(datetime.datetime.fromtimestamp(info["last_active"])) if info["last_active"] else "never"
        now = '<div class="acct-now">app is on this one</div>' if key == D["current_key"] else ""
        acct_cards += (f'<div class="acct-card {"is-current" if key == D["current_key"] else ""}"><div class="acct-email">{E(info["email"])}</div>'
                       f'<div class="acct-meta">{info["n_sessions"]} Code sessions · {n_cw} Claude-tab sessions · last used {E(last)}</div>{now}</div>')

    loose = [c for c in D["cowork"] if not c["folders"]]
    loose_html = "".join(f'<li><span class="when">{E(ago(c["last"]))}</span><span class="what">{E(c["title"][:70]) or "(untitled)"}</span><span class="act">{acct_note(c["email"])}</span></li>' for c in loose)

    task_html = ""
    for name, desc, reg in D["tasks"]:
        if reg:
            for email, en, lr, cwd in reg:
                task_html += (f'<li><span class="pill {"on" if en else "off"}">{"on" if en else "off"}</span>'
                              f'<span class="what"><b>{E(name)}</b> <span class="dim">{E(desc[:90])}</span></span>'
                              f'<span class="act">{acct_note(email) or E(email)}</span></li>')
        else:
            task_html += f'<li><span class="pill off">none</span><span class="what"><b>{E(name)}</b> <span class="dim">{E(desc[:90])}</span></span><span class="act dim">not registered</span></li>'

    renamed_html = "".join(f'<li><s>{E(r["name"])}</s> is now <b>{E(r["alias_to"])}</b></li>' for r in renamed)
    globals_html = "".join(f'<li><span class="what"><b>{E(l)}</b></span><code>{E(p)}</code></li>' for l, p in CFG.get("global_pieces", []))

    css = CSS_V2
    js = JS_V2
    stamp = NOW.strftime("%a %b %d, %H:%M")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Workflow Map</title>'
            f'<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Source+Sans+3:wght@400;600;700&family=JetBrains+Mono:wght@400&display=swap">'
            f'<style>{css}</style></head><body><div class="wrap">'
            f'<p class="eyebrow">Every project on this computer, what it is, and where to pick it up</p>'
            f'<h1>Workflow Map</h1>'
            f'<p class="sub">Updated {stamp}. Rebuilds itself whenever a Claude session starts or ends. Each card says what the project is, which file to read first, and the session to resume. '
            f'"Copy resume command" puts a terminal command on your clipboard that reopens that exact session in that folder.</p>'
            f'{banner}<div class="accts">{acct_cards}</div>'
            f'<div class="toolbar"><input id="q" type="search" placeholder="Find a project or session, e.g. valorant, priced in, medkit" aria-label="Search projects"></div>'
            f'{sections}'
            f'<section><h2>Claude-tab sessions with no project folder <small>{len(loose)}</small></h2><ul class="plain">{loose_html or "<li class=dim>none</li>"}</ul></section>'
            f'<section><h2>Automations <small>only run on the account they belong to</small></h2><ul class="plain">{task_html}</ul></section>'
            f'<section><h2>Renamed folders</h2><ul class="plain simple">{renamed_html or "<li class=dim>none on record</li>"}</ul></section>'
            f'<section><h2>Shared by every project</h2><ul class="plain">{globals_html}</ul></section>'
            f'<p class="foot">This page is <code>{E(str(CFG.get("output_html", HERE / "00-WORKFLOW-MAP.html")))}</code>. The builder and its config live in <code>{E(str(HERE))}</code>. '
            f'Edit <code>config.json</code> to change a project\'s description or group, or to record a rename.</p>'
            f'</div><script>{js}</script></body></html>')


CSS_V2 = """
:root{--bg:#EEF1F5;--surface:#FFFFFF;--surface-2:#F6F8FA;--ink:#16202B;--mute:#5B6B7A;--line:#D5DCE4;--acc:#1F6F8B;--acc-ink:#FFFFFF;
--ok-bg:#DDF3E4;--ok-ink:#155F3A;--bad-bg:#FBE9E2;--bad-ink:#8A2E12;--warn-bg:#FFF1D6;--warn-ink:#7A4E00;--code-bg:#E9EEF3;--chip-bg:#E3EEF2;--chip-ink:#1F6F8B}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0F1519;--surface:#172028;--surface-2:#1C2731;--ink:#E6ECF1;--mute:#9AAAB8;--line:#2A3641;--acc:#5FB3CF;--acc-ink:#0F1519;
--ok-bg:#153A28;--ok-ink:#9FE1B8;--bad-bg:#4A1F12;--bad-ink:#FFC3AE;--warn-bg:#3A2A08;--warn-ink:#F2C879;--code-bg:#202B35;--chip-bg:#1E3540;--chip-ink:#8FD0E4}}
:root[data-theme="dark"]{--bg:#0F1519;--surface:#172028;--surface-2:#1C2731;--ink:#E6ECF1;--mute:#9AAAB8;--line:#2A3641;--acc:#5FB3CF;--acc-ink:#0F1519;
--ok-bg:#153A28;--ok-ink:#9FE1B8;--bad-bg:#4A1F12;--bad-ink:#FFC3AE;--warn-bg:#3A2A08;--warn-ink:#F2C879;--code-bg:#202B35;--chip-bg:#1E3540;--chip-ink:#8FD0E4}
*{box-sizing:border-box}html,body{margin:0}
body{background:var(--bg);color:var(--ink);font:15px/1.45 "Source Sans 3","Segoe UI",system-ui,sans-serif;padding-block:24px 56px;padding-inline:16px}
.wrap{max-width:1320px;margin:0 auto}
h1,h2,h3,.banner-k,.lbl,.k,.chip,.eyebrow,.acct-now,.pill,.k-cw-inline{font-family:"Barlow Condensed","Arial Narrow",sans-serif}
h1{font-size:40px;font-weight:700;line-height:1;margin:0;text-wrap:balance}
.eyebrow{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin:0 0 6px}
.sub{color:var(--mute);margin:8px 0 0;max-width:72ch}
.toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:22px 0 6px}
.toolbar input{flex:1 1 280px;font:inherit;padding:10px 14px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink)}
.toolbar input:focus{outline:2px solid var(--acc);outline-offset:1px}
.banner{display:grid;grid-template-columns:auto 1fr;gap:16px;align-items:start;margin:18px 0 0;padding:16px 18px;border-radius:10px}
.banner-k{font-size:14px;letter-spacing:.12em;text-transform:uppercase;padding-top:3px;white-space:nowrap}
.banner.ok{background:var(--ok-bg);color:var(--ok-ink)}.banner.bad{background:var(--bad-bg);color:var(--bad-ink)}
.banner-v{font-size:16px;line-height:1.45}
.accts{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-top:12px}
.acct-card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.acct-card.is-current{border-color:var(--acc);box-shadow:inset 3px 0 0 var(--acc)}
.acct-email{font-weight:700}.acct-meta{color:var(--mute);font-size:13.5px;margin-top:2px}
.acct-now{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--acc);margin-top:6px}
section{margin-top:34px}
h2{font-size:24px;font-weight:600;margin:0 0 10px;display:flex;align-items:baseline;gap:10px}
h2 small{font:600 13px/1 "Barlow Condensed",sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--mute)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px 12px;display:flex;flex-direction:column;gap:10px}
.card.hide{display:none}
.card-top{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;color:var(--mute)}
.card-top .ago{font-weight:600;color:var(--acc);letter-spacing:.02em;white-space:nowrap}
.card-top .path{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:"JetBrains Mono",Consolas,monospace;font-size:11.5px}
h3{font-size:23px;font-weight:700;margin:0;line-height:1.1}
.desc{margin:0;color:var(--ink);font-size:14.5px;line-height:1.4}
.card-body{display:grid;grid-template-columns:1fr;gap:10px}
.pickup,.read{background:var(--surface-2);border-radius:8px;padding:10px 12px}
.lbl{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--mute);margin-bottom:4px}
.pick-title{font-weight:600;line-height:1.3}
.pick-meta{color:var(--mute);font-size:13px;margin-top:2px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.file{font-family:"JetBrains Mono",Consolas,monospace;font-size:12.5px;margin:2px 0;word-break:break-all}
.copy{font:600 12.5px/1 "Source Sans 3",system-ui,sans-serif;border:1px solid var(--line);background:var(--surface);color:var(--acc);padding:6px 10px;border-radius:6px;cursor:pointer}
.copy.primary{margin-top:8px;background:var(--acc);color:var(--acc-ink);border-color:var(--acc)}
.copy:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.copy.done{background:var(--ok-bg);color:var(--ok-ink);border-color:transparent}
details{border-top:1px solid var(--line);padding-top:8px}
summary{cursor:pointer;font-weight:600;color:var(--mute);font-size:13.5px;list-style:none;display:flex;gap:8px;align-items:center}
summary::-webkit-details-marker{display:none}
summary::before{content:"";display:inline-block;width:0;height:0;border:5px solid transparent;border-left-color:var(--mute);transition:transform .15s}
details[open] summary::before{transform:rotate(90deg)}
.cnt{background:var(--code-bg);border-radius:999px;padding:1px 8px;font-size:12px}
.sess-list{list-style:none;margin:8px 0 0;padding:0;display:grid;gap:6px}
.sess-list li,.plain li{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;font-size:13.5px}
.sess-list .when,.plain .when{color:var(--mute);white-space:nowrap;font-size:12.5px;min-width:86px}
.sess-list .what,.plain .what{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.act{display:flex;gap:8px;align-items:center;white-space:nowrap}
.k{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;padding:2px 6px;border-radius:3px;margin-right:6px;vertical-align:1px}
.k-cw{background:var(--chip-bg);color:var(--chip-ink)}
.k-cw-inline{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;padding:2px 6px;border-radius:3px;vertical-align:2px;background:var(--chip-bg);color:var(--chip-ink)}
.k-from{background:var(--code-bg);color:var(--mute)}
.needs{font-size:12px;background:var(--warn-bg);color:var(--warn-ink);padding:2px 7px;border-radius:4px;white-space:nowrap}
.chip{display:inline-block;font-size:12px;letter-spacing:.06em;text-transform:uppercase;background:var(--chip-bg);color:var(--chip-ink);padding:2px 7px;border-radius:4px}
.meta{color:var(--mute);font-size:12.5px}.dim{color:var(--mute);font-size:13px}.warn-inline{color:var(--warn-ink)}
.plain{list-style:none;margin:0;display:grid;gap:8px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.plain code{font-family:"JetBrains Mono",Consolas,monospace;font-size:12px;background:var(--code-bg);padding:2px 6px;border-radius:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%}
.plain.simple li{display:block}
.pill{display:inline-block;font-size:12px;letter-spacing:.08em;text-transform:uppercase;padding:2px 9px;border-radius:999px;background:var(--code-bg);min-width:44px;text-align:center}
.pill.on{background:var(--ok-bg);color:var(--ok-ink)}.pill.off{background:var(--bad-bg);color:var(--bad-ink)}
.foot{color:var(--mute);font-size:13px;margin-top:40px;border-top:1px solid var(--line);padding-top:12px;max-width:80ch}
code{font-family:"JetBrains Mono",Consolas,monospace;font-size:12.5px;background:var(--code-bg);padding:1px 5px;border-radius:4px}
s{color:var(--mute)}
@media(max-width:700px){h1{font-size:32px}.banner{grid-template-columns:1fr}.grid{grid-template-columns:1fr}.sess-list li,.plain li{grid-template-columns:1fr;gap:2px}.act{white-space:normal}}
@media(prefers-reduced-motion:reduce){summary::before{transition:none}}
"""

JS_V2 = """
document.querySelectorAll('.copy').forEach(function(b){b.addEventListener('click',async function(){try{await navigator.clipboard.writeText(b.dataset.copy);b.classList.add('done');var t=b.textContent;b.textContent='Copied';setTimeout(function(){b.classList.remove('done');b.textContent=t},1400)}catch(e){prompt('Copy this:',b.dataset.copy)}})});
var q=document.getElementById('q');q.addEventListener('input',function(){var v=q.value.trim().toLowerCase();document.querySelectorAll('.card').forEach(function(c){c.classList.toggle('hide',!!v&&c.dataset.search.indexOf(v)<0)});document.querySelectorAll('section').forEach(function(s){if(!s.querySelector('.card'))return;var any=Array.prototype.some.call(s.querySelectorAll('.card'),function(c){return !c.classList.contains('hide')});s.style.display=any?'':'none'})});
"""


def main():
    try:
        D = build()
        md = render_md(D)
        Path(CFG.get("output_md", HERE / "00-WORKFLOW-MAP.md")).write_text(md, encoding="utf-8")
        Path(CFG.get("output_html", HERE / "00-WORKFLOW-MAP.html")).write_text(render_html(D), encoding="utf-8")
        (HERE / "last-run.log").write_text(f"ok {NOW.isoformat()} projects={len(D['rows'])} sessions={D['n_sessions']} app_as={(D['current_info'] or {}).get('email')}\n", encoding="utf-8")
        log(f"wrote {CFG.get('output_html', HERE / '00-WORKFLOW-MAP.html')}: {len(D['rows'])} projects, {D['n_sessions']} desktop sessions, {D['n_cowork']} cowork sessions")
    except Exception:
        (HERE / "last-run.log").write_text("ERROR " + NOW.isoformat() + "\n" + traceback.format_exc(), encoding="utf-8")
        if VERBOSE:
            raise


if __name__ == "__main__":
    main()

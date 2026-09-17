"""Full-text index of every conversation (user and assistant text only, no tool output).

SQLite FTS5, stored at history/search.sqlite next to the map. Incremental: a transcript is
re-read only when its size or mtime changed. Used by build-map.py (to update) and
search-server.py (to query). Nothing leaves the machine.
"""
import json, os, re, sqlite3, datetime
from pathlib import Path

SCHEMA = """
create table if not exists files(path text primary key, mtime real, size integer);
create virtual table if not exists msg using fts5(
    text, path unindexed, session unindexed, kind unindexed, project unindexed, account unindexed,
    ts unindexed, role unindexed, tokenize='porter unicode61');
create table if not exists docfiles(path text primary key, mtime real, size integer);
create virtual table if not exists doc using fts5(
    name, title, excerpt, path unindexed, project unindexed, mtime unindexed, tokenize='porter unicode61');
"""

TEXT_EXT = {".md", ".txt", ".html", ".htm", ".csv", ".json", ".py", ".js", ".cmd", ".bat", ".yaml", ".yml"}
NAME_ONLY_EXT = {".pdf", ".docx", ".pptx", ".xlsx", ".zip", ".png", ".jpg", ".jpeg", ".mp4", ".mp3", ".svg"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", "dist", ".next", ".claude", "build", ".cache", "site-packages"}


def _doc_title_excerpt(p):
    """Title and a short excerpt from a text file: <title>/h1 for html, first heading for md, first line otherwise."""
    try:
        head = open(p, encoding="utf-8", errors="replace").read(6000)
    except Exception:
        return "", ""
    ext = p.suffix.lower()
    title = ""
    if ext in (".html", ".htm"):
        m = re.search(r"<title[^>]*>(.*?)</title>", head, re.S | re.I) or re.search(r"<h1[^>]*>(.*?)</h1>", head, re.S | re.I)
        title = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
        body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", head, flags=re.S | re.I)
        body = re.sub(r"<[^>]+>", " ", body)
    else:
        m = re.search(r"^\s*#+\s+(.+)$", head, re.M)
        title = m.group(1) if m else ""
        body = re.sub(r"^---.*?---", " ", head, count=1, flags=re.S)  # front matter
        body = re.sub(r"[#*`>|_\-]{2,}", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return re.sub(r"\s+", " ", title).strip()[:160], body[:400]


def update_files(db_path, roots, log=lambda m: None, max_depth=5):
    """roots: {project_name: folder_path}. Indexes documents by name, title and excerpt. Incremental by mtime/size."""
    db = connect(db_path)
    known = {r[0]: (r[1], r[2]) for r in db.execute("select path, mtime, size from docfiles")}
    seen, n_new = set(), 0
    for project, root in roots.items():
        root = Path(root)
        if not root.exists():
            continue
        base = len(root.parts)
        for cur, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            if len(Path(cur).parts) - base >= max_depth:
                dirs[:] = []
            for fn in files:
                p = Path(cur) / fn
                ext = p.suffix.lower()
                if ext not in TEXT_EXT and ext not in NAME_ONLY_EXT:
                    continue
                try:
                    st = p.stat()
                except Exception:
                    continue
                k = str(p)
                seen.add(k)
                if known.get(k) == (st.st_mtime, st.st_size):
                    continue
                if ext in TEXT_EXT and st.st_size < 4_000_000:
                    title, excerpt = _doc_title_excerpt(p)
                else:
                    title, excerpt = "", ""
                rel = str(p.relative_to(root))
                db.execute("delete from doc where path = ?", (k,))
                db.execute("insert into doc(name, title, excerpt, path, project, mtime) values (?,?,?,?,?,?)",
                           (rel.replace("\\", " ").replace("/", " ").replace("-", " ").replace("_", " ") + " " + fn, title, excerpt, k, project, st.st_mtime))
                db.execute("insert or replace into docfiles(path, mtime, size) values (?,?,?)", (k, st.st_mtime, st.st_size))
                n_new += 1
    gone = [k for k in known if k not in seen]
    for k in gone:
        db.execute("delete from doc where path = ?", (k,))
        db.execute("delete from docfiles where path = ?", (k,))
    db.commit()
    total = db.execute("select count(*) from docfiles").fetchone()[0]
    db.close()
    log(f"file index: {n_new} documents (re)indexed, {len(gone)} removed, {total} on record")
    return n_new


def search_files(db_path, q, limit=40):
    fq = fts_query(q)
    if not fq:
        return []
    db = connect(db_path)
    try:
        rows = db.execute("select path, project, title, snippet(doc, 2, '\u2039', '\u203a', ' \u2026 ', 20), mtime, bm25(doc, 4.0, 3.0, 1.0) "
                          "from doc where doc match ? order by bm25(doc, 4.0, 3.0, 1.0) limit ?", (fq, limit)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    db.close()
    return [{"path": r[0], "project": r[1], "title": r[2], "snippet": r[3], "mtime": r[4]} for r in rows]



def connect(db_path):
    db = sqlite3.connect(str(db_path))
    db.executescript(SCHEMA)
    return db


def _text_of(d):
    c = d.get("message", {}).get("content")
    if isinstance(c, str):
        txt = c
    else:
        txt = "\n".join(x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text")
    txt = re.sub(r"<system-reminder>.*?</system-reminder>", " ", txt, flags=re.S)
    txt = re.sub(r"<[^>]{1,60}>", " ", txt)
    return re.sub(r"[ \t]+", " ", txt).strip()


def iter_messages(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except Exception:
                continue
            role = d.get("type")
            if role not in ("user", "assistant"):
                continue
            txt = _text_of(d)
            if not txt or txt.startswith("scheduled-task") or len(txt) < 2:
                continue
            ts = d.get("timestamp") or ""
            yield role, ts[:19].replace("T", " "), txt


def update_index(db_path, entries, log=lambda m: None):
    """entries: list of dicts {path, session, kind, project, account}. Returns (files_reindexed, messages_added)."""
    db = connect(db_path)
    known = {r[0]: (r[1], r[2]) for r in db.execute("select path, mtime, size from files")}
    seen, n_files, n_msgs = set(), 0, 0
    for e in entries:
        p = Path(e["path"])
        try:
            st = p.stat()
        except Exception:
            continue
        seen.add(str(p))
        if known.get(str(p)) == (st.st_mtime, st.st_size):
            continue
        db.execute("delete from msg where path = ?", (str(p),))
        rows = [(txt, str(p), e["session"], e["kind"], e["project"], e["account"], ts, role) for role, ts, txt in iter_messages(p)]
        db.executemany("insert into msg(text, path, session, kind, project, account, ts, role) values (?,?,?,?,?,?,?,?)", rows)
        db.execute("insert or replace into files(path, mtime, size) values (?,?,?)", (str(p), st.st_mtime, st.st_size))
        n_files += 1; n_msgs += len(rows)
    # transcripts that disappeared keep their rows: the index is part of the history
    db.commit()
    db.close()
    log(f"search index: {n_files} transcripts re-indexed, {n_msgs} messages added")
    return n_files, n_msgs


def fts_query(q):
    """Turn free text into a safe FTS5 query: every word required, last word as a prefix, phrases in quotes kept."""
    q = q.strip()
    if not q:
        return ""
    phrases = re.findall(r'"([^"]+)"', q)
    rest = re.sub(r'"[^"]*"', " ", q)
    words = [w for w in re.split(r"\s+", rest) if w]
    parts = [f'"{p}"' for p in phrases]
    for i, w in enumerate(words):
        w = w.replace('"', "")
        if not w:
            continue
        parts.append(f'"{w}"*' if i == len(words) - 1 and len(w) >= 3 else f'"{w}"')
    return " ".join(parts)


def search(db_path, q, limit_sessions=40, per_session=3):
    """Group hits by session. Returns list of {session, kind, project, account, hits, last_ts, snippets:[(role, ts, snippet)]}."""
    fq = fts_query(q)
    if not fq:
        return []
    db = connect(db_path)
    try:
        rows = db.execute(
            "select session, kind, project, account, ts, role, snippet(msg, 0, '‹', '›', ' … ', 28), bm25(msg) "
            "from msg where msg match ? order by bm25(msg) limit 600", (fq,)).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        db.close()
    groups = {}
    for session, kind, project, account, ts, role, snip, score in rows:
        g = groups.setdefault(session, {"session": session, "kind": kind, "project": project, "account": account,
                                        "hits": 0, "best": score, "last_ts": "", "snippets": []})
        g["hits"] += 1
        g["last_ts"] = max(g["last_ts"], ts or "")
        if len(g["snippets"]) < per_session:
            g["snippets"].append((role, ts, snip))
    out = sorted(groups.values(), key=lambda g: g["best"])
    return out[:limit_sessions]


def session_dialogue(db_path, session):
    """Every indexed message of one session, in order."""
    db = connect(db_path)
    rows = db.execute("select role, ts, text, project, kind, account from msg where session = ? order by rowid", (session,)).fetchall()
    db.close()
    return rows

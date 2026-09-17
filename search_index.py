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
"""


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

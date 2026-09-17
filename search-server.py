#!/usr/bin/env python3
"""Local conversation search for the Workflow Map.

    python search-server.py                 serve on http://127.0.0.1:27183 (stays up; the map talks to it)
    python search-server.py --query "text"  one-off search from a terminal or a Claude session
    python search-server.py --session ID    print one conversation

Listens on 127.0.0.1 only. Nothing leaves the machine.
"""
import argparse, html, json, os, sys, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import search_index  # noqa: E402

DB = HERE / "history" / "search.sqlite"
LEDGER = HERE / "history" / "ledger.json"
PORT = 27183
try:
    PORT = int(json.load(open(HERE / "config.json", encoding="utf-8")).get("search_port", 27183))
except Exception:
    pass


def titles():
    try:
        L = json.load(open(LEDGER, encoding="utf-8"))
        return {k: (v.get("title") or "") for k, v in L.items()}
    except Exception:
        return {}


def folder_of(g):
    p = g.get("project") or ""
    return os.path.basename(p) if p else ""


CSS = """
:root{--bg:#EEF1F5;--surface:#fff;--ink:#16202B;--mute:#5B6B7A;--line:#D5DCE4;--acc:#1F6F8B;--acc-ink:#fff;--hl:#FFF1B8;--code:#E9EEF3;--user:#E3EEF2;--asst:#F6F8FA}
@media(prefers-color-scheme:dark){:root{--bg:#0F1519;--surface:#172028;--ink:#E6ECF1;--mute:#9AAAB8;--line:#2A3641;--acc:#5FB3CF;--acc-ink:#0F1519;--hl:#5A4A00;--code:#202B35;--user:#1E3540;--asst:#1C2731}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 "Source Sans 3","Segoe UI",system-ui,sans-serif;padding:24px 16px 56px}
.wrap{max-width:960px;margin:0 auto}h1{font:700 32px/1 "Barlow Condensed","Arial Narrow",sans-serif;margin:0 0 12px}
form{display:flex;gap:8px;margin-bottom:16px}input{flex:1;font:inherit;padding:10px 14px;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink)}
button{font:600 14px system-ui;background:var(--acc);color:var(--acc-ink);border:0;border-radius:8px;padding:10px 16px;cursor:pointer}
.hit{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:10px 0}
.hit h3{margin:0 0 2px;font-size:17px}.hit h3 a{color:inherit;text-decoration:none}.hit h3 a:hover{text-decoration:underline}
.meta{color:var(--mute);font-size:12.5px;display:flex;gap:10px;flex-wrap:wrap}.snip{margin:8px 0 0;padding:6px 10px;border-left:3px solid var(--line);font-size:14px;color:var(--ink)}
.snip .r{color:var(--mute);font-size:12px;margin-right:6px;text-transform:uppercase;letter-spacing:.06em}mark{background:var(--hl);color:inherit;padding:0 2px;border-radius:2px}
code{font-family:Consolas,monospace;font-size:12.5px;background:var(--code);padding:1px 5px;border-radius:4px}
.turn{padding:12px 14px;border-radius:10px;margin:8px 0;white-space:pre-wrap;word-wrap:break-word}.turn.user{background:var(--user)}.turn.assistant{background:var(--asst)}
.turn .who{font:600 12px system-ui;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin-bottom:4px}
.dim{color:var(--mute)}a{color:var(--acc)}
"""


def page(title, body):
    return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class='wrap'>{body}</div></body></html>"


def mark(snip):
    return html.escape(snip).replace("‹", "<mark>").replace("›", "</mark>")


def render_results(q, results, T):
    body = [f"<h1>Conversation search</h1><form method='get' action='/'><input name='q' value='{html.escape(q)}' placeholder='Search inside every conversation' autofocus><button>Search</button></form>"]
    if q and not results:
        body.append("<p class='dim'>Nothing matched. Fewer words, or a phrase in quotes.</p>")
    for g in results:
        t = T.get(g["session"], "") or "(untitled)"
        resume = f"<code>claude --resume {html.escape(g['session'])}</code>" if g["kind"] in ("code", "terminal") else "<span class='dim'>Claude-tab session</span>"
        body.append(f"<div class='hit'><h3><a href='/session?id={urllib.parse.quote(g['session'])}'>{html.escape(t)}</a></h3>"
                    f"<div class='meta'><span>{html.escape(g['last_ts'][:16])}</span><span>{html.escape(folder_of(g))}</span><span>{html.escape(g['account'] or '')}</span><span>{g['hits']} matching messages</span>{resume}</div>"
                    + "".join(f"<div class='snip'><span class='r'>{html.escape(r)}</span>{mark(s)}</div>" for r, ts, s in g["snippets"]) + "</div>")
    return page("Conversation search", "".join(body))


def render_session(sid, T):
    rows = search_index.session_dialogue(DB, sid)
    t = T.get(sid, "") or "(untitled)"
    if not rows:
        return page(t, f"<h1>{html.escape(t)}</h1><p class='dim'>No indexed dialogue for this session.</p>")
    meta = rows[0]
    head = (f"<p><a href='/'>&larr; search</a></p><h1>{html.escape(t)}</h1><div class='meta'><span>{html.escape(os.path.basename(meta[3] or ''))}</span>"
            f"<span>{html.escape(meta[5] or '')}</span><span>{len(rows)} messages</span><span class='dim'>tool calls and file contents omitted</span></div>")
    turns = "".join(f"<div class='turn {html.escape(r)}'><div class='who'>{'You' if r == 'user' else 'Claude'} <span class='dim'>{html.escape(ts)}</span></div>{html.escape(txt)}</div>" for r, ts, txt, *_ in rows)
    return page(t, head + turns)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        q = (qs.get("q") or [""])[0]
        T = titles()
        if u.path == "/ping":
            return self._send('{"ok":true}', "application/json")
        if u.path == "/map":
            try:
                cfg = json.load(open(HERE / "config.json", encoding="utf-8"))
                page_path = Path(cfg.get("output_html", HERE / "00-WORKFLOW-MAP.html"))
                return self._send(page_path.read_text(encoding="utf-8"))
            except Exception as e:
                return self._send(page("Map", f"<p>Map not built yet: {html.escape(str(e))}</p>"), code=404)
        if u.path == "/search":
            res = search_index.search(DB, q)
            for g in res:
                g["title"] = T.get(g["session"], "") or "(untitled)"
                g["folder"] = folder_of(g)
                g["snippets"] = [{"role": r, "ts": ts, "html": mark(s)} for r, ts, s in g["snippets"]]
                g.pop("best", None)
            return self._send(json.dumps(res, ensure_ascii=False), "application/json")
        if u.path == "/session":
            return self._send(render_session((qs.get("id") or [""])[0], T))
        return self._send(render_results(q, search_index.search(DB, q) if q else [], T))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query")
    ap.add_argument("--session")
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    if a.query:
        T = titles()
        for g in search_index.search(DB, a.query, limit_sessions=15):
            print(f"{g['last_ts'][:16]}  {T.get(g['session'], '') or '(untitled)'}  [{folder_of(g)}] [{g['kind']}] {g['hits']} hits  id={g['session']}")
            for r, ts, s in g["snippets"]:
                print(f"    {r:9s} {s.replace(chr(0x2039), '[').replace(chr(0x203a), ']')}")
        return
    if a.session:
        for r, ts, txt, *_ in search_index.session_dialogue(DB, a.session):
            print(f"--- {r} {ts}\n{txt}\n")
        return
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), H)
    print(f"conversation search on http://127.0.0.1:{a.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()

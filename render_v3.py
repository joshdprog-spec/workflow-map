# Workflow Map page renderer, version 3: an app shell with views, driven by one embedded JSON blob.
# Imported by build-map.py. Python gathers; the page renders itself.
import json, html, datetime, os
from pathlib import Path


def _iso(dt):
    return dt.isoformat(timespec="minutes") if dt else ""


def _sess(s):
    return {"t": s.get("title", ""), "id": s.get("cli", ""), "d": _iso(s.get("last")), "a": s.get("email", ""), "k": s.get("kind", "code"),
            "from": s.get("from", "")}


def _norm(t):
    return " ".join(w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in str(t)).split())


def _match_arts(name, arts, extra_words=""):
    """Artifacts whose 'project' field or title shares a distinctive word (4+ letters) with the name."""
    generic = {"the", "system", "audit", "deep", "team", "with", "your", "page", "pages", "list", "screen", "screens", "every", "channel", "channels",
               "hours", "price", "find", "real", "steps", "little", "friend", "keeps", "open", "themselves", "own", "full", "planner", "weekly", "master", "app"}
    words = {w for w in _norm(name + " " + extra_words).split() if len(w) >= 4 and w not in generic}
    out = []
    for a in arts:
        hay = _norm((a.get("project") or "") + " " + (a.get("title") or ""))
        hay_words = set(hay.split())
        if words & hay_words or any(w in hay.replace(" ", "") for w in words if len(w) >= 7):
            out.append({"title": a.get("title", ""), "url": a.get("url", ""), "account": a.get("account", ""), "updated": a.get("updated", ""), "m": a.get("m", "")})
    return out


def _data_uri(path, limit=600_000):
    """Small images are baked into the page so they show anywhere; larger ones are left as a path (served locally)."""
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size > limit:
            return ""
        import base64
        ext = p.suffix.lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml"}.get(ext, "image/png")
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
    except Exception:
        return ""


def build_data(D, CFG, HERE, NOW, ROOT):
    cur = D["current_info"] or {}
    cur_email = cur.get("email")
    mirror = bool(CFG.get("mirror_sessions"))
    hidden_code = sum(1 for r in D["rows"] for s in r["work"] if s["email"] not in (cur_email, "terminal"))
    hidden_cw = sum(1 for c in D["cowork"] if c["email"] != cur_email)
    accounts = []
    for key, info in sorted(D["accts"].items(), key=lambda kv: -kv[1]["last_active"]):
        n_cw = sum(1 for c in D["cowork"] if c["acct"] == key)
        if not info["n_sessions"] and not n_cw:
            continue
        accounts.append({"email": info["email"], "org": info["org_name"], "plan": info["plan"], "n_code": info["n_sessions"], "n_cowork": n_cw,
                         "last": _iso(datetime.datetime.fromtimestamp(info["last_active"])) if info["last_active"] else "", "current": key == D["current_key"]})
    projects = []
    for r in D["rows"]:
        projects.append({
            "name": r["name"], "exists": r["exists"], "alias_to": r["alias_to"], "group": r["group"] or "Other", "note": r["note"],
            "last": _iso(r["last"]), "touched": _iso(r["touched"]), "folder": str(ROOT / r["name"]), "state": r["state"][:4],
            "work": [_sess(s) for s in r["work"]], "cowork": [_sess(dict(s, kind="cowork")) for s in r["cowork"]],
            "elsewhere": [_sess(s) for s in r["elsewhere"]], "n_work": r["n_work"], "n_cowork": r["n_cowork"], "n_elsewhere": r["n_elsewhere"],
            "n_mem": r["n_mem"], "n_auto": r["n_auto"], "arts": _match_arts(r["name"] + " " + (r["alias_to"] or ""), CFG.get("artifacts", [])),
            "thumb": _data_uri(D.get("thumbs", {}).get("projects", {}).get(r["name"], ""))})
    # connectors: what each account's newest sessions were started with = what a new session gets today
    _now = {}
    _conn = {}
    for s in D.get("sessions", []):
        if s.get("cli"):
            _conn[s["cli"]] = {c.lower(): c for c in (s.get("connectors") or [])}
    for email in {s.get("email") for s in D.get("sessions", [])}:
        fresh = sorted([s for s in D.get("sessions", []) if s.get("email") == email and s.get("connectors")],
                       key=lambda s: s.get("created") or datetime.datetime.min, reverse=True)[:5]
        acc = {}
        for s in fresh:
            for c in s["connectors"]:
                acc.setdefault(c.lower(), c)
        _now[email] = acc
    _auto = [p.lower() for p in CFG.get("automation_title_patterns", [])]
    ledger = []
    try:
        L = json.load(open(HERE / "history" / "ledger.json", encoding="utf-8"))
        for sid, e in L.items():
            folder = os.path.basename(e.get("cwd", "")) if e.get("cwd") else ", ".join(e.get("folders", [])[:3])
            if not folder and e.get("project_slug"):
                folder = e["project_slug"].split("-")[-1]
            born = e.get("account") or (e.get("accounts") or [""])[0]
            have = _conn.get(sid)
            miss = sorted([v for k, v in _now.get(born, {}).items() if k not in have], key=str.lower) if have is not None and e.get("kind") == "code" else []
            t_ = (e.get("title") or "").lower()
            ledger.append({"id": sid, "t": e.get("title", ""), "d": (e.get("last_activity") or "")[:16], "f": folder, "a": ", ".join(e.get("accounts", [])),
                           "k": e.get("kind", ""), "r": e.get("kind") in ("code", "terminal"), "b": born, "x": miss,
                           "u": 1 if any(p in t_ for p in _auto) else 0})
        ledger.sort(key=lambda r: r["d"], reverse=True)
    except Exception:
        pass
    tasks = []
    for name, desc, reg in D["tasks"]:
        if reg:
            for email, en, lr, cwd in reg:
                tasks.append({"name": name, "desc": desc, "email": email, "on": bool(en), "last": str(lr)[:16], "cwd": cwd})
        else:
            tasks.append({"name": name, "desc": desc, "email": "", "on": False, "last": "", "cwd": ""})
    outputs = [{"t": o["title"], "a": o["account"], "d": _iso(o["last"]), "folders": o["folders"], "dir": o["dir"], "files": o["files"],
                "thumb": _data_uri(D.get("thumbs", {}).get("deliverables", {}).get(o["dir"], ""))} for o in D.get("cowork_outputs", [])]
    cps = [{"name": x["name"], "desc": x["description"], "a": x["account"], "docs": x["docs"], "synced": x["synced"]} for x in D.get("claude_projects", [])]
    loose = [_sess(dict(c, kind="cowork")) for c in D["cowork"] if not c["folders"]]
    products = [{"name": x["name"], "stage": x["stage"], "project": x["project"], "folder": x["folder"], "where": x["where"], "page": x["page"], "tags": x.get("tags", ""),
                 "arts": _match_arts(x["name"], CFG.get("artifacts", [])), "thumb": _data_uri(D.get("thumbs", {}).get("products", {}).get(x["folder"], "")),
                 "ship_kit": x["ship_kit"], "offer": x["offer"], "course": x["course"], "bundle": x["bundle"], "last": _iso(x["last"]), "n_files": x["n_files"]}
                for x in D.get("products", [])]
    # other machines
    machines = []
    for m in D.get("machines", []):
        data = m.get("data", {})
        for sid, e in m.get("ledger", {}).items():
            folder = os.path.basename(e.get("cwd", "")) if e.get("cwd") else ", ".join(e.get("folders", [])[:3])
            ledger.append({"id": sid, "t": e.get("title", ""), "d": (e.get("last_activity") or "")[:16], "f": folder, "a": ", ".join(e.get("accounts", [])),
                           "k": e.get("kind", ""), "r": False, "m": m["name"]})
        for p in data.get("products", []):
            products.append(dict(p, m=m["name"], tags=p.get("tags", "")))
        for a in data.get("artifacts", []):
            if a.get("url") not in {x.get("url") for x in CFG.get("artifacts", [])}:
                pass
        for x in data.get("claude_projects", []):
            cps.append({"name": x["name"], "desc": x.get("description", ""), "a": x.get("account", ""), "docs": x.get("docs", []), "synced": x.get("synced", ""), "m": m["name"]})
        for o in data.get("outputs", []):
            outputs.append({"t": o["title"], "a": o["account"], "d": o.get("last", ""), "folders": o.get("folders", []), "dir": o.get("dir", ""), "files": o.get("files", []), "m": m["name"]})
        for a in data.get("accounts", []):
            if not any(x["email"] == a["email"] for x in accounts):
                accounts.append({"email": a["email"], "org": a.get("org", ""), "plan": a.get("plan", ""), "n_code": a.get("n_code", 0), "n_cowork": 0, "last": "", "current": False, "m": m["name"]})
        machines.append({"name": m["name"], "stamp": m.get("stamp", ""), "n": len(m.get("ledger", {})), "path": m.get("path", "")})
    ledger.sort(key=lambda r: r["d"], reverse=True)
    remote_arts = []
    for m in D.get("machines", []):
        for a in m.get("data", {}).get("artifacts", []):
            if a.get("url") not in {x.get("url") for x in CFG.get("artifacts", [])} and a.get("url") not in {x.get("url") for x in remote_arts}:
                remote_arts.append(dict(a, m=m["name"]))
    return {
        "meta": {"stamp": NOW.strftime("%a %b %d, %H:%M"), "n_projects": len(D["rows"]), "n_code": D["n_sessions"], "n_cowork": D["n_cowork"], "machine": D.get("machine", ""), "machines": machines,
                 "port": D.get("search_port", 27183), "primary": D["primary_email"], "current": cur_email, "mirror": mirror,
                 "hidden_code": hidden_code, "hidden_cw": hidden_cw, "ledger_n": len(ledger), "map_html": str(CFG.get("output_html", HERE / "00-WORKFLOW-MAP.html")),
                 "here": str(HERE), "group_order": CFG.get("group_order", [])},
        "accounts": accounts, "projects": projects, "ledger": ledger, "loose": loose, "tasks": tasks, "outputs": outputs, "claude_projects": cps, "products": products,
        "artifacts": CFG.get("artifacts", []) + remote_arts, "aliases": CFG.get("aliases", {}), "globals": CFG.get("global_pieces", []),
    }


def render_html(D, CFG, HERE, NOW, ROOT):
    data = build_data(D, CFG, HERE, NOW, ROOT)
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (SHELL.replace("{{DATA}}", blob).replace("{{CSS}}", CSS).replace("{{JS}}", JS)
            .replace("{{STAMP}}", html.escape(data["meta"]["stamp"])))


SHELL = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Workflow Map</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Sora:wght@500;600;700&family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>{{CSS}}</style></head>
<body>
<div class="app">
  <nav class="rail" aria-label="Sections">
    <div class="brand"><span class="brand-mark"></span><span class="brand-name">Workflow Map</span></div>
    <a href="#home" data-view="home"><span class="ico">&#9638;</span>Map</a>
    <a href="#projects" data-view="projects"><span class="ico">&#9781;</span>Tree</a>
    <a href="#glance" data-view="glance"><span class="ico">&#9783;</span>Table</a>
    <a href="#sessions" data-view="sessions"><span class="ico">&#9776;</span>Timeline</a>
    <a href="#assets" data-view="assets"><span class="ico">&#9670;</span>Assets</a>
    <a href="#automations" data-view="automations"><span class="ico">&#8635;</span>Automations</a>
    <div class="rail-foot"><span id="stamp">{{STAMP}}</span><br><span class="dim">rebuilds itself</span></div>
  </nav>
  <main class="main">
    <header class="topbar">
      <div class="search-wrap"><span class="search-ico">&#8981;</span><input id="q" type="search" placeholder="Filter this view &middot; Enter searches inside every conversation" aria-label="Search" autocomplete="off"><kbd>/</kbd></div>
      <div id="acct-pill" class="pill"></div>
    </header>
    <section id="view-home" class="view"></section>
    <section id="view-glance" class="view" hidden></section>
    <section id="view-projects" class="view" hidden></section>
    <section id="view-sessions" class="view" hidden></section>
    <section id="view-assets" class="view" hidden></section>
    <section id="view-automations" class="view" hidden></section>
    <section id="view-search" class="view" hidden></section>
  </main>
</div>
<script id="data" type="application/json">{{DATA}}</script>
<script>{{JS}}</script>
</body></html>"""


CSS = """
:root{--bg:#0B0F14;--bg-2:#10161E;--surface:#141B24;--surface-2:#1B2431;--line:#243040;--line-2:#2E3B4E;--ink:#E8EDF3;--ink-2:#B6C2CF;--mute:#7F8C9B;
--acc:#F2B544;--acc-ink:#1A1204;--acc-2:#3FB8AF;--ok:#3DD68C;--ok-bg:#12301F;--bad:#FF7A59;--bad-bg:#3A1F16;--warn:#F2B544;--warn-bg:#3A2D0E;--code:#1A2230;--sel:#1D2A3A;--shadow:0 12px 32px rgba(0,0,0,.35)}
@media(prefers-color-scheme:light){:root:not([data-theme="dark"]){--bg:#F3F5F8;--bg-2:#EAEEF3;--surface:#FFFFFF;--surface-2:#F5F7FA;--line:#DDE3EA;--line-2:#CBD3DD;--ink:#141A22;--ink-2:#3B4754;--mute:#6B7886;
--acc:#C98A0C;--acc-ink:#FFFFFF;--acc-2:#137F79;--ok:#1E8A5A;--ok-bg:#DDF3E7;--bad:#C4451E;--bad-bg:#FBE6DF;--warn:#9A6A00;--warn-bg:#FFF1CC;--code:#EDF1F5;--sel:#E9F0F8;--shadow:0 12px 32px rgba(20,30,45,.10)}}
:root[data-theme="light"]{--bg:#F3F5F8;--bg-2:#EAEEF3;--surface:#FFFFFF;--surface-2:#F5F7FA;--line:#DDE3EA;--line-2:#CBD3DD;--ink:#141A22;--ink-2:#3B4754;--mute:#6B7886;
--acc:#C98A0C;--acc-ink:#FFFFFF;--acc-2:#137F79;--ok:#1E8A5A;--ok-bg:#DDF3E7;--bad:#C4451E;--bad-bg:#FBE6DF;--warn:#9A6A00;--warn-bg:#FFF1CC;--code:#EDF1F5;--sel:#E9F0F8;--shadow:0 12px 32px rgba(20,30,45,.10)}
*{box-sizing:border-box}html,body{margin:0;height:100%}
body{background:var(--bg);color:var(--ink);font:14.5px/1.5 "Manrope","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--acc-2);text-decoration:none}a:hover{text-decoration:underline}
h1,h2,h3,.brand-name,.kpi b,.tab,.chip,.lbl{font-family:"Sora","Manrope",sans-serif}
.app{display:grid;grid-template-columns:220px 1fr;min-height:100%}
.rail{position:sticky;top:0;height:100vh;background:var(--bg-2);border-right:1px solid var(--line);padding:22px 14px;display:flex;flex-direction:column;gap:4px}
.brand{display:flex;align-items:center;gap:10px;padding:4px 10px 18px}
.brand-mark{width:12px;height:12px;border-radius:3px;background:var(--acc);box-shadow:0 0 0 4px color-mix(in srgb,var(--acc) 22%,transparent)}
.brand-name{font-weight:700;font-size:15px;letter-spacing:.01em}
.rail a{display:flex;align-items:center;gap:10px;padding:9px 10px;border-radius:8px;color:var(--ink-2);font-weight:600;font-size:14px}
.rail a:hover{background:var(--sel);text-decoration:none;color:var(--ink)}.rail a.on{background:var(--sel);color:var(--ink);box-shadow:inset 3px 0 0 var(--acc)}
.rail .ico{width:18px;text-align:center;color:var(--mute);font-size:13px}.rail a.on .ico{color:var(--acc)}
.rail-foot{margin-top:auto;padding:10px;font-size:12px;color:var(--ink-2)}
.main{min-width:0;padding:0 28px 60px}
.topbar{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);display:flex;gap:14px;align-items:center;padding:16px 0 12px;border-bottom:1px solid var(--line);margin-bottom:22px}
.search-wrap{flex:1;display:flex;align-items:center;gap:10px;background:var(--surface);border:1px solid var(--line-2);border-radius:10px;padding:0 12px;height:42px}
.search-wrap:focus-within{border-color:var(--acc);box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 20%,transparent)}
.search-ico{color:var(--mute)}#q{flex:1;border:0;background:transparent;color:var(--ink);font:inherit;outline:none;min-width:0}
kbd{font:500 11px "JetBrains Mono",monospace;color:var(--mute);border:1px solid var(--line-2);border-radius:4px;padding:1px 5px}
.pill{font-size:12.5px;font-weight:600;padding:7px 12px;border-radius:999px;white-space:nowrap}.pill.ok{background:var(--ok-bg);color:var(--ok)}.pill.bad{background:var(--bad-bg);color:var(--bad)}
h1{font-size:26px;font-weight:700;margin:6px 0 4px;letter-spacing:-.01em}h2{font-size:17px;font-weight:600;margin:28px 0 10px}h3{font-size:15px;font-weight:600;margin:0}
.sub{color:var(--mute);margin:0 0 18px;max-width:70ch}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin:14px 0 6px}
@media(max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}}@media(max-width:600px){.kpis{grid-template-columns:1fr 1fr}}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}.kpi b{display:block;font-size:24px;font-weight:700;line-height:1.1}.kpi span{color:var(--mute);font-size:12.5px}
.banner{display:flex;gap:12px;align-items:flex-start;padding:14px 16px;border-radius:12px;margin:14px 0 4px;font-size:14px}
.banner.ok{background:var(--ok-bg);color:var(--ok)}.banner.bad{background:var(--bad-bg);color:var(--bad)}.banner b{font-weight:700}
.list{display:flex;flex-direction:column;gap:8px}
.row{display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer;transition:border-color .12s,transform .12s}
.row:hover{border-color:var(--line-2);transform:translateY(-1px)}.row.open{border-color:var(--acc)}
.row .head{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 12px;min-width:0}.row .name{font-family:"Sora",sans-serif;font-weight:600;font-size:15px}
.row .note{color:var(--ink-2);font-size:13.5px;margin-top:2px}.row .ago{color:var(--mute);font-size:12.5px;white-space:nowrap;font-variant-numeric:tabular-nums}
.row .ago.hot{color:var(--acc);font-weight:600}
.chip{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;padding:2px 8px;border-radius:999px;background:var(--surface-2);color:var(--mute);border:1px solid var(--line)}
.chip.acc{background:color-mix(in srgb,var(--acc) 16%,transparent);color:var(--acc);border-color:transparent}.chip.mc{background:color-mix(in srgb,var(--acc-2) 14%,transparent);color:var(--acc-2);border-color:transparent}.chip.cw{background:color-mix(in srgb,var(--acc-2) 16%,transparent);color:var(--acc-2);border-color:transparent}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 14px}.chips .chip{cursor:pointer;padding:6px 12px;font-size:12px;letter-spacing:.04em;text-transform:none}.chips .chip.on{background:var(--acc);color:var(--acc-ink);border-color:transparent}
.detail{grid-column:1/-1;border-top:1px solid var(--line);margin-top:8px;padding-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:14px;cursor:default}
.detail .box{background:var(--surface-2);border-radius:10px;padding:10px 12px}.lbl{font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);margin-bottom:6px;font-weight:600}
.file{font:12.5px "JetBrains Mono",monospace;color:var(--ink-2);margin:2px 0;word-break:break-all}
.sess{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;padding:6px 0;border-top:1px solid var(--line);font-size:13.5px}.sess:first-of-type{border-top:0}
.sess .when{color:var(--mute);font-size:12px;white-space:nowrap;min-width:78px;font-variant-numeric:tabular-nums}.sess .what{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sess .k{margin-right:6px}.needs{font-size:11.5px;color:var(--warn);background:var(--warn-bg);padding:2px 7px;border-radius:5px;white-space:nowrap}
.btn{font:600 12.5px "Manrope",sans-serif;border:1px solid var(--line-2);background:var(--surface);color:var(--ink);padding:7px 11px;border-radius:8px;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--acc)}.btn.primary{background:var(--acc);color:var(--acc-ink);border-color:transparent}.btn.done{background:var(--ok-bg);color:var(--ok);border-color:transparent}
.btn:focus-visible,.row:focus-visible,.rail a:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
.glance{column-width:290px;column-gap:20px}
.gf{break-inside:avoid;margin:0 0 14px;padding:6px 0 4px;border-top:1px solid var(--line)}
.gf h3{display:flex;align-items:center;gap:8px;margin:0 0 4px;padding:4px 6px;font-family:"Sora",sans-serif;font-size:13px;font-weight:600;color:var(--ink)}
.gf h3 .n{color:var(--mute);font-weight:500;font-size:12px}
.gf h3 .g{margin-left:auto;font-size:10.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}
.gf h3 a{color:inherit;text-decoration:none}
.gr{display:flex;align-items:center;gap:7px;padding:3px 6px;border-radius:6px;font-size:12.5px;line-height:1.35;color:var(--ink-2);cursor:pointer;position:relative}
.gr:hover{background:var(--sel);color:var(--ink)}
.gr.copied::after{content:"copied";position:absolute;right:6px;top:2px;font-size:10.5px;font-weight:600;color:var(--ok);background:var(--surface);padding:1px 6px;border-radius:999px}
.gr .t{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gr .d{color:var(--mute);font-size:11px;white-space:nowrap;font-variant-numeric:tabular-nums}
.gr .cwm{font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--acc-2)}
.gr .x{color:var(--warn);font-weight:700;font-size:12px}
.gr.au{opacity:.6}
.dot{width:8px;height:8px;border-radius:50%;flex:none;display:inline-block}
.gmore{display:block;padding:2px 6px;font-size:11.5px;color:var(--mute);cursor:pointer}
.gmore:hover{color:var(--ink)}
.glegend{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;margin:0 0 10px;font-size:12px;color:var(--ink-2)}
.glegend .cur{font-size:10.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--acc);margin-left:4px}
.sec{margin:0 0 22px}.sec-head{display:flex;align-items:baseline;gap:10px;cursor:pointer;user-select:none;padding:8px 0;border-bottom:1px solid var(--line);margin-bottom:12px}
.sec-head .st{font-family:"Sora",sans-serif;font-size:16px;font-weight:600}.sec-head .sm{color:var(--mute);font-size:12px;font-family:"JetBrains Mono",monospace}
.caret{display:inline-block;color:var(--acc);font-size:11px;transition:transform .15s}.caret.off{transform:rotate(-90deg)}
.sec.off .grid,.sec.off .acct-cards,.sec.off h2{display:none}
.pcard{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column}.pcard:hover{border-color:var(--line-2)}
.pcard .shot{aspect-ratio:16/9;border-bottom:1px solid var(--line)}.pcard .pb{padding:10px 14px 12px;display:flex;flex-direction:column;gap:6px}
.pcard .head{display:flex;align-items:center;gap:8px}.pcard .name{font-weight:700}.pcard .ago{margin-left:auto;color:var(--mute);font-size:12px;white-space:nowrap}.pcard .ago.hot{color:var(--ok)}
.pcard .note{color:var(--ink-2);font-size:13px;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}.pcard .pstats{display:flex;align-items:center;gap:6px;font-size:12.5px;color:var(--ink-2);min-width:0}.pcard .pstats .t{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pcard .pfoot{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;margin-top:2px}
.tnode{margin:0 0 10px}.tparent{display:grid;grid-template-columns:auto auto 1fr auto;gap:12px;align-items:center;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:10px 14px;cursor:pointer;user-select:none}.tparent:hover{border-color:var(--line-2)}
.tp-main{min-width:0}.tp-main .head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.tp-main .name{font-weight:700}.tp-main .note{color:var(--ink-2);font-size:13px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.tnode:not(.off) .tp-main .note{-webkit-line-clamp:4}.tp-meta{color:var(--mute);font-size:12px;font-family:"JetBrains Mono",monospace;margin-top:2px}
.tchildren{margin:4px 0 0 30px;border-left:2px solid var(--line);padding:6px 0 4px 14px}.tnode.off .tchildren{display:none}
.tleaf{position:relative}.tleaf::before{content:"";position:absolute;left:-16px;top:50%;width:12px;height:2px;background:var(--line)}
.tfiles{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;padding:4px 6px;font-size:12px}.tfiles .lbl{color:var(--mute);font-weight:600;text-transform:uppercase;letter-spacing:.06em;font-size:10.5px}.tfiles .file{color:var(--acc-2);font:12px "JetBrains Mono",monospace;text-decoration:none}
.twrap{overflow-x:auto}.tbl{width:100%;border-collapse:collapse;font-size:13px}.tbl th,.tbl td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:middle}
.tbl th{color:var(--mute);font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.1em;cursor:pointer;white-space:nowrap;position:sticky;top:0;background:var(--bg)}.tbl th.asc::after{content:" \25B2"}.tbl th.desc::after{content:" \25BC"}
.tbl tbody tr:hover{background:var(--sel)}.tbl td.tt{font-weight:600}.tbl td.tf{color:var(--ink-2)}.tbl td.td{font-family:"JetBrains Mono",monospace;font-size:12px;white-space:nowrap;color:var(--mute)}.tbl tr.au{opacity:.6}
.tcount{font-size:12px;margin:0 0 8px}
.day{font-family:"Sora",sans-serif;font-size:12px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);margin:18px 0 6px}
.srow{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center;padding:9px 12px;background:var(--surface);border:1px solid var(--line);border-radius:10px;margin-bottom:6px;font-size:13.5px}
.srow .when{color:var(--mute);font-size:12px;min-width:44px;font-variant-numeric:tabular-nums}.srow .what{min-width:0}.srow .what b{font-weight:600}.srow .f{color:var(--mute);font-size:12.5px;margin-left:8px}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-bottom:16px}.tab{background:none;border:0;color:var(--mute);font-weight:600;font-size:14px;padding:10px 14px;cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px}.tab.on{color:var(--ink);border-color:var(--acc)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
.card .desc{color:var(--ink-2);font-size:13.5px;margin:0}.card .meta{color:var(--mute);font-size:12.5px}
details summary{cursor:pointer;color:var(--mute);font-size:13px;font-weight:600;list-style:none;display:flex;gap:6px;align-items:center}
summary::-webkit-details-marker{display:none}summary::before{content:"";width:0;height:0;border:4px solid transparent;border-left-color:var(--mute);display:inline-block;transition:transform .12s}
details[open] summary::before{transform:rotate(90deg)}.cnt{background:var(--surface-2);border:1px solid var(--line);border-radius:999px;padding:0 7px;font-size:11.5px}
.hit{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px;margin-bottom:8px}.hit h3 a{color:inherit}.hit .meta{color:var(--mute);font-size:12.5px;display:flex;gap:10px;flex-wrap:wrap;margin:2px 0 6px}
.snip{padding:5px 10px;border-left:3px solid var(--line-2);font-size:13.5px;color:var(--ink-2);margin:4px 0}.snip .r{color:var(--mute);font-size:11px;letter-spacing:.06em;text-transform:uppercase;margin-right:6px}
mark{background:color-mix(in srgb,var(--acc) 30%,transparent);color:inherit;padding:0 2px;border-radius:3px}
.dim{color:var(--mute)}.empty{color:var(--mute);padding:20px;text-align:center;border:1px dashed var(--line-2);border-radius:12px}
.two{display:grid;grid-template-columns:1.4fr 1fr;gap:18px}
code{font:12.5px "JetBrains Mono",monospace;background:var(--code);padding:1px 5px;border-radius:4px}
.acct-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.acct{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}.acct.on{border-color:var(--acc)}.acct b{display:block;font-size:14px}.acct span{color:var(--mute);font-size:12.5px}
.acct .now{color:var(--acc);font-size:11px;letter-spacing:.1em;text-transform:uppercase;font-weight:700;margin-top:6px;display:block}
.prod{background:linear-gradient(180deg,color-mix(in srgb,var(--acc) 9%,var(--surface)),var(--surface));border:1px solid color-mix(in srgb,var(--acc) 35%,var(--line));border-radius:14px;padding:0 0 14px;display:flex;flex-direction:column;gap:8px;overflow:hidden}
.prod>*:not(.shot){margin-left:18px;margin-right:18px}.prod .stage{margin-top:12px}
.shot{aspect-ratio:16/10;width:100%;background:var(--surface-2);overflow:hidden;border-bottom:1px solid var(--line);display:block}.shot img{width:100%;height:100%;object-fit:cover;object-position:top;display:block}
.tile{width:56px;height:42px;border-radius:8px;flex:0 0 auto;overflow:hidden;background:var(--surface-2);display:grid;place-items:center;font:700 13px "Sora",sans-serif;letter-spacing:.04em;color:var(--acc-ink)}
.tile img{width:100%;height:100%;object-fit:cover;object-position:top}.row.with-tile{grid-template-columns:auto 1fr auto}
.shot.mono{display:grid;place-items:center;font:700 40px "Sora",sans-serif;color:var(--acc-ink);letter-spacing:.06em}
.card .shot{border-radius:8px;border:1px solid var(--line);aspect-ratio:16/9;margin-bottom:4px}
.prod .stage{font-family:"Sora",sans-serif;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--acc)}.prod .stage.ready{color:var(--ok)}
.prod h3{font-size:19px;line-height:1.2}.prod .where{font:12px "JetBrains Mono",monospace;color:var(--mute);word-break:break-all}.prod .acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:4px}
.frow{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:start;padding:9px 12px;background:var(--surface);border:1px solid var(--line);border-radius:10px;margin-bottom:6px}
.frow .n{font-weight:600}.frow .t{color:var(--ink-2);font-size:13px}.frow .p{font:11.5px "JetBrains Mono",monospace;color:var(--mute);word-break:break-all;margin-top:2px}
@media(max-width:860px){.app{grid-template-columns:1fr}.rail{position:sticky;top:0;height:auto;flex-direction:row;flex-wrap:wrap;padding:10px 12px;gap:2px;z-index:6}.brand{padding:4px 8px;width:100%}.rail-foot{display:none}.rail a{padding:7px 10px;font-size:13px}
.main{padding:0 16px 40px}.topbar{position:static}.detail,.two{grid-template-columns:1fr}.row{grid-template-columns:1fr}.sess{grid-template-columns:1fr}.srow{grid-template-columns:auto 1fr}}
@media(prefers-reduced-motion:reduce){.row,summary::before{transition:none}}
"""


JS = r"""
var D=JSON.parse(document.getElementById('data').textContent),M=D.meta;
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function ago(iso){if(!iso)return 'never';var d=(Date.now()-new Date(iso).getTime())/864e5;if(d<1)return 'today';if(d<2)return 'yesterday';if(d<14)return Math.floor(d)+' days ago';if(d<60)return Math.floor(d/7)+' weeks ago';return Math.floor(d/30)+' months ago'}
function hot(iso){return iso&&(Date.now()-new Date(iso).getTime())<3*864e5}
function acctNote(a,k){if(!a||a===M.current||a==='terminal')return '';if(k==='cowork'||!M.mirror)return '<span class="needs">needs '+esc(a)+'</span>';return '<span class="dim" style="font-size:12px">'+esc(a)+'</span>'}
function copyBtn(cmd,label,primary){return '<button class="btn'+(primary?' primary':'')+'" data-copy="'+esc(cmd)+'">'+esc(label||'Copy resume')+'</button>'}
function wireCopy(root){root.querySelectorAll('[data-copy]').forEach(function(b){if(b._w)return;b._w=1;b.addEventListener('click',async function(e){e.stopPropagation();try{await navigator.clipboard.writeText(b.dataset.copy);var t=b.textContent;b.textContent='Copied';b.classList.add('done');setTimeout(function(){b.textContent=t;b.classList.remove('done')},1400)}catch(err){prompt('Copy this:',b.dataset.copy)}})})}
function kchip(k){return k==='cowork'?'<span class="chip cw k">Claude tab</span>':(k==='terminal'?'<span class="chip k">terminal</span>':'')}
function mchip(m){return m?'<span class="chip mc k">on '+esc(m)+'</span>':''}
function fileUrl(p){return 'http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(p)}
function hue(s){var h=0;for(var i=0;i<s.length;i++)h=(h*31+s.charCodeAt(i))>>>0;return h%360}
function mono(name){var w=name.replace(/[^A-Za-z0-9 ]/g,' ').trim().split(/\s+/);var t=(w[0]||'?').slice(0,1)+(w[1]?w[1].slice(0,1):(w[0]||'').slice(1,2));return {t:t.toUpperCase(),bg:'hsl('+hue(name)+' 45% 42%)'}}
function imgSrc(img){return img.indexOf('data:')===0?img:fileUrl(img)}
function tile(name,img){var m=mono(name);if(img)return '<div class="tile" style="background:'+m.bg+'"><img loading="lazy" src="'+imgSrc(img)+'" alt="" onerror="this.remove()"></div>';return '<div class="tile" style="background:'+m.bg+'">'+m.t+'</div>'}
function shot(name,img,cls){var m=mono(name);if(img)return '<div class="shot '+(cls||'')+'" style="background:'+m.bg+'"><img loading="lazy" src="'+imgSrc(img)+'" alt="" onerror="this.parentNode.classList.add(\'mono\');this.parentNode.textContent=\''+m.t+'\'"></div>';return '<div class="shot mono '+(cls||'')+'" style="background:'+m.bg+'">'+m.t+'</div>'}
function sessLine(s){var can=(s.k==='code'||s.k==='terminal')&&s.id&&s.id.length>20;return '<div class="sess"><span class="when">'+esc(ago(s.d))+'</span><span class="what">'+kchip(s.k)+(s.from?'<span class="chip k">from '+esc(s.from)+'</span>':'')+esc(s.t||'(untitled)')+'</span><span>'+(can?copyBtn('claude --resume '+s.id):'')+acctNote(s.a,s.k)+'</span></div>'}

/* ---------- account pill + banner ---------- */
var pill=document.getElementById('acct-pill');
if(M.mirror){pill.className='pill ok';pill.textContent='All sessions visible · on '+(M.current||'?')}
else if(M.current===M.primary){pill.className='pill ok';pill.textContent='On '+M.current}
else{pill.className='pill bad';pill.textContent='Wrong account: '+(M.hidden_code+M.hidden_cw)+' sessions hidden'}

/* ---------- shared: filter, folding, ledger by folder ---------- */
var Q='',CUR='home';
function words(){return Q.toLowerCase().split(/\s+/).filter(Boolean)}
function matchQ(h){var w=words();if(!w.length)return true;h=String(h||'').toLowerCase();return w.every(function(x){return h.indexOf(x)>=0})}
var COLL={};try{COLL=JSON.parse(localStorage.getItem('wm_collapsed')||'{}')}catch(e){COLL={}}
function collapsed(key,def){return (key in COLL)?!!COLL[key]:!!def}
function setColl(key,val){COLL[key]=!!val;try{localStorage.setItem('wm_collapsed',JSON.stringify(COLL))}catch(e){}}
function secHead(key,title,meta,def){return '<div class="sec-head" data-sec="'+esc(key)+'" data-def="'+(def?1:0)+'"><span class="caret'+(collapsed(key,def)?' off':'')+'">&#9660;</span><span class="st">'+title+'</span><span class="sm">'+esc(meta||'')+'</span></div>'}
function wireSec(v,rerender){v.querySelectorAll('[data-sec]').forEach(function(h){h.addEventListener('click',function(e){if(e.target.closest('button,a'))return;var def=h.dataset.def==='1';setColl(h.dataset.sec,!collapsed(h.dataset.sec,def));rerender()})})}
function hot14(iso){return !!iso&&(Date.now()-new Date(iso).getTime())<14*864e5}
function short(d){return ago(d).replace(' days ago','d').replace(' weeks ago','w').replace(' months ago','mo').replace('yesterday','1d').replace('today','now')}
var LBF={};D.ledger.forEach(function(s){(s.f||'').split(', ').filter(Boolean).forEach(function(f){(LBF[f]=LBF[f]||[]).push(s)})});
var DOTS=['#7F77DD','#1D9E75','#D85A30','#378ADD','#D4537E','#888780'];
function dotColor(email){var all=D.accounts.map(function(a){return a.email}).filter(function(e){return e&&e!=='(unknown account)'}).sort();var i=all.indexOf(email);if(email==='(unknown account)'||email==='terminal'||!email)return '#888780';return DOTS[(i<0?all.length:i)%DOTS.length]}
function dot(email,title){return '<span class="dot" style="background:'+dotColor(email)+'" title="'+esc(title||email)+'"></span>'}
function legendHtml(){return '<div class="glegend">'+D.accounts.filter(function(a){return a.email!=='(unknown account)'}).map(function(a){return '<span>'+dot(a.email)+' '+esc(a.email.split('@')[0])+(a.current?'<span class="cur">app is here</span>':'')+'</span>'}).join('')+'<span>'+dot('(unknown account)')+' other</span><span><span class="x">!</span> started before a connector this account has now</span></div>'}
function wireGcopy(v){v.querySelectorAll('[data-gcopy]').forEach(function(r){r.addEventListener('click',async function(e){e.stopPropagation();try{await navigator.clipboard.writeText(r.dataset.gcopy)}catch(err){}r.classList.add('copied');setTimeout(function(){r.classList.remove('copied')},1100)})})}
function leaf(s){var acct=s.b||(s.a||'').split(', ')[0];var cmd=(s.k==='code'||s.k==='terminal')&&s.id&&s.id.length>20?'claude --resume '+s.id:'';
return '<div class="tleaf"><div class="gr'+(s.u?' au':'')+'" '+(cmd?'data-gcopy="'+esc(cmd)+'"':'')+' title="'+esc((s.t||'(untitled)')+' · '+acct+(s.k==='cowork'?' · Claude tab (open from that account)':'')+(s.x&&s.x.length?' · started without: '+s.x.join(', '):'')+(cmd?' · click to copy the resume command':''))+'">'+dot(acct)+'<span class="t">'+esc(s.t||'(untitled)')+'</span>'+(s.k==='cowork'?'<span class="cwm">tab</span>':'')+(s.from?'<span class="cwm">from '+esc(s.from)+'</span>':'')+(s.x&&s.x.length?'<span class="x">!</span>':'')+(s.m?mchip(s.m):'')+'<span class="d">'+esc(short(s.d))+'</span></div></div>'}

/* ---------- MAP (home) ---------- */
function prodCard(p){var acts='';if(p.page)acts+='<a class="btn primary" href="'+fileUrl(p.page)+'" target="_blank">Open the page</a>';if(p.ship_kit)acts+='<a class="btn" href="'+fileUrl(p.ship_kit)+'" target="_blank">Launch checklist</a>';if(p.offer)acts+='<a class="btn" href="'+fileUrl(p.offer)+'" target="_blank">Offer</a>';if(p.course)acts+='<a class="btn" href="'+fileUrl(p.course)+'" target="_blank">Course</a>';
var artb=(p.arts||[]).map(function(a){return '<a class="btn" href="'+esc(a.url)+'" target="_blank" title="'+esc(a.account)+'">&#9670; '+esc(a.title)+'</a>'}).join('');
return '<div class="prod">'+shot(p.name,p.thumb)+'<span class="stage'+(p.stage==='Ready to launch'?' ready':'')+'">'+esc(p.stage)+'</span>'+mchip(p.m)+'<h3>'+esc(p.name)+'</h3><div class="where">'+esc(p.where)+'</div><div class="dim" style="font-size:12.5px">in '+esc(p.project)+' · '+esc(ago(p.last))+(p.bundle?' · bundle ready':'')+'</div><div class="acts">'+(p.m?'<span class="dim">files are on '+esc(p.m)+'</span>':acts+artb)+'</div></div>'}
function projCard(p){var pick=p.work[0]||p.cowork[0];var cmd=pick&&pick.k==='code'&&pick.id?'cd "'+p.folder+'" && claude --resume '+pick.id:'';var n=LBF[p.name]||[];var nc=n.filter(function(s){return s.k==='code'&&!s.u}).length,nt=n.filter(function(s){return s.k==='cowork'}).length;
return '<div class="pcard" data-open="'+esc(p.name)+'" tabindex="0">'+shot(p.name,p.thumb)+'<div class="pb"><div class="head"><span class="name">'+esc(p.name)+'</span><span class="ago'+(hot(p.last)?' hot':'')+'">'+esc(ago(p.last))+'</span></div><div class="note">'+(esc(p.note)||'<span class="dim">No description yet.</span>')+'</div><div class="pstats">'+(pick?dot(pick.a)+'<span class="t">'+esc(pick.t||'(untitled)')+'</span>':'<span class="dim">no session yet</span>')+'</div><div class="pfoot"><span class="dim">'+nc+' code · '+nt+' tab'+((p.arts||[]).length?' · &#9670; '+p.arts.length:'')+'</span>'+(cmd?copyBtn(cmd,'Copy resume'):'')+'</div></div></div>'}
function renderHome(){var v=document.getElementById('view-home');
var banner=M.mirror?'<div class="banner ok"><span>&#10003;</span><div><b>Every session is reachable from either account.</b> The app was last used as '+esc(M.current)+'. Claude-tab sessions still belong to the account shown on them.</div></div>':
(M.current===M.primary?'<div class="banner ok"><span>&#10003;</span><div><b>You are on '+esc(M.current)+'.</b> Everything below is in the sidebar.</div></div>':'<div class="banner bad"><span>&#9888;</span><div><b>Wrong account.</b> The app is on '+esc(M.current)+'; '+M.hidden_code+' Code and '+M.hidden_cw+' Claude-tab sessions belong to '+esc(M.primary)+'. Nothing is deleted. Sign out and back in as '+esc(M.primary)+'.</div></div>');
var kpis='<div class="kpis"><div class="kpi"><b>'+D.projects.filter(function(p){return p.exists&&!p.alias_to}).length+'</b><span>projects</span></div><div class="kpi"><b>'+M.n_code+'</b><span>Code sessions</span></div><div class="kpi"><b>'+M.n_cowork+'</b><span>Claude-tab sessions</span></div><div class="kpi"><b>'+D.products.length+'</b><span>things you are building</span></div><div class="kpi"><b>'+D.artifacts.length+'</b><span>published pages</span></div></div>';
var prods=D.products.filter(function(p){return matchQ(p.name+' '+p.stage+' '+p.where+' '+p.project+' '+(p.tags||''))});
var secs='';
if(prods.length){var k='s:products';secs+='<div class="sec'+(collapsed(k,false)?' off':'')+'">'+secHead(k,'Things you are building',prods.length+(prods.length===1?' product':' products'),false)+'<div class="grid">'+prods.map(prodCard).join('')+'</div></div>'}
var groups=(M.group_order||[]).slice();D.projects.forEach(function(p){if(groups.indexOf(p.group)<0)groups.push(p.group)});
groups.forEach(function(g){var ps=D.projects.filter(function(p){return p.group===g&&p.exists&&!p.alias_to&&matchQ(p.name+' '+p.note+' '+p.work.concat(p.cowork).map(function(x){return x.t}).join(' '))});if(!ps.length)return;var key='s:'+g;var last=ps.reduce(function(m,x){return x.last>m?x.last:m},'');
secs+='<div class="sec'+(collapsed(key,false)?' off':'')+'">'+secHead(key,esc(g),ps.length+(ps.length===1?' project':' projects')+' · '+ago(last),false)+'<div class="grid">'+ps.map(projCard).join('')+'</div></div>'});
var accts=D.accounts.map(function(a){return '<div class="acct'+(a.current?' on':'')+'"><b>'+dot(a.email)+' '+esc(a.email)+'</b><span>'+a.n_code+' Code · '+a.n_cowork+' Claude-tab · last used '+esc(ago(a.last))+'</span>'+(a.current?'<span class="now">app is on this one</span>':'')+'</div>'}).join('');
var mach=(M.machines||[]).map(function(m){return '<div class="acct"><b>'+esc(m.name)+'</b><span>'+m.n+' sessions · reported '+esc(ago(m.stamp))+'</span></div>'}).join('');
v.innerHTML='<h1>Map</h1><p class="sub">Everything you are building, then every project folder in the groups you filed them under. Click a card to open it in the tree. The search box narrows this view.</p>'+banner+kpis+(secs||'<div class="empty">Nothing matches.</div>')+'<div class="sec'+(collapsed('s:accounts',true)?' off':'')+'">'+secHead('s:accounts','Accounts on this PC',D.accounts.length+' accounts'+((M.machines||[]).length?' · '+(M.machines||[]).length+' other computer(s)':''),true)+'<div class="acct-cards">'+accts+'</div>'+(mach?'<h2>Other computers</h2><div class="acct-cards">'+mach+'</div>':'')+'</div>';
v.querySelectorAll('[data-open]').forEach(function(r){r.addEventListener('click',function(e){if(e.target.closest('button,a'))return;location.hash='#projects/'+encodeURIComponent(r.dataset.open)})});wireCopy(v);wireSec(v,renderHome)}

/* ---------- TREE (projects) ---------- */
var pFilter='All',pOpen=null,tMore={};
function renderProjects(){var v=document.getElementById('view-projects');
var groups=['All'].concat((M.group_order||[]).filter(function(g){return D.projects.some(function(p){return p.group===g})}));D.projects.forEach(function(p){if(groups.indexOf(p.group)<0)groups.push(p.group)});
var chips='<div class="chips">'+groups.map(function(g){return '<span class="chip'+(g===pFilter?' on':'')+'" data-g="'+esc(g)+'">'+esc(g)+'</span>'}).join('')+'</div>';
var list=D.projects.filter(function(p){return pFilter==='All'||p.group===pFilter}).map(function(p){var sess=(LBF[p.name]||[]).filter(function(s){return gFilter.auto||!s.u});var all=sess.concat(p.elsewhere||[]);
var pm=matchQ(p.name+' '+p.note+' '+p.group);if(Q&&!pm){all=all.filter(function(s){return matchQ(s.t+' '+(s.a||'')+' '+(s.b||''))});if(!all.length)return ''}
var key='p:'+p.name,def=!hot14(p.last);var isOpen=pOpen===p.name||!collapsed(key,def)||(!!Q&&!pm);
var pick=p.work[0]||p.cowork[0];var cmd=pick&&pick.k==='code'&&pick.id?'cd "'+p.folder+'" && claude --resume '+pick.id:'';
var name=p.alias_to?'<s>'+esc(p.name)+'</s> <span class="dim">is now '+esc(p.alias_to)+'</span>':(p.exists?esc(p.name):'<s>'+esc(p.name)+'</s> <span class="dim">folder gone</span>');
var nc=sess.filter(function(s){return s.k==='code'}).length,nt=sess.filter(function(s){return s.k==='cowork'}).length;
var files=(p.state||[]).map(function(f){return '<a class="file" href="'+fileUrl(p.folder+'\\'+f)+'" target="_blank">'+esc(f)+'</a>'}).join('')+(p.arts||[]).map(function(a){return '<a class="file" href="'+esc(a.url)+'" target="_blank" title="'+esc(a.account)+'">&#9670; '+esc(a.title)+'</a>'}).join('');
var shown=tMore[p.name]?all:all.slice(0,10);var more=all.length>shown.length?'<span class="gmore" data-tmore="'+esc(p.name)+'">+ '+(all.length-shown.length)+' more</span>':(tMore[p.name]&&all.length>10?'<span class="gmore" data-tmore="'+esc(p.name)+'">show fewer</span>':'');
return '<div class="tnode'+(isOpen?'':' off')+'" id="tn-'+esc(p.name)+'"><div class="tparent" data-tp="'+esc(p.name)+'"><span class="caret'+(isOpen?'':' off')+'">&#9660;</span>'+tile(p.name,p.thumb)+'<div class="tp-main"><div class="head"><span class="name">'+name+'</span><span class="chip">'+esc(p.group)+'</span><span class="ago'+(hot(p.last)?' hot':'')+'">'+esc(ago(p.last))+'</span></div><div class="note">'+(esc(p.note)||'<span class="dim">No description yet.</span>')+'</div><div class="tp-meta">'+nc+' code · '+nt+' tab'+(p.n_elsewhere?' · '+p.n_elsewhere+' from elsewhere':'')+((p.arts||[]).length?' · '+p.arts.length+' published':'')+(p.n_mem?' · '+p.n_mem+' memory':'')+'</div></div><div>'+(cmd?copyBtn(cmd,'Copy resume'):'')+'</div></div><div class="tchildren">'+(files?'<div class="tleaf tfiles"><span class="lbl">Read first</span>'+files+'</div>':'')+shown.map(leaf).join('')+more+(all.length?'':'<div class="tleaf dim" style="font-size:12.5px;padding:4px 6px">No session in this folder yet.</div>')+'</div></div>'}).join('');
v.innerHTML='<h1>Tree</h1><p class="sub">Every project folder with every session under it. Click a project to fold or unfold it, click a session to copy its resume command. Folded state is remembered.</p>'+chips+legendHtml()+(list||'<div class="empty">Nothing matches.</div>');
v.querySelectorAll('.chips .chip').forEach(function(c){c.addEventListener('click',function(){pFilter=c.dataset.g;renderProjects()})});
v.querySelectorAll('[data-tp]').forEach(function(h){h.addEventListener('click',function(e){if(e.target.closest('button,a'))return;var n=h.dataset.tp;var p=D.projects.filter(function(x){return x.name===n})[0];var def=!hot14(p?p.last:'');var wasOpen=pOpen===n||!collapsed('p:'+n,def);pOpen=null;setColl('p:'+n,wasOpen);renderProjects()})});
v.querySelectorAll('[data-tmore]').forEach(function(c){c.addEventListener('click',function(){tMore[c.dataset.tmore]=!tMore[c.dataset.tmore];renderProjects()})});
wireGcopy(v);wireCopy(v);
if(pOpen){var el=document.getElementById('tn-'+pOpen);if(el)el.scrollIntoView({block:'start'})}}

/* ---------- SESSIONS ---------- */
var sFilter={a:'All',k:'All'};
function renderSessions(){var v=document.getElementById('view-sessions');
var accts=['All'].concat(D.accounts.map(function(a){return a.email}));var kinds=['All','code','cowork','terminal'];var machs=['All',M.machine].concat((M.machines||[]).map(function(m){return m.name}));var kl={All:'All kinds',code:'Code',cowork:'Claude tab',terminal:'Terminal'};
var chips='<div class="chips">'+accts.map(function(a){return '<span class="chip'+(a===sFilter.a?' on':'')+'" data-a="'+esc(a)+'">'+esc(a==='All'?'All accounts':a)+'</span>'}).join('')+'</div><div class="chips">'+kinds.map(function(k){return '<span class="chip'+(k===sFilter.k?' on':'')+'" data-k="'+k+'">'+kl[k]+'</span>'}).join('')+'</div>';
var mchips=(M.machines||[]).length?'<div class="chips">'+machs.map(function(m){return '<span class="chip'+((sFilter.m||'All')===m?' on':'')+'" data-m="'+esc(m)+'">'+esc(m==='All'?'All computers':m)+'</span>'}).join('')+'</div>':'';
var rows=D.ledger.filter(function(s){var sm=s.m||M.machine;return (sFilter.a==='All'||(s.a||'').indexOf(sFilter.a)>=0)&&(sFilter.k==='All'||s.k===sFilter.k)&&((sFilter.m||'All')==='All'||sm===sFilter.m)}).slice(0,400);
var out='',day='';rows.forEach(function(s){var d=(s.d||'').slice(0,10);if(d!==day){day=d;out+='<div class="day">'+esc(d||'undated')+'</div>'}
out+='<div class="srow"><span class="when">'+esc((s.d||'').slice(11,16))+'</span><span class="what">'+kchip(s.k)+mchip(s.m)+'<b>'+esc(s.t||'(untitled)')+'</b><span class="f">'+esc(s.f||'')+'</span></span><span>'+(s.r&&s.id.length>20?copyBtn('claude --resume '+s.id):'')+' '+(s.m?'':acctNote((s.a||'').split(', ')[0],s.k))+'</span></div>'});
v.innerHTML='<h1>Sessions</h1><p class="sub">Every session ever recorded, newest first, from every account'+((M.machines||[]).length?' and every computer':'')+'. '+D.ledger.length+' in the ledger. Use the search box to find one by what was said.</p>'+chips+mchips+(out||'<div class="empty">Nothing matches.</div>');
v.querySelectorAll('[data-m]').forEach(function(c){c.addEventListener('click',function(){sFilter.m=c.dataset.m;renderSessions()})});
v.querySelectorAll('[data-a]').forEach(function(c){c.addEventListener('click',function(){sFilter.a=c.dataset.a;renderSessions()})});v.querySelectorAll('[data-k]').forEach(function(c){c.addEventListener('click',function(){sFilter.k=c.dataset.k;renderSessions()})});wireCopy(v)}

/* ---------- ASSETS ---------- */
var aTab='projects';
function renderAssets(){var v=document.getElementById('view-assets');
var tabs='<div class="tabs">'+[['projects','Claude Projects',D.claude_projects.length],['deliverables','Deliverables',D.outputs.length],['artifacts','Published pages',D.artifacts.length]].map(function(t){return '<button class="tab'+(aTab===t[0]?' on':'')+'" data-t="'+t[0]+'">'+t[1]+' <span class="cnt">'+t[2]+'</span></button>'}).join('')+'</div>';
var body='';
if(aTab==='projects'){var by={};D.claude_projects.forEach(function(x){(by[x.a]=by[x.a]||[]).push(x)});body=Object.keys(by).map(function(a){return '<h2>'+esc(a)+' <span class="cnt">'+by[a].length+'</span></h2><div class="grid">'+by[a].map(function(x){return '<div class="card"><h3>'+esc(x.name)+'</h3><p class="desc">'+(esc(x.desc)||'<span class="dim">no description</span>')+'</p>'+(x.docs.length?'<details><summary>Knowledge docs <span class="cnt">'+x.docs.length+'</span></summary>'+x.docs.map(function(f){return '<div class="file">'+esc(f)+'</div>'}).join('')+'</details>':'<span class="dim">no docs</span>')+'</div>'}).join('')+'</div>'}).join('')||'<div class="empty">No Claude Projects found on this machine.</div>'}
if(aTab==='deliverables'){body='<p class="sub">Files produced by Claude-tab sessions, each in its own output folder.</p><div class="grid">'+D.outputs.map(function(o){return '<div class="card">'+(o.thumb?shot(o.t,o.thumb):'')+'<h3>'+esc(o.t||'(untitled)')+'</h3><div class="meta">'+esc(ago(o.d))+' · '+esc(o.a)+(o.folders.length?' · '+esc(o.folders.join(', ')):'')+' · '+o.files.length+' files</div>'+o.files.slice(0,6).map(function(f){return '<div class="file">'+esc(f)+'</div>'}).join('')+(o.files.length>6?'<details><summary>'+(o.files.length-6)+' more</summary>'+o.files.slice(6).map(function(f){return '<div class="file">'+esc(f)+'</div>'}).join('')+'</details>':'')+'<div class="meta"><code>'+esc(o.dir)+'</code></div></div>'}).join('')+'</div>'}
if(aTab==='artifacts'){var byA={};D.artifacts.forEach(function(x){(byA[x.account||'?']=byA[x.account||'?']||[]).push(x)});body='<p class="sub">Pages on claude.ai. Each belongs to the account that published it; a link shared from its Share menu opens from any account.</p>'+Object.keys(byA).map(function(a){return '<h2>'+esc(a)+' <span class="cnt">'+byA[a].length+'</span></h2><div class="list">'+byA[a].sort(function(x,y){return (y.updated||'').localeCompare(x.updated||'')}).map(function(x){return '<div class="srow"><span class="when">'+esc(x.updated||'')+'</span><span class="what"><a href="'+esc(x.url)+'" target="_blank"><b>'+esc(x.title)+'</b></a><span class="f">'+esc(x.project||'')+'</span></span><span></span></div>'}).join('')+'</div>'}).join('')}
v.innerHTML='<h1>Assets</h1><p class="sub">Things that belong to an account rather than a folder, gathered from both accounts.</p>'+tabs+body;
v.querySelectorAll('.tab').forEach(function(t){t.addEventListener('click',function(){aTab=t.dataset.t;renderAssets()})})}

/* ---------- AUTOMATIONS ---------- */
function renderAutomations(){var v=document.getElementById('view-automations');
var rows=D.tasks.map(function(t){return '<div class="srow"><span class="pill '+(t.on?'ok':'bad')+'" style="min-width:44px;text-align:center">'+(t.on?'on':'off')+'</span><span class="what"><b>'+esc(t.name)+'</b><div class="dim" style="font-size:12.5px">'+esc(t.desc)+'</div></span><span class="dim" style="font-size:12.5px;text-align:right">'+esc(t.email||'not registered')+(t.last?'<br>last run '+esc(t.last):'')+'</span></div>'}).join('');
var aliases=Object.keys(D.aliases).map(function(k){return '<div class="srow"><span class="when"></span><span class="what"><s class="dim">'+esc(k)+'</s> is now <b>'+esc(D.aliases[k])+'</b></span><span></span></div>'}).join('');
var globals=D.globals.map(function(g){return '<div class="srow"><span class="when"></span><span class="what"><b>'+esc(g[0])+'</b><div class="file">'+esc(g[1])+'</div></span><span></span></div>'}).join('');
v.innerHTML='<h1>Automations</h1><p class="sub">Scheduled tasks only run while the app is signed in to the account they belong to.</p><div class="list">'+(rows||'<div class="empty">No scheduled tasks.</div>')+'</div><h2>Renamed folders</h2>'+(aliases||'<div class="dim">none on record</div>')+'<h2>Shared by every project and every account</h2>'+globals+'<h2>This map</h2><div class="srow"><span class="when"></span><span class="what">Rebuilt '+esc(M.stamp)+' by <code>build-map.py</code> in <code>'+esc(M.here)+'</code>. Edit <code>config.json</code> to change descriptions, groups or renames.</span><span></span></div>'}

/* ---------- SEARCH ---------- */
var q=document.getElementById('q'),deepOK=null,deepT=null,lastQ='';
fetch('http://127.0.0.1:'+M.port+'/ping',{mode:'cors'}).then(function(r){deepOK=r.ok}).catch(function(){deepOK=false});
function renderSearch(v0){var v=document.getElementById('view-search');var words=v0.toLowerCase().split(/\s+/).filter(Boolean);
var pm=D.projects.filter(function(p){var h=(p.name+' '+p.note+' '+p.group+' '+p.work.concat(p.cowork).map(function(s){return s.t}).join(' ')).toLowerCase();return words.every(function(w){return h.indexOf(w)>=0})});
var lm=D.ledger.filter(function(s){var h=(s.t+' '+s.f+' '+s.a+' '+s.d+' '+s.k).toLowerCase();return words.every(function(w){return h.indexOf(w)>=0})});
var am=D.artifacts.filter(function(a){var h=((a.title||'')+' '+(a.project||'')+' '+(a.account||'')).toLowerCase();return words.every(function(w){return h.indexOf(w)>=0})});
var prm=D.products.filter(function(p){var h=(p.name+' '+p.stage+' '+p.where+' '+p.project+' '+(p.tags||'')).toLowerCase();return words.every(function(w){return h.indexOf(w)>=0})});
v.innerHTML='<h1>Search: <span class="dim" style="font-weight:500">'+esc(v0)+'</span></h1>'+(prm.length?'<h2>Things you are building <span class="cnt">'+prm.length+'</span></h2><div class="grid">'+prm.map(function(p){return '<div class="prod">'+shot(p.name,p.thumb)+'<span class="stage'+(p.stage==='Ready to launch'?' ready':'')+'">'+esc(p.stage)+'</span><h3>'+esc(p.name)+'</h3><div class="where">'+esc(p.where)+'</div><div class="acts">'+(p.page?'<a class="btn primary" href="http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(p.page)+'" target="_blank">Open the page</a>':'')+(p.ship_kit?'<a class="btn" href="http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(p.ship_kit)+'" target="_blank">Launch checklist</a>':'')+'</div></div>'}).join('')+'</div>':'')+'<div class="two"><div><h2>Files <span id="files-n" class="cnt">…</span></h2><div id="files"><div class="dim">Searching…</div></div><h2>Inside conversations <span id="deep-n" class="cnt">…</span></h2><div id="deep"><div class="dim">Searching…</div></div></div><div><h2>Projects <span class="cnt">'+pm.length+'</span></h2><div class="list">'+pm.slice(0,8).map(function(p){return '<div class="row with-tile" data-open="'+esc(p.name)+'" tabindex="0">'+tile(p.name,p.thumb)+'<div><div class="head"><span class="name">'+esc(p.name)+'</span><span class="chip">'+esc(p.group)+'</span></div><div class="note">'+esc(p.note)+'</div></div><div></div></div>'}).join('')+'</div>'+(am.length?'<h2>Published pages <span class="cnt">'+am.length+'</span></h2>'+am.map(function(a){return '<div class="srow"><span class="when">'+esc(a.updated||'')+'</span><span class="what"><a href="'+esc(a.url)+'" target="_blank"><b>&#9670; '+esc(a.title)+'</b></a><span class="f">'+esc(a.project||'')+'</span></span><span class="dim" style="font-size:12px">'+esc(a.account||'')+'</span></div>'}).join(''):'')+'<h2>Session titles <span class="cnt">'+lm.length+'</span></h2>'+lm.slice(0,25).map(function(s){return '<div class="srow"><span class="when">'+esc((s.d||'').slice(0,10))+'</span><span class="what">'+kchip(s.k)+'<b>'+esc(s.t||'(untitled)')+'</b><span class="f">'+esc(s.f||'')+'</span></span><span>'+(s.r&&s.id.length>20?copyBtn('claude --resume '+s.id):'')+'</span></div>'}).join('')+'</div></div>';
v.querySelectorAll('[data-open]').forEach(function(r){r.addEventListener('click',function(){pOpen=r.dataset.open;location.hash='#projects/'+encodeURIComponent(r.dataset.open)})});wireCopy(v);
var deep=document.getElementById('deep'),dn=document.getElementById('deep-n'),fl=document.getElementById('files'),fn=document.getElementById('files-n');
if(deepOK===false){deep.innerHTML='<div class="dim">Search server is not running. It starts with the next Claude session, or run <code>python "'+esc(M.here)+'\\search-server.py"</code>.</div>';dn.textContent='off';fl.innerHTML='';fn.textContent='off';return}
fetch('http://127.0.0.1:'+M.port+'/search?q='+encodeURIComponent(v0),{mode:'cors'}).then(function(r){return r.json()}).then(function(all){var res=all.conversations||[],files=all.files||[];deepOK=true;dn.textContent=res.length;fn.textContent=files.length;
fl.innerHTML=files.length?files.slice(0,25).map(function(f){return '<div class="frow"><div><div class="n">'+mchip(f.machine)+(f.machine?esc(f.name||f.path.split(/[\\/]/).pop()):'<a href="http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(f.path)+'" target="_blank">'+esc(f.name)+'</a>')+(f.title?' <span class="t">'+esc(f.title)+'</span>':'')+'</div>'+(f.snippet?'<div class="t">'+f.snippet+'</div>':'')+'<div class="p">'+esc(f.rel)+'</div></div><div class="dim" style="font-size:12px;white-space:nowrap">'+esc(f.project)+'</div></div>'}).join(''):'<div class="dim">No file matches.</div>';
deep.innerHTML=res.length?res.map(function(g){return '<div class="hit"><h3>'+(g.machine?esc(g.title):'<a href="http://127.0.0.1:'+M.port+'/session?id='+encodeURIComponent(g.session)+'" target="_blank">'+esc(g.title)+'</a>')+'</h3><div class="meta">'+kchip(g.kind)+mchip(g.machine)+'<span>'+esc((g.last_ts||'').slice(0,16))+'</span><span>'+esc(g.folder||'')+'</span><span>'+esc(g.account||'')+'</span><span>'+g.hits+' matching messages</span>'+((g.kind==='code'||g.kind==='terminal')?copyBtn('claude --resume '+g.session):'')+'</div>'+g.snippets.map(function(s){return '<div class="snip"><span class="r">'+esc(s.role)+'</span>'+s.html+'</div>'}).join('')+'</div>'}).join(''):'<div class="dim">No conversation contains that.</div>';wireCopy(deep)}).catch(function(){deepOK=false;deep.innerHTML='<div class="dim">Conversation search is not reachable right now.</div>';dn.textContent='off'})}
q.addEventListener('input',function(){var v0=q.value.trim();clearTimeout(deepT);Q=v0;if(location.hash.indexOf('#search')===0){if(!v0){location.hash='#home';return}deepT=setTimeout(function(){lastQ=v0;renderSearch(v0)},220);return}if(views[CUR])views[CUR]()});
q.addEventListener('keydown',function(e){if(e.key==='Enter'&&q.value.trim()){e.preventDefault();lastQ=q.value.trim();if(location.hash!=='#search')history.replaceState(null,'','#search');show('search');renderSearch(lastQ)}});
document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus()}if(e.key==='Escape'&&document.activeElement===q){q.value='';Q='';q.blur();if(location.hash==='#search')location.hash='#home';else if(views[CUR])views[CUR]()}});

/* ---------- router ---------- */
var views={home:renderHome,projects:renderProjects,glance:renderGlance,sessions:renderSessions,assets:renderAssets,automations:renderAutomations};
/* ---------- TABLE (glance) ---------- */
var gFilter={a:'All',k:'All',auto:false},gSort={k:'d',dir:-1};
function renderGlance(){var v=document.getElementById('view-glance');
var accts=['All'].concat(D.accounts.map(function(a){return a.email}).filter(function(e){return e!=='(unknown account)'}));var kinds=['All','code','cowork'];var kl={All:'Everything',code:'Code only',cowork:'Claude tab only'};
var chips='<div class="chips">'+accts.map(function(a){return '<span class="chip'+(a===gFilter.a?' on':'')+'" data-ga="'+esc(a)+'">'+esc(a==='All'?'Both accounts':a.split('@')[0])+'</span>'}).join('')+'</div><div class="chips">'+kinds.map(function(k){return '<span class="chip'+(k===gFilter.k?' on':'')+'" data-gk="'+k+'">'+kl[k]+'</span>'}).join('')+'<span class="chip'+(gFilter.auto?' on':'')+'" data-gauto="1">Automation runs</span></div>';
var rows=D.ledger.filter(function(s){if(s.k==='terminal')return false;if(!gFilter.auto&&s.u)return false;if(gFilter.k!=='All'&&s.k!==gFilter.k)return false;if(gFilter.a!=='All'&&(s.b||s.a||'').indexOf(gFilter.a)<0)return false;return matchQ(s.t+' '+s.f+' '+(s.b||s.a||'')+' '+s.d+' '+(s.x||[]).join(' ')+' '+(s.m||''))});
var key=gSort.k;rows.sort(function(x,y){var a,b;if(key==='x'){a=(x.x||[]).length;b=(y.x||[]).length}else if(key==='b'){a=(x.b||x.a||'');b=(y.b||y.a||'')}else{a=x[key]==null?'':x[key];b=y[key]==null?'':y[key]}if(typeof a==='string'){a=a.toLowerCase();b=String(b).toLowerCase()}return (a<b?-1:a>b?1:0)*gSort.dir});
var hasM=(M.machines||[]).length>0;var cols=[['t','Session'],['f','Folder'],['b','Account'],['k','Kind'],['d','Last active'],['x','Started without']].concat(hasM?[['m','Computer']]:[]);
var th=cols.map(function(c){return '<th data-sort="'+c[0]+'" class="'+(gSort.k===c[0]?(gSort.dir>0?'asc':'desc'):'')+'">'+c[1]+'</th>'}).join('')+'<th></th>';
var body=rows.slice(0,600).map(function(s){var acct=s.b||(s.a||'').split(', ')[0];var cmd=s.k==='code'&&s.id&&s.id.length>20?'claude --resume '+s.id:'';return '<tr'+(s.u?' class="au"':'')+'><td class="tt">'+esc(s.t||'(untitled)')+'</td><td class="tf">'+esc(s.f||'')+'</td><td style="white-space:nowrap">'+dot(acct)+' '+esc((acct||'').split('@')[0])+'</td><td>'+(s.k==='cowork'?'<span class="cwm">tab</span>':'code')+'</td><td class="td">'+esc((s.d||'').replace('T',' '))+'</td><td>'+(s.x&&s.x.length?'<span class="x">!</span> '+esc(s.x.join(', ')):'')+'</td>'+(hasM?'<td>'+esc(s.m||M.machine)+'</td>':'')+'<td>'+(cmd?copyBtn(cmd,'Copy'):'')+'</td></tr>'}).join('');
v.innerHTML='<h1>Table</h1><p class="sub">Every session as plain data. Click a column heading to sort; the search box filters the rows.</p>'+chips+legendHtml()+'<div class="tcount dim">'+rows.length+' of '+D.ledger.length+' sessions'+(rows.length>600?' (first 600 shown)':'')+'</div><div class="twrap"><table class="tbl"><thead><tr>'+th+'</tr></thead><tbody>'+(body||'<tr><td colspan="9" class="dim">Nothing matches.</td></tr>')+'</tbody></table></div>';
v.querySelectorAll('[data-ga]').forEach(function(c){c.addEventListener('click',function(){gFilter.a=c.dataset.ga;renderGlance()})});
v.querySelectorAll('[data-gk]').forEach(function(c){c.addEventListener('click',function(){gFilter.k=c.dataset.gk;renderGlance()})});
v.querySelectorAll('[data-gauto]').forEach(function(c){c.addEventListener('click',function(){gFilter.auto=!gFilter.auto;renderGlance()})});
v.querySelectorAll('th[data-sort]').forEach(function(h){h.addEventListener('click',function(){if(gSort.k===h.dataset.sort)gSort.dir=-gSort.dir;else{gSort.k=h.dataset.sort;gSort.dir=h.dataset.sort==='d'?-1:1}renderGlance()})});
wireCopy(v)}
function show(name){document.querySelectorAll('.view').forEach(function(s){s.hidden=s.id!=='view-'+name});document.querySelectorAll('.rail a').forEach(function(a){a.classList.toggle('on',a.dataset.view===name)});window.scrollTo(0,0)}
function route(){var h=(location.hash||'#home').slice(1).split('/');var name=h[0]||'home';if(name==='projects'&&h[1]){pOpen=decodeURIComponent(h[1])}if(name==='search'){if(q.value.trim()){show('search');renderSearch(q.value.trim());return}name='home'}
if(views[name]){CUR=name;views[name]();show(name)}}
window.addEventListener('hashchange',route);route();
"""

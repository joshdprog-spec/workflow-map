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
    ledger = []
    try:
        L = json.load(open(HERE / "history" / "ledger.json", encoding="utf-8"))
        for sid, e in L.items():
            folder = os.path.basename(e.get("cwd", "")) if e.get("cwd") else ", ".join(e.get("folders", [])[:3])
            if not folder and e.get("project_slug"):
                folder = e["project_slug"].split("-")[-1]
            ledger.append({"id": sid, "t": e.get("title", ""), "d": (e.get("last_activity") or "")[:16], "f": folder, "a": ", ".join(e.get("accounts", [])),
                           "k": e.get("kind", ""), "r": e.get("kind") in ("code", "terminal")})
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
    <a href="#home" data-view="home"><span class="ico">&#9679;</span>Home</a>
    <a href="#projects" data-view="projects"><span class="ico">&#9638;</span>Projects</a>
    <a href="#sessions" data-view="sessions"><span class="ico">&#9776;</span>Sessions</a>
    <a href="#assets" data-view="assets"><span class="ico">&#9670;</span>Assets</a>
    <a href="#automations" data-view="automations"><span class="ico">&#8635;</span>Automations</a>
    <div class="rail-foot"><span id="stamp">{{STAMP}}</span><br><span class="dim">rebuilds itself</span></div>
  </nav>
  <main class="main">
    <header class="topbar">
      <div class="search-wrap"><span class="search-ico">&#8981;</span><input id="q" type="search" placeholder="Search projects, sessions, and inside every conversation" aria-label="Search" autocomplete="off"><kbd>/</kbd></div>
      <div id="acct-pill" class="pill"></div>
    </header>
    <section id="view-home" class="view"></section>
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

/* ---------- HOME ---------- */
function renderHome(){var v=document.getElementById('view-home');
var recent=D.projects.filter(function(p){return !p.alias_to&&p.exists}).slice(0,6);
var banner=M.mirror?'<div class="banner ok"><span>&#10003;</span><div><b>Every session is reachable from either account.</b> The app was last used as '+esc(M.current)+'. Claude-tab sessions still belong to the account shown on them.</div></div>':
(M.current===M.primary?'<div class="banner ok"><span>&#10003;</span><div><b>You are on '+esc(M.current)+'.</b> Everything below is in the sidebar.</div></div>':'<div class="banner bad"><span>&#9888;</span><div><b>Wrong account.</b> The app is on '+esc(M.current)+'; '+M.hidden_code+' Code and '+M.hidden_cw+' Claude-tab sessions belong to '+esc(M.primary)+'. Nothing is deleted. Sign out and back in as '+esc(M.primary)+'.</div></div>');
var kpis='<div class="kpis"><div class="kpi"><b>'+D.projects.filter(function(p){return p.exists&&!p.alias_to}).length+'</b><span>projects</span></div><div class="kpi"><b>'+M.n_code+'</b><span>Code sessions</span></div><div class="kpi"><b>'+M.n_cowork+'</b><span>Claude-tab sessions</span></div><div class="kpi"><b>'+M.ledger_n+'</b><span>in the history ledger</span></div><div class="kpi"><b>'+D.artifacts.length+'</b><span>published pages</span></div></div>';
var rows=recent.map(function(p){var pick=p.work[0]||p.cowork[0];var cmd=pick&&pick.k==='code'&&pick.id?'cd "'+p.folder+'" && claude --resume '+pick.id:'';
return '<div class="row with-tile" data-open="'+esc(p.name)+'" tabindex="0">'+tile(p.name,p.thumb)+'<div><div class="head"><span class="name">'+esc(p.name)+'</span><span class="chip">'+esc(p.group)+'</span></div><div class="note">'+(pick?esc(pick.t||'(untitled)')+' <span class="dim">· '+esc(ago(pick.d))+'</span>':'<span class="dim">no session yet</span>')+'</div></div><div>'+(cmd?copyBtn(cmd,'Copy resume',true):'')+'</div></div>'}).join('');
var accts=D.accounts.map(function(a){return '<div class="acct'+(a.current?' on':'')+'"><b>'+esc(a.email)+'</b><span>'+a.n_code+' Code · '+a.n_cowork+' Claude-tab · last used '+esc(ago(a.last))+'</span>'+(a.current?'<span class="now">app is on this one</span>':'')+'</div>'}).join('');
var prods=D.products.slice(0,showAllProds?999:6).map(function(p){var acts='';if(p.page)acts+='<a class="btn primary" href="http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(p.page)+'" target="_blank">Open the page</a>';if(p.ship_kit)acts+='<a class="btn" href="http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(p.ship_kit)+'" target="_blank">Launch checklist</a>';if(p.offer)acts+='<a class="btn" href="http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(p.offer)+'" target="_blank">Offer</a>';if(p.course)acts+='<a class="btn" href="http://127.0.0.1:'+M.port+'/file?path='+encodeURIComponent(p.course)+'" target="_blank">Course</a>';
var artb=(p.arts||[]).map(function(a){return '<a class="btn" href="'+esc(a.url)+'" target="_blank" title="'+esc(a.account)+'">&#9670; '+esc(a.title)+'</a>'}).join('');
return '<div class="prod">'+shot(p.name,p.thumb)+'<span class="stage'+(p.stage==='Ready to launch'?' ready':'')+'">'+esc(p.stage)+'</span>'+mchip(p.m)+'<h3>'+esc(p.name)+'</h3><div class="where">'+esc(p.where)+'</div><div class="dim" style="font-size:12.5px">in '+esc(p.project)+' · '+esc(ago(p.last))+(p.bundle?' · bundle ready':'')+'</div><div class="acts">'+(p.m?'<span class="dim">files are on '+esc(p.m)+'</span>':acts+artb)+'</div></div>'}).join('');
var mach=(M.machines||[]).map(function(m){return '<div class="acct"><b>'+esc(m.name)+'</b><span>'+m.n+' sessions · reported '+esc(ago(m.stamp))+'</span></div>'}).join('');
v.innerHTML='<h1>Where you left off</h1><p class="sub">The things you are building, then the projects you touched last. Copy a resume command, paste it in a terminal, and you are back inside that conversation.</p>'+banner+kpis+(prods?'<h2>Things you are building <span class="cnt">'+D.products.length+'</span></h2><div class="grid">'+prods+'</div>'+(D.products.length>6?'<div style="margin-top:10px"><button class="btn" id="all-prods">'+(showAllProds?'Show fewer':'Show all '+D.products.length)+'</button></div>':''):'')+'<h2>Pick up here</h2><div class="list">'+rows+'</div><h2>Accounts on this PC</h2><div class="acct-cards">'+accts+'</div>'+(mach?'<h2>Other computers</h2><div class="acct-cards">'+mach+'</div>':'');
v.querySelectorAll('[data-open]').forEach(function(r){r.addEventListener('click',function(){location.hash='#projects/'+encodeURIComponent(r.dataset.open)})});wireCopy(v);
var ap=document.getElementById('all-prods');if(ap)ap.addEventListener('click',function(){showAllProds=!showAllProds;renderHome()})}
var showAllProds=false;

/* ---------- PROJECTS ---------- */
var pFilter='All',pOpen=null;
function renderProjects(){var v=document.getElementById('view-projects');
var groups=[];D.projects.forEach(function(p){if(groups.indexOf(p.group)<0)groups.push(p.group)});
var order=M.group_order||[];groups.sort(function(a,b){var ia=order.indexOf(a),ib=order.indexOf(b);ia=ia<0?99:ia;ib=ib<0?99:ib;return ia-ib||a.localeCompare(b)});
var chips='<div class="chips">'+['All'].concat(groups).map(function(g){return '<span class="chip'+(g===pFilter?' on':'')+'" data-g="'+esc(g)+'">'+esc(g)+'</span>'}).join('')+'</div>';
var list=D.projects.filter(function(p){return pFilter==='All'||p.group===pFilter}).map(function(p){var open=p.name===pOpen;var pick=p.work[0]||p.cowork[0];var cmd=pick&&pick.k==='code'&&pick.id?'cd "'+p.folder+'" && claude --resume '+pick.id:'';
var name=p.alias_to?'<s class="dim">'+esc(p.name)+'</s> <span class="dim">is now</span> <b>'+esc(p.alias_to)+'</b>':(p.exists?esc(p.name):'<s>'+esc(p.name)+'</s> <span class="needs">folder gone</span>');
var det='';if(open){var files=p.state.length?p.state.map(function(f){return '<div class="file">'+esc(f)+'</div>'}).join(''):'<span class="dim">no state file</span>';
var all=p.work.map(sessLine).join('')+p.cowork.map(sessLine).join('')+p.elsewhere.map(sessLine).join('');var more=[];if(p.n_work>p.work.length)more.push((p.n_work-p.work.length)+' more here');if(p.n_cowork>p.cowork.length)more.push((p.n_cowork-p.cowork.length)+' more Claude-tab');if(p.n_elsewhere>p.elsewhere.length)more.push((p.n_elsewhere-p.elsewhere.length)+' more from other folders');
det='<div class="detail"><div class="box"><div class="lbl">Pick up here</div>'+(pick?'<div><b>'+esc(pick.t||'(untitled)')+'</b> <span class="dim">· '+esc(ago(pick.d))+'</span> '+acctNote(pick.a,pick.k)+'</div>'+(cmd?'<div style="margin-top:8px">'+copyBtn(cmd,'Copy resume command',true)+'</div>':''):'<span class="dim">No session in this folder yet.</span>')+'<div class="lbl" style="margin-top:12px">Read first</div>'+files+'<div class="lbl" style="margin-top:12px">Folder</div><div class="file">'+esc(p.folder)+'</div>'+((p.arts||[]).length?'<div class="lbl" style="margin-top:12px">Published pages</div>'+p.arts.map(function(a){return '<div class="sess" style="grid-template-columns:1fr auto"><span class="what"><a href="'+esc(a.url)+'" target="_blank">&#9670; '+esc(a.title)+'</a></span><span class="dim" style="font-size:12px">'+esc(a.account)+'</span></div>'}).join(''):'')+'</div><div class="box"><div class="lbl">Sessions that touched it <span class="cnt">'+(p.n_work+p.n_cowork+p.n_elsewhere)+'</span></div>'+(all||'<span class="dim">none found</span>')+(more.length?'<div class="dim" style="margin-top:6px">'+esc(more.join(', '))+'</div>':'')+(p.n_mem?'<div class="dim" style="margin-top:6px">'+p.n_mem+' memory notes</div>':'')+'</div></div>'}
return '<div class="row with-tile'+(open?' open':'')+'" data-p="'+esc(p.name)+'" tabindex="0">'+tile(p.name,p.thumb)+'<div><div class="head"><span class="name">'+name+'</span><span class="chip">'+esc(p.group)+'</span><span class="ago'+(hot(p.last)?' hot':'')+'">'+esc(ago(p.last))+'</span>'+((p.arts||[]).length?'<span class="chip acc">&#9670; '+p.arts.length+(p.arts.length===1?' page':' pages')+'</span>':'')+'</div><div class="note">'+(esc(p.note)||'<span class="dim">No description yet.</span>')+'</div></div><div>'+(cmd&&!open?copyBtn(cmd,'Copy resume'):'')+'</div>'+det+'</div>'}).join('');
v.innerHTML='<h1>Projects</h1><p class="sub">Every project folder, what it is, and where to pick it up. Click a row for its state file and every session that touched it.</p>'+chips+'<div class="list">'+list+'</div>';
v.querySelectorAll('.chips .chip').forEach(function(c){c.addEventListener('click',function(){pFilter=c.dataset.g;renderProjects()})});
v.querySelectorAll('.row[data-p]').forEach(function(r){r.addEventListener('click',function(e){if(e.target.closest('button,a,.detail'))return;pOpen=pOpen===r.dataset.p?null:r.dataset.p;renderProjects();var el=v.querySelector('.row.open');if(el)el.scrollIntoView({block:'nearest'})});r.addEventListener('keydown',function(e){if(e.key==='Enter'){pOpen=pOpen===r.dataset.p?null:r.dataset.p;renderProjects()}})});wireCopy(v)}

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
q.addEventListener('input',function(){var v0=q.value.trim();clearTimeout(deepT);if(!v0){if(location.hash==='#search')location.hash='#home';return}deepT=setTimeout(function(){lastQ=v0;if(location.hash!=='#search'){history.replaceState(null,'','#search')}show('search');renderSearch(v0)},220)});
document.addEventListener('keydown',function(e){if(e.key==='/'&&document.activeElement!==q){e.preventDefault();q.focus()}if(e.key==='Escape'&&document.activeElement===q){q.value='';q.blur();location.hash='#home'}});

/* ---------- router ---------- */
var views={home:renderHome,projects:renderProjects,sessions:renderSessions,assets:renderAssets,automations:renderAutomations};
function show(name){document.querySelectorAll('.view').forEach(function(s){s.hidden=s.id!=='view-'+name});document.querySelectorAll('.rail a').forEach(function(a){a.classList.toggle('on',a.dataset.view===name)});window.scrollTo(0,0)}
function route(){var h=(location.hash||'#home').slice(1).split('/');var name=h[0]||'home';if(name==='projects'&&h[1]){pOpen=decodeURIComponent(h[1])}if(name==='search'){if(q.value.trim()){show('search');renderSearch(q.value.trim())}else{name='home'}}
if(views[name]){views[name]();show(name)}}
window.addEventListener('hashchange',route);route();
"""

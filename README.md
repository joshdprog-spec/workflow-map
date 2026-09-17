# Workflow Map

A bird's-eye view of every project you work on with Claude Code, that keeps itself up to date.

One page. Every project folder on your computer, grouped by what it is, each with:

- a one-line description in your own words
- how long ago you last touched it
- which file to read first (HANDOFF, STATE, README, whatever you use)
- the session to pick up, with a one-click "copy resume command"
- every other session that touched it, including Cowork sessions from the Claude tab and sessions opened in other folders
- a plain warning if the Claude desktop app is signed into a different account than the one holding your work

It rebuilds itself every time a Claude session starts or ends. You never run anything.

Nothing leaves your machine. It reads local files only: your project folders, Claude Code's transcripts, and the desktop app's session index.

## Why

Claude Code stores sessions per account. If you have more than one Claude account on one computer, or your subscription lapses and the app comes back up on a different login, the sidebar goes empty and it looks like everything was deleted. It wasn't. The transcripts are still on disk. This map reads all of them, for every account, and tells you which login can see what.

Even with one account, twenty project folders and a hundred sessions is more than a sidebar can explain. The map is the "what is what" that the sidebar never gives you.

## Install

Requires Python 3.9+ and Claude Code (desktop app or terminal).

```bash
python install.py
```

That copies the builder to `~/workflow-map`, finds your project folders, writes a starter `config.json`, adds a hook to `~/.claude/settings.json` so the map rebuilds on every session start and end, installs a small Claude skill, and builds the first map.

Then open `~/workflow-map/00-WORKFLOW-MAP.html` in a browser.

Options:

```bash
python install.py --dir "D:\Maps\mine"     # install elsewhere
python install.py --root ~/code            # your projects live under a folder other than home
python install.py --no-hook                # build on demand only
python install.py --uninstall              # remove the hook and skill
```

## First thing to do after installing

The starter config has empty descriptions. Open any Claude session and say:

> describe my projects in the workflow map

The installed skill tells Claude how: read each folder's README or state file and latest sessions, write one plain sentence per project, assign a group, rebuild. Correct whatever it gets wrong in `config.json`.

## Two accounts? Turn on the mirror

Set `"mirror_sessions": true` in `config.json`. At every rebuild the builder copies each Code session's small sidebar record into every account's folder. The transcripts are already shared on disk, so a mirrored session opens normally from either login. Sign out and back in once after the first mirror and both sidebars show everything. From then on it is automatic.

- Archived and deleted sessions are left alone.
- Cowork (Claude-tab) sessions are not mirrored; the map still shows which account they need.
- Undo it exactly with `python build-map.py --unmirror`. A manifest records every file the mirror wrote, and only those are removed.

This writes into the desktop app's own data folder. It has been used on Windows against the app's session layout as of September 2026. If the app changes that layout the mirror may stop working, but it cannot delete anything of yours.

## History that survives

Every rebuild updates `history/ledger.json`: one entry per session ever seen, with its title, folder, account, kind, first and last seen. Entries are never removed, so a session the app or a cleanup deletes is still on record. `history/records/` keeps the latest copy of every sidebar record file.

Set `"backup_transcripts": true` to also keep a copy of every transcript under `history/transcripts/`, refreshed when the original changes. Budget roughly the size of `~/.claude/projects` (often a gigabyte or two). The first run copies everything; later runs copy only what changed.

Claude Code deletes terminal transcripts after 30 days by default. `python install.py --keep-transcripts` raises that to ten years by setting `cleanupPeriodDays` in your Claude settings.

## Assets that live per account

Three sections read what each Claude account holds on this machine, so you can see across accounts in one place:

- **Claude Projects**: the claude.ai kind, with name, description and knowledge docs, from each account's project cache.
- **Cowork deliverables**: the files each Claude-tab session produced, in its own output folder.
- **Published artifacts**: pages on claude.ai, listed from the `artifacts` list in `config.json` (ask Claude to add this account's artifacts; a session can only list its own account's).

## Search everything, including inside conversations

The search box at the top does three things at once:

1. filters the project cards
2. searches the history ledger: every session ever seen, by title, folder, account, date or kind
3. searches **inside every conversation**: what you said and what Claude said, with highlighted snippets, grouped by session. Click a title to read the whole conversation.

Number 3 uses a full-text index (`history/search.sqlite`, SQLite FTS5) that every rebuild keeps current. Only dialogue is indexed; tool output and file contents are not, so the index stays small (a few percent of the transcripts). Phrases in quotes work. Every word is required; the last word matches as a prefix.

The map page is a plain file, so to query the index it talks to a tiny local server, `search-server.py`, on `127.0.0.1:27183`. Enable it with `python install.py --search` (or `"search_server": true` in config): the builder starts it if it is not running, at every session start. It listens on the loopback address only. It also works without the map:

```bash
python search-server.py --query "pricing decision"     # from a terminal, or from a Claude session
python search-server.py --session <id>                 # print one whole conversation
```

While the server runs it also serves the map itself at `http://127.0.0.1:27183/map`, always the current build. Bookmark that instead of the file.

Without the server the first two searches still work; the page just says conversation search is not running.

## The session-start line

The SessionStart hook prints one line into every new Claude session: how many projects and sessions exist, which account the app is on, whether anything is hidden, the most recently touched projects, and where the full map is. So any session you open already knows the state of your work before you say a word.

## config.json

| Key | What it does |
|---|---|
| `projects_root` | Folder whose subfolders are your projects. Default: your home folder. |
| `primary_email` | The account that holds your real work. Auto-detected from the terminal login if blank. The banner turns red when the app is on a different one. |
| `notes` | One line per project folder. Shown on the card. |
| `group` | Label per project. Cards are clustered by it. |
| `group_order` | Order the groups appear in. Unlisted groups follow alphabetically. |
| `aliases` | `"OldFolderName": "NewFolderName"`. Old sessions show under the new name. |
| `exclude` | Subfolders of `projects_root` that are not projects. |
| `active_days` | Projects touched within this many days go in the top section of the Markdown map. |
| `min_mentions` | How many times a session must mention a project's folder name to count as having worked on it from another folder. Raise it if the "from" lines look noisy. |
| `mirror_sessions` | Copy every Code session's sidebar record into every account, so any login shows all of them. Default off. |
| `backup_transcripts` | Keep a copy of every transcript under `history/`. Default off. |
| `search_index` | Maintain the full-text index of conversations. Default on. |
| `search_server` | Keep the local search server running so the map can search inside conversations. Default off. |
| `search_port` | Port for that server on 127.0.0.1. Default 27183. |
| `automation_title_patterns` | Session titles matching these are scheduled-task runs, listed as counts rather than as work. |

## Files

| File | |
|---|---|
| `00-WORKFLOW-MAP.html` | The map. Open in a browser. Dark and light themes, search box, works on a phone. |
| `00-WORKFLOW-MAP.md` | Same content as Markdown, for Claude to read at the start of a session. |
| `build-map.py` | The builder. `python build-map.py --verbose` rebuilds by hand. |
| `config.json` | Your descriptions, groups, aliases, exclusions. The only file you edit. |
| `mention-cache.json` | Speeds up the transcript scan. Safe to delete. |
| `mirror-manifest.json` | Every sidebar record the mirror has written. `--unmirror` removes exactly these. |
| `history/` | The ledger, record backups, and (optionally) transcript backups. |
| `last-run.log` | One line per rebuild, or the traceback if it failed. |

## What it reads

- Project folders: top-level subfolders of `projects_root`
- Code-tab sessions: the desktop app's session index, for every account folder found (Windows `%APPDATA%\Claude\claude-code-sessions`, macOS `~/Library/Application Support/Claude/claude-code-sessions`)
- Terminal sessions: `~/.claude/projects/<slug>/*.jsonl`
- Cowork sessions: `local-agent-mode-sessions` next to the session index, with the folders each one had attached
- Scheduled tasks: `~/.claude/scheduled-tasks` plus which account each is registered to
- Memory: `~/.claude/projects/<slug>/memory`

The first build reads every transcript once to learn which sessions touched which projects (a few seconds per gigabyte). After that it only re-reads changed files, so a rebuild takes well under a second.

## Limits

- Cowork sessions cannot be resumed from a terminal. The map shows them and which account they need; reopen them from the Claude tab's history.
- The map reads the desktop app's index files as they exist today. If Anthropic changes that layout, the account and Cowork sections may go quiet until the builder is updated. Terminal sessions and project folders will still work.
- One projects root per install. If your projects are spread across drives, install twice with different `--dir` and `--root`.

## License

MIT. Do what you like with it.

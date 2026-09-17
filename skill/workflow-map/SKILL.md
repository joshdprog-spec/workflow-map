---
name: workflow-map
description: Keep the user's Workflow Map current. Use when the user asks where a project is, what they were working on, which session to resume, which Claude account holds their work, or asks to update, rebuild, describe, or fix the workflow map. Also use when a project folder is renamed so the map records the alias.
---

# Workflow Map

The map is a self-rebuilding page listing every project folder on this computer: what it is, when it was last touched, which file to read first, the latest sessions to resume, Cowork sessions, scheduled tasks, and which Claude account the desktop app is signed into.

## Where it lives

The folder holding `build-map.py` and `config.json` is the map's home. Find it with:

    grep -rl "build-map.py" ~/.claude/settings.json

and read the path out of the hook `args`. The default is `~/workflow-map`. Outputs are `00-WORKFLOW-MAP.md` (read this) and `00-WORKFLOW-MAP.html` (the user opens this) in that folder unless `config.json` says otherwise.

## Answering "where is X / what was I doing"

1. Read `00-WORKFLOW-MAP.md`. It is regenerated at every session start, so it is current.
2. Check the account banner first. If the app is on the wrong account, say so before anything else: nothing is deleted, the sidebar just cannot show the other account's sessions.
3. Answer from the map. Give the folder, the "read first" file, and the resume id. A Code session reopens with `claude --resume <id>` from a terminal inside that folder.

## Filling in or fixing descriptions

`config.json` holds `notes` (one line per project), `group` (label used to cluster cards), `group_order`, and `aliases` (old folder name -> new name). To describe projects:

1. For each project with an empty note, look at its top-level files, its README or HANDOFF or STATE file, and its latest session titles.
2. Write one plain sentence a stranger would understand: what it is and, if relevant, what stage it is at. Name the folder for the most important thing if the folder name hides it.
3. Assign a short group label ("App", "Product to sell", "Writing", "YouTube channel", "Client work"). Reuse labels; do not invent one per project.
4. Save `config.json` and rebuild:

       python <map folder>/build-map.py --verbose

5. Tell the user which projects you described and ask them to correct anything wrong.

## When a folder is renamed

Add `"OldName": "NewName"` to `aliases` in `config.json` and rebuild. Old sessions then show under the new name instead of as a missing folder.

## Searching inside conversations

When the user asks "where did we decide X", "which session talked about Y", or wants something they said weeks ago, search the full-text index instead of guessing:

    python "<map folder>/search-server.py" --query "the words"

It prints matching sessions, newest-best first, with snippets and the resume id. `--session <id>` prints one whole conversation (dialogue only). Quote a phrase to require it exactly.

## Artifacts

Published claude.ai pages belong to the account that published them, and there is no file on disk to mirror. The map lists them from the `artifacts` list in `config.json`: `{title, url, account, updated, project}`. When the user asks to add or refresh them, run the Artifact tool's `list` action (it shows this account's artifacts), merge any new ones into `config.json` with this account's email, and rebuild. Only a session on an account can list that account's artifacts, so ask the user to repeat the request from the other account if some are missing. A link the user shared from the artifact's Share menu opens from any account.

## Mirror and history

- If the user has more than one Claude account on this machine and complains that sessions vanished after switching, set `"mirror_sessions": true` in `config.json`, rebuild, and tell them to sign out and back in once. Explain that the transcripts were never gone; only the sidebar is per account.
- `history/ledger.json` lists every session ever seen, including ones the app no longer shows. Use it when the user asks about an old session that is missing from the map.
- `python build-map.py --unmirror` removes every record the mirror wrote and nothing else.

## Rules

- Never edit `00-WORKFLOW-MAP.md` or `.html` by hand. They are overwritten on the next rebuild. Edit `config.json`.
- Do not delete `mention-cache.json` unless the scan looks wrong; it only speeds up rebuilds.
- If a rebuild fails, `last-run.log` in the map folder has the traceback.

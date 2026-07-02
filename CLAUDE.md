@AGENTS.md

Claude-Code-specific notes (everything else lives in AGENTS.md):

- `.claude/settings.local.json` holds per-user permission grants and is gitignored — never commit
  it; a shared `.claude/settings.json` may be committed if the team wants one.
- Some allow-list entries in `settings.local.json` reference venv console scripts
  (`.venv/bin/coop-dax-review ...`, `.venv/bin/pytest`); prefer the `.venv/bin/python -m ...`
  forms from AGENTS.md — the console scripts have stale shebangs from the repo's old location.

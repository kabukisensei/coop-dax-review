# Publishing coop-dax-review

How to get this onto GitHub and PyPI so anyone can install it with
`pipx install coop-dax-review`. You do the GitHub + PyPI account steps **once**; after that,
**every release is just a git tag** and GitHub does the rest automatically — no passwords or API
tokens stored anywhere.

> Most steps run in a terminal. Lines starting with `$` are commands to type (without the `$`).

---

## Part A — Put the code on GitHub (one time)

The repo is already `git init`'d on `main` with `origin` set to
`https://github.com/kabukisensei/coop-dax-review.git`. The CI/publish workflows and
`pyproject.toml` assume the owner/name `kabukisensei/coop-dax-review`; use that or update those
references if you pick a different name.

1. **Make sure you're logged in to the GitHub CLI** (`gh auth status`).
2. **Create the GitHub repo and push** (from the project folder):
   ```
   $ gh repo create kabukisensei/coop-dax-review --private --source=. --remote=origin --push
   ```
   If the repo already exists, just push: `$ git push -u origin main`.
   (Use `--public` instead of `--private` if it should be open.)
3. Confirm the **CI** workflow runs green on GitHub (Actions tab). It lints (`ruff check` +
   `ruff format --check`) and tests on Windows + Linux across Python 3.10–3.13.

---

## Part B — Set up PyPI Trusted Publishing (one time, no tokens)

This lets GitHub publish to PyPI securely without storing any secret.

1. **Create a PyPI account** at https://pypi.org and **turn on 2FA** (Account settings → Add 2FA).
2. **Add a "pending publisher"** so PyPI accepts the first upload from your GitHub Action. Go to
   https://pypi.org/manage/account/publishing/ and fill in:
   - **PyPI project name:** `coop-dax-review`
   - **Owner:** `kabukisensei`
   - **Repository name:** `coop-dax-review`
   - **Workflow name:** `publish.yml`
   - **Environment name:** `pypi`

   Click **Add**.
3. **Create the matching GitHub environment:** repo → **Settings → Environments → New environment**
   → name it exactly **`pypi`** → Save. (No secrets needed inside it.)

The repo's `.github/workflows/publish.yml` already requests the right permissions
(`id-token: write`, `environment: pypi`) and uses the official `pypa/gh-action-pypi-publish` action.

---

## Part C — Cut a release (every time)

A release is triggered by pushing a **version tag** that starts with `v`.

> **Agents — hard guardrails.** The tag push in step 2 publishes to PyPI immediately. Only cut a
> release when Aaron has explicitly asked for one **naming the version** in the current
> conversation. Never infer a release from a clean working tree, a version bump you notice, or
> green CI (real incident 2026-07-02: a spurious empty release was tagged off a "clean tree"
> signal while another agent shared the tree). Never move, delete, or reuse an existing `v*` tag.
> Suite ordering: `coop-review-core` is released **first** (this repo pins
> `coop-review-core>=...`), and a suite release is **not done** until the `coop-website` repo is
> synced + pushed — `versions.json` first, then both of its check scripts `PASS` (procedure:
> coop-website's `AGENTS.md`, "Release-time procedure").

1. **Bump the version in one place** — the version is single-sourced:
   - `src/coop_dax_review/__init__.py` → `__version__ = "0.1.1"`

   `pyproject.toml` derives the version from this via hatchling dynamic versioning
   (`dynamic = ["version"]` + `[tool.hatch.version]`), so do **not** add a `version =` line to
   `pyproject.toml` — it breaks the build.

   Use [semver](https://semver.org): last number for fixes, middle for features, first for breaking.
2. **Commit and tag:**
   ```
   $ git add -A && git commit -m "Release v0.1.1"
   $ git push
   $ git tag v0.1.1 && git push origin v0.1.1
   ```
3. The **publish workflow** runs automatically: builds, smoke-tests the wheel in a clean venv
   (`coop-dax-review --version`), and publishes to PyPI. Watch the **Actions** tab. Within a couple
   of minutes the new version is live at https://pypi.org/project/coop-dax-review/.

4. **Verify — both must be true before calling the release done:**
   - the `Publish to PyPI` workflow run shows a green check on the Actions tab
     (`gh run list --workflow=publish.yml --limit 1` shows `completed  success`);
   - `python -m pip index versions coop-dax-review` lists the new version (or the PyPI page
     shows it). If the workflow failed, **do not delete or re-push the tag** — fix the cause,
     bump to the next patch version, and release that instead.

> **PyPI version numbers are permanent** — you can't re-upload or reuse a number (even after
> deleting it). If a release is bad, bump to the next number and publish again.

---

## Before any release — green locally (CI enforces the same)

```
$ make lint             # = .venv/bin/python -m ruff check src tests  +  ruff format --check src tests
$ make test             # = .venv/bin/python -m pytest -q  (expect all tests passing)
$ make release-check    # must print `release-check: OK`
$ make build            # optional: validate the artifacts build cleanly
```

> Dev note: in some local venvs the editable `coop-dax-review` console script can intermittently
> fail to import — run the CLI as `PYTHONPATH=src python -m coop_dax_review ...` if so. This never
> affects pipx/pip installs from PyPI (those are real installs).

---

## Quick reference

| Task | Command |
|---|---|
| First push to GitHub | `gh repo create kabukisensei/coop-dax-review --source=. --remote=origin --push` |
| Build + validate locally | `python -m build && twine check dist/*` |
| Cut release `vX.Y.Z` | bump version in `src/coop_dax_review/__init__.py` → commit → `git tag vX.Y.Z && git push origin vX.Y.Z` |
| What published | https://pypi.org/project/coop-dax-review/ |
| First-run setup | PyPI 2FA + pending publisher + GitHub `pypi` environment (Part B, once) |

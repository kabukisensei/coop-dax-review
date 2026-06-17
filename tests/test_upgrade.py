"""Self-update logic (no network): classification + the user-facing command shapes.

`update`/`upgrade` never self-apply (a running program can't reliably replace
itself); they print `upgrade_command(plan)` for the user to run. These assertions
pin the command shape for every install method, including the fragile editable
``-e`` slice and the git-checkout pull+reinstall pair.
"""

from pathlib import Path

from coop_dax_review.upgrade import (
    UpgradePlan,
    classify_update,
    is_vcs_spec,
    upgrade_command,
)


def test_classify_update():
    assert classify_update("1.0.0", None) == "unknown"
    assert classify_update("1.0.0", "1.0.0") == "current"
    assert classify_update("1.0.0", "1.2.0") == "safe"
    assert classify_update("1.0.0", "2.0.0") == "major"


def test_is_vcs_spec_by_scheme_not_substring():
    assert is_vcs_spec("git+https://example/x.git")
    assert not is_vcs_spec("/home/u/c++proj")  # a bare '+' is not VCS
    assert not is_vcs_spec(None)


def test_upgrade_command_pipx_pypi_is_pipx_upgrade():
    plan = UpgradePlan("pipx", None, "0.1.0", "note", pip_spec=None)
    assert upgrade_command(plan) == [["pipx", "upgrade", "coop-dax-review"]]


def test_upgrade_command_pipx_vcs_is_reinstall():
    plan = UpgradePlan("pipx", None, "0.1.0", "note", pip_spec="git+https://e/x.git@main")
    assert upgrade_command(plan) == [["pipx", "reinstall", "coop-dax-review"]]


def test_upgrade_command_uv_tool_pypi():
    plan = UpgradePlan("uv-tool", None, "0.1.0", "note", pip_spec=None)
    assert upgrade_command(plan) == [["uv", "tool", "upgrade", "coop-dax-review"]]


def test_upgrade_command_uv_tool_vcs_force_installs_spec():
    plan = UpgradePlan("uv-tool", None, "0.1.0", "note", pip_spec="git+https://e/x.git@main")
    assert upgrade_command(plan) == [["uv", "tool", "install", "--force", "git+https://e/x.git@main"]]


def test_upgrade_command_pip_pypi_uses_friendly_python():
    # Display tokens, not sys.executable: a copy-pasteable `python -m pip ...`.
    plan = UpgradePlan("pip", None, "0.1.0", "note", pip_spec=None)
    assert upgrade_command(plan) == [["python", "-m", "pip", "install", "-U", "coop-dax-review"]]


def test_upgrade_command_pip_url_force_reinstalls():
    plan = UpgradePlan("pip", None, "0.1.0", "note", pip_spec="git+https://e/x.git@main")
    assert upgrade_command(plan) == [
        ["python", "-m", "pip", "install", "-U", "--force-reinstall", "git+https://e/x.git@main"]
    ]


def test_upgrade_command_pip_editable_keeps_the_dash_e_token():
    # The `[3:]` slice strips the literal "-e " — pin it so an off-by-one is caught.
    plan = UpgradePlan("pip", None, "0.1.0", "note", pip_spec="-e /home/u/proj")
    assert upgrade_command(plan) == [
        ["python", "-m", "pip", "install", "-U", "--force-reinstall", "-e", "/home/u/proj"]
    ]


def test_upgrade_command_git_checkout_with_new_commits_pulls_then_reinstalls():
    plan = UpgradePlan("git-checkout", Path("/repo"), "0.1.0", "2 new commit(s) available")
    assert upgrade_command(plan) == [
        ["git", "-C", "/repo", "pull", "--ff-only"],
        ["python", "-m", "pip", "install", "-U", "/repo"],
    ]


def test_upgrade_command_git_checkout_up_to_date_reinstalls_only():
    # No upstream / already current -> never emit `git pull` (it would error / no-op);
    # still reinstall so a non-editable clone is actually refreshed.
    plan = UpgradePlan("git-checkout", Path("/repo"), "0.1.0", "checkout is up to date with its upstream")
    assert upgrade_command(plan) == [["python", "-m", "pip", "install", "-U", "/repo"]]

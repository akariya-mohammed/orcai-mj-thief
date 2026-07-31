"""Task 7.8: the two-repo submission builder — role separation, cross-links,
tags, and secrets hygiene by construction."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "prepare_submission", Path("scripts/prepare_submission.py"))
prep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prep)


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                          text=True).stdout.strip()


IN_A_BUILT_REPO = not (Path("config/police").exists() and Path("config/thief").exists())
BUILD_ONLY = pytest.mark.skipif(
    IN_A_BUILT_REPO,
    reason="running inside a role-separated submission build: the other role's config is "
           "stripped by design, so the builder's own round-trip cannot be exercised here")


@BUILD_ONLY
def test_role_file_selection_strips_the_other_side():
    files = prep.tracked_files()
    police = prep.select_files(files, "police")
    thief = prep.select_files(files, "thief")
    assert "config/police/game.toml" in police
    assert not any(f.startswith("config/thief") for f in police)
    assert "config/thief/game.toml" in thief
    assert not any(f.startswith("config/police") for f in thief)
    assert "src/police_thief/domain/board.py" in police   # shared engine ships in both


@BUILD_ONLY
def test_full_build_two_repos_with_tags_and_cross_links(tmp_path):
    out = prep.build_all(tmp_path, police_url="https://github.com/x/cop",
                         thief_url="https://github.com/x/thief",
                         tag="v1.0-submission")
    for role, other_url in (("police", "https://github.com/x/thief"),
                            ("thief", "https://github.com/x/cop")):
        repo = tmp_path / role
        assert (repo / ".git").exists()
        assert _git(repo, "tag", "-l") == "v1.0-submission"
        readme = (repo / "README.md").read_text(encoding="utf-8")
        assert other_url in readme                          # cross-link (Rule 49)
        assert f"the {role.upper()} peer" in readme         # role banner
        assert _git(repo, "remote", "get-url", "origin")    # remote configured
    assert out["police"]["files"] > 50


@BUILD_ONLY
def test_secrets_never_reach_the_build(tmp_path):
    # Plant secrets in the working tree (gitignored -> untracked -> excluded by
    # construction); the scanner must ALSO pass as belt-and-suspenders.
    for name in ("credentials.json", "token.json"):
        Path(name).write_text("{}", encoding="utf-8")
    try:
        prep.build_all(tmp_path, police_url="", thief_url="", tag="v0-test")
        for role in ("police", "thief"):
            hits = [p for p in (tmp_path / role).rglob("*")
                    if p.name in ("credentials.json", "token.json")]
            assert hits == []
    finally:
        Path("credentials.json").unlink()
        Path("token.json").unlink()

"""Build the two submission repositories (task 7.8, Rules 49-50).

One engine, two role-separated repos: each build contains every TRACKED file
(so secrets / outbox / artifacts / logs are excluded BY CONSTRUCTION — they are
gitignored and untracked) minus the OTHER role's private config tree, plus a
role banner and the cross-link to the paired repo (Rule 49). Each build is git-
initialized, committed, tagged, and its remote configured. Nothing is pushed
automatically — the exact push commands are printed (--push opts in).

Run:  uv run python scripts/prepare_submission.py \
          --police-url https://github.com/YOU/cop-repo \
          --thief-url  https://github.com/YOU/thief-repo
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SECRETS = {"credentials.json", "token.json"}
OTHER_CONFIG = {"police": "config/thief", "thief": "config/police"}
BANNER = "> **This repository: the {role} peer.** Paired repo (the other agent): {url}\n"


def _drop_tree(path: Path) -> None:
    """Remove a previous build. Git marks objects read-only, which makes plain
    rmtree fail on Windows — clear the bit and retry rather than leaving a stale
    build that would be pushed by mistake."""
    def _unlock(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if path.exists():
        shutil.rmtree(path, onexc=_unlock)


def _git(cwd, *args) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def tracked_files() -> list[str]:
    return _git(".", "ls-files").splitlines()


def select_files(files: list[str], role: str) -> list[str]:
    return [f for f in files if not f.startswith(OTHER_CONFIG[role])]


def _patch_readme(repo: Path, role: str, other_url: str) -> None:
    readme = repo / "README.md"
    text = readme.read_text(encoding="utf-8")
    url = other_url or "[LINK TO PAIRED REPO]"
    text = text.replace("**[LINK TO PAIRED REPO]**", url).replace(
        "[LINK TO PAIRED REPO]", url)
    lines = text.splitlines(keepends=True)
    lines.insert(1, "\n" + BANNER.format(role=role.upper(), url=url))
    readme.write_text("".join(lines), encoding="utf-8")


def _scan_secrets(repo: Path) -> None:
    hits = [p for p in repo.rglob("*") if p.name in SECRETS]
    if hits:
        sys.exit(f"FATAL: secrets found in build: {hits} — aborting (Rules 39-40)")


def build_role(out_dir: Path, role: str, my_url: str, other_url: str,
               tag: str) -> dict:
    repo = out_dir / role
    _drop_tree(repo)
    files = select_files(tracked_files(), role)
    for f in files:
        dest = repo / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    _patch_readme(repo, role, other_url)
    _scan_secrets(repo)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m",
         f"Final submission — {role} peer (police-thief P2P)")
    _git(repo, "tag", "-a", tag, "-m", f"Final submission: {role} peer, {tag}")
    if my_url:
        _git(repo, "remote", "add", "origin", my_url)
    return {"path": str(repo), "files": len(files)}


def build_all(out_dir, police_url: str, thief_url: str,
              tag: str = "v1.0-submission") -> dict:
    out = Path(out_dir)
    return {"police": build_role(out, "police", police_url, thief_url, tag),
            "thief": build_role(out, "thief", thief_url, police_url, tag)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build the two submission repos")
    parser.add_argument("--out", default="build")
    parser.add_argument("--police-url", default="")
    parser.add_argument("--thief-url", default="")
    parser.add_argument("--tag", default="v1.0-submission")
    parser.add_argument("--push", action="store_true",
                        help="actually push (default: print the commands)")
    parser.add_argument("--force", action="store_true",
                        help="replace the remote snapshot (each build is a fresh "
                             "squashed history, so re-cutting a release needs this)")
    args = parser.parse_args(argv)

    result = build_all(args.out, args.police_url, args.thief_url, args.tag)
    for role, info in result.items():
        print(f"{role}: {info['files']} files -> {info['path']} (tag {args.tag})")
        url = args.police_url if role == "police" else args.thief_url
        if url and args.push:
            flags = ["--force"] if args.force else []
            _git(info["path"], "push", "-u", *flags, "origin", "main")
            _git(info["path"], "push", *flags, "origin", args.tag)
            print(f"  pushed to {url}" + (" (forced)" if args.force else ""))
        elif url:
            print(f"  to publish:  cd {info['path']} && git push -u origin main --tags")
        else:
            print("  no remote URL given — create the GitHub repo and re-run with "
                  f"--{role}-url")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Sync GitLab pipeline schedules with .ci/schedules.yaml.

Shows the difference by default. --apply creates and updates schedules;
--prune also deletes schedules the file does not list, in the projects the
file names. Talks to GitLab through `glab api`, so it uses the operator's
glab login and stores no token.

Usage:
    python3 sync_schedules.py [--file .ci/schedules.yaml] [--apply [--prune]]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import yaml

HOST = "source.example.com"

Api = Callable[..., Any]


def glab_api(path: str, method: str = "GET", fields: dict[str, str] | None = None) -> Any:
    cmd = ["glab", "api", "--hostname", HOST, "-X", method, path]
    for key, value in (fields or {}).items():
        cmd += ["-f", f"{key}={value}"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else None


def load_desired(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text()) or {}
    timezone, ref = data.get("timezone", "UTC"), data.get("ref", "main")
    out, seen = [], set()
    for s in data.get("schedules") or []:
        key = (s["project"], s["description"])
        if key in seen:
            raise ValueError(f"{path}: duplicate schedule {key}")
        seen.add(key)
        out.append({
            "project": s["project"],
            "description": s["description"],
            "cron": s["cron"],
            "cron_timezone": s.get("timezone", timezone),
            "ref": s.get("ref", ref),
            "active": s.get("active", True),
            "variables": {k: str(v) for k, v in (s.get("variables") or {}).items()},
        })
    return out


def _pid(project: str) -> str:
    return quote(project, safe="")


def load_live(projects: set[str], api: Api) -> list[dict[str, Any]]:
    out = []
    for project in sorted(projects):
        for s in api(f"projects/{_pid(project)}/pipeline_schedules"):
            full = api(f"projects/{_pid(project)}/pipeline_schedules/{s['id']}")
            out.append({
                "project": project,
                "id": s["id"],
                "description": s["description"],
                "cron": s["cron"],
                "cron_timezone": s["cron_timezone"],
                "ref": s["ref"].removeprefix("refs/heads/"),
                "active": s["active"],
                "variables": {v["key"]: v["value"] for v in full.get("variables") or []},
            })
    return out


FIELDS = ("cron", "cron_timezone", "ref", "active")


def plan(desired: list[dict[str, Any]], live: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any], Any]]:
    """Actions as (kind, desired-or-live schedule, detail)."""
    by_key = {(s["project"], s["description"]): s for s in live}
    actions: list[tuple[str, dict[str, Any], Any]] = []
    for want in desired:
        have = by_key.pop((want["project"], want["description"]), None)
        if have is None:
            actions.append(("create", want, None))
            continue
        changed = {f: (have[f], want[f]) for f in FIELDS if have[f] != want[f]}
        if changed:
            actions.append(("update", dict(want, id=have["id"]), changed))
        for key in sorted(set(want["variables"]) | set(have["variables"])):
            old, new = have["variables"].get(key), want["variables"].get(key)
            if old != new:
                actions.append(("variable", dict(want, id=have["id"]), (key, old, new)))
    for extra in by_key.values():
        actions.append(("unlisted", extra, None))
    return actions


def describe(kind: str, s: dict[str, Any], detail: Any) -> str:
    name = f"{s['project']} {s['description']!r}"
    if kind == "create":
        return f"create {name}: {s['cron']} {s['cron_timezone']} variables={s['variables']}"
    if kind == "update":
        return f"update {name}: " + ", ".join(f"{f} {a!r} -> {b!r}" for f, (a, b) in detail.items())
    if kind == "variable":
        key, old, new = detail
        return f"variable {name}: {key} {old!r} -> {new!r}"
    return f"unlisted {name} (id {s['id']}): deleted only with --prune"


def apply(actions: list[tuple[str, dict[str, Any], Any]], prune: bool, api: Api) -> None:
    for kind, s, detail in actions:
        base = f"projects/{_pid(s['project'])}/pipeline_schedules"
        if kind == "create":
            made = api(base, "POST", {"description": s["description"], "ref": s["ref"],
                                      "cron": s["cron"], "cron_timezone": s["cron_timezone"],
                                      "active": str(s["active"]).lower()})
            for key, value in s["variables"].items():
                api(f"{base}/{made['id']}/variables", "POST", {"key": key, "value": value})
        elif kind == "update":
            api(f"{base}/{s['id']}", "PUT", {f: str(s[f]).lower() if f == "active" else s[f] for f in detail})
        elif kind == "variable":
            key, old, new = detail
            if new is None:
                api(f"{base}/{s['id']}/variables/{key}", "DELETE")
            elif old is None:
                api(f"{base}/{s['id']}/variables", "POST", {"key": key, "value": new})
            else:
                api(f"{base}/{s['id']}/variables/{key}", "PUT", {"value": new})
        elif kind == "unlisted" and prune:
            api(f"{base}/{s['id']}", "DELETE")


def main(argv: list[str] | None = None, api: Api = glab_api) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--file", default=".ci/schedules.yaml", type=Path)
    parser.add_argument("--apply", action="store_true", help="create and update schedules")
    parser.add_argument("--prune", action="store_true", help="with --apply, delete unlisted schedules")
    args = parser.parse_args(argv)
    if args.prune and not args.apply:
        parser.error("--prune needs --apply")

    desired = load_desired(args.file)
    actions = plan(desired, load_live({s["project"] for s in desired}, api))
    for action in actions:
        print(describe(*action))
    if not actions:
        print(f"schedules: {len(desired)} in sync")
        return 0
    if args.apply:
        apply(actions, args.prune, api)
        print("applied")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

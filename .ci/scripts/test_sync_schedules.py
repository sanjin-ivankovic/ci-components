"""Tests for sync_schedules.py against an in-memory GitLab."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import sync_schedules as ss

FILE = """
timezone: Europe/Berlin
ref: main
schedules:
  - project: homelab/a
    description: GitHub Mirror
    cron: "0 4 * * *"
    variables:
      SCHEDULE_TYPE: mirror
  - project: homelab/b
    description: nightly
    cron: "0 3 * * *"
"""


class FakeGitLab:
    """Pipeline schedules keyed by project, served through the api() signature."""

    def __init__(self, schedules: dict[str, list[dict[str, Any]]]):
        self.schedules = schedules
        self.calls: list[tuple[str, str, dict[str, str] | None]] = []
        self.next_id = 100

    def __call__(self, path: str, method: str = "GET", fields: dict[str, str] | None = None) -> Any:
        self.calls.append((method, path, fields))
        parts = path.split("/")
        project = parts[1].replace("%2F", "/")
        items = self.schedules.setdefault(project, [])
        if method == "GET" and len(parts) == 3:
            return items
        if method == "GET":
            return next(s for s in items if s["id"] == int(parts[3]))
        if method == "POST" and len(parts) == 3:
            self.next_id += 1
            items.append(dict(id=self.next_id, variables=[], cron_timezone=fields["cron_timezone"],
                              ref=fields["ref"], active=fields["active"] == "true",
                              description=fields["description"], cron=fields["cron"]))
            return items[-1]
        return {}


def live(id_: int, description: str, cron: str, variables: dict[str, str] | None = None,
         **over: Any) -> dict[str, Any]:
    base = {"id": id_, "description": description, "cron": cron, "cron_timezone": "Europe/Berlin",
            "ref": "refs/heads/main", "active": True,
            "variables": [{"key": k, "value": v} for k, v in (variables or {}).items()]}
    return dict(base, **over)


@pytest.fixture
def file(tmp_path: Path) -> Path:
    path = tmp_path / "schedules.yaml"
    path.write_text(FILE)
    return path


def in_sync() -> FakeGitLab:
    return FakeGitLab({
        "homelab/a": [live(1, "GitHub Mirror", "0 4 * * *", {"SCHEDULE_TYPE": "mirror"})],
        "homelab/b": [live(2, "nightly", "0 3 * * *")],
    })


def test_in_sync(file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ss.main(["--file", str(file)], api=in_sync()) == 0
    assert "2 in sync" in capsys.readouterr().out


def test_drift_is_reported_not_applied(file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gl = FakeGitLab({
        "homelab/a": [live(1, "GitHub Mirror", "5 4 * * *", {"SCHEDULE_TYPE": "rebuild", "X": "1"})],
        "homelab/b": [live(3, "old", "0 1 * * *")],
    })
    assert ss.main(["--file", str(file)], api=gl) == 2
    out = capsys.readouterr().out
    assert "update homelab/a 'GitHub Mirror': cron '5 4 * * *' -> '0 4 * * *'" in out
    assert "variable homelab/a 'GitHub Mirror': SCHEDULE_TYPE 'rebuild' -> 'mirror'" in out
    assert "variable homelab/a 'GitHub Mirror': X '1' -> None" in out
    assert "create homelab/b 'nightly'" in out
    assert "unlisted homelab/b 'old' (id 3)" in out
    assert all(method == "GET" for method, _, _ in gl.calls)


def test_apply_without_prune_keeps_unlisted(file: Path) -> None:
    gl = FakeGitLab({
        "homelab/a": [live(1, "GitHub Mirror", "5 4 * * *", {"X": "1"}, active=False)],
        "homelab/b": [live(3, "old", "0 1 * * *")],
    })
    assert ss.main(["--file", str(file), "--apply"], api=gl) == 0
    writes = [(m, p, f) for m, p, f in gl.calls if m != "GET"]
    assert ("PUT", "projects/homelab%2Fa/pipeline_schedules/1",
            {"cron": "0 4 * * *", "active": "true"}) in writes
    assert ("POST", "projects/homelab%2Fa/pipeline_schedules/1/variables",
            {"key": "SCHEDULE_TYPE", "value": "mirror"}) in writes
    assert ("DELETE", "projects/homelab%2Fa/pipeline_schedules/1/variables/X", None) in writes
    assert any(m == "POST" and p == "projects/homelab%2Fb/pipeline_schedules" for m, p, _ in writes)
    assert not any(m == "DELETE" and p.endswith("/pipeline_schedules/3") for m, p, _ in writes)


def test_variable_value_change_is_a_put(file: Path) -> None:
    gl = in_sync()
    gl.schedules["homelab/a"][0]["variables"] = [{"key": "SCHEDULE_TYPE", "value": "rebuild"}]
    ss.main(["--file", str(file), "--apply"], api=gl)
    assert ("PUT", "projects/homelab%2Fa/pipeline_schedules/1/variables/SCHEDULE_TYPE",
            {"value": "mirror"}) in gl.calls


def test_create_adds_variables(file: Path) -> None:
    gl = FakeGitLab({"homelab/b": [live(2, "nightly", "0 3 * * *")]})
    ss.main(["--file", str(file), "--apply"], api=gl)
    assert ("POST", "projects/homelab%2Fa/pipeline_schedules/101/variables",
            {"key": "SCHEDULE_TYPE", "value": "mirror"}) in gl.calls


def test_prune_deletes_unlisted(file: Path) -> None:
    gl = in_sync()
    gl.schedules["homelab/b"].append(live(3, "old", "0 1 * * *"))
    ss.main(["--file", str(file), "--apply", "--prune"], api=gl)
    assert ("DELETE", "projects/homelab%2Fb/pipeline_schedules/3", None) in gl.calls


def test_prune_needs_apply(file: Path) -> None:
    with pytest.raises(SystemExit):
        ss.main(["--file", str(file), "--prune"], api=in_sync())


def test_duplicate_schedule_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.yaml"
    path.write_text("schedules:\n  - {project: p, description: d, cron: x}\n"
                    "  - {project: p, description: d, cron: y}\n")
    with pytest.raises(ValueError, match="duplicate"):
        ss.load_desired(path)

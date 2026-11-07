"""Tests for check_repo_standard.py, each against a throwaway git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import check_repo_standard as crs

RULES_MD = "\n".join(f"## {s}\n" for s in crs.RULES_SECTIONS)
CI_OK = """
default:
  interruptible: true
workflow:
  auto_cancel:
    on_new_commit: interruptible
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule"'
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - if: '$CI_COMMIT_BRANCH == "main" && $CI_PIPELINE_SOURCE == "push"'
    - if: '$CI_COMMIT_TAG =~ /^v/'
    - when: never
stages: [scan, lint, test, mirror]
include:
  - component: $CI_SERVER_FQDN/example-org/ci-components/scan-secrets@4.2.1
  - component: $CI_SERVER_FQDN/example-org/ci-components/lint-yaml@4.2.1
test:unit:
  stage: test
  rules:
    - when: always
  script: [pytest]
"""
PRECOMMIT_OK = "repos:\n" + "".join(
    f"  - repo: local\n    hooks:\n      - id: {hid}\n" for hid in crs.PRECOMMIT_CORE
    if hid != "conventional-pre-commit"
) + "  - repo: x\n    hooks:\n      - id: conventional-pre-commit\n        args: [" + ", ".join(crs.COMMIT_TYPES) + "]\n"
GOOD = {
    "README.md": ("# repo\n\n## Purpose\n\n```bash\n# a comment, not a heading\n```\n\n"
                  "## Quick start\n\n## Develop\n\n## Documentation\n\n## License\n"),
    "LICENSE": "MIT License\n\nCopyright (c) 2025 Someone\n",
    ".editorconfig": "root = true\n",
    ".gitattributes": "\n".join(crs.GITATTRIBUTES_BASE) + "\n*.go text eol=lf\n",
    ".gitignore": "\n".join(crs.GITIGNORE_BASE) + "\nbuild/\n",
    ".pre-commit-config.yaml": PRECOMMIT_OK,
    "renovate.json": "{}\n",
    "Makefile": ".DEFAULT_GOAL := help\nhelp: ## Show help\n\t@true\n",
    ".gitlab-ci.yml": CI_OK,
    ".claude/CLAUDE.md": "# CLAUDE.md\n",
    ".claude/rules/devops.md": "# rules\n\n" + RULES_MD,
    ".config/.yamllint": "extends: default\n",
    "docs/README.md": "# Docs\n",
    "docs/ARCHITECTURE.md": "# Architecture\n",
    "scripts/do-thing.sh": "#!/bin/sh\n",
    ".ci/scripts/detect_apps.py": "",
}


@pytest.fixture
def base(tmp_path: Path) -> Path:
    base = tmp_path / "base"
    base.mkdir()
    (base / ".editorconfig").write_text("root = true\n")
    for name in crs.CONFIG_BASE_FILES:
        (base / name).write_text("extends: default\n" if name == ".yamllint" else f"{name}\n")
    return base


def make_repo(tmp_path: Path, files: dict[str, str]) -> crs.Repo:
    root = tmp_path / "repo"
    root.mkdir()
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-f", "."], check=True)
    return crs.Repo(root)


def violations(tmp_path: Path, base: Path, files: dict[str, str]) -> list[crs.Violation]:
    repo = make_repo(tmp_path, files)
    return crs.check_repo(repo, base, base / ".editorconfig")


def rules_hit(tmp_path: Path, base: Path, changes: dict[str, str | None]) -> set[str]:
    files = dict(GOOD)
    for rel, text in changes.items():
        if text is None:
            files.pop(rel)
        else:
            files[rel] = text
    return {v[0] for v in violations(tmp_path, base, files)}


def test_good_repo_is_clean(tmp_path: Path, base: Path) -> None:
    assert violations(tmp_path, base, GOOD) == []


def test_missing_file(tmp_path: Path, base: Path) -> None:
    assert rules_hit(tmp_path, base, {"Makefile": None}) == {"required-files"}


@pytest.mark.parametrize("text", [
    "# rules\n\n## Skill routing\n## Hard rules\n## Commit conventions\n## Docs contract\n## Operating principle\n",
    "# rules\n\n## Hard rules\n",
])
def test_rules_file_sections(tmp_path: Path, base: Path, text: str) -> None:
    assert rules_hit(tmp_path, base, {".claude/rules/devops.md": text}) == {"rules-file"}


def test_rules_file_extra_section_allowed(tmp_path: Path, base: Path) -> None:
    text = GOOD[".claude/rules/devops.md"].replace("## Commit", "## Extra\n\n## Commit")
    assert rules_hit(tmp_path, base, {".claude/rules/devops.md": text}) == set()


def test_two_rules_files(tmp_path: Path, base: Path) -> None:
    files = dict(GOOD, **{".claude/rules/other.md": RULES_MD})
    assert {v[0] for v in violations(tmp_path, base, files)} == {"rules-file"}


@pytest.mark.parametrize("text", ["Apache License\n\nCopyright (c) 2025 X\n", "MIT License\n\nby X\n"])
def test_license(tmp_path: Path, base: Path, text: str) -> None:
    assert rules_hit(tmp_path, base, {"LICENSE": text}) == {"license"}


def test_editorconfig_differs(tmp_path: Path, base: Path) -> None:
    assert rules_hit(tmp_path, base, {".editorconfig": "root = false\n"}) == {"editorconfig"}


def test_gitattributes_and_gitignore(tmp_path: Path, base: Path) -> None:
    hit = rules_hit(tmp_path, base, {".gitattributes": "* text=auto\n", ".gitignore": ".DS_Store\n"})
    assert hit == {"gitattributes", "gitignore"}


def test_config_drift(tmp_path: Path, base: Path) -> None:
    assert rules_hit(tmp_path, base, {".config/.yamllint": "extends: relaxed\n"}) == {"config-drift"}


@pytest.mark.parametrize("text, hit", [
    ("# ignored\nCVE-2026-1 exp:2027-01-31\n", False),
    ("misconfigurations:\n  - id: AVD-KSV-0118\n", True),
])
def test_config_names_trivyignore(tmp_path: Path, base: Path, text: str, hit: bool) -> None:
    found = rules_hit(tmp_path, base, {".config/.trivyignore": text})
    assert found == ({"config-names"} if hit else set())


def test_ci_workflow_missing(tmp_path: Path, base: Path) -> None:
    ci = "stages: [scan]\nscan:x:\n  stage: scan\n  rules: [{when: always}]\n  script: [x]\n"
    found = [v for v in violations(tmp_path, base, dict(GOOD, **{".gitlab-ci.yml": ci}))]
    assert [v[1] for v in found] == ["workflow", "workflow", "default"]


MR = "- if: '$CI_PIPELINE_SOURCE == \"merge_request_event\"'"
MAIN = "- if: '$CI_COMMIT_BRANCH == \"main\" && $CI_PIPELINE_SOURCE == \"push\"'"


@pytest.mark.parametrize("rules, found", [
    ([MR, MAIN, "- when: never"], []),
    ([MR, MAIN + "\n  auto_cancel:\n    on_new_commit: none", "- when: never"], []),
    ([MR, "- if: '$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS'\n  when: never",
      "- if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'"],
     ["last rule is not 'when: never'",
      "non-standard rule {'if': '$CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS', 'when': 'never'}",
      "non-standard rule {'if': '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'}",
      "lacks rule '$CI_COMMIT_BRANCH == \"main\" && $CI_PIPELINE_SOURCE == \"push\"'"]),
    ([MAIN, MR, "- when: never"], ["rules out of order, expected schedule > MR > main push > tag"]),
])
def test_ci_workflow_rules(tmp_path: Path, base: Path, rules: list[str], found: list[str]) -> None:
    body = "\n".join("    " + r.replace("\n", "\n    ") for r in rules)
    ci = CI_OK.replace(CI_OK[CI_OK.index("    - if:"):CI_OK.index("stages:")], body + "\n")
    hits = [v[2] for v in violations(tmp_path, base, dict(GOOD, **{".gitlab-ci.yml": ci}))
            if v[1] == "workflow:rules"]
    assert hits == found


def test_ci_stage_order(tmp_path: Path, base: Path) -> None:
    ci = CI_OK.replace("[scan, lint, test, mirror]", "[lint, scan, test, mirror, extra]")
    found = [v[2] for v in violations(tmp_path, base, dict(GOOD, **{".gitlab-ci.yml": ci}))]
    assert len(found) == 2 and "non-standard" in found[0] and "order" in found[1]


def test_ci_jobs(tmp_path: Path, base: Path) -> None:
    ci = CI_OK + """
lint:extra:
  stage: test
  allow_failure: true
  script: [x]
scan:override:
  before_script: [x]
"""
    found = {(v[0], v[1]) for v in violations(tmp_path, base, dict(GOOD, **{".gitlab-ci.yml": ci}))}
    assert found == {("ci-job-stage", "lint:extra"), ("ci-job-rules", "lint:extra"),
                     ("ci-no-allow-failure", "lint:extra")}


def test_ci_reference_tag_loads(tmp_path: Path, base: Path) -> None:
    ci = CI_OK + "  before_script:\n    - !reference [.x, script]\n"
    assert rules_hit(tmp_path, base, {".gitlab-ci.yml": ci}) == set()


def test_ci_component_pins(tmp_path: Path, base: Path) -> None:
    ci = (CI_OK.replace("lint-yaml@4.2.1", "lint-yaml@4.1.0")
          .replace("include:\n", "include:\n  - component: gitlab.com/x/y@main\n"))
    found = {v[1] for v in violations(tmp_path, base, dict(GOOD, **{".gitlab-ci.yml": ci}))}
    assert found == {"gitlab.com/x/y@main", "example-org/ci-components"}


def test_makefile_help(tmp_path: Path, base: Path) -> None:
    found = [v for v in violations(tmp_path, base, dict(GOOD, Makefile="build:\n\tgo build\n"))]
    assert [v[0] for v in found] == ["makefile-help", "makefile-help"]


def test_names_and_docs(tmp_path: Path, base: Path) -> None:
    files = dict(GOOD)
    files.pop("docs/README.md")
    files.update({"scripts/km_run.sh": "", "tools/Bad-Name.py": "", "docs/how-to.md": "",
                  ".archive/old_name.sh": ""})
    found = {(v[0], v[1]) for v in violations(tmp_path, base, files)}
    assert found == {("script-names", "scripts/km_run.sh"), ("script-names", "tools/Bad-Name.py"),
                     ("doc-names", "docs/how-to.md"), ("docs-index", "docs/README.md")}


def test_generated_files(tmp_path: Path, base: Path) -> None:
    files = dict(GOOD, **{".ci/scripts/__pycache__/x.pyc": "", "htmlcov/index.html": ""})
    found = {v[1] for v in violations(tmp_path, base, files) if v[0] == "no-generated-files"}
    assert found == {".ci/scripts/__pycache__/x.pyc", "htmlcov/index.html"}


def test_readme_headings(tmp_path: Path, base: Path) -> None:
    text = ("# One\n\n## \U0001f680 Quick start\n\n# Two\n\n## Develop\n\n"
            "## Documentation\n\n## License\n")
    found = [v[2] for v in violations(tmp_path, base, dict(GOOD, **{"README.md": text}))]
    assert found == ["2 H1 headings, expected 1", "emoji in heading '\U0001f680 Quick start'"]


@pytest.mark.parametrize("sections, docs, detail", [
    (["\u26a1 Quick Start", "Usage", "Develop", "Documentation", "License"], True, None),
    (["Quick start", "Develop", "License"], False, None),
    (["Quick start", "Develop", "License"], True, "lacks section(s) Documentation"),
    (["Quick start", "Development", "License"], False, "lacks section(s) Develop"),
    (["Develop", "Quick start", "License"], False,
     "sections out of order, expected Quick start > Develop > License"),
])
def test_readme_sections(tmp_path: Path, base: Path, sections: list[str], docs: bool,
                         detail: str | None) -> None:
    files = dict(GOOD, **{"README.md": "# r\n\n" + "".join(f"## {s}\n\n" for s in sections)})
    if not docs:
        files.pop("docs/README.md")
        files.pop("docs/ARCHITECTURE.md")
    found = [v[2] for v in violations(tmp_path, base, files) if v[0] == "readme-sections"]
    assert found == ([detail] if detail else [])


@pytest.mark.parametrize("text, hit", [
    ("# C\n\n## Commands\n", []),
    ("# C\n\n## Skills (workflow detail lives there)\n\n## Hard rules\n",
     ["section 'Skills (workflow detail lives there)' belongs in the rules file",
      "section 'Hard rules' belongs in the rules file"]),
])
def test_claude_md(tmp_path: Path, base: Path, text: str, hit: list[str]) -> None:
    found = [v[2] for v in violations(tmp_path, base, dict(GOOD, **{".claude/CLAUDE.md": text}))
             if v[0] == "claude-md"]
    assert found == hit


@pytest.mark.parametrize("text, hit", [
    ("git checkout -b feature/x\n", True),
    ("git push origin feature/x\n", True),
    ("git checkout -b feat/x\n", False),
    ("Keep the README feature/derive tables in sync\n", False),
])
def test_contributing_branches(tmp_path: Path, base: Path, text: str, hit: bool) -> None:
    files = dict(GOOD, **{"CONTRIBUTING.md": text})
    found = {v[0] for v in violations(tmp_path, base, files)}
    assert found == ({"contributing-branches"} if hit else set())


def test_readme_feature_branch(tmp_path: Path, base: Path) -> None:
    files = dict(GOOD, **{"README.md": GOOD["README.md"] + "\ngit checkout -b feature/x\n"})
    found = {(v[0], v[1]) for v in violations(tmp_path, base, files)}
    assert found == {("contributing-branches", "README.md")}


VIOLATIONS = [("gitignore", ".gitignore", "lacks '.env'"),
              ("config-drift", ".config/.yamllint", "differs"),
              ("config-drift", ".config/.gitleaks.toml", "differs")]


def test_evaluate_rule_and_subject_exceptions() -> None:
    exceptions = {"gitignore": "accepted: reason",
                  "config-drift": {".config/.yamllint": "accepted: reason"}}
    assert crs.evaluate(VIOLATIONS, exceptions) == ["config-drift: .config/.gitleaks.toml: differs"]


def test_evaluate_stale_exceptions() -> None:
    exceptions = {"license": "fix: x", "config-drift": {
        ".config/.yamllint": "a", ".config/.gitleaks.toml": "a", ".config/.shellcheckrc": "a"}}
    problems = crs.evaluate(VIOLATIONS, exceptions)
    assert "config-drift: .config/.shellcheckrc: exception listed but the rule passes; remove it" in problems
    assert "license: exception listed but the rule passes; remove it" in problems


@pytest.mark.parametrize("text, message", [
    ("exceptions:\n  bogus: x\n", "unknown rule"),
    ("exceptions:\n  license: ''\n", "without a reason"),
    ("exceptions:\n  config-drift:\n    .config/.yamllint: ''\n", "without a reason"),
])
def test_load_exceptions_rejects(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "ex.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match=message):
        crs.load_exceptions(path)


def test_load_exceptions_missing_file(tmp_path: Path) -> None:
    assert crs.load_exceptions(tmp_path / "absent.yaml") == {}


def test_main_exit_codes(tmp_path: Path, base: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = make_repo(tmp_path, dict(GOOD, Makefile="build:\n"))
    args = ["--repo", str(repo.root), "--base-dir", str(base)]
    assert crs.main(args) == 1
    assert "FAIL makefile-help" in capsys.readouterr().out
    (repo.root / ".ci").mkdir(exist_ok=True)
    (repo.root / ".ci/repo-standard.yaml").write_text(
        "exceptions:\n  makefile-help: 'accepted: test'\n")
    assert crs.main(args) == 0
    assert "2 excused violation(s), 0 problem(s)" in capsys.readouterr().out


def test_precommit_core(tmp_path: Path, base: Path) -> None:
    missing = PRECOMMIT_OK.replace("      - id: gitleaks\n", "")
    found = [v for v in violations(tmp_path, base, dict(GOOD, **{".pre-commit-config.yaml": missing}))]
    assert [(v[0], v[2]) for v in found] == [("precommit-core", "lacks hook gitleaks")]


def test_precommit_commit_types(tmp_path: Path, base: Path) -> None:
    text = PRECOMMIT_OK.replace(", build]", "]")
    found = [v[2] for v in violations(tmp_path, base, dict(GOOD, **{".pre-commit-config.yaml": text}))]
    assert len(found) == 1 and "commit types" in found[0]


def test_precommit_invalid_yaml(tmp_path: Path, base: Path) -> None:
    found = [v[2] for v in violations(tmp_path, base, dict(GOOD, **{".pre-commit-config.yaml": "repos: [\n"}))]
    assert len(found) == 1 and "not valid YAML" in found[0]

#!/usr/bin/env python3
"""
Check a homelab repo against the repo standard (docs/REPO-STANDARD.md).

Every rule yields violations as (rule, subject, detail). A violation fails
unless the repo's .ci/repo-standard.yaml excuses it with a reason, either for
the whole rule or for one subject. An exception that excuses nothing also
fails, so the list never outlives the problem it excuses.

Usage:
    python3 check_repo_standard.py [--repo DIR] [--exceptions FILE]
                                   [--base-dir DIR] [--base-editorconfig FILE]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

RULES = {
    "required-files": "the shared hygiene and tooling files exist",
    "rules-file": "one .claude/rules/*.md with the standard sections in order",
    "claude-md": ".claude/CLAUDE.md leaves skills and hard rules to the rules file",
    "license": "LICENSE is MIT with a copyright line",
    "editorconfig": ".editorconfig is identical to the base",
    "gitattributes": ".gitattributes contains the base lines",
    "gitignore": ".gitignore contains the base entries",
    "config-drift": "every .config/ lint file that has a base is identical to it",
    "config-names": "a YAML trivy ignorefile is named .trivyignore.yaml",
    "ci-workflow": "standard workflow:rules, auto_cancel on interruptible, default interruptible",
    "ci-stage-order": "stages follow the standard order",
    "ci-job-stage": "a job named <stage>:<x> runs in <stage>",
    "ci-job-rules": "every inline job with a script has rules",
    "ci-no-allow-failure": "no inline job sets allow_failure",
    "ci-component-pins": "components are pinned to X.Y.Z, one version per hub",
    "makefile-help": "the Makefile defaults to a help target",
    "script-names": "shell scripts are kebab-case, Python files snake_case",
    "doc-names": "docs/*.md are UPPER-KEBAB",
    "docs-index": "a docs/ with two or more pages has docs/README.md",
    "no-generated-files": "no caches, coverage output or OS files are tracked",
    "readme-headings": "README.md has one H1 and no emoji headings",
    "readme-sections": "README.md has Quick start, Develop, Documentation and License in order",
    "precommit-core": "pre-commit runs the core hooks and the shared commit-type list",
    "contributing-branches": "CONTRIBUTING.md and README.md name <type>/<slug> branches, not feature/",
}

REQUIRED_FILES = (
    "README.md", "LICENSE", ".editorconfig", ".gitattributes", ".gitignore",
    ".pre-commit-config.yaml", "renovate.json", "Makefile", ".gitlab-ci.yml",
    ".claude/CLAUDE.md",
)
# The hooks every repo's .pre-commit-config.yaml runs, mirroring the CI jobs
# every repo has (scan:secrets, lint:yaml/shell/markdown, lint:commits). Repos
# add their own hooks and their own excludes; revisions are Renovate's job.
PRECOMMIT_CORE = (
    "trailing-whitespace", "end-of-file-fixer", "check-yaml", "check-added-large-files",
    "check-merge-conflict", "detect-private-key", "check-case-conflict", "mixed-line-ending",
    "check-executables-have-shebangs", "check-shebang-scripts-are-executable", "check-json",
    "yamllint", "markdownlint-cli2", "conventional-pre-commit", "gitleaks", "shellcheck",
)
# The lint-commits component's default type list.
COMMIT_TYPES = ("feat", "fix", "docs", "refactor", "chore", "test", "ci", "build")
RULES_SECTIONS = ("Hard rules", "Skill routing", "Commit conventions",
                  "Docs contract", "Operating principle")
# Sections the rules file owns; CLAUDE.md is loaded alongside it, so a copy
# there is loaded twice and drifts.
CLAUDE_MD_FORBIDDEN = ("Skills", "Hard rules")
# README skeleton; other sections may sit anywhere between them.
# Documentation is required only where docs-index applies.
README_SECTIONS = ("Quick start", "Develop", "Documentation", "License")
GITATTRIBUTES_BASE = (
    "* text=auto eol=lf", "*.md text eol=lf diff=markdown", "*.yaml text eol=lf",
    "*.yml text eol=lf", "*.json text eol=lf", "*.png binary", "*.jpg binary",
    "*.ico binary",
)
GITIGNORE_BASE = (".DS_Store", ".env", ".idea/", "*.swp")
# Lint files the components fall back to. .gitleaksignore holds per-repo
# finding fingerprints, so it has no base.
CONFIG_BASE_FILES = (".yamllint", ".markdownlint-cli2.jsonc", ".shellcheckrc", ".gitleaks.toml")
TRIVY_YAML_KEYS = re.compile(r"^(vulnerabilities|misconfigurations|secrets|licenses):", re.M)
# The workflow:rules every repo uses, in this order: MR and main-push
# pipelines always, schedules where a repo has one, a tag pattern where tags
# release, then nothing else. A branch push with no MR gets no pipeline. A
# rule may override auto_cancel (helm-charts keeps main pipelines running so
# a publish is never canceled).
WORKFLOW_SCHEDULE = '$CI_PIPELINE_SOURCE == "schedule"'
WORKFLOW_MR = '$CI_PIPELINE_SOURCE == "merge_request_event"'
WORKFLOW_MAIN = '$CI_COMMIT_BRANCH == "main" && $CI_PIPELINE_SOURCE == "push"'
WORKFLOW_TAG = re.compile(r"^\$CI_COMMIT_TAG =~ /.+/$")
STAGE_ORDER = ("scan", "lint", "validate", "test", "build", "publish", "image",
               "release", "deploy", "mirror")
CI_RESERVED = {"default", "workflow", "variables", "include", "stages", "image",
               "services", "cache", "before_script", "after_script", "spec"}
HUB = "example-org/ci-components/"
GENERATED = re.compile(r"(^|/)(htmlcov|__pycache__|\.pytest_cache|\.venv|\.coverage|coverage\.xml|\.DS_Store)(/|$)")
KEBAB_SH = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*\.sh$")
SNAKE_PY = re.compile(r"^[a-z0-9_]+\.py$")
UPPER_KEBAB_MD = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*\.md$")
EMOJI = re.compile("[\u2600-\u27bf\u2b00-\u2bff\ufe0f\U0001f000-\U0001faff]")
FEATURE_BRANCH = re.compile(r"(checkout -b|switch -c|branch|push \S+)\s+feature/")
LICENSE_COPYRIGHT = re.compile(r"^Copyright \(c\) \d{4}(-\d{4})? \S", re.M)

Violation = tuple[str, str, str]  # (rule, subject, detail)


class Repo:
    """A checkout: its root and its tracked files outside .archive/."""

    def __init__(self, root: Path, run: Callable[..., Any] = subprocess.run):
        self.root = root
        out = run(["git", "-C", str(root), "ls-files", "-z"],
                  capture_output=True, text=True, check=True).stdout
        self.files = sorted(f for f in out.split("\0") if f and not f.startswith(".archive/"))

    def exists(self, rel: str) -> bool:
        return (self.root / rel).is_file()

    def read(self, rel: str) -> str:
        return (self.root / rel).read_text()


def check_required_files(repo: Repo) -> list[Violation]:
    return [("required-files", f, "missing") for f in REQUIRED_FILES if not repo.exists(f)]


def check_rules_file(repo: Repo) -> list[Violation]:
    found = sorted(f for f in repo.files if re.fullmatch(r"\.claude/rules/[^/]+\.md", f))
    if len(found) != 1:
        return [("rules-file", ".claude/rules", f"{len(found)} rules files, expected 1")]
    headings = re.findall(r"^## (.+?)\s*$", repo.read(found[0]), re.M)
    missing = [s for s in RULES_SECTIONS if s not in headings]
    if missing:
        return [("rules-file", found[0], f"lacks section(s) {', '.join(missing)}")]
    order = [headings.index(s) for s in RULES_SECTIONS]
    if order != sorted(order):
        return [("rules-file", found[0], f"sections out of order, expected {' > '.join(RULES_SECTIONS)}")]
    return []


def check_claude_md(repo: Repo) -> list[Violation]:
    if not repo.exists(".claude/CLAUDE.md"):
        return []
    headings = re.findall(r"^## (.+?)\s*$", repo.read(".claude/CLAUDE.md"), re.M)
    return [("claude-md", ".claude/CLAUDE.md", f"section {h!r} belongs in the rules file")
            for h in headings if h.split(" (")[0] in CLAUDE_MD_FORBIDDEN]


def check_license(repo: Repo) -> list[Violation]:
    if not repo.exists("LICENSE"):
        return []
    text = repo.read("LICENSE")
    out = []
    if not text.startswith("MIT License"):
        out.append(("license", "LICENSE", "not the MIT license"))
    if not LICENSE_COPYRIGHT.search(text):
        out.append(("license", "LICENSE", "no 'Copyright (c) YYYY <holder>' line"))
    return out


def check_editorconfig(repo: Repo, base: Path) -> list[Violation]:
    if not repo.exists(".editorconfig"):
        return []
    if repo.read(".editorconfig") != base.read_text():
        return [("editorconfig", ".editorconfig", f"differs from {base}")]
    return []


def _lines(text: str) -> set[str]:
    return {line.strip() for line in text.splitlines()}


def check_gitattributes(repo: Repo) -> list[Violation]:
    if not repo.exists(".gitattributes"):
        return []
    missing = [line for line in GITATTRIBUTES_BASE if line not in _lines(repo.read(".gitattributes"))]
    return [("gitattributes", ".gitattributes", f"lacks {line!r}") for line in missing]


def check_gitignore(repo: Repo) -> list[Violation]:
    if not repo.exists(".gitignore"):
        return []
    missing = [line for line in GITIGNORE_BASE if line not in _lines(repo.read(".gitignore"))]
    return [("gitignore", ".gitignore", f"lacks {line!r}") for line in missing]


def check_config(repo: Repo, base_dir: Path) -> list[Violation]:
    out = []
    for name in CONFIG_BASE_FILES:
        rel = f".config/{name}"
        if repo.exists(rel) and repo.read(rel) != (base_dir / name).read_text():
            out.append(("config-drift", rel, f"differs from {base_dir / name}"))
    # trivy reads YAML ignore rules only from a *.yaml name; under any other
    # name the rules are read as an ID list and match nothing.
    if repo.exists(".config/.trivyignore") and TRIVY_YAML_KEYS.search(repo.read(".config/.trivyignore")):
        out.append(("config-names", ".config/.trivyignore", "YAML rules; rename to .config/.trivyignore.yaml"))
    return out


class _CILoader(yaml.SafeLoader):
    """Loads .gitlab-ci.yml, ignoring GitLab tags such as !reference."""


_CILoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _ci(repo: Repo) -> dict[str, Any] | None:
    if not repo.exists(".gitlab-ci.yml"):
        return None
    return yaml.load(repo.read(".gitlab-ci.yml"), Loader=_CILoader) or {}


def _jobs(ci: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in ci.items()
            if isinstance(v, dict) and k not in CI_RESERVED and not k.startswith(".")}


def check_ci(repo: Repo) -> list[Violation]:
    ci = _ci(repo)
    if ci is None:
        return []
    out: list[Violation] = []
    workflow = ci.get("workflow") or {}
    if not workflow.get("rules"):
        out.append(("ci-workflow", "workflow", "no workflow:rules"))
    else:
        out += [("ci-workflow", "workflow:rules", d) for d in _workflow_rules(workflow["rules"])]
    if (workflow.get("auto_cancel") or {}).get("on_new_commit") != "interruptible":
        out.append(("ci-workflow", "workflow", "auto_cancel:on_new_commit is not interruptible"))
    if (ci.get("default") or {}).get("interruptible") is not True:
        out.append(("ci-workflow", "default", "default:interruptible is not true"))

    stages = list(ci.get("stages") or [])
    unknown = [s for s in stages if s not in STAGE_ORDER]
    if unknown:
        out.append(("ci-stage-order", "stages", f"non-standard stage(s) {', '.join(unknown)}"))
    known = [STAGE_ORDER.index(s) for s in stages if s in STAGE_ORDER]
    if known != sorted(known):
        out.append(("ci-stage-order", "stages", f"order {stages}, expected {' > '.join(STAGE_ORDER)}"))

    for name, job in _jobs(ci).items():
        prefix = name.split(":", 1)[0]
        if ":" in name and prefix in stages and job.get("stage") not in (None, prefix):
            out.append(("ci-job-stage", name, f"runs in stage {job.get('stage')}"))
        # A job without a script is a local override merged into a component job.
        if "script" in job and "rules" not in job:
            out.append(("ci-job-rules", name, "has a script but no rules"))
        if job.get("allow_failure"):
            out.append(("ci-no-allow-failure", name, "sets allow_failure"))

    includes = ci.get("include") or []
    hub_versions = set()
    for inc in includes if isinstance(includes, list) else [includes]:
        ref = inc.get("component") if isinstance(inc, dict) else None
        if not ref:
            continue
        path, _, version = ref.rpartition("@")
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            out.append(("ci-component-pins", ref, "not pinned to X.Y.Z"))
        if HUB in path:
            hub_versions.add(version)
    if len(hub_versions) > 1:
        out.append(("ci-component-pins", HUB.rstrip("/"),
                    f"mixed versions {', '.join(sorted(hub_versions))}"))
    return out


def _workflow_rules(rules: list[Any]) -> list[str]:
    *body, last = rules
    out = []
    if last != {"when": "never"}:
        out.append("last rule is not 'when: never'")
        body = rules
    order = [WORKFLOW_SCHEDULE, WORKFLOW_MR, WORKFLOW_MAIN]
    seen = []
    for rule in body:
        plain = isinstance(rule, dict) and "if" in rule and set(rule) <= {"if", "auto_cancel"}
        cond = rule["if"] if plain else None
        if cond in order:
            seen.append(order.index(cond))
        elif cond is not None and WORKFLOW_TAG.match(cond):
            seen.append(len(order))
        else:
            out.append(f"non-standard rule {rule!r}")
    for cond in (WORKFLOW_MR, WORKFLOW_MAIN):
        if order.index(cond) not in seen:
            out.append(f"lacks rule {cond!r}")
    if seen != sorted(seen):
        out.append("rules out of order, expected schedule > MR > main push > tag")
    return out


def check_makefile(repo: Repo) -> list[Violation]:
    if not repo.exists("Makefile"):
        return []
    text = repo.read("Makefile")
    out = []
    if not re.search(r"^\.DEFAULT_GOAL\s*:=\s*help\s*$", text, re.M):
        out.append(("makefile-help", "Makefile", "no '.DEFAULT_GOAL := help'"))
    if not re.search(r"^help:", text, re.M):
        out.append(("makefile-help", "Makefile", "no help target"))
    return out


def check_names(repo: Repo) -> list[Violation]:
    out = []
    for f in repo.files:
        base = f.rsplit("/", 1)[-1]
        if base.endswith(".sh") and not KEBAB_SH.match(base):
            out.append(("script-names", f, "shell scripts are kebab-case"))
        if base.endswith(".py") and not SNAKE_PY.match(base):
            out.append(("script-names", f, "Python files are snake_case"))
    docs = [f for f in repo.files if re.fullmatch(r"docs/[^/]+\.md", f)]
    for f in docs:
        name = f.split("/", 1)[1]
        if name != "README.md" and not UPPER_KEBAB_MD.match(name):
            out.append(("doc-names", f, "docs pages are UPPER-KEBAB.md"))
    if len(docs) >= 2 and "docs/README.md" not in docs:
        out.append(("docs-index", "docs/README.md", f"missing for {len(docs)} pages"))
    return out


def check_generated(repo: Repo) -> list[Violation]:
    return [("no-generated-files", f, "tracked") for f in repo.files if GENERATED.search(f)]


def _headings(text: str) -> list[tuple[int, str]]:
    """Markdown ATX headings outside fenced code blocks, as (level, text)."""
    out, fence = [], None
    for line in text.splitlines():
        marker = re.match(r"^\s*(```|~~~)", line)
        if marker:
            fence = None if fence == marker.group(1) else (fence or marker.group(1))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading and fence is None:
            out.append((len(heading.group(1)), heading.group(2)))
    return out


def check_readme(repo: Repo) -> list[Violation]:
    if not repo.exists("README.md"):
        return []
    headings = _headings(repo.read("README.md"))
    out = []
    h1 = [text for level, text in headings if level == 1]
    if len(h1) != 1:
        out.append(("readme-headings", "README.md", f"{len(h1)} H1 headings, expected 1"))
    for _, text in headings:
        if EMOJI.search(text):
            out.append(("readme-headings", "README.md", f"emoji in heading {text!r}"))
    h2 = [EMOJI.sub("", text).strip().casefold() for level, text in headings if level == 2]
    docs = [f for f in repo.files if re.fullmatch(r"docs/[^/]+\.md", f)]
    wanted = [s for s in README_SECTIONS if s != "Documentation" or len(docs) >= 2]
    missing = [s for s in wanted if s.casefold() not in h2]
    if missing:
        out.append(("readme-sections", "README.md", f"lacks section(s) {', '.join(missing)}"))
    else:
        order = [h2.index(s.casefold()) for s in wanted]
        if order != sorted(order):
            out.append(("readme-sections", "README.md",
                        f"sections out of order, expected {' > '.join(wanted)}"))
    return out


def check_contributing(repo: Repo) -> list[Violation]:
    return [("contributing-branches", f, "names feature/ branches")
            for f in ("CONTRIBUTING.md", "README.md")
            if repo.exists(f) and FEATURE_BRANCH.search(repo.read(f))]


def check_precommit(repo: Repo) -> list[Violation]:
    if not repo.exists(".pre-commit-config.yaml"):
        return []
    try:
        config = yaml.safe_load(repo.read(".pre-commit-config.yaml")) or {}
    except yaml.YAMLError as err:
        return [("precommit-core", ".pre-commit-config.yaml", f"not valid YAML: {err}")]
    hooks = {h.get("id"): h for r in config.get("repos") or [] for h in r.get("hooks") or []}
    out = [("precommit-core", ".pre-commit-config.yaml", f"lacks hook {hid}")
           for hid in PRECOMMIT_CORE if hid not in hooks]
    conventional = hooks.get("conventional-pre-commit")
    if conventional is not None:
        types = [a for a in conventional.get("args") or [] if not a.startswith("-")]
        if sorted(types) != sorted(COMMIT_TYPES):
            out.append(("precommit-core", ".pre-commit-config.yaml",
                        f"commit types {types}, expected {list(COMMIT_TYPES)}"))
    return out


def check_repo(repo: Repo, base_dir: Path, base_editorconfig: Path) -> list[Violation]:
    return (check_required_files(repo) + check_rules_file(repo) + check_claude_md(repo)
            + check_license(repo)
            + check_editorconfig(repo, base_editorconfig) + check_gitattributes(repo)
            + check_gitignore(repo) + check_config(repo, base_dir) + check_ci(repo)
            + check_makefile(repo) + check_names(repo) + check_generated(repo)
            + check_readme(repo) + check_contributing(repo) + check_precommit(repo))


Exceptions = dict[str, "str | dict[str, str]"]


def load_exceptions(path: Path) -> Exceptions:
    data = yaml.safe_load(path.read_text()) if path.exists() else None
    exceptions = (data or {}).get("exceptions") or {}
    for rule, entry in exceptions.items():
        if rule not in RULES:
            raise ValueError(f"{path}: unknown rule {rule!r}")
        reasons = entry.values() if isinstance(entry, dict) else [entry]
        if not entry or any(not str(r or "").strip() for r in reasons):
            raise ValueError(f"{path}: {rule} has an exception without a reason")
    return exceptions


def evaluate(violations: list[Violation], exceptions: Exceptions) -> list[str]:
    """Problems: violations without an exception, and exceptions that excuse nothing."""
    problems = []
    for rule, subject, detail in violations:
        entry = exceptions.get(rule)
        if entry is None or (isinstance(entry, dict) and subject not in entry):
            problems.append(f"{rule}: {subject}: {detail}")
    for rule, entry in sorted(exceptions.items()):
        subjects = {s for r, s, _ in violations if r == rule}
        if isinstance(entry, dict):
            for subject in sorted(set(entry) - subjects):
                problems.append(f"{rule}: {subject}: exception listed but the rule passes; remove it")
        elif not subjects:
            problems.append(f"{rule}: exception listed but the rule passes; remove it")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--repo", default=".", type=Path)
    parser.add_argument("--exceptions", default=None, type=Path,
                        help="default: <repo>/.ci/repo-standard.yaml")
    parser.add_argument("--base-dir", default="/opt/ci/config", type=Path,
                        help="the shared lint configs (ci-base bakes them here)")
    parser.add_argument("--base-editorconfig", default=None, type=Path,
                        help="default: <base-dir>/.editorconfig")
    args = parser.parse_args(argv)

    exceptions_path = args.exceptions or args.repo / ".ci/repo-standard.yaml"
    exceptions = load_exceptions(exceptions_path)
    repo = Repo(args.repo)
    violations = check_repo(repo, args.base_dir, args.base_editorconfig or args.base_dir / ".editorconfig")
    problems = evaluate(violations, exceptions)
    for problem in problems:
        print(f"FAIL {problem}")
    excused = len(violations) - (len(problems) - sum(p.endswith("remove it") for p in problems))
    print(f"repo standard: {len(RULES)} rules, {len(repo.files)} files, "
          f"{excused} excused violation(s), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

# Repo standard

Every homelab repo follows the same layout, hygiene files and CI shape.
[`check_repo_standard.py`](../.ci/scripts/check_repo_standard.py) checks
each rule below; the
[`lint-repo-standard`](../templates/lint-repo-standard/template.yml)
component runs it on every MR and `main` push, and `make standard` runs it
locally.

## Exceptions

A repo declares a deviation in `.ci/repo-standard.yaml`, for a whole rule or
for one subject (the file or job the violation names):

```yaml
exceptions:
  readme-headings: "accepted: the README is the GitHub portfolio page"
  config-drift:
    .config/.yamllint: "accepted: Helm templates need the relaxed indent rule"
```

Each reason starts with one of:

- `accepted:` a deliberate deviation; the reason says why the rule cannot
  hold.
- `fix:` a defect; the MR that fixes it removes the entry.
- `investigate:` needs a check before it is fixed or accepted.

An unknown rule, an empty reason, or an exception whose rule passes fails
the check, so the file never outlives the problem it excuses.

## The base

The shared defaults are this repo's own files, baked into `ci-base`:

- `.config/.yamllint`, `.config/.markdownlint-cli2.jsonc`,
  `.config/.shellcheckrc`, `.config/.gitleaks.toml` and `.editorconfig`,
  at `/opt/ci/config/`.
- The checker itself, at `/opt/ci/check_repo_standard.py`.

A repo may carry a `.config/` copy so that its Makefile and pre-commit hooks
read the same file locally. A copy that differs from the base is drift and
needs an exception. `.gitleaksignore` holds per-repo fingerprints and has no
base.

## Files

- `required-files`: `README.md`, `LICENSE`, `.editorconfig`,
  `.gitattributes`, `.gitignore`, `.pre-commit-config.yaml`,
  `renovate.json`, `Makefile`, `.gitlab-ci.yml` and `.claude/CLAUDE.md`
  exist.
- `rules-file`: exactly one `.claude/rules/*.md`, with the sections Hard
  rules, Skill routing, Commit conventions, Docs contract and Operating
  principle in that order. Extra sections may sit between them.
- `claude-md`: `.claude/CLAUDE.md` has no `## Skills` or `## Hard rules`
  section. Both load alongside the rules file, which owns skill routing and
  hard rules; a copy in CLAUDE.md is loaded twice and drifts.
- `license`: MIT, with a `Copyright (c) YYYY <holder>` line. The year is
  the repo's first year, so it differs between repos.
- `editorconfig`: identical to the base.
- `gitattributes`: contains the base lines (`* text=auto eol=lf`, LF for
  `*.md`, `*.yaml`, `*.yml`, `*.json`, binary for `*.png`, `*.jpg`,
  `*.ico`). A repo adds its own file types below them.
- `gitignore`: contains `.DS_Store`, `.env`, `.idea/` and `*.swp`.
- `config-drift`: every `.config/` file that has a base is identical to it.
- `config-names`: a trivy ignorefile in the YAML format is named
  `.config/.trivyignore.yaml`. trivy parses YAML rules only from a `.yaml`
  name and reads any other name as a plain ID list, so YAML rules there
  match nothing. A plain ID list stays `.config/.trivyignore`.

## CI

- `ci-workflow`: `workflow:rules` is the standard set, in this order: an
  optional `$CI_PIPELINE_SOURCE == "schedule"`, then
  `$CI_PIPELINE_SOURCE == "merge_request_event"`, then
  `$CI_COMMIT_BRANCH == "main" && $CI_PIPELINE_SOURCE == "push"`, an
  optional `$CI_COMMIT_TAG =~ /.../` where tags release, and last
  `when: never`. A branch push without an MR gets no pipeline. A rule may
  add `auto_cancel` (helm-charts: a `main` pipeline is never canceled, so a
  chart publish is never lost).
  `workflow:auto_cancel:on_new_commit` is `interruptible`, and
  `default:interruptible` is `true`. Jobs with side effects opt out per job.
- `ci-stage-order`: stages are a subset of `scan lint validate test build
  publish image release deploy mirror`, in that order. `image` comes after
  `publish` and before `release` because a release tag is immutable, so
  the image it points at must exist first.
- `ci-job-stage`: an inline job named `<stage>:<name>` runs in `<stage>`.
- `ci-job-rules`: every inline job with a `script` has `rules`. A job with
  no `script` is a local override merged into a component job.
- `ci-no-allow-failure`: no inline job sets `allow_failure`. A check that
  may fail is not a gate.
- `ci-component-pins`: every `component:` include is pinned to `X.Y.Z`,
  and all ci-components includes in a repo use one version.

Component jobs are checked where they are defined, in this repo's
`templates/`.

- `precommit-core`: `.pre-commit-config.yaml` runs the core hooks:
  the pre-commit-hooks file checks (`trailing-whitespace`,
  `end-of-file-fixer`, `check-yaml`, `check-added-large-files`,
  `check-merge-conflict`, `detect-private-key`, `check-case-conflict`,
  `mixed-line-ending`, `check-executables-have-shebangs`,
  `check-shebang-scripts-are-executable`, `check-json`), `yamllint`,
  `markdownlint-cli2`, `conventional-pre-commit` with the `lint-commits`
  type list, `gitleaks` and `shellcheck`. They mirror the CI jobs every repo
  runs. A repo adds its own hooks and excludes; Renovate keeps the revisions.

## Naming and layout

- `script-names`: `*.sh` files are kebab-case, `*.py` files snake_case,
  because Python imports them as modules.
- `doc-names`: `docs/*.md` are `UPPER-KEBAB.md`, apart from
  `docs/README.md`.
- `docs-index`: a `docs/` with two or more pages has a `docs/README.md`.
- `no-generated-files`: no tracked `htmlcov/`, `__pycache__/`,
  `.pytest_cache/`, `.venv/`, `.coverage`, `coverage.xml` or `.DS_Store`.
- `makefile-help`: `.DEFAULT_GOAL := help` and a `help` target, so a bare
  `make` lists the targets.

Files under `.archive/` are exempt from every rule.

## Docs

- `readme-headings`: `README.md` has exactly one H1, and no heading
  carries an emoji. Lines inside fenced code blocks are not headings.
- `readme-sections`: `README.md` has the H2 sections Quick start, Develop,
  Documentation and License, in that order. Matching ignores case and emoji;
  other sections may sit anywhere. Documentation is required only when
  `docs/` has two or more pages.
- `contributing-branches`: `CONTRIBUTING.md` and `README.md` do not
  create or push `feature/` branches. Branches are `<type>/<slug>`, with
  the type from the Conventional Commit list that `lint-commits` enforces.

## Run it

```bash
make standard                    # this repo
make standard REPO=../argo-apps  # a sibling checkout
```

In a consumer, include the component:

```yaml
include:
  - component: $CI_SERVER_FQDN/example-org/ci-components/lint-repo-standard@<version>
```

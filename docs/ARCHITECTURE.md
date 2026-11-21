# Architecture

`ci-components` is the shared CI hub for the homelab GitLab group. It exists so
that one repo, not each of the six consumers, owns the CI job definitions,
the CI toolchain image, and the publish/sanitize tooling that every repo needs.

It is the CI-side twin of the `renovate` repo, which already centralizes
dependency config as one shared preset (`default.json`) that every repo
extends. `ci-components` does the same for CI.

## What lives here

| Path | Role |
| --- | --- |
| `templates/` | Versioned, parameterized CI jobs consumers `include:` |
| `.ci/docker/Dockerfile` | `ci-base` — the common toolchain, built here |
| `.ci/scripts/*.py` | Tooling; publish, sanitize, standard baked in `ci-base` |
| `.config/` | This repo's own yamllint/markdownlint/shellcheck rules |
| `.ci/schedules.yaml` | Pipeline schedules of every homelab repo |
| `.gitlab-ci.yml` | Dogfoods components, runs `auto-tag`, builds + mirrors |

## Consumer contract

A consumer repo pulls a component and parameterizes it with typed inputs:

```yaml
include:
  - component: $CI_SERVER_FQDN/example-org/ci-components/lint-yaml@<version>
  - component: $CI_SERVER_FQDN/example-org/ci-components/scan-secrets@<version>
  - component: $CI_SERVER_FQDN/example-org/ci-components/mirror-github@<version>
    inputs:
      repo_name: argo-apps
  - component: $CI_SERVER_FQDN/example-org/ci-components/ci-image@<version>
    inputs:
      image_name: homelab/argo-apps/ci
```

(Lint is split into per-tool components: `lint-yaml`, `lint-shell`,
`lint-markdown`.)

Each component reads the **consumer's own** `.config/` rule files and
`.ci/sanitize/sanitize-config.yaml`. Those stay per-repo because they are
genuinely divergent (an app repo's yamllint ignore list is not a chart repo's).
The shared part is the *job logic*; the variable part is *config*, and config
stays home. The sanitize config is layered: every repo's file `extends:` the
shared `/opt/ci/config/sanitize-base.yaml` (this repo's
`.ci/config/sanitize-base.yaml`), which carries the identifiers common to all
mirrors (domains, names, the internal VLAN prefixes, token prefixes, the
standard excludes). Lists only grow through layering, so a child can add
protections but never remove one.

### The mirror gate

`publish_github.py` runs four steps and pushes only when all pass:
`sanitize_repo.py` copies the files git tracks (nothing untracked or ignored
in the workspace can be published) and rewrites every text file (anything
that is not a known binary extension and carries no NUL byte, so `.drawio`,
`.svg`, `.j2` or `known_hosts` are rewritten like `.md`);
`verify_sanitization.py` scans every file *and path* in the output for every
replacement key and verification term; `gitleaks dir` scans the output with
the consumer's own `.config/.gitleaks.toml` (the rules its `scan:secrets`
passes with), falling back to the shared rules, as an independent credential
check; then one fresh commit is force-pushed. `--dry-run` runs the three
gates locally without a token.

## The shared image

`ci-base` (`registry.example.com/example-org/ci-components/ci`) bakes the tools
every repo's CI needs — git, gitleaks, cosign, syft, trivy, yamllint,
markdownlint-cli2, shellcheck, the Python test stack — plus the three publish
`.py` tools and `check_repo_standard.py` at `/opt/ci/`, and the shared config
defaults (sanitize base, lint and gitleaks rules, `.editorconfig`) at
`/opt/ci/config/`. [REPO-STANDARD.md](REPO-STANDARD.md) describes the rules
the checker enforces. Consumer images layer on top:

```text
FROM registry.example.com/example-org/ci-components/ci:latest@sha256:...
# only the repo-specific tools, e.g. for argo-apps:
#   helm, kustomize, kubeconform, the CRDs-catalog
```

Consumers pin the base by **digest** and adopt a new base only via a Renovate
bump PR, so a base rebuild can never silently change a downstream build.

## Why the Python tooling is baked, not copied

`sanitize_repo.py` / `publish_github.py` / `verify_sanitization.py` are
universal — the per-repo variation lives entirely in each repo's
`sanitize-config.yaml`, which the tools read at runtime via `SOURCE_REPO`. So
the **code** is baked once into `ci-base`; the **config** stays per-repo. One
source of truth, no per-repo copies to keep in sync.

## Pipeline schedules

[`.ci/schedules.yaml`](../.ci/schedules.yaml) lists every repo's pipeline
schedules: the daily Renovate run, the weekly `ci-base` rebuild and the six
GitHub mirror runs. `make schedules` shows how GitLab differs from the file
and exits 2 on a difference; `make schedules-apply` creates and updates
schedules, and `PRUNE=1` also deletes the ones the file does not list. The
script calls `glab api`, so it runs from a laptop with a glab login and no
token lives in CI.

## Releases

A git tag is the release. `auto-tag` (on `main` push) computes the next semver
from Conventional Commits and pushes it; the tag pipeline then creates the
GitLab release object that publishes the version to the CI/CD Catalog. Consumers
pin `@<version>` and bump via Renovate.

A MAJOR bump means a breaking change to a component's contract (a renamed or
removed input, a changed default, a removed component).

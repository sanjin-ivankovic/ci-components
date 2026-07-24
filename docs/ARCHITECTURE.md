# Architecture

`ci-components` is the shared CI hub for the homelab GitLab group. It exists so
that one repo — not four — owns the CI job definitions, the CI toolchain image,
and the publish/sanitize tooling that every repo needs.

It is the CI-side twin of the `renovate` repo, which already centralizes
dependency config as one shared preset (`default.json`) that every repo
extends. `ci-components` does the same for CI.

## What lives here

| Path | Role |
| --- | --- |
| `templates/` | Versioned, parameterized CI jobs consumers `include:` |
| `.ci/docker/Dockerfile` | `ci-base` — the common toolchain, built here |
| `.ci/scripts/*.py` | Publish/sanitize tooling, baked into `ci-base` |
| `.config/` | This repo's own yamllint/markdownlint/shellcheck rules |
| `.gitlab-ci.yml` | Dogfoods components, runs `auto-tag`, builds + mirrors |

## Consumer contract

A consumer repo pulls a component and parameterizes it with typed inputs:

```yaml
include:
  - component: source.example.com/example-org/ci-components/lint-yaml@<version>
  - component: source.example.com/example-org/ci-components/scan-secrets@<version>
  - component: source.example.com/example-org/ci-components/mirror-github@<version>
    inputs:
      repo_name: argo-apps
  - component: source.example.com/example-org/ci-components/ci-image@<version>
    inputs:
      image_name: homelab/argo-apps/ci
```

(Lint is split into per-tool components: `lint-yaml`, `lint-shell`,
`lint-markdown`.)

Each component reads the **consumer's own** `.config/` rule files and
`.ci/sanitize/sanitize-config.yaml`. Those stay per-repo because they are
genuinely divergent (an app repo's yamllint ignore list is not a chart repo's).
The shared part is the *job logic*; the variable part is *config*, and config
stays home.

## The shared image

`ci-base` (`registry.example.com/example-org/ci-components/ci`) bakes the tools
every repo's CI needs — git, gitleaks, cosign, yamllint, markdownlint-cli2,
shellcheck, the Python test stack — plus the three publish `.py` tools at
`/opt/ci/`. Consumer images layer on top:

```text
FROM registry.example.com/example-org/ci-components/ci:latest@sha256:...
# only the repo-specific tools, e.g. for argo-apps:
#   helm, kustomize, kubeconform, the CRDs-catalog, the kryptos binary
```

Consumers pin the base by **digest** and adopt a new base only via a Renovate
bump PR, so a base rebuild can never silently change a downstream build.
`kryptos` is the deliberate exception — it keeps a standalone Go-toolchain
image and consumes only the `scan-secrets` component.

## Why the Python tooling is baked, not copied

`sanitize_repo.py` / `publish_github.py` / `verify_sanitization.py` are
universal — the per-repo variation lives entirely in each repo's
`sanitize-config.yaml`, which the tools read at runtime via `SOURCE_REPO`. So
the **code** is baked once into `ci-base`; the **config** stays per-repo. One
source of truth, no per-repo copies to keep in sync.

## Releases

A git tag is the release. `auto-tag` (on `main` push) computes the next semver
from Conventional Commits and pushes it; the tag pipeline then creates the
GitLab release object that publishes the version to the CI/CD Catalog. Consumers
pin `@<version>` and bump via Renovate.

A MAJOR bump means a breaking change to a component's contract (a renamed or
removed input, a changed default, a removed component).

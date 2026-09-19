# ci-components

The shared GitLab **CI/CD components** hub for the homelab repos (`argo-apps`,
`helm-charts`, `proxmox-infra`, `kryptos`). One source of truth for the CI jobs,
the `ci-base` image, and the publish/sanitize tooling every repo needs — the
CI-side twin of the [`renovate`](https://source.example.com/homelab/renovate) preset
hub.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design.

## Components

Each component is a `templates/<name>/template.yml` with typed `spec:inputs`.
A consumer pulls it with `include: component:` and sets only what it overrides.

<!-- markdownlint-disable MD013 -->
| Component | Generates | Use |
| --- | --- | --- |
| [`scan-secrets`](templates/scan-secrets/template.yml) | `scan:secrets` | Bypass-proof gitleaks scan over full history, reading the consumer's `.config/.gitleaks.toml` + `.gitleaksignore`. |
| [`lint-yaml`](templates/lint-yaml/template.yml) | `lint:yaml` | yamllint, reading the consumer's `.config/.yamllint`. |
| [`lint-shell`](templates/lint-shell/template.yml) | `lint:shell` | shellcheck, reading the consumer's `.config/.shellcheckrc`. |
| [`lint-markdown`](templates/lint-markdown/template.yml) | `lint:markdown` | markdownlint-cli2, reading the consumer's `.config/.markdownlint-cli2.jsonc`. |
| [`lint-commits`](templates/lint-commits/template.yml) | `lint:commits` | Conventional-Commit check on MR commit subjects (protects auto-tag's SemVer bumps). |
| [`trivy-config`](templates/trivy-config/template.yml) | `scan:trivy-config` | `trivy config` misconfig/IaC scan of a path; console + SARIF. |
| [`trivy-image`](templates/trivy-image/template.yml) | `scan:trivy-image` | `trivy image` vuln scan of a built image (the `image-ref.txt` artifact). |
| [`cosign-sign`](templates/cosign-sign/template.yml) | `sign:image` | Sign a container image by ref with the keyed cosign setup. |
| [`mirror-github`](templates/mirror-github/template.yml) | `mirror:github` | Sanitize + force-push the repo to its public GitHub mirror. |
| [`sbom-attest`](templates/sbom-attest/template.yml) | `sbom:image` | syft SPDX SBOM of a built image, attached as a cosign attestation. |
| [`ci-image`](templates/ci-image/template.yml) | `build:ci-image` | Build + push + digest-pin a repo's CI image; writes `image-ref.txt`. Also rebuilds on `SCHEDULE_TYPE=rebuild` schedules. |
| [`test-ci-scripts`](templates/test-ci-scripts/template.yml) | `test:ci-scripts` | pytest + coverage for a repo's `.ci/scripts`. |
| [`auto-tag`](templates/auto-tag/template.yml) | `auto-tag` | Conventional-commit SemVer release tagging (bare or `v`-prefixed tags). |
| [`notify-discord`](templates/notify-discord/template.yml) | `notify:pipeline` | Discord embed for pipeline events (failure alert by default; skips when no webhook). |
<!-- markdownlint-enable MD013 -->

Each component's `template.yml` header documents its full input contract.

## Usage

Pin the include to a version and pass inputs:

```yaml
variables:
  # Every component's image input defaults to $CI_IMAGE — set it once here.
  CI_IMAGE: registry.example.com/homelab/<repo>/ci:latest

include:
  - component: source.example.com/example-org/ci-components/scan-secrets@<version>
  - component: source.example.com/example-org/ci-components/lint-yaml@<version>
  - component: source.example.com/example-org/ci-components/lint-markdown@<version>
  - component: source.example.com/example-org/ci-components/mirror-github@<version>
    inputs:
      repo_name: argo-apps
  - component: source.example.com/example-org/ci-components/ci-image@<version>
    inputs:
      image_name: homelab/argo-apps/ci
      # argo-apps' kryptos BuildKit secret:
      build_args: "--secret id=kryptos_token,src=$CI_PROJECT_DIR/.kryptos_token"
  - component: source.example.com/example-org/ci-components/cosign-sign@<version>
    inputs:
      job_name: "sign:ci-image"
      needs_job: "build:ci-image"
  - component: source.example.com/example-org/ci-components/sbom-attest@<version>
    inputs:
      job_name: "sbom:ci-image"
      needs_job: "build:ci-image"
```

Key input patterns:

- **`image`** — every component defaults to `$CI_IMAGE`. Define it once in the
  consumer's `variables:` block (its thin CI image) instead of repeating an
  `image:` input per include; override per component only when a job needs a
  different image.
- **`rules`** — an array input. The default is MR + main push (build/sign/
  attest components also fire on `SCHEDULE_TYPE=rebuild` schedules). A consumer
  that also runs on release tags or gates by path passes the full `rules` array
  once, declaratively.
- **Config resolution** — each lint/scan component reads the **consumer's own**
  `.config/` rule file when it exists and falls back to the shared default
  baked into ci-base at `/opt/ci/config/`. Keep a repo-local copy only when the
  repo genuinely diverges (or when local pre-commit hooks need it).
  `.ci/sanitize/sanitize-config.yaml` stays repo-local and may
  `extends: /opt/ci/config/sanitize-base.yaml` to inherit the common
  replacement/exclusion base (protective lists only ever grow through the
  merge).

## Versioning

Component releases are SemVer tags (`1.0.0`, referenced as `@1.0.0`).

Tags are cut **automatically**: a `main` push runs `auto-tag`, which reads the
[Conventional Commit](https://www.conventionalcommits.org/) messages since the
latest tag and pushes the next SemVer (`feat:` → minor, `fix:` →
patch, `!`/`BREAKING CHANGE:` → major). The tag pipeline's `release` job then
creates the GitLab release object that publishes the version to the CI/CD
Catalog. **Do not create tags by hand.**

A MAJOR bump is a breaking change to a component's contract: a renamed/removed
input, a changed default, or a removed component.

## Group CI contract

Conventions every homelab repo follows — this section is the reference.

**Two hubs.** `ci-components` (this repo) owns CI job logic, the ci-base image,
baked config defaults, and the publish/sanitize tooling — released via SemVer
tags. [`renovate`](https://source.example.com/homelab/renovate) owns dependency
policy (shared preset + modular presets) and the central autodiscover runner —
branch-tracked, validated by its own CI. Consumers pull from both; neither hub
depends on the other at runtime.

**Stage vocabulary.** Each repo uses the subset it needs, in this canonical
order (same names, same order, no synonyms):

```text
scan → lint → test → validate → publish → image → release → mirror
```

**Tag conventions.** Bare SemVer (`1.2.3`) for this catalog (the CI/CD Catalog
resolves `@1.2.3` to tag `1.2.3`); `v`-prefixed (`v1.2.3`) for Go tooling
(kryptos, goreleaser convention). Both are cut by the `auto-tag` component —
never by hand.

**Pipeline schedules** (Settings → CI/CD → Schedules, Europe/Berlin), each
carrying a `SCHEDULE_TYPE` variable the jobs gate on:

<!-- markdownlint-disable MD013 -->
| Schedule | Where | Cron | Purpose |
| --- | --- | --- | --- |
| `SCHEDULE_TYPE=rebuild` | every image-owning repo (ci-components, argo-apps, helm-charts, proxmox-infra, kryptos) | weekly, e.g. Sun 03:30–03:50 staggered | full CI-image rebuild so base-layer CVE fixes land without a Dockerfile edit; rebuilt images are re-signed + re-attested, and consumers pick up the new ci-base digest via Renovate |
| `SCHEDULE_TYPE=mirror` | every mirrored repo | daily 04:00–04:30 staggered | sanitized GitHub portfolio mirror |
| (renovate) | homelab/renovate only | daily 03:00 | central dependency runner |
<!-- markdownlint-enable MD013 -->

**Harbor retention.** SHA- and version-tagged CI images accumulate; set a
Harbor retention policy per `homelab/*/ci` repository: retain the 10 most
recent tags, always retain `latest`. (Harbor UI → Project → Policy → Tag
Retention; cosign signatures/attestations ride along with their subject.)

## CI

This repo runs its own pipeline ([`.gitlab-ci.yml`](.gitlab-ci.yml)) on the
homelab runner and validates its own components — the pipeline includes each
`templates/<name>/template.yml` by local path, so a branch validates the
components before they are tagged. It needs:

- `CI_COMPONENTS_RELEASE_TOKEN` — a `write_repository` token whose role may
  create the release tags (`auto-tag` pushes with it).
- Group CI/CD variables: `HARBOR_*` (image build/sign), `COSIGN_KEY` +
  `COSIGN_PASSWORD` (signing), `GITHUB_PUBLISH_TOKEN` (mirror).

## Authoring components

A component template is **one job** (consumed via `include: component:`, a
template can emit only a single job), in `templates/<name>/template.yml` with a
`spec:inputs` block, the `---` separator, then the job body. Two non-obvious
GitLab constraints (a violation silently renders zero jobs via the
`component:@version` path, even though `include: local:` still works):

- **No YAML anchors** (`&`/`*`) in the job body — expand them inline.
- **No nested maps in an array-input default** — keep array defaults flat and
  bake `changes:`-gated rules into the body.

See the `component-authoring` skill under `.claude/skills/` for the full
contract.

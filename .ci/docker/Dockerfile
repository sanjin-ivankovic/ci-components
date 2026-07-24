# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
#
# ci-components-ci — the shared ci-base image for the homelab CI pipelines.
# Build/push/version-model: see argo-apps .ci/docker/README.md.
#
# Carries the COMMON toolchain every consumer needs: gitleaks, cosign, syft,
# shellcheck, yamllint, markdownlint-cli2, pytest, python3 (+ pyyaml/tqdm/
# requests/yq), nodejs, git, docker CLI, plus trivy (used by 3 of 4 consumers:
# argo-apps, helm-charts, proxmox-infra) and the publish/sanitize tooling at
# /opt/ci. Consumers layer their repo-specific tools on top (FROM this image):
# helm/kustomize/kubeconform (argo, helm), crane (helm), terraform/ansible
# (proxmox). kryptos opts out entirely (standalone golang image).
#
# Non-obvious by design (don't "fix" without reading the README):
#   - runs as root, no USER/HEALTHCHECK — ephemeral CI pods, root-writable cache
#   - shellcheck is the one binary with no checksum verify (no upstream file)
#   - cosign IS required even though ci-components builds no app images: the
#     sign:ci-image job (cosign-sign component) runs cosign ON this image to sign it.
#   - base image carries tag@sha256:<digest> so Renovate pins the digest too

# Tool versions are ARG defaults here (Renovate-tracked in this file) so
# `docker build` needs no --build-arg — the GitLab CI build:ci-image job builds
# it plainly.

# renovate: datasource=docker depName=docker versioning=docker
ARG DOCKER_VERSION=29.6.2-cli@sha256:be132a9f282288de4afaf63379dff75711fda0147c6b72a9df44e51841402144
# renovate: datasource=docker depName=aquasec/trivy
ARG TRIVY_VERSION=0.72.0@sha256:cffe3f5161a47a6823fbd23d985795b3ed72a4c806da4c4df16266c02accdd6f

# trivy — vuln + misconfig/IaC scanner (trivy-config / trivy-image components).
# Used by 3 of 4 consumers; baked here so they don't each fetch it.
FROM aquasec/trivy:${TRIVY_VERSION} AS trivy-bin

# fetcher: download + checksum-verify each binary, one RUN per tool so a
# single-tool Renovate bump only busts that tool's layer. curl/tar/xz live
# here only — never in the final image.
FROM docker:${DOCKER_VERSION} AS fetcher

# renovate: datasource=github-releases depName=koalaman/shellcheck
ARG SHELLCHECK_VERSION=v0.11.0
# renovate: datasource=github-releases depName=gitleaks/gitleaks
ARG GITLEAKS_VERSION=v8.30.1
# renovate: datasource=github-releases depName=sigstore/cosign
ARG COSIGN_VERSION=v3.1.2
# renovate: datasource=github-releases depName=anchore/syft
ARG SYFT_VERSION=v1.49.0

RUN apk add --no-cache curl tar xz && mkdir -p /out/usr/local/bin

# ShellCheck — no upstream checksum file, so version-pinned only (no verify).
RUN curl -fLsS "https://github.com/koalaman/shellcheck/releases/download/${SHELLCHECK_VERSION}/shellcheck-${SHELLCHECK_VERSION}.linux.x86_64.tar.xz" | tar -xJ -C /tmp && \
  mv "/tmp/shellcheck-${SHELLCHECK_VERSION}/shellcheck" /out/usr/local/bin/ && \
  /out/usr/local/bin/shellcheck --version

RUN curl -fLsS "https://github.com/gitleaks/gitleaks/releases/download/${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION#v}_linux_x64.tar.gz" -o /tmp/gitleaks.tgz && \
  curl -fLsS "https://github.com/gitleaks/gitleaks/releases/download/${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION#v}_checksums.txt" \
    | grep "gitleaks_${GITLEAKS_VERSION#v}_linux_x64.tar.gz" | awk '{print $1"  /tmp/gitleaks.tgz"}' | sha256sum -c - && \
  tar xz -f /tmp/gitleaks.tgz -C /out/usr/local/bin/ gitleaks && \
  /out/usr/local/bin/gitleaks version

# cosign — signs THIS CI image by digest (sign:ci-image, via the cosign-sign component).
RUN curl -fsSL "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-amd64" -o /out/usr/local/bin/cosign && \
  curl -fsSL "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign_checksums.txt" \
    | grep 'cosign-linux-amd64$' | awk '{print $1"  /out/usr/local/bin/cosign"}' | sha256sum -c - && \
  chmod +x /out/usr/local/bin/cosign && \
  /out/usr/local/bin/cosign version

# syft — SBOM generator (sbom-attest component; cosign attaches the attestation).
RUN curl -fLsS "https://github.com/anchore/syft/releases/download/${SYFT_VERSION}/syft_${SYFT_VERSION#v}_linux_amd64.tar.gz" -o /tmp/syft.tgz && \
  curl -fLsS "https://github.com/anchore/syft/releases/download/${SYFT_VERSION}/syft_${SYFT_VERSION#v}_checksums.txt" \
    | grep "syft_${SYFT_VERSION#v}_linux_amd64.tar.gz" | awk '{print $1"  /tmp/syft.tgz"}' | sha256sum -c - && \
  tar xz -f /tmp/syft.tgz -C /out/usr/local/bin/ syft && \
  /out/usr/local/bin/syft version

# --- final image ---
FROM docker:${DOCKER_VERSION}

LABEL maintainer="maintainer@example.io"
LABEL org.opencontainers.image.title="ci-components-ci"
LABEL org.opencontainers.image.description="Minimal CI image (lint/scan/mirror) for the ci-components pipeline"
LABEL org.opencontainers.image.source="https://source.example.com/example-org/ci-components"
LABEL org.opencontainers.image.licenses="MIT"

# renovate: datasource=pypi depName=pyyaml
ARG PYYAML_VERSION=6.0.3
# renovate: datasource=pypi depName=tqdm
ARG TQDM_VERSION=4.69.0
# renovate: datasource=pypi depName=yamllint
ARG YAMLLINT_VERSION=1.38.0
# renovate: datasource=pypi depName=pytest
ARG PYTEST_VERSION=9.1.1
# renovate: datasource=pypi depName=pytest-cov
ARG PYTEST_COV_VERSION=7.1.0
# renovate: datasource=pypi depName=requests
ARG REQUESTS_VERSION=2.34.2
# renovate: datasource=npm depName=markdownlint-cli2
ARG MARKDOWNLINT_VERSION=0.23.1

# Runtime only — no curl/tar (fetcher does downloads). nodejs/npm stay for the
# markdownlint-cli2 JS CLI; python3 for yamllint + the .ci/scripts (publish/
# sanitize/verify) and their pytest suite. yq is a common YAML CLI used by
# consumer jobs. No pre-commit: CI runs the linters/scanners directly as native
# .gitlab-ci.yml jobs; pre-commit is a LOCAL-only dev hook.
RUN apk add --no-cache \
  bash \
  git \
  coreutils \
  openssh-client \
  yq \
  python3 \
  py3-pip \
  nodejs \
  npm

COPY --from=fetcher /out/usr/local/bin/ /usr/local/bin/
# trivy from the official image (base digest-pinned).
COPY --from=trivy-bin /usr/local/bin/trivy /usr/local/bin/trivy

RUN pip3 install --no-cache-dir --break-system-packages \
  "pyyaml==${PYYAML_VERSION}" \
  "tqdm==${TQDM_VERSION}" \
  "requests==${REQUESTS_VERSION}" \
  "yamllint==${YAMLLINT_VERSION}" \
  "pytest==${PYTEST_VERSION}" \
  "pytest-cov==${PYTEST_COV_VERSION}"

RUN npm install -g "markdownlint-cli2@${MARKDOWNLINT_VERSION}" && \
  npm cache clean --force && \
  markdownlint-cli2 --version

# Publish/sanitize tooling — baked at /opt/ci so every consumer's mirror job
# runs it from the image at runtime. Editing these trips build:ci-image's
# rules:changes, so changes ship to :latest.
RUN mkdir -p /opt/ci
COPY .ci/scripts/publish_github.py      /opt/ci/
COPY .ci/scripts/sanitize_repo.py       /opt/ci/
COPY .ci/scripts/verify_sanitization.py /opt/ci/
RUN chmod +x /opt/ci/*.py

# Shared config defaults at /opt/ci/config/ — the lint/scan components fall
# back to these when a consumer repo carries no local .config/ copy, and
# consumer sanitize-configs may `extends:` the sanitize base. This repo's own
# .config/ rule files ARE the canonical defaults.
RUN mkdir -p /opt/ci/config
COPY .config/.yamllint \
  .config/.markdownlint-cli2.jsonc \
  .config/.shellcheckrc \
  .config/.gitleaks.toml \
  .ci/config/sanitize-base.yaml \
  /opt/ci/config/

# Smoke-test every tool at build so a broken install fails here, not in CI.
RUN echo "=== Installed Tools ===" && \
  echo "shellcheck: $(shellcheck --version | grep version)" && \
  echo "gitleaks: $(gitleaks version)" && \
  echo "cosign: $(cosign version 2>&1 | awk '/^GitVersion:/{print $2}')" && \
  echo "syft: $(syft version 2>&1 | awk '/^Version:/{print $2}')" && \
  echo "trivy: $(trivy version | head -n1)" && \
  echo "yamllint: $(yamllint --version)" && \
  echo "markdownlint-cli2: $(markdownlint-cli2 --version 2>&1 | head -n1)" && \
  echo "pytest: $(pytest --version)" && \
  echo "python3: $(python3 --version)" && \
  echo "yq: $(yq --version)" && \
  echo "git: $(git --version)" && \
  echo "======================="

WORKDIR /workspace

CMD ["/bin/bash"]

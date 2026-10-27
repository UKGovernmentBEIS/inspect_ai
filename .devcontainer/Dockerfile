# Base images are pinned by digest; Dependabot's docker entry for
# .devcontainer updates them. uv is pinned through ARGs instead, which
# Dependabot skips, so it moves with the CI pin (tests/test_dependency_cooldown.py
# checks the version); update the digest with it.
ARG UV_VERSION=0.13.5
ARG UV_DIGEST=sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff

FROM amazon/aws-cli:2.38.2@sha256:5d39fd52f236ed01c5c25fba66c9aebcfc6cbb88e7bb1b727c5fe1f150540597 AS aws-cli
FROM rancher/kubectl:v1.36.2@sha256:06c7a7a9772737494ae1e0c3af90f1b5385630c147e47c1c7cea92f4bed55fbe AS kubectl
FROM node:22.23.3-bookworm-slim@sha256:3ed98443660ff48413b5af19ecefce3b9d50845a901a43420d47cc63a9fddbe9 AS node
FROM ghcr.io/astral-sh/uv:${UV_VERSION}@${UV_DIGEST} AS uv

FROM python:3.13.16-bookworm@sha256:dc02fc25f16160c36dee14de37869973422b2fa9e0096888328793c949c166df AS python
ARG UV_PROJECT_ENVIRONMENT=/opt/inspect_ai
ENV PATH=${UV_PROJECT_ENVIRONMENT}/bin:$PATH
# Login shells reset PATH from /etc/profile.
RUN echo "export PATH=${UV_PROJECT_ENVIRONMENT}/bin:\$PATH" > /etc/profile.d/inspect-ai.sh

FROM python AS builder-base
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_INSTALLER_METADATA=1
RUN uv venv ${UV_PROJECT_ENVIRONMENT}
WORKDIR /source
COPY pyproject.toml uv.lock requirements*.txt .release-please-manifest.json ./

# The build context has no .git, so setuptools-scm can't read a version; the
# RUN steps below set the last release instead. It satisfies the inspect-ai
# floors of inspect-scout and inspect-sentinel, which the dev dependencies
# pull in. The dependencies install before the source is copied, so a source
# change doesn't reinstall them; building the metadata needs a package dir.
FROM builder-base AS builder-prod
RUN --mount=type=cache,target=/root/.cache/uv \
    export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INSPECT_AI="$(python -c "import json; print(json.load(open('.release-please-manifest.json'))['.'])")" \
 && mkdir -p src/inspect_ai \
 && uv sync --locked --no-default-groups --no-editable --no-install-project
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv \
    export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INSPECT_AI="$(python -c "import json; print(json.load(open('.release-please-manifest.json'))['.'])")" \
 && uv sync --locked --no-default-groups --no-editable

FROM builder-base AS builder-dev
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y \
        cmake
RUN --mount=type=cache,target=/root/.cache/uv \
    export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INSPECT_AI="$(python -c "import json; print(json.load(open('.release-please-manifest.json'))['.'])")" \
 && mkdir -p src/inspect_ai \
 && uv sync --locked --all-extras --all-groups --no-install-project

FROM python AS prod
ARG TARGETARCH

# The install script is pinned to a commit of devcontainers/features. It pins
# the Moby engine and CLI; compose, buildx, containerd and runc come at the
# version Microsoft's package repository has at build time.
ARG DOCKER_VERSION=29.9.1
ARG DIND_FEATURE_VERSION=cf6f1cd2066d598edc938e47f0436d33d20c0d29
ARG DOCKER_GID=999
ENV DOCKER_BUILDKIT=1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && curl -fsSL https://raw.githubusercontent.com/devcontainers/features/${DIND_FEATURE_VERSION}/src/docker-in-docker/install.sh \
    | VERSION=${DOCKER_VERSION} DOCKERDASHCOMPOSEVERSION=v2 bash \
 && groupmod -g ${DOCKER_GID} docker

# Each download below is checked against the sha256 (sha512 for gVisor) of its
# published release, pinned here per architecture.
ARG GVISOR_VERSION=20261012
ARG GVISOR_SHA512_AMD64=9606445eed5aedfcf05310e7ccef61d994089914c6622fc82624c24d2b18db1b2210f40e40a7be27b8b7772859de7d95c501b4eba66423053c960bf671377c5e
ARG GVISOR_SHA512_ARM64=2fe7425abd16ad6ca649ab9bc3d7e8e76756834d86ffcc08dbe97c82c3b7262a7d6401f23632f2b296649cc1408b560416b2ab65a4043aa123fc7b90f3a1b2e2
RUN case "${TARGETARCH}" in \
        amd64) ARCH=x86_64 SHA512=${GVISOR_SHA512_AMD64} ;; \
        arm64) ARCH=aarch64 SHA512=${GVISOR_SHA512_ARM64} ;; \
    esac \
 && curl -fsSLo gvisor.tar.bz2 https://storage.googleapis.com/gvisor/releases/release/${GVISOR_VERSION}/${ARCH}/gvisor.tar.bz2 \
 && echo "${SHA512}  gvisor.tar.bz2" | sha512sum -c - \
 && tar -xjf gvisor.tar.bz2 -C /usr/local/bin runsc containerd-shim-runsc-v1 gvisor-bin \
 && rm gvisor.tar.bz2 \
 && chmod -R a+rX /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1 /usr/local/bin/gvisor-bin \
 && mkdir -p /etc/docker \
 && cat <<EOF > /etc/docker/daemon.json
{
    "runtimes": {
        "runsc": {
            "path": "/usr/local/bin/runsc"
        }
    }
}
EOF

ARG HELM_VERSION=3.22.1
ARG HELM_SHA256_AMD64=896cf63684a42a723d61c980369d6e588330927deb13676ca0d85006dd6da0ea
ARG HELM_SHA256_ARM64=4c29e286b279d170fa048ddfc3e4e83dcd069ca9c52102766ba672d7149e694d
RUN case "${TARGETARCH}" in \
        amd64) SHA256=${HELM_SHA256_AMD64} ;; \
        arm64) SHA256=${HELM_SHA256_ARM64} ;; \
    esac \
 && curl -fsSLo helm.tar.gz https://get.helm.sh/helm-v${HELM_VERSION}-linux-${TARGETARCH}.tar.gz \
 && echo "${SHA256}  helm.tar.gz" | sha256sum -c - \
 && tar -xzf helm.tar.gz --strip-components=1 -C /usr/local/bin linux-${TARGETARCH}/helm \
 && rm helm.tar.gz

ARG APP_USER=inspect
ARG APP_DIR=/home/${APP_USER}/app
ARG APP_UID=1000
ARG APP_GID=1000
RUN groupadd -g ${APP_GID} ${APP_USER} \
 && useradd -u ${APP_UID} -g ${APP_USER} -G docker -m -s /bin/bash ${APP_USER} \
 && mkdir -p \
        /home/${APP_USER}/.aws \
        ${APP_DIR} \
 && chown -R ${APP_UID}:${APP_GID} \
        /home/${APP_USER} \
        ${APP_DIR}

COPY --from=builder-prod ${UV_PROJECT_ENVIRONMENT} ${UV_PROJECT_ENVIRONMENT}

WORKDIR ${APP_DIR}
USER ${APP_USER}
ENTRYPOINT ["inspect"]
CMD ["--help"]

FROM prod AS dev
USER root
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && apt-get install -y \
        bash-completion \
        jq \
        less \
        locales \
        nano \
        zsh \
 && sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen \
 && locale-gen en_US.UTF-8 \
 && docker completion bash > /etc/bash_completion.d/docker \
 && helm completion bash > /etc/bash_completion.d/helm

# Node for the viewer (src/inspect_ai/_view/ts-mono). Corepack runs the exact
# pnpm that ts-mono's package.json names in `packageManager`, downloading and
# verifying it on first use.
COPY --from=node /usr/local/bin/node /usr/local/bin/
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
# pnpm otherwise puts its store on the project's filesystem, the bind-mounted
# checkout.
ENV pnpm_config_store_dir=/home/inspect/.local/share/pnpm/store
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && ln -s ../lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
 && corepack enable pnpm

ARG K9S_VERSION=0.51.0
ARG K9S_SHA256_AMD64=c3752ad51a5a4015a113819c4eeb6e55a4d0e4b8e652494797532f6fc8161dd7
ARG K9S_SHA256_ARM64=3ee05c82e5f9198928a4e86133608ba6a2c10a2244d6a7789e820f78319d640c
RUN case "${TARGETARCH}" in \
        amd64) SHA256=${K9S_SHA256_AMD64} ;; \
        arm64) SHA256=${K9S_SHA256_ARM64} ;; \
    esac \
 && curl -fsSLo k9s.tar.gz https://github.com/derailed/k9s/releases/download/v${K9S_VERSION}/k9s_Linux_${TARGETARCH}.tar.gz \
 && echo "${SHA256}  k9s.tar.gz" | sha256sum -c - \
 && tar -xzf k9s.tar.gz -C /usr/local/bin k9s \
 && rm k9s.tar.gz

ARG MINIKUBE_VERSION=1.39.0
ARG MINIKUBE_SHA256_AMD64=b738496da01be06bbaf80c688f57ce25acd3849fbb518155f3a88e03ef555aa4
ARG MINIKUBE_SHA256_ARM64=202f331cb677761c5aec81c58472d16d65707358b9f66226210be3fe3275b1c3
RUN case "${TARGETARCH}" in \
        amd64) SHA256=${MINIKUBE_SHA256_AMD64} ;; \
        arm64) SHA256=${MINIKUBE_SHA256_ARM64} ;; \
    esac \
 && curl -fsSLo minikube https://github.com/kubernetes/minikube/releases/download/v${MINIKUBE_VERSION}/minikube-linux-${TARGETARCH} \
 && echo "${SHA256}  minikube" | sha256sum -c - \
 && install -m 755 minikube /usr/local/bin/minikube \
 && rm minikube \
 && minikube completion bash > /etc/bash_completion.d/minikube

ARG CILIUM_CLI_VERSION=0.20.1
ARG CILIUM_CLI_SHA256_AMD64=24e817dcfcc8a12e325ce7547617bcbcf171c5b0b335bb24d2bb1207ba047f61
ARG CILIUM_CLI_SHA256_ARM64=d237550b882af6f2e01e8985e1e024d57c0774611c0a527c7a20dcee7dc4fd07
RUN case "${TARGETARCH}" in \
        amd64) SHA256=${CILIUM_CLI_SHA256_AMD64} ;; \
        arm64) SHA256=${CILIUM_CLI_SHA256_ARM64} ;; \
    esac \
 && curl -fsSLo cilium.tar.gz https://github.com/cilium/cilium-cli/releases/download/v${CILIUM_CLI_VERSION}/cilium-linux-${TARGETARCH}.tar.gz \
 && echo "${SHA256}  cilium.tar.gz" | sha256sum -c - \
 && tar -xzf cilium.tar.gz -C /usr/local/bin cilium \
 && rm cilium.tar.gz \
 && cilium completion bash > /etc/bash_completion.d/cilium

COPY --from=aws-cli /usr/local/aws-cli/v2/current /usr/local
COPY --from=kubectl /bin/kubectl /usr/local/bin/
COPY --from=uv /uv /uvx /usr/local/bin/
RUN echo "complete -C '/usr/local/bin/aws_completer' aws" >> /etc/bash_completion.d/aws \
 && kubectl completion bash > /etc/bash_completion.d/kubectl \
 && echo 'eval "$(uv generate-shell-completion bash)"' >> /etc/bash_completion.d/uv

WORKDIR ${APP_DIR}
COPY --from=builder-dev --chown=${APP_UID}:${APP_GID} ${UV_PROJECT_ENVIRONMENT} ${UV_PROJECT_ENVIRONMENT}
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INSPECT_AI="$(python -c "import json; print(json.load(open('.release-please-manifest.json'))['.'])")" \
 && uv sync --all-extras --all-groups --locked \
 && chown -R ${APP_UID}:${APP_GID} ${UV_PROJECT_ENVIRONMENT}

ENTRYPOINT ["/usr/local/share/docker-init.sh"]
CMD ["sleep", "infinity"]

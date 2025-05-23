ARG AWS_CLI_VERSION=2.27.17
ARG KUBECTL_VERSION=1.33.1
ARG PYTHON_VERSION=3.13.3
ARG UV_VERSION=0.7.5

FROM amazon/aws-cli:${AWS_CLI_VERSION} AS aws-cli
FROM bitnami/kubectl:${KUBECTL_VERSION} AS kubectl
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM python:${PYTHON_VERSION}-bookworm AS python
ARG UV_PROJECT_ENVIRONMENT=/opt/inspect_ai
ENV PATH=${UV_PROJECT_ENVIRONMENT}/bin:$PATH

FROM python AS builder-base
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_INSTALLER_METADATA=1
RUN uv venv ${UV_PROJECT_ENVIRONMENT}

WORKDIR /source
COPY pyproject.toml uv.lock requirements.txt ./

FROM builder-base AS builder-prod
# Use `uv export` to get around setuptools_scm requiring src/ at this stage
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export \
    --format=requirements.txt \
    --locked \
    --no-emit-project \
    | uv pip install --requirements=-

COPY src src
ARG INSPECT_AI_VERSION=1
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INSPECT_AI=${INSPECT_AI_VERSION}
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync \
    --locked \
    --no-editable

FROM builder-base AS builder-dev
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INSPECT_AI=0.0.1
# quarto-cli has some bug that doesn't let it be installed via `uv sync` or `uv
# pip install`. But it works using `pip install`. So, let's install it manually
# first, then `uv sync` will fill in the rest. Yes, this is ugly.
RUN --mount=type=cache,target=/root/.cache/uv \
    mkdir src \
 && touch src/__init__.py \
 && QUARTO_CLI_VERSION="$(uv export --all-extras --locked --no-hashes | grep -oP '(?<=^quarto-cli==).+')" \
 && pip install \
    --no-deps \
    --no-cache-dir \
    --prefix=${UV_PROJECT_ENVIRONMENT} \
        quarto-cli==${QUARTO_CLI_VERSION} \
 && uv sync \
    --all-extras \
    --all-groups \
    --locked \
    --no-install-project

FROM python AS prod

ARG DOCKER_VERSION=28.1.1
ARG DOCKER_COMPOSE_VERSION=2.36.0
ARG DIND_FEATURE_VERSION=87fd9a35c50496f889ce309c284b9cffd3061920
ARG DOCKER_GID=999
ENV DOCKER_BUILDKIT=1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update \
 && curl -fsSL https://raw.githubusercontent.com/devcontainers/features/${DIND_FEATURE_VERSION}/src/docker-in-docker/install.sh \
    | VERSION=${DOCKER_VERSION} DOCKERDASHCOMPOSEVERSION=${DOCKER_COMPOSE_VERSION} bash \
 && groupmod -g ${DOCKER_GID} docker

ARG GVISOR_VERSION=20250429
RUN ARCH=$(uname -m) \
 && URL=https://storage.googleapis.com/gvisor/releases/release/${GVISOR_VERSION}/${ARCH} \
 && wget \
        ${URL}/containerd-shim-runsc-v1 \
        ${URL}/containerd-shim-runsc-v1.sha512 \
        ${URL}/runsc \
        ${URL}/runsc.sha512 \
 && sha512sum -c runsc.sha512 -c containerd-shim-runsc-v1.sha512 \
 && rm -f *.sha512 \
 && chmod a+rx runsc containerd-shim-runsc-v1 \
 && mv runsc containerd-shim-runsc-v1 /usr/local/bin \
 && cat <<EOF > /etc/docker/daemon.json
{
    "runtimes": {
        "runsc": {
            "path": "/usr/local/bin/runsc"
        }
    }
}
EOF

ARG HELM_VERSION=3.17.3
RUN [ $(uname -m) = aarch64 ] && ARCH=arm64 || ARCH=amd64 \
 && curl -fsSL https://get.helm.sh/helm-v${HELM_VERSION}-linux-${ARCH}.tar.gz \
    | tar -zxvf - \
 && install -m 755 linux-${ARCH}/helm /usr/local/bin/helm \
 && rm -r linux-${ARCH}

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

ARG NODE_VERSION=22.15.0
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/root/.npm \
    curl -sL https://deb.nodesource.com/setup_$(echo ${NODE_VERSION} \
    | cut -d . -f 1).x \
    | bash - \
 && apt-get install -y --no-install-recommends \
        nodejs=${NODE_VERSION}-1nodesource1 \
 && apt-get update \
 && npm install -g yarn

ARG K9S_VERSION=0.50.4
RUN [ $(uname -m) = aarch64 ] && ARCH=arm64 || ARCH=amd64 \
 && curl -fsSL https://github.com/derailed/k9s/releases/download/v${K9S_VERSION}/k9s_Linux_${ARCH}.tar.gz \
    | tar -zxvf - \
 && install -m 755 k9s /usr/local/bin/k9s \
 && rm LICENSE README.md

ARG MINIKUBE_VERSION=1.35.0
RUN [ $(uname -m) = aarch64 ] && ARCH=arm64 || ARCH=amd64 \
 && curl -Lo ./minikube https://github.com/kubernetes/minikube/releases/download/v${MINIKUBE_VERSION}/minikube-linux-${ARCH} \
 && install -m 755 minikube /usr/local/bin/minikube \
 && minikube completion bash > /etc/bash_completion.d/minikube

ARG CILIUM_CLI_VERSION=0.18.3
RUN [ $(uname -m) = aarch64 ] && ARCH=arm64 || ARCH=amd64 \
 && curl -fsSL https://github.com/cilium/cilium-cli/releases/download/v${CILIUM_CLI_VERSION}/cilium-linux-${ARCH}.tar.gz \
    | tar -zxvf - \
 && install -m 755 cilium /usr/local/bin/cilium \
 && cilium completion bash > /etc/bash_completion.d/cilium

COPY --from=aws-cli /usr/local/aws-cli/v2/current /usr/local
COPY --from=kubectl /opt/bitnami/kubectl/bin/kubectl /usr/local/bin/
COPY --from=uv /uv /uvx /usr/local/bin/
RUN echo "complete -C '/usr/local/bin/aws_completer' aws" >> /etc/bash_completion.d/aws \
 && kubectl completion bash > /etc/bash_completion.d/kubectl \
 && echo 'eval "$(uv generate-shell-completion bash)"' >> /etc/bash_completion.d/uv

WORKDIR ${APP_DIR}
COPY --from=builder-dev --chown=${APP_UID}:${APP_GID} ${UV_PROJECT_ENVIRONMENT} ${UV_PROJECT_ENVIRONMENT}
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INSPECT_AI=0.0.1 \
    uv sync \
        --all-extras \
        --all-groups \
        --locked \
 && chown -R ${APP_UID}:${APP_GID} ${UV_PROJECT_ENVIRONMENT}

ENTRYPOINT ["/usr/local/share/docker-init.sh"]
CMD ["sleep", "infinity"]

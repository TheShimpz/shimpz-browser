# syntax=docker/dockerfile:1@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89
# check=skip=SecretsUsedInArgOrEnv ; false positive: the *_TOKEN_GID/*_TOKEN_* ARGs here hold numeric group IDs and file paths, never secret values
#
# shimpz-browser — the ONLY container that runs Chrome, the desktop, XTEST, and CDP.
#
# SECURITY_ENGINEERING_PLAN.md item 0: the browser opens hostile external content by design (pages,
# PDFs, OAuth flows, downloads); it used to share a container with Claude Code (the brain), the
# full workspace, and every remaining credential. Split so an RCE in the renderer/PDF/page lands
# here — a container with NO workspace, NO Anthropic/OpenAI/Telegram/R2/git credential, and NO way
# to reach the rest of the stack except through browser-agent's narrow, audited API.
#
# Same base as before (KasmVNC web desktop, real Xvnc → genuine headful browser fingerprint).
# MUST keep CAP_SYS_ADMIN + unconfined seccomp/apparmor at the compose level — Chrome's OWN
# sandbox needs them; dropping forces --no-sandbox, a regression for a browser that exists to
# visit untrusted sites. `shimpz-brain` (the brain) is the one that loses those caps, not this container.
ARG NODE_VERSION=24.18.0
ARG NODE_SHA256=55aa7153f9d88f28d765fcdad5ae6945b5c0f98a36881703817e4c450fa76742

FROM lscr.io/linuxserver/baseimage-kasmvnc:ubuntunoble@sha256:c6d902c207d6e4a66ca41ce36dda549cd58a5bc8d353468b24b0cf780eb528c8 AS shimpz-kasm-base
ARG SOURCE_DATE_EPOCH=0

ARG UBUNTU_SNAPSHOT=20260623T000000Z
RUN set -eux; \
    find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -delete; \
    printf '%s\n' \
        "deb https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT} noble main restricted universe multiverse" \
        "deb https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT} noble-updates main restricted universe multiverse" \
        "deb https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT} noble-security main restricted universe multiverse" \
        > /etc/apt/sources.list; \
    printf 'Acquire::Check-Valid-Until "false";\n' > /etc/apt/apt.conf.d/99shimpz-snapshot; \
    test "$(grep -Fc "https://snapshot.ubuntu.com/ubuntu/${UBUNTU_SNAPSHOT}" /etc/apt/sources.list)" -eq 3; \
    ! grep -RqsE 'https?://(archive|security)\.ubuntu\.com|https?://download\.docker\.com' \
        /etc/apt/sources.list /etc/apt/sources.list.d

# The pinned Kasm base ships kclient on Ubuntu's EOL Node 18 ABI 109. Build its only native addon
# twice against the exact Node 24 archive and keep only equal, stripped ABI-137 output. Build tools,
# headers, npm, and node-gyp remain in this throwaway stage; the final image receives one runtime
# binary, its license, and one addon. npm_config_nodedir prevents node-gyp from downloading mutable
# headers.
FROM shimpz-kasm-base AS kclient-node24-builder
ARG SOURCE_DATE_EPOCH=0
ARG NODE_VERSION
ARG NODE_SHA256
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends build-essential ca-certificates curl libpulse-dev pkg-config python3; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        -o /tmp/node.tar.xz; \
    echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c -; \
    mkdir -p /opt/node24 /out; \
    tar -xJf /tmp/node.tar.xz -C /opt/node24 --strip-components=1; \
    test "$(/opt/node24/bin/node --version)" = "v${NODE_VERSION}"; \
    test "$(/opt/node24/bin/node -p 'process.versions.modules')" = "137"; \
    cd /kclient/node_modules/pulseaudio2; \
    export PATH="/opt/node24/bin:${PATH}" npm_config_nodedir=/opt/node24 SOURCE_DATE_EPOCH; \
    build_addon() { \
        rm -rf build; \
        /opt/node24/bin/node \
            /opt/node24/lib/node_modules/npm/node_modules/node-gyp/bin/node-gyp.js \
            rebuild --nodedir=/opt/node24; \
        strip --strip-unneeded build/Release/pulse.node; \
    }; \
    build_addon; \
    install -m 0755 build/Release/pulse.node /out/pulse.first.node; \
    build_addon; \
    cmp /out/pulse.first.node build/Release/pulse.node; \
    install -m 0755 build/Release/pulse.node /out/pulse.node; \
    ! ldd /out/pulse.node | grep -q 'libnode\.so'; \
    /opt/node24/bin/node -e "require('/out/pulse.node')"; \
    rm -f /tmp/node.tar.xz; \
    rm -rf /root/.cache/node-gyp /root/.npm /config/.npm /tmp/node-compile-cache; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/lib/apt/periodic/* /var/cache/apt/* /var/cache/fontconfig/* \
        /var/cache/ldconfig/aux-cache /var/cache/man/* /var/log/apt/* \
        /var/log/alternatives.log /var/log/dpkg.log

FROM shimpz-kasm-base AS shimpz-browser
ARG SOURCE_DATE_EPOCH=0
ARG NODE_VERSION

LABEL org.opencontainers.image.title="shimpz-browser" \
      org.opencontainers.image.description="Chrome + KasmVNC desktop + browser-agent (SECURITY_ENGINEERING_PLAN.md item 0)"

ENV DEBIAN_FRONTEND=noninteractive

ARG PYTHON_VERSION=3.14.6
ARG UV_VERSION=0.11.25
ARG GOST_VERSION=2.12.0
ARG GOOGLE_CHROME_VERSION=150.0.7871.114-1
ARG GOOGLE_CHROME_SHA256=0f19e68dca574849632e25229f15853d2beac33fa06498feed43f34628bc2d53
ARG UV_INSTALL_SHA256=ca2de1bca2913ba30ce88658b6d90a663c627ecac378803aa58084a9adb35a46
ARG GOST_SHA256=1b6d47e6b850479b23fda484b3a8193c7bc0d5dc38fa5a02b4b4c57a77534d92

# Same IPv6 fix as the main image — Chrome/gost/apt all do outbound HTTPS from here too.
RUN sed -i 's/^#\(precedence ::ffff:0:0\/96  100\)/\1/' /etc/gai.conf || \
    echo 'precedence ::ffff:0:0/96  100' >> /etc/gai.conf && \
    grep -q '^precedence ::ffff:0:0/96' /etc/gai.conf

# browser-agent's bearer token — same shared-volume/GID pattern as every other sidecar. Fixed GID,
# distinct from shimpz-brain's own 1000x-series token GIDs, MUST match the main Dockerfile's own groupadd
# exactly so `shimpz-brain`'s `abc` can read the token file without being its owner.
ARG SHIMPZ_BROWSERAGENT_TOKEN_GID=10006
RUN groupadd -g "${SHIMPZ_BROWSERAGENT_TOKEN_GID}" shimpzbrowseragent-token \
    && usermod -aG shimpzbrowseragent-token abc

# --- SECURITY: strip the base image's root-escalation path for the agent user ---
# The LSIO base adds `abc` to `sudo` (with `%sudo NOPASSWD: ALL` in /etc/sudoers) and `docker`.
# This container keeps CAP_SYS_ADMIN + unconfined seccomp/apparmor for Chrome's sandbox, so an
# abc→root escalation here would mean a container escape to the host — the exact worst case. Remove
# the membership AND neuter the NOPASSWD grant so root is unreachable to `abc` even if the single
# `no-new-privileges` flag is ever dropped. Re-asserted at boot in 10-shimpz-browser-init.sh.
RUN gpasswd -d abc sudo 2>/dev/null || true; \
    gpasswd -d abc docker 2>/dev/null || true; \
    sed -i 's/^%sudo/# shimpz-disabled: %sudo/' /etc/sudoers

# --- System deps: Chrome, desktop terminal, real-input stack, screenshot toolbelt ---
# Everything here is Chrome/desktop/automation-specific — NONE of the document-toolbelt/dev-tooling
# packages the brain needs (those moved to shimpz-brain/Dockerfile; this container never runs Claude Code,
# ruff, or project scaffolding; its sole Node runtime executes the inherited kclient service).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates \
        xterm fonts-noto fonts-noto-color-emoji fonts-liberation fonts-noto-cjk \
        # a11y runtime + REAL input. xdotool injects REAL XTEST events that GTK/Qt
        # native dialogs honor (synthetic XSendEvent is silently ignored).
        at-spi2-core xdotool \
        # software GL (Mesa llvmpipe) for headful WebGL without a GPU.
        libgl1-mesa-dri libglu1-mesa \
        # shimpz-shot's screenshot capture (server-side, in screenshot_client.py).
        imagemagick \
        python3-venv && \
    # gost = local proxy relay. Chrome can't do user:pass on --proxy-server, so gost adds the
    # upstream auth (Chrome → 127.0.0.1 → IPRoyal SP residential IP). Single Go binary.
    curl -4 -fsSL "https://github.com/ginuerzh/gost/releases/download/v${GOST_VERSION}/gost_${GOST_VERSION}_linux_amd64.tar.gz" -o /tmp/gost.tar.gz && \
    echo "${GOST_SHA256}  /tmp/gost.tar.gz" | sha256sum -c - && \
    tar -xzf /tmp/gost.tar.gz -C /tmp gost && install -m 0755 /tmp/gost /usr/local/bin/gost && rm -f /tmp/gost /tmp/gost.tar.gz && \
    # The signed APT index retains only the current stable version. Fetch the immutable versioned
    # pool object instead, bind its exact bytes, and verify the embedded package version before install.
    curl --proto '=https' --tlsv1.2 -fsSL \
        "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/google-chrome-stable_${GOOGLE_CHROME_VERSION}_amd64.deb" \
        -o /tmp/google-chrome-stable.deb && \
    echo "${GOOGLE_CHROME_SHA256}  /tmp/google-chrome-stable.deb" | sha256sum -c - && \
    test "$(dpkg-deb --field /tmp/google-chrome-stable.deb Version)" = "${GOOGLE_CHROME_VERSION}" && \
    apt-get install -y --no-install-recommends /tmp/google-chrome-stable.deb && \
    rm -f /tmp/google-chrome-stable.deb && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/lib/apt/periodic/* /var/cache/apt/* /var/cache/fontconfig/* \
        /var/cache/ldconfig/aux-cache /var/cache/man/* /var/log/apt/* \
        /var/log/alternatives.log /var/log/dpkg.log

# --- uv + a minimal Python venv for browser-agent (websockets/requests — the SAME pins the main
# image uses, so there's only ever one version of each to track across the whole stack). uv.lock
# binds the transitive graph and artifact hashes; --frozen refuses manifest/lock drift. ---
COPY pyproject.toml uv.lock /opt/shimpz-browser-runtime/
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" -o /tmp/uv-install.sh && \
    echo "${UV_INSTALL_SHA256}  /tmp/uv-install.sh" | sha256sum -c - && \
    env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh /tmp/uv-install.sh && \
    rm -f /tmp/uv-install.sh && \
    export UV_CACHE_DIR=/tmp/shimpz-uv-cache UV_LINK_MODE=copy && \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python uv python install "${PYTHON_VERSION}" && \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python uv venv --python "${PYTHON_VERSION}" /opt/venv && \
    UV_PROJECT_ENVIRONMENT=/opt/venv uv sync --project /opt/shimpz-browser-runtime \
        --frozen --no-dev --no-install-project --python /opt/venv/bin/python && \
    /opt/venv/bin/python -c 'import websockets, requests' && \
    find /opt/uv-python /opt/venv -type f -name '*.pyc' -delete && \
    /opt/venv/bin/python -m compileall -q -f --invalidation-mode checked-hash /opt/uv-python /opt/venv && \
    rm -rf "${UV_CACHE_DIR}" /config/.cache/uv

WORKDIR /opt/browser-agent
COPY browser-agent/app.py browser-agent/validate.py browser-agent/audit.py browser-agent/token_store.py \
     browser-agent/xtest_client.py browser-agent/cdp_client.py browser-agent/screenshot_client.py \
     browser-agent/upload_client.py browser-agent/downloads_client.py browser-agent/healthcheck.py \
     browser-agent/native_process.py ./

# Replace the inherited Node 18 runtime without carrying a compiler or package manager forward.
# kclient's rebuilt addon resolves Node symbols from the executable and no longer needs libnode109.
COPY --from=kclient-node24-builder /opt/node24/bin/node /opt/node24/bin/node
COPY --from=kclient-node24-builder /opt/node24/LICENSE /opt/node24/LICENSE
COPY --from=kclient-node24-builder /out/pulse.node /kclient/node_modules/pulseaudio2/build/Release/pulse.node
RUN set -eux; \
    apt-get purge -y nodejs libnode109 node-acorn; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /var/lib/apt/periodic/* /var/cache/apt/* /var/cache/fontconfig/* \
        /var/cache/ldconfig/aux-cache /var/cache/man/* /var/log/apt/* \
        /var/log/alternatives.log /var/log/dpkg.log; \
    test ! -e /usr/bin/node; \
    test "$(/opt/node24/bin/node --version)" = "v${NODE_VERSION}"; \
    test "$(/opt/node24/bin/node -p 'process.versions.modules')" = "137"; \
    s6-setuidgid abc /opt/node24/bin/node \
        -e "require('/kclient/node_modules/pulseaudio2/build/Release/pulse.node')"; \
    ! ldd /kclient/node_modules/pulseaudio2/build/Release/pulse.node | grep -q 'libnode\.so'; \
    for package in nodejs libnode109 node-acorn; do \
        ! dpkg-query -W -f='${db:Status-Abbrev}' "$package" 2>/dev/null | grep -q '^ii'; \
    done
ENV PATH="/opt/node24/bin:$PATH"

# --- Overlay browser-only s6 services, autostart, and Chrome policy/spoof assets ---
COPY rootfs-browser/ /

RUN chmod +x /usr/local/bin/shimpz-glspoof /usr/local/bin/shimpz-kasm-patch \
             /defaults/autostart \
             /etc/s6-overlay/s6-rc.d/svc-kasmvnc/run \
             /etc/s6-overlay/s6-rc.d/svc-kclient/run \
             /custom-cont-init.d/*.sh 2>/dev/null || true

RUN grep -qF '/opt/node24/bin/node index.js' /etc/s6-overlay/s6-rc.d/svc-kclient/run

# Patch the served KasmVNC web client (human-watch UX only — Shimpz drives via browser-agent).
RUN /usr/local/bin/shimpz-kasm-patch || true

# Pre-create + own every path a NAMED VOLUME will be mounted onto. This chown is BUILD-TIME only —
# a fresh named volume gets populated from this image layer, carrying this build-time ownership
# (the base image's own abc, uid 911), NOT the runtime PUID/PGID remap (confirmed live: 911:1001 on
# a first real boot). `custom-cont-init.d/10-shimpz-browser-init.sh` re-chowns these same 3 `/config`
# subdirectories as ROOT, at container start, AFTER the PUID/PGID remap — that's the fix that
# actually matters for the volume-backed downloads/.chrome/logs paths; this block only matters for
# `/run/shimpz-browseragent` (a separate volume, but not user-data — token perms are fine either way)
# and the (rare) ephemeral-no-volume case.
RUN mkdir -p /run/shimpz-browseragent /var/log/browser-agent /config/downloads /config/.chrome /config/logs \
    && chown abc:shimpzbrowseragent-token /run/shimpz-browseragent && chmod 750 /run/shimpz-browseragent \
    && chown -R abc:abc /var/log/browser-agent /config/downloads /config/.chrome /config/logs

# KasmVNC desktop: 3000 = HTTP (behind Cloudflare Tunnel), 3001 = HTTPS (direct).
# 9222 = Chrome CDP (loopback only). 7074 = browser-agent (internal network only, never published).
EXPOSE 3000 3001

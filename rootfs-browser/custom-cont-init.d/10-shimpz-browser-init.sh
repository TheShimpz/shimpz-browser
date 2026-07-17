#!/usr/bin/with-contenv bash
# shellcheck shell=bash
# Runs as ROOT during LSIO's init stage — BEFORE openbox/autostart (which runs unprivileged as
# `abc`, already remapped to PUID/PGID by that point). `/config` is the fresh `shimpz-browser-config`
# volume: Docker populated it from the image's `/config` tree on first mount, which carries the
# BUILD-TIME ownership (the base image's default abc, uid 911) — not this container's runtime
# PUID/PGID (1000). `autostart`'s own `mkdir -p` is a silent no-op on an already-existing directory,
# so without this fix every log/profile/download write there fails EACCES forever (confirmed via a
# real first boot, not assumed).
mkdir -p /config/.chrome /config/downloads /config/logs
chown -R "${PUID:-1000}:${PGID:-1000}" /config/.chrome /config/downloads /config/logs

# SECURITY (re-assert the Dockerfile hardening at boot): keep `abc` OUT of `sudo`/`docker`. This
# container has CAP_SYS_ADMIN + unconfined seccomp/apparmor for Chrome's sandbox, so an abc→root here
# would be a host escape; sudo-group membership (+ the base's `%sudo NOPASSWD: ALL`) must never grant it.
gpasswd -d abc sudo 2>/dev/null || true
gpasswd -d abc docker 2>/dev/null || true
sed -i 's/^%sudo/# shimpz-disabled: %sudo/' /etc/sudoers 2>/dev/null || true

# `.cache` is a build-time artifact too (root-owned `uv` cache from the Dockerfile's own `uv python
# install`/`uv venv` RUN steps, HOME=/config at build time) — openbox needs to write
# `.cache/openbox/sessions` at runtime. Narrow chown (not a blanket recursive /config chown every
# boot, which would get slow once the Chrome profile grows large).
mkdir -p /config/.cache
chown -R "${PUID:-1000}:${PGID:-1000}" /config/.cache

# Same stale-build-time-uid problem on the `shimpz-browseragent-token` volume: browser-agent (running
# as the remapped abc, PUID) needs WRITE on the directory to create/rotate its token file — group
# read through `shimpzbrowseragent-token` is unaffected; only the owner uid changes.
mkdir -p /run/shimpz-browseragent
chown "${PUID:-1000}:shimpzbrowseragent-token" /run/shimpz-browseragent
chmod 750 /run/shimpz-browseragent

# And the THIRD (and last) named volume this service mounts — the audit log directory. Every one
# of shimpz-browser's 3 volumes (config/token/audit) hit this exact issue on first real boot; fixing
# all 3 here instead of finding them one at a time.
mkdir -p /var/log/browser-agent
chown -R "${PUID:-1000}:${PGID:-1000}" /var/log/browser-agent

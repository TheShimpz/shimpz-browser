#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKERFILE="$ROOT/shimpz-browser/Dockerfile"
KCLIENT_RUN="$ROOT/rootfs-browser/etc/s6-overlay/s6-rc.d/svc-kclient/run"

require_literal() {
  local file="$1" literal="$2"
  grep -qF -- "$literal" "$file" || {
    printf 'missing Node 24 contract in %s: %s\n' "$file" "$literal" >&2
    exit 1
  }
}

require_literal "$DOCKERFILE" 'ARG NODE_VERSION=24.18.0'
require_literal "$DOCKERFILE" 'ARG NODE_SHA256=55aa7153f9d88f28d765fcdad5ae6945b5c0f98a36881703817e4c450fa76742'
require_literal "$DOCKERFILE" 'FROM shimpz-kasm-base AS kclient-node24-builder'
require_literal "$DOCKERFILE" 'npm_config_nodedir=/opt/node24'
require_literal "$DOCKERFILE" 'cmp /out/pulse.first.node build/Release/pulse.node'
require_literal "$DOCKERFILE" "! ldd /out/pulse.node | grep -q 'libnode\\.so'"
require_literal "$DOCKERFILE" 'COPY --from=kclient-node24-builder /opt/node24/bin/node /opt/node24/bin/node'
require_literal "$DOCKERFILE" 'COPY --from=kclient-node24-builder /opt/node24/LICENSE /opt/node24/LICENSE'
require_literal "$DOCKERFILE" 'apt-get purge -y nodejs libnode109 node-acorn'
require_literal "$DOCKERFILE" 's6-setuidgid abc /opt/node24/bin/node'
require_literal "$KCLIENT_RUN" '/opt/node24/bin/node index.js'

printf 'Node 24 kclient contract: ok\n'

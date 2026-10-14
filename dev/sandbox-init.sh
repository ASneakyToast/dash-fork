#!/usr/bin/with-contenv sh
set -eu
mkdir -p /config/workspace
chown 1000:1000 /config/workspace
apk add --no-cache git ripgrep fd python3 py3-pip yq
[ -f /config/.gitconfig ] || printf '[user]\n\tname = hermes-agent\n\temail = hermes-agent@users.noreply.github.com\n' > /config/.gitconfig
chown 1000:1000 /config/.gitconfig

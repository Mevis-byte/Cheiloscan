#!/bin/sh
# Prepare the mounted data volume, then run the app as the non-root user.
# Render mounts persistent disks root-owned, so the chown must happen before
# privileges are dropped.
set -e

if [ "$(id -u)" = "0" ]; then
    mkdir -p /data
    chown -R 10001:10001 /data
    exec python -c 'import os, sys; os.setgroups([]); os.setgid(10001); os.setuid(10001); os.execv(sys.executable, [sys.executable, "serve.py"])'
fi

exec "$@"

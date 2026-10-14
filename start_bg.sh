#!/bin/bash
set -e
cd "$(dirname "$0")"
nohup ./start.sh --no-browser "$@" </dev/null > /tmp/server_v12.log 2>&1 &
echo "PID=$!"

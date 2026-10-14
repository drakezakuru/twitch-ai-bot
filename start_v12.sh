#!/bin/bash
set -e
cd "$(dirname "$0")"
exec ./start.sh --no-browser "$@"

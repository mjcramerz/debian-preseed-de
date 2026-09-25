#!/bin/sh
set -eu
printf '[late:standard] target=%s\n' "${1:-/target}" >&2

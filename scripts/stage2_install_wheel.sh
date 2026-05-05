#!/usr/bin/env sh
# Stage-2 helper: install python3 + pip + the bundled wheel inside a
# clean distro container.  Mounted into the container and invoked
# from CI right before either selfcheck, smoketest or pytest is run.
#
# Reads:
#   $BASENAME      – wheel filename in /dist (set by the caller)
#   $HOST_MIRROR   – optional ubuntu apt mirror URL from the runner host
#
# Idempotent: re-running just no-ops on already-installed packages.
set -e

# Step 1: install python3 + pip via the distro package manager.
sh /host-scripts/stage2_install_python.sh

# Step 2: install the wheel.
pip3 install --quiet --break-system-packages "/dist/$BASENAME" 2>/dev/null \
    || pip3 install --quiet "/dist/$BASENAME"

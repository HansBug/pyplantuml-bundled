#!/usr/bin/env sh
# Stage-2 helper: install python3 + pip + the bundled wheel inside a
# clean distro container.  Mounted into the container and invoked
# from CI right before either selfcheck or pytest is executed.
#
# Reads:
#   $BASENAME      – wheel filename in /dist (set by the caller)
#   $HOST_MIRROR   – optional ubuntu apt mirror URL from the runner host
#
# Idempotent: re-running just no-ops on already-installed packages.
set -e

if command -v apk >/dev/null 2>&1; then
    # Alpine (musllinux distros).
    apk add --no-cache python3 py3-pip
elif command -v dnf >/dev/null 2>&1; then
    # Rocky / Fedora (modern Red Hat family).  dnf default mirror
    # selection is already a global CDN; no host-mirror rewrite.
    dnf install -y --setopt=install_weak_deps=False \
        python3 python3-pip ca-certificates
elif command -v yum >/dev/null 2>&1; then
    # CentOS 7 reaches yum but its repo is EOL'd to vault.
    # Patch sources before any yum install can run.
    if [ -d /etc/yum.repos.d ]; then
        for r in /etc/yum.repos.d/CentOS-*.repo; do
            [ -f "$r" ] && sed -i \
                -e 's|^mirrorlist=|#mirrorlist=|g' \
                -e 's|^#baseurl=http://mirror.centos.org/centos|baseurl=http://vault.centos.org|g' \
                "$r"
        done
    fi
    yum install -y python3 python3-pip ca-certificates
else
    # Debian / Ubuntu (apt).  Detect EOL'd debian (buster/stretch/jessie)
    # and patch sources to archive.debian.org first.  Then optionally
    # rewrite ubuntu mirrors to the runner-host's azure mirror for speed.
    CONTAINER_ID=
    CODENAME=
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        CONTAINER_ID="$ID"
        CODENAME="$VERSION_CODENAME"
    fi
    case "$CODENAME" in
        stretch|buster|jessie)
            sed -i \
                -e "s|deb.debian.org|archive.debian.org|g" \
                -e "s|security.debian.org/debian-security|archive.debian.org/debian-security|g" \
                -e "s|security.debian.org|archive.debian.org/debian-security|g" \
                -e "/${CODENAME}-updates/d" \
                /etc/apt/sources.list
            printf '%s\n' 'Acquire::Check-Valid-Until "false";' \
                > /etc/apt/apt.conf.d/99no-check-valid-until
            ;;
    esac
    if [ -n "$HOST_MIRROR" ] && [ "$CONTAINER_ID" = "ubuntu" ]; then
        for f in /etc/apt/sources.list \
                 /etc/apt/sources.list.d/*.list \
                 /etc/apt/sources.list.d/*.sources; do
            [ -f "$f" ] || continue
            sed -i -E \
                -e "s|https?://[^ /]*\\.?archive\\.ubuntu\\.com|$HOST_MIRROR|g" \
                -e "s|https?://[^ /]*\\.?security\\.ubuntu\\.com|$HOST_MIRROR|g" \
                -e "s|https?://[^ /]*\\.?ports\\.ubuntu\\.com|$HOST_MIRROR|g" \
                "$f"
        done
    fi
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        python3 python3-pip ca-certificates
fi

# Old apt-pip on debian:10 / ubuntu:18.04 / python:3.6-slim-* cannot
# read PEP 600 (manylinux_2_17 / musllinux_1_1) tags.  Bootstrap pip.
python3 -m pip install --quiet --upgrade pip --break-system-packages 2>/dev/null \
    || python3 -m pip install --quiet --upgrade pip 2>/dev/null \
    || true

# Install the wheel.
pip3 install --quiet --break-system-packages "/dist/$BASENAME" 2>/dev/null \
    || pip3 install --quiet "/dist/$BASENAME"

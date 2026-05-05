#!/usr/bin/env sh
# Stage-2 helper: install python3 + pip inside a clean distro
# container.  Used by both wheel and portable pytest passes; the
# portable variant invokes only this (since the binary is already
# on disk), while the wheel variant chains stage2_install_wheel.sh
# afterwards to also install the wheel.
#
# Reads:
#   $HOST_MIRROR   – optional ubuntu apt mirror URL from the runner host
#
# Idempotent.
set -e

if command -v apk >/dev/null 2>&1; then
    apk add --no-cache python3 py3-pip
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y --setopt=install_weak_deps=False \
        python3 python3-pip ca-certificates
elif command -v yum >/dev/null 2>&1; then
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
    if [ -n "${HOST_MIRROR:-}" ] && [ "$CONTAINER_ID" = "ubuntu" ]; then
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

# Old apt-pip on debian:10 / ubuntu:18.04 cannot read PEP 600
# (manylinux_2_17 / musllinux_1_1) tags.  Bootstrap a recent pip.
python3 -m pip install --quiet --upgrade pip --break-system-packages 2>/dev/null \
    || python3 -m pip install --quiet --upgrade pip 2>/dev/null \
    || true

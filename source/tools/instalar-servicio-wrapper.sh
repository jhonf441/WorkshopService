#!/bin/bash
# PROPOSAL (plan F1): the envelope that would replace Projects/instalar-servicio.sh. Same call: bash instalar-servicio.sh <version>
# It only finds the release zip and hands everything to tools/install_service.sh, which takes ALL the files from the zip
# (verified against dsf/RELEASE.json), refuses a busy machine, keeps leftovers in ~/sd-backup, checks api.ping and restores on failure.
# Keep the old script one version as instalar-servicio-old.sh. Install with the machine IDLE; add --dry-run first to see the plan:
#   bash instalar-servicio.sh <version> [--dry-run] [--force-busy] [--reinstall]     (FORCE=1 still means --reinstall)
set -e
VER=${1:?version}; shift || true
REPO="${WORKSHOP_REPO:-/c/Users/alejo/Projects/WorkshopService}"   # MAIN checkout: it holds the installer
TALLER="${TALLER_RELEASES:-/c/Users/alejo/Projects/TallerPlugins/releases/WorkshopService}"
NAME="WorkshopService-$VER-dwc3.6.zip"   # the Pi runs DWC/DSF 3.6
ZIP=""
for d in "$REPO/dist/release" "$TALLER"; do [ -f "$d/$NAME" ] && { ZIP="$d/$NAME"; break; }; done
[ -n "$ZIP" ] || { echo "missing $NAME in $REPO/dist/release or $TALLER (build it: python tools/build_release.py in WorkshopService)"; exit 1; }
[ "${FORCE:-0}" = 1 ] && set -- "$@" --reinstall
[ -n "${WORKSHOP_HOST:-}" ] && [ -n "${WORKSHOP_USER:-}" ] || { echo "set WORKSHOP_HOST and WORKSHOP_USER (the address and the login of the Pi)"; exit 1; }
exec bash "$REPO/tools/install_service.sh" --host "$WORKSHOP_HOST" --user "$WORKSHOP_USER" --version "$VER" --zip "$ZIP" "$@"

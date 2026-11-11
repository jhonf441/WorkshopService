#!/bin/sh
# Phase 0 of the SD layout plan (SD-LAYOUT.md F.1): a backup of the SD files of the workshop BEFORE anything moves.
#
# DELIVERED, NOT RUN BY ANYTHING: the owner (or whoever he says) runs it by hand on the Raspberry Pi, over SSH. It only READS the
# SD and only WRITES inside the backup folder it creates; it changes, moves and deletes nothing on the SD. Safe while a job runs
# except that the tar reads about 2-3 MB: prefer an idle moment anyway.
#
# What it saves, into  ~/sd-backup/layout-<date>/ :
#   sd-<date>.tar.gz          sys/  macros/  and  sys/workshop/{config,data,zones}  (they are inside sys/, so one tar of sys/ + macros/)
#   sha256sums.txt            sha256 of every file saved, relative to the SD root (check with:  cd <SD> && sha256sum -c <this file>)
#   inventory.txt             path, size, mtime of every file saved
#   MANIFEST.txt              date, host, SD root, counts, how to restore
# It does NOT take the config.snapshot of the native set into config-history (that one is a service operation: config.snapshot).
#
# Usage:   sh sd_backup.sh [SD_ROOT] [DEST_ROOT]
#   SD_ROOT    default /opt/dsf/sd         (the virtual SD, 0:/)
#   DEST_ROOT  default $HOME/sd-backup
# Dry run:  DRY_RUN=1 sh sd_backup.sh      (lists what it would save, writes nothing)
#
# Restore (by hand, never automatic): extract the tar into a scratch folder, compare with sha256sums.txt and copy back only the
# file you need:   mkdir /tmp/r && tar -xzf sd-<date>.tar.gz -C /tmp/r
set -eu

SD="${1:-/opt/dsf/sd}"
DEST_ROOT="${2:-$HOME/sd-backup}"
DATE="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST_ROOT/layout-$DATE"

[ -d "$SD/sys" ] || { echo "sd_backup: $SD/sys is not there: is this the right SD root?" >&2; exit 2; }
case "$OUT" in "$SD"/*) echo "sd_backup: the destination must be outside the SD ($SD)" >&2; exit 2;; esac

# the folders saved, relative to the SD root; macros/ may not exist on a fresh SD
LIST=""
for d in sys macros; do [ -d "$SD/$d" ] && LIST="$LIST $d"; done

FILES="$(cd "$SD" && find $LIST -type f | sort)"
COUNT="$(printf '%s\n' "$FILES" | grep -c . || true)"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "sd_backup (dry run): would save $COUNT files of:$LIST from $SD into $OUT"
  printf '%s\n' "$FILES" | head -20
  [ "$COUNT" -gt 20 ] && echo "... and $((COUNT - 20)) more"
  exit 0
fi

[ -e "$OUT" ] && { echo "sd_backup: $OUT already exists" >&2; exit 2; }
mkdir -p "$OUT"
chmod 700 "$OUT"   # config.g can hold the DWC password

(cd "$SD" && printf '%s\n' "$FILES" | xargs -d '\n' sha256sum) > "$OUT/sha256sums.txt"
(cd "$SD" && printf '%s\n' "$FILES" | xargs -d '\n' stat -c '%n %s %y') > "$OUT/inventory.txt"
(cd "$SD" && printf '%s\n' "$FILES" | tar -czf "$OUT/sd-$DATE.tar.gz" -T -)

# the tar must hold what the list says: compare the number of files and check its integrity
IN_TAR="$(tar -tzf "$OUT/sd-$DATE.tar.gz" | grep -vc '/$' || true)"
[ "$IN_TAR" = "$COUNT" ] || { echo "sd_backup: the tar holds $IN_TAR files and $COUNT were listed: do not trust it" >&2; exit 3; }

cat > "$OUT/MANIFEST.txt" <<EOF
SD layout backup (phase 0)
date:      $DATE
host:      $(hostname)
sd root:   $SD
folders:  $LIST
files:     $COUNT
tar:       sd-$DATE.tar.gz
checksums: sha256sums.txt   (cd $SD && sha256sum -c $OUT/sha256sums.txt)
restore:   by hand only: extract to a scratch folder, compare, copy back the one file you need
EOF
chmod 600 "$OUT"/*
echo "sd_backup: $COUNT files saved in $OUT"

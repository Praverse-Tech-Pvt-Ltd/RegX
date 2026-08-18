#!/bin/sh
# Restore the company runtime assets that are deliberately not in Git.
#
# See docs/COMPANY_RUNTIME_ASSETS.md. Three categories are excluded from
# version control and copied here on demand instead:
#
#   media/                                     runtime media (196 MB)
#   static/videos/                             dead marketing videos (82 MB)
#   AIDatabase/management/commands/*.xlsx      data-import spreadsheets (14 MB)
#
# The company source tree is READ-ONLY. This script only ever copies FROM it;
# it never writes to, renames in, or deletes from that directory.
set -eu

SRC="${1:-../Booking final/booking-demo-final}"
# `CDPATH= cd` is deliberate: it empties CDPATH for this one command so a
# user's CDPATH cannot silently redirect the cd somewhere else. ShellCheck
# reads the trailing `=` as a typo; it is not.
# shellcheck disable=SC1007
DEST="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)/company_site"

if [ ! -d "$SRC" ]; then
    echo "error: company source not found at: $SRC" >&2
    echo "usage: $0 [path-to-booking-demo-final]" >&2
    exit 1
fi

if [ ! -f "$SRC/manage.py" ] || [ ! -d "$SRC/RAAI" ]; then
    echo "error: $SRC does not look like booking-demo-final (no manage.py/RAAI)" >&2
    exit 1
fi

echo "source (read-only): $SRC"
echo "destination:        $DEST"
echo

copy_tree() {
    from="$SRC/$1"
    to="$DEST/$1"
    if [ ! -d "$from" ]; then
        echo "skip  $1 (not present in source)"
        return
    fi
    echo "copy  $1"
    mkdir -p "$to"
    # -a preserves timestamps so repeat runs are cheap; no --delete, so
    # anything the running app has written locally is left alone.
    cp -a "$from/." "$to/"
}

copy_tree "media"
copy_tree "static/videos"

echo "copy  AIDatabase/management/commands/*.xlsx"
mkdir -p "$DEST/AIDatabase/management/commands"
found=0
for f in "$SRC"/AIDatabase/management/commands/*.xlsx; do
    [ -e "$f" ] || continue
    cp -a "$f" "$DEST/AIDatabase/management/commands/"
    found=$((found + 1))
done
echo "      $found spreadsheet(s)"

echo
echo "done. Company source left untouched."

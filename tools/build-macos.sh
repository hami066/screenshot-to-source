#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

python_bin="${1:-python3.12}"
arch="$("$python_bin" -c 'import platform; print(platform.machine())')"
case "$arch" in
  arm64|x86_64) ;;
  *) echo "Unsupported macOS architecture: $arch" >&2; exit 1 ;;
esac
build_root="$(mktemp -d "${TMPDIR:-/tmp}/screenshot-to-source.XXXXXXXX")"
trap 'rm -rf -- "$build_root"' EXIT
mkdir -p dist
stage="$build_root/Screenshot to Source"
mkdir "$stage"
app="$stage/Screenshot to Source.app"
archive="$PWD/dist/screenshot-to-source-macos-$arch.zip"

"$python_bin" -c 'import sys; from desktop_theme import icon; icon("crop", "#2158a8", 1024).save(sys.argv[1])' \
  "$build_root/icon.icns"
"$python_bin" -m PyInstaller --noconfirm --onedir --windowed --noupx \
  --target-arch "$arch" --name "Screenshot to Source" \
  --osx-bundle-identifier io.github.hami066.screenshot-to-source \
  --icon "$build_root/icon.icns" --add-data assets/frosted-lens.png:assets --add-data demo:demo \
  --collect-all tkinterdnd2 --collect-all pypdfium2_raw --collect-data pypdfium2 \
  --distpath "$stage" --workpath "$build_root/build" --specpath "$build_root" app.py

rm -rf -- "$stage/Screenshot to Source"
"$python_bin" -c 'import sys; from pathlib import Path; from tools.make_release import copy_notices; copy_notices(Path(sys.argv[1]))' "$stage"
/usr/bin/codesign --verify --deep --strict "$app"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$stage" "$archive"
mkdir "$build_root/extracted"
/usr/bin/ditto -x -k "$archive" "$build_root/extracted"
extracted="$build_root/extracted/Screenshot to Source/Screenshot to Source.app"
/usr/bin/codesign --verify --deep --strict "$extracted"
"$extracted/Contents/MacOS/Screenshot to Source" --self-test
(cd dist && shasum -a 256 "$(basename "$archive")" > "SHA256SUMS-macos-$arch.txt")
printf '%s\n' "$archive"

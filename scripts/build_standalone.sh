#!/bin/sh
# Build the standalone spsync command-line tool for Apple silicon Macs.
#
# The build needs uv and the Xcode Command Line Tools. The result needs neither Python nor uv:
#
#   dist/spsync-macos-arm64/spsync       the executable; it loads the other files in its folder
#   dist/spsync-macos-arm64.tar.gz       the folder, packed for download
#
# spsync supports only Apple silicon. Nuitka compiles for the architecture of the Python that runs
# it, so the script stops on a Mac that is not arm64.
set -eu

repo="$(cd "$(dirname "$0")/.." && pwd)"
arch="$(uname -m)"
if [ "$arch" != "arm64" ]; then
  echo "build_standalone.sh builds for Apple silicon (arm64) only; this Mac is $arch." >&2
  exit 1
fi
name="spsync-macos-$arch"
work="$repo/build/$arch"
dist="$repo/dist"

rm -rf "$work" "$dist/$name" "$dist/$name.tar.gz"
mkdir -p "$work" "$dist"

# A separate environment keeps the project .venv and its dev tools unchanged.
UV_PROJECT_ENVIRONMENT="$work/venv" uv sync --project "$repo" --locked --no-dev --group build --no-editable --quiet

# Nuitka downloads an x86_64 ccache, which fails on Apple silicon; a clean build does not need a cache.
"$work/venv/bin/python" -m nuitka \
  --mode=standalone \
  --assume-yes-for-downloads \
  --disable-ccache \
  --no-progressbar \
  --output-dir="$work" \
  --output-folder-name="$name" \
  --output-filename=spsync \
  "$repo/scripts/standalone_entry.py"

mv "$work/$name.dist" "$dist/$name"
"$dist/$name/spsync" --help >/dev/null
tar -C "$dist" -czf "$dist/$name.tar.gz" "$name"
echo "Built $dist/$name.tar.gz"

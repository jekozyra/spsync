#!/bin/sh
# Build the standalone spsync command-line tool for the architecture of this Mac.
#
# The build needs uv and the Xcode Command Line Tools. The result needs neither Python nor uv:
#
#   dist/spsync-macos-<arch>/spsync      the executable; it loads the other files in its folder
#   dist/spsync-macos-<arch>.tar.gz      the folder, packed for download
#
# Nuitka compiles for the architecture of the Python that runs it. Build arm64 on an Apple silicon
# Mac and x86_64 on an Intel Mac.
set -eu

repo="$(cd "$(dirname "$0")/.." && pwd)"
arch="$(uname -m)"
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

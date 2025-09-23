#!/usr/bin/env zsh

set -eu

PREFIX="${1:-/usr/local}"
ZSH_CUSTOM="${ZSH_CUSTOM:-$PREFIX/share/zshcustom}"

local build="$PWD/build/auto"
local target="$PREFIX/bin/auto"
local compdir="$ZSH_CUSTOM/zsh-auto-script"

echo "Building $build..."
make
echo "Installing $build to $target..."
install -m755 "$build" "$target"
echo "Installing $PWD/zsh-auto-script to $compdir..."
[[ -d "$compdir" ]] && rm -rf "$compdir"
cp -r zsh-auto-script "$compdir"
echo "Done."


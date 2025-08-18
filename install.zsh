#!/usr/bin/env zsh

set -eu

PREFIX="${PREFIX:-/usr/local}"
ZSH_CUSTOM="${ZSH_CUSTOM:-$PREFIX/share/zshcustom}"

local script="$PREFIX/bin/auto"
local compdir="$ZSH_CUSTOM/zsh-auto-script"

echo "Installing $PWD/auto to $script..."
install -m755 auto "$script"
echo "Installing $PWD/zsh-auto-script to $compdir..."
[[ -d "$compdir" ]] && rm -rf "$compdir"
cp -r zsh-auto-script "$compdir"
echo "Done."


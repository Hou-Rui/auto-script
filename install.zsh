#!/usr/bin/env zsh

PREFIX="${PREFIX:-/usr/local}"
ZSH_CUSTOM="${ZSH_CUSTOM:-$PREFIX/share/zshcustom}"

local script="$PREFIX/bin/auto"
local compdir="$ZSH_CUSTOM/zsh-auto-script"

setopt verbose
install -m755 auto "$script"
[[ -d "$compdir" ]] && rm -rf "$compdir"
cp -r zsh-auto-script "$compdir"

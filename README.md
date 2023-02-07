# Auto Script

## Overview

A single shell script to manage Arch Linux repositories, AUR, and flatpak. Arch Linux / Manjaro supported.

## Features

- Install, search, or uninstall package from system repositories, AUR, or Flatpak.
- Update system packages, AUR packages, package file database index, Flatpak packages, custom ZSH plugins, custom Neovim plugins at the same time.
- Autoremove unused dependecies and cache.
- Support command completion in zsh.

## Dependency

- GNU Bash (Latest)
- Zsh and Oh My Zsh
- Flatpak
- Neovim (With Vimplug and COC, can be customized)
- An AUR helper (`yay` and `paru` can be auto-detected)
- A privilege levitation tool (`sudo` and `doas` can be auto-detected)

## Installation

- Install `auto` to your PATH (e.g. `$HOME/.local/bin/`)
- Install `custom-completions` as one of your custom Zsh plugins (e.g. if you are using Oh My Zsh, copy the directory to `$ZSH_CUSTOM/plugins/`)


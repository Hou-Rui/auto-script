# Auto Script

## Overview

A single shell script to manage Arch Linux repositories, AUR, and flatpak. Arch Linux / Manjaro supported.

## Features

- Install, search, list, or uninstall package from system repositories, AUR, or Flatpak.
- Update system packages, AUR packages, package file database index, Flatpak packages, custom ZSH plugins, custom Neovim plugins at the same time.
- Autoremove unused dependecies and cache.
- Query for local or remote package information.
- Query ownership of a certain file.
- Support command completion in zsh.

## Usage

```
Usage: auto <command> [options] [packages]

Available commands:
  install:    install package(s) (default to native)
  remove:     remove package(s) (default to native)
  search:     search package(s) in remote repositories (default to native and flatpak)
  update:     update package(s) (default to native, flatpak, zsh, vim)
  autoremove: remove unused packages (default to native and flatpak)
  clean:      clean cache and unused packages (default to native and flatpak)
  info:       display info for a package (default to native)
  which:      query which package owns an executable (default to native)
  list:       list installed packages (default to native and flatpak)
  help:       display this message

Available options:
  -n, --native:     apply operation on native packages
  -f, --flatpak:    apply operation on flatpak packages
  -v, --vim:        apply operation on vim packages
  -z, --zsh:        apply operation on zsh packages
  -y, --noconfirm:  skip all confirmation
  -r, --regex:      (only for search) use regular expression in searching terms
  -w, --remote:     (only for info and which) display or query remote info
  -e <src>,
  --exclude <src>:  exclude source when performing operation
```

## Dependencies

- GNU Bash (Latest)
- Zsh and Oh My Zsh
- Flatpak
- Neovim (With Vimplug and COC, can be customized)
- An AUR helper (`yay` and `paru` can be auto-detected)
- A privilege levitation tool (`sudo` and `doas` can be auto-detected)

## Installation

- Install `auto` to your PATH (e.g. `$HOME/.local/bin/`)
- Install `custom-completions` as one of your custom Zsh plugins (e.g. if you are using Oh My Zsh, copy the directory to `$ZSH_CUSTOM/plugins/`)


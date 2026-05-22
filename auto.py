#!/usr/bin/env python3

from __future__ import annotations

import abc
import sys
import os
import re
import glob
import math
import shutil
import subprocess
import threading
import argparse
from collections.abc import Callable
from dataclasses import dataclass
from os.path import basename
from typing import ClassVar, NoReturn


@dataclass
class Options:
    yes: bool = False
    force: bool = False
    remote: bool = False

    def flag_yes_native(self) -> list[str]:
        return ["--noconfirm"] if self.yes else []

    def flag_yes_flatpak(self) -> list[str]:
        return ["--assumeyes"] if self.yes else []

    def flag_force_native(self) -> list[str]:
        return ["--overwrite", "*"] if self.force else []

    def flag_force_flatpak(self) -> list[str]:
        return ["--reinstall"] if self.force else []


OPT = Options()
ARGS: list[str] = []
AUR_HELPER: str
SUDO: str


class AutoError(Exception):
    _HINT = "type 'auto help' to see usage."

    def __str__(self) -> str:
        return f"{super().__str__()}.\n{self._HINT}"


class SubcmdError(AutoError):
    """Error raised within a subcommand context; prefixes the message with the subcommand name."""

    def __init__(self, subcmd: str, msg: str) -> None:
        Exception.__init__(self, f"in {subcmd}: {msg}")


class Sources:
    ALL = ("native", "flatpak", "zsh", "vim")

    def __init__(self) -> None:
        self._active: set[str] = set()
        self._excluded: set[str] = set()
        self._context: str = ""

    def __len__(self) -> int:
        return len(self._active)

    def __bool__(self) -> bool:
        return bool(self._active)

    def __str__(self) -> str:
        return ", ".join(s for s in self.ALL if s in self._active)

    def set_context(self, name: str) -> None:
        self._context = name

    def _error(self, msg: str) -> SubcmdError:
        return SubcmdError(self._context, msg)

    def enable(self, src: str) -> None:
        self._active.add(src)

    def exclude(self, src: str) -> None:
        if src not in self.ALL:
            raise self._error(f"unknown source {src}")
        self._excluded.add(src)

    def require(
        self,
        defaults: list[str] | None = None,
        exclusive: bool = False,
        pkgs: bool = False,
    ) -> None:
        if not self and defaults:
            self._active = set(defaults)
        if exclusive and len(self) != 1:
            raise self._error(f"multiple sources {self} specified")
        if pkgs and not ARGS:
            raise self._error("no packages specified")

    def handle(self, **handlers: Callable[[list[str]], None]) -> None:
        for src in self.ALL:
            if src not in self._active:
                continue
            if src not in handlers:
                raise self._error(f"source(s) {self} not applicable")
            if src not in self._excluded:
                handlers[src](ARGS)
            self._active.discard(src)
        if self._active:
            raise self._error(f"source(s) {self} not applicable")


SOURCES = Sources()


def run(*args: str) -> None:
    result = subprocess.run(list(args))
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, list(args))


def capture(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, check=True).stdout


def pkgs_str() -> str:
    return ", ".join(ARGS)


def first_of(desc: str, *cmds: str) -> str:
    for cmd in cmds:
        if shutil.which(cmd):
            return cmd
    raise AutoError(f"no {desc} found")


def colored(text: str, style: str) -> str:
    codes = {
        "bold": "\033[1m",
        "bold blue": "\033[1;34m",
        "bold green": "\033[1;32m",
        "bold red": "\033[1;31m",
        "cyan": "\033[36m",
        "dark white": "\033[2;37m",
    }
    return f"{codes.get(style, '')}{text}\033[0m"


def title(fmt: str, *args: object) -> None:
    text = fmt % args if args else fmt
    cols = shutil.get_terminal_size().columns
    pad = (cols - len(text) - 2) / 2
    s1 = colored("⎼" * max(0, max(1, math.floor(pad)) - 1), "dark white")
    s2 = colored("⎼" * max(0, max(1, math.ceil(pad)) - 1), "dark white")
    print(f" {s1} {colored(text, 'bold')} {s2} ")


def subtitle(fmt: str, *args: object) -> None:
    text = fmt % args if args else fmt
    print(colored(":: ", "bold blue") + colored(text, "bold"))


class FlatpakPkg:
    def __init__(self, cols: list[str], values: list[str]) -> None:
        self._data = dict(zip(cols, values))

    def __getitem__(self, key: str) -> str:
        return self._data.get(key, "")

    def match(self, *pkgs: str) -> bool:
        for pkg in pkgs:
            pattern = re.compile(pkg, re.IGNORECASE)
            for key in ("name", "application", "description"):
                if pattern.search(self._data.get(key, "")):
                    return True
        return False


class FlatpakList:
    def __init__(self, items: list[FlatpakPkg] | None = None) -> None:
        self.items = items if items is not None else []

    @classmethod
    def _build(
        cls, cmds: list[str], extra_cols: list[str], filter_pkgs: list[str]
    ) -> FlatpakList:
        cols = ["name", "description", "application", "version", "branch"] + extra_cols
        proc = subprocess.Popen(
            ["flatpak"] + cmds + [f"--columns={','.join(cols)}"],
            stdout=subprocess.PIPE,
            text=True,
        )
        if proc.stdout is None:
            proc.wait()
            return cls()
        result = cls()
        for line in proc.stdout:
            line = line.rstrip("\n")
            if line == "No matches found":
                break
            pkg = FlatpakPkg(cols, line.split("\t"))
            if filter_pkgs and not pkg.match(*filter_pkgs):
                continue
            result.items.append(pkg)
        proc.wait()
        return result

    def reversed(self) -> FlatpakList:
        return FlatpakList(list(reversed(self.items)))

    @classmethod
    def new_list(cls, *pkgs: str) -> FlatpakList:
        return cls._build(["list"], ["origin", "ref"], list(pkgs))

    @classmethod
    def new_search(cls, *pkgs: str) -> FlatpakList:
        return cls._build(["search"] + list(pkgs), ["remotes"], []).reversed()

    def refs(self) -> list[str]:
        return [item["ref"] for item in self.items]

    def print(self) -> None:
        for f in self.items:
            remote_str = f["remotes"] or f["origin"]
            print(
                f"{colored(remote_str, 'bold blue')}/{colored(f['application'], 'bold')} "
                f"{colored(f['branch'], 'bold green')} {colored(f['version'], 'cyan')}"
            )
            print(f"    {f['name']}: {f['description']}")


def github_search(topic: str, *pkgs: str) -> None:
    gh = first_of("GitHub CLI", "gh")
    env = os.environ.copy()
    env["GH_PAGER"] = ""
    subprocess.run([gh, "search", "repos", f"--topic={topic}", *pkgs], env=env)


def update_keyring_pkgs() -> None:
    needed_pkgs = []
    for name in ("archlinux", "manjaro", "chaotic", "archlinuxcn"):
        pkg = f"{name}-keyring"
        if not glob.glob(f"/var/lib/pacman/local/{pkg}*"):
            continue
        try:
            run("pacman", "-Qu", pkg)
        except subprocess.CalledProcessError:
            continue
        needed_pkgs.append(pkg)
    run(AUR_HELPER, "-S", "--needed", *needed_pkgs)


def _git_pull_parallel(paths: list[str]) -> None:
    threads: list[threading.Thread] = []
    for path in paths:
        if not os.path.isdir(os.path.join(path, ".git")):
            continue
        subtitle("Updating plugin %s...", basename(path))
        t = threading.Thread(
            target=lambda p=path: subprocess.run(f"cd {p}; git pull", shell=True)
        )
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


def update_zsh_plugins() -> None:
    home = os.environ.get("HOME", "")
    zplug_path = os.path.join(home, ".zplug")
    omz_path = os.path.join(home, ".oh-my-zsh")
    plugin_path = os.environ.get("ZPLUGINDIR", "")

    if os.path.isdir(zplug_path):
        title("Updating ZPlug plugins...")
        run("zsh", "-ic", "zplug update")
    elif os.path.isdir(omz_path):
        title("Updating Oh-My-Zsh plugins...")
        run("zsh", "-c", f"{omz_path}/tools/upgrade.sh")
        custom = os.path.join(omz_path, "custom")
        paths = glob.glob(f"{custom}/plugins/*") + glob.glob(f"{custom}/themes/*")
        _git_pull_parallel(paths)
    elif plugin_path and os.path.isdir(plugin_path):
        title("Updating ZSH plugins...")
        _git_pull_parallel(glob.glob(f"{plugin_path}/*"))


class Subcommand(abc.ABC):
    name: ClassVar[str]
    _registry: ClassVar[dict[str, type[Subcommand]]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "name"):
            Subcommand._registry[cls.name] = cls

    @classmethod
    def dispatch(cls, name: str) -> Subcommand:
        subcls = cls._registry.get(name)
        if subcls is None:
            raise AutoError(f"unknown subcommand '{name}'")
        return subcls()

    @abc.abstractmethod
    def run(self) -> None: ...


class HelpCmd(Subcommand):
    name = "help"

    def run(self) -> NoReturn:
        print("""Usage: auto <command> [options] [packages]

    Available commands:
    install:    install package(s) (default to native)
    remove:     remove package(s) (default to native)
    search:     search package(s) in remote repositories (default to native and flatpak)
    update:     update package(s) (default to native, flatpak, zsh, vim)
    clean:      clean cache and unused packages (default to native and flatpak)
    info:       display info for a package (default to native)
    files:      list installed files for a package (default to native)
    which:      query which package owns an executable (default to native)
    list:       list installed packages (default to native and flatpak)
    help:       display this message

    Available options:
    -n, --native:     apply operation on native packages
    -f, --flatpak:    apply operation on flatpak packages
    -v, --vim:        apply operation on vim packages
    -z, --zsh:        apply operation on zsh packages
    -e, --exclude:    exclude a specific source
    -y, --yes:        skip all confirmation
    -w, --remote:     (only for info and which) display or query remote info
    -x, --force:      (only for install) force options
    -h, --help:       display this message
  """)
        sys.exit(0)


class InfoCmd(Subcommand):
    name = "info"

    def run(self) -> None:
        SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title("Querying information on native package(s) %s...", pkgs_str())
            query = "-Sii" if OPT.remote else "-Qii"
            remote = "remote" if OPT.remote else "local"
            try:
                run(AUR_HELPER, query, *pkgs)
            except subprocess.CalledProcessError:
                raise AutoError(
                    f"no information found for {remote} package(s) {pkgs_str()}"
                )

        def handle_flatpak(pkgs: list[str]) -> None:
            remote = "remote" if OPT.remote else "local"
            title(
                "Querying information on %s Flatpak package(s) %s...",
                remote,
                pkgs_str(),
            )
            if OPT.remote:
                pkglist = FlatpakList.new_search(*pkgs).reversed()
            else:
                pkglist = FlatpakList.new_list(*pkgs)
            if not pkglist.items:
                raise AutoError(
                    f"No information found for {remote} Flatpak package {pkgs_str()}"
                )
            for pkg in pkglist.items:
                appid = pkg["application"]
                subtitle("Querying %s information for %s...", remote, appid)
                if OPT.remote:
                    run("flatpak", "remote-info", pkg["remotes"], appid)
                else:
                    run("flatpak", "info", appid)

        SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


class FilesCmd(Subcommand):
    name = "files"

    def run(self) -> None:
        SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title("Querying installed files of native package(s) %s...", pkgs_str())
            if OPT.remote:
                run("pkgfile", "--list", *pkgs)
            else:
                run(AUR_HELPER, "-Ql", *pkgs)

        def handle_flatpak(pkgs: list[str]) -> None:
            title("Querying installed files of Flatpak package(s) %s...", pkgs_str())
            for ref in FlatpakList.new_list(*pkgs).refs():
                path = capture("flatpak", "info", "-l", ref).strip()
                run("tree", path)

        SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


class CleanCmd(Subcommand):
    name = "clean"

    def run(self) -> None:
        SOURCES.require(defaults=["native", "flatpak"])

        def handle_native(_: list[str]) -> None:
            title("Cleaning native packages...")
            subtitle("Removing unneeded packages...")
            try:
                orphans = [p for p in capture(AUR_HELPER, "-Qdtq").split("\n") if p]
                run(AUR_HELPER, "-Rscn", *orphans, *OPT.flag_yes_native())
            except subprocess.CalledProcessError:
                print("Nothing unused to uninstall")
            downloads = [
                d
                for d in glob.glob("/var/cache/pacman/pkg/download*")
                if os.path.isdir(d)
            ]
            if downloads:
                subtitle("Removing pacman download remains...")
                for d in downloads:
                    run(SUDO, "rm", "-r", d)
            subtitle("Cleaning cache...")
            subprocess.run(f"yes | {AUR_HELPER} -Sccd", shell=True)
            print("\nDone cleaning.")

        def handle_flatpak(_: list[str]) -> None:
            title("Cleaning flatpak packages...")
            run(
                "flatpak",
                "uninstall",
                "--unused",
                "--delete-data",
                *OPT.flag_yes_flatpak(),
            )

        SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


class SearchCmd(Subcommand):
    name = "search"

    def run(self) -> None:
        SOURCES.require(defaults=["native", "flatpak"], pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title("Searching native package(s) %s...", pkgs_str())
            run(AUR_HELPER, "-Ss", *pkgs)

        def handle_flatpak(pkgs: list[str]) -> None:
            title("Searching Flatpak package(s) %s...", pkgs_str())
            try:
                FlatpakList.new_search(*pkgs).print()
            except Exception:
                pass

        def handle_vim(pkgs: list[str]) -> None:
            title("Searching Vim plugins(s) %s...", pkgs_str())
            github_search("neovim,nvim,vim", *pkgs)

        def handle_zsh(pkgs: list[str]) -> None:
            title("Searching Zsh plugins(s) %s...", pkgs_str())
            github_search("zsh", *pkgs)

        SOURCES.handle(
            native=handle_native, flatpak=handle_flatpak, vim=handle_vim, zsh=handle_zsh
        )


class InstallCmd(Subcommand):
    name = "install"

    def run(self) -> None:
        SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title("Installing native package(s) %s...", pkgs_str())
            run(
                AUR_HELPER,
                "-S",
                *pkgs,
                *OPT.flag_yes_native(),
                *OPT.flag_force_native(),
            )

        def handle_flatpak(pkgs: list[str]) -> None:
            title("Installing flatpak package(s) %s...", pkgs_str())
            run(
                "flatpak",
                "install",
                *pkgs,
                *OPT.flag_yes_flatpak(),
                *OPT.flag_force_flatpak(),
            )

        SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


class RemoveCmd(Subcommand):
    name = "remove"

    def run(self) -> None:
        SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title("Removing native package(s) %s...", pkgs_str())
            run(AUR_HELPER, "-Rscn", *pkgs)

        def handle_flatpak(pkgs: list[str]) -> None:
            title("Removing Flatpak package(s) %s...", pkgs_str())
            run("flatpak", "uninstall", "--delete-data", *pkgs)

        SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


class ListCmd(Subcommand):
    name = "list"

    def run(self) -> None:
        SOURCES.require(defaults=["native", "flatpak"])

        def handle_native(pkgs: list[str]) -> None:
            title("Listing native package(s) %s...", pkgs_str())
            try:
                run(AUR_HELPER, "-Qs", *pkgs)
            except subprocess.CalledProcessError:
                raise AutoError(f"No native packages found with keyword {pkgs_str()}")

        def handle_flatpak(pkgs: list[str]) -> None:
            title("Listing Flatpak package(s) %s...", pkgs_str())
            pkglist = FlatpakList.new_list(*pkgs)
            if not pkglist.items:
                raise AutoError(f"No Flatpak packages found with keyword {pkgs_str()}")
            pkglist.print()

        SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


class WhichCmd(Subcommand):
    name = "which"

    def run(self) -> None:
        SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title("Querying which package provides %s...", pkgs_str())
            cmd = ["pkgfile", "-v"] if OPT.remote else [AUR_HELPER, "-Qo"]
            run(*cmd, *pkgs)

        SOURCES.handle(native=handle_native)


class UpdateCmd(Subcommand):
    name = "update"

    def run(self) -> None:
        SOURCES.require(defaults=["native"] if ARGS else list(Sources.ALL))

        def handle_native(pkgs: list[str]) -> None:
            title("Updating native plugin(s) %s...", pkgs_str())
            update_keyring_pkgs()
            flags = ["-S", "--needed", *pkgs] if pkgs else ["-Syu", "--devel"]
            run(AUR_HELPER, *flags, *OPT.flag_yes_native())
            run(SUDO, "pkgfile", "-u")

        def handle_flatpak(pkgs: list[str]) -> None:
            title("Updating Flatpak plugin(s) %s...", pkgs_str())
            run(
                "flatpak",
                "update",
                *OPT.flag_yes_flatpak(),
                *FlatpakList.new_list(*pkgs).refs(),
            )

        def handle_zsh(_: list[str]) -> None:
            if shutil.which("zsh"):
                update_zsh_plugins()

        def handle_vim(_: list[str]) -> None:
            if not shutil.which("nvim"):
                return
            title("Updating Vim plugins...")
            run("nvim", "+Lazy! sync", "+qa", "--headless")
            print("Done.")

        SOURCES.handle(
            native=handle_native, flatpak=handle_flatpak, zsh=handle_zsh, vim=handle_vim
        )


def parse_args() -> str:
    global ARGS

    if len(sys.argv) < 2:
        raise AutoError("missing subcommand")

    subcmd_name = sys.argv[1]

    if subcmd_name in ("-h", "--help"):
        HelpCmd().run()

    SOURCES.set_context(subcmd_name)

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-n", "--native", action="store_true")
    parser.add_argument("-f", "--flatpak", action="store_true")
    parser.add_argument("-z", "--zsh", action="store_true")
    parser.add_argument("-v", "--vim", action="store_true")
    parser.add_argument("-e", "--exclude", action="append", default=[])
    parser.add_argument("-w", "--remote", action="store_true")
    parser.add_argument("-x", "--force", action="store_true")
    parser.add_argument("-y", "--yes", action="store_true")
    parser.add_argument("-h", "--help", action="store_true")

    parsed, remaining = parser.parse_known_args(sys.argv[2:])

    for src in Sources.ALL:
        if getattr(parsed, src):
            SOURCES.enable(src)

    for exc in parsed.exclude:
        SOURCES.exclude(exc)

    OPT.remote = parsed.remote
    OPT.force = parsed.force
    OPT.yes = parsed.yes

    if parsed.help:
        HelpCmd().run()

    ARGS = remaining
    return subcmd_name


def main() -> None:
    global AUR_HELPER, SUDO

    AUR_HELPER = first_of("AUR helpers", "yay", "paru", "pacman")
    SUDO = first_of("sudo utilities", "sudo", "doas", "pkexec")

    subcmd_name = parse_args()
    Subcommand.dispatch(subcmd_name).run()


if __name__ == "__main__":
    try:
        main()
    except (AutoError, subprocess.CalledProcessError) as e:
        msg = str(e).rstrip("\n")
        print(f"\033[1;31merror:\033[0m {msg}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

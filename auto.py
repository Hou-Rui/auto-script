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
from dataclasses import dataclass, field
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

    def __init__(self, context: str = "") -> None:
        self._active: set[str] = set()
        self._excluded: set[str] = set()
        self._context = context

    def __len__(self) -> int:
        return len(self._active)

    def __bool__(self) -> bool:
        return bool(self._active)

    def __str__(self) -> str:
        return ", ".join(s for s in self.ALL if s in self._active)

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
        args: list[str],
        defaults: list[str] | None = None,
        exclusive: bool = False,
        pkgs: bool = False,
    ) -> None:
        if not self and defaults:
            self._active = set(defaults)
        if exclusive and len(self) != 1:
            raise self._error(f"multiple sources {self} specified")
        if pkgs and not args:
            raise self._error("no packages specified")

    def handle(
        self, args: list[str], **handlers: Callable[[list[str]], None]
    ) -> None:
        for src in self.ALL:
            if src not in self._active:
                continue
            if src not in handlers:
                raise self._error(f"source(s) {self} not applicable")
            if src not in self._excluded:
                handlers[src](args)
            self._active.discard(src)
        if self._active:
            raise self._error(f"source(s) {self} not applicable")


@dataclass
class Context:
    """Per-invocation state: parsed options, package arguments, selected sources
    and the resolved external tools. Created once during parsing and passed to
    the dispatched subcommand."""

    opts: Options = field(default_factory=Options)
    args: list[str] = field(default_factory=list)
    sources: Sources = field(default_factory=Sources)
    aur_helper: str = ""
    sudo: str = ""

    def pkgs_str(self) -> str:
        return ", ".join(self.args)


def run(*args: str) -> None:
    result = subprocess.run(list(args))
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, list(args))


def capture(*args: str) -> str:
    return subprocess.run(list(args), capture_output=True, text=True, check=True).stdout


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


def title(text: str) -> None:
    cols = shutil.get_terminal_size().columns
    pad = (cols - len(text) - 2) / 2
    s1 = colored("⎼" * max(0, max(1, math.floor(pad)) - 1), "dark white")
    s2 = colored("⎼" * max(0, max(1, math.ceil(pad)) - 1), "dark white")
    print(f" {s1} {colored(text, 'bold')} {s2} ")


def subtitle(text: str) -> None:
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


COMMANDS = [
    ("install", "install package(s) (default to native)"),
    ("remove", "remove package(s) (default to native)"),
    ("search", "search package(s) in remote repositories (default to native and flatpak)"),
    ("update", "update package(s) (default to native, flatpak, zsh, vim)"),
    ("clean", "clean cache and unused packages (default to native and flatpak)"),
    ("info", "display info for a package (default to native)"),
    ("files", "list installed files for a package (default to native)"),
    ("which", "query which package owns an executable (default to native)"),
    ("list", "list installed packages (default to native and flatpak)"),
    ("help", "display this message"),
]


# (short, long, help, arg_choices). arg_choices is None for a plain flag, or the
# list of values the option expects (making it a value-taking option).
OPTIONS = [
    ("-n", "--native", "apply operation on native packages", None),
    ("-f", "--flatpak", "apply operation on flatpak packages", None),
    ("-v", "--vim", "apply operation on vim packages", None),
    ("-z", "--zsh", "apply operation on zsh packages", None),
    ("-e", "--exclude", "exclude a specific source", list(Sources.ALL)),
    ("-y", "--yes", "skip all confirmation", None),
    ("-w", "--remote", "(only for info and which) display or query remote info", None),
    ("-x", "--force", "(only for install) force options", None),
    ("-h", "--help", "display this message", None),
]


def _add_options(parser: argparse.ArgumentParser) -> None:
    for short, long, help_text, choices in OPTIONS:
        if choices is None:
            parser.add_argument(short, long, action="store_true", help=help_text)
        else:
            parser.add_argument(short, long, action="append", default=[], help=help_text)


def print_completions(kind: str) -> NoReturn:
    """Emit machine-readable completion metadata consumed by the zsh `_auto`
    completion so it never drifts from the definitions above."""
    if kind == "commands":
        for name, desc in COMMANDS:
            print(f"{name}:{desc}")
    elif kind == "options":
        for short, long, help_text, choices in OPTIONS:
            arg = " ".join(choices) if choices else ""
            print(f"{short} {long}\t{help_text}\t{arg}")
    sys.exit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="auto", add_help=False)
    _add_options(parser)
    return parser


def print_help() -> NoReturn:
    parser = argparse.ArgumentParser(
        prog="auto",
        usage="auto <command> [options] [packages]",
        add_help=False,
    )
    commands = parser.add_argument_group("commands")
    for name, desc in COMMANDS:
        commands.add_argument(name, nargs="?", help=desc)
    _add_options(parser)
    parser.print_help()
    sys.exit(0)


class Subcommand(abc.ABC):
    name: ClassVar[str]
    _registry: ClassVar[dict[str, type[Subcommand]]] = {}

    def __init__(self, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.opts = ctx.opts
        self.args = ctx.args
        self.sources = ctx.sources
        self.aur_helper = ctx.aur_helper
        self.sudo = ctx.sudo

    def pkgs_str(self) -> str:
        return self.ctx.pkgs_str()

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "name"):
            Subcommand._registry[cls.name] = cls

    @classmethod
    def dispatch(cls, name: str, ctx: Context) -> Subcommand:
        subcls = cls._registry.get(name)
        if subcls is None:
            raise AutoError(f"unknown subcommand '{name}'")
        return subcls(ctx)

    @abc.abstractmethod
    def run(self) -> None: ...


class HelpCmd(Subcommand):
    name = "help"

    def run(self) -> NoReturn:
        print_help()


class InfoCmd(Subcommand):
    name = "info"

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title(f"Querying information on native package(s) {self.pkgs_str()}...")
            query = "-Sii" if self.opts.remote else "-Qii"
            remote = "remote" if self.opts.remote else "local"
            try:
                run(self.aur_helper, query, *pkgs)
            except subprocess.CalledProcessError:
                raise AutoError(
                    f"no information found for {remote} package(s) {self.pkgs_str()}"
                )

        def handle_flatpak(pkgs: list[str]) -> None:
            remote = "remote" if self.opts.remote else "local"
            title(
                f"Querying information on {remote} Flatpak package(s) {self.pkgs_str()}..."
            )
            if self.opts.remote:
                pkglist = FlatpakList.new_search(*pkgs).reversed()
            else:
                pkglist = FlatpakList.new_list(*pkgs)
            if not pkglist.items:
                raise AutoError(
                    f"No information found for {remote} Flatpak package {self.pkgs_str()}"
                )
            for pkg in pkglist.items:
                appid = pkg["application"]
                subtitle(f"Querying {remote} information for {appid}...")
                if self.opts.remote:
                    run("flatpak", "remote-info", pkg["remotes"], appid)
                else:
                    run("flatpak", "info", appid)

        self.sources.handle(self.args, native=handle_native, flatpak=handle_flatpak)


class FilesCmd(Subcommand):
    name = "files"

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title(f"Querying installed files of native package(s) {self.pkgs_str()}...")
            if self.opts.remote and shutil.which("pkgfile"):
                run("pkgfile", "--list", *pkgs)
            else:
                run(self.aur_helper, "-Ql", *pkgs)

        def handle_flatpak(pkgs: list[str]) -> None:
            title(f"Querying installed files of Flatpak package(s) {self.pkgs_str()}...")
            for ref in FlatpakList.new_list(*pkgs).refs():
                path = capture("flatpak", "info", "-l", ref).strip()
                run("tree", path)

        self.sources.handle(self.args, native=handle_native, flatpak=handle_flatpak)


class CleanCmd(Subcommand):
    name = "clean"

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native", "flatpak"])

        def handle_native(_: list[str]) -> None:
            title("Cleaning native packages...")
            subtitle("Removing unneeded packages...")
            try:
                orphans = [
                    p for p in capture(self.aur_helper, "-Qdtq").split("\n") if p
                ]
                run(self.aur_helper, "-Rscn", *orphans, *self.opts.flag_yes_native())
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
                    run(self.sudo, "rm", "-r", d)
            subtitle("Cleaning cache...")
            subprocess.run(f"yes | {self.aur_helper} -Sccd", shell=True)
            print("\nDone cleaning.")

        def handle_flatpak(_: list[str]) -> None:
            title("Cleaning flatpak packages...")
            run(
                "flatpak",
                "uninstall",
                "--unused",
                "--delete-data",
                *self.opts.flag_yes_flatpak(),
            )

        self.sources.handle(self.args, native=handle_native, flatpak=handle_flatpak)


class SearchCmd(Subcommand):
    name = "search"

    def github_search(self, topic: str, *pkgs: str) -> None:
        gh = first_of("GitHub CLI", "gh")
        env = os.environ.copy()
        env["GH_PAGER"] = ""
        subprocess.run([gh, "search", "repos", f"--topic={topic}", *pkgs], env=env)

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native", "flatpak"], pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title(f"Searching native package(s) {self.pkgs_str()}...")
            run(self.aur_helper, "-Ss", *pkgs)

        def handle_flatpak(pkgs: list[str]) -> None:
            title(f"Searching Flatpak package(s) {self.pkgs_str()}...")
            try:
                FlatpakList.new_search(*pkgs).print()
            except Exception:
                pass

        def handle_vim(pkgs: list[str]) -> None:
            title(f"Searching Vim plugins(s) {self.pkgs_str()}...")
            self.github_search("neovim,nvim,vim", *pkgs)

        def handle_zsh(pkgs: list[str]) -> None:
            title(f"Searching Zsh plugins(s) {self.pkgs_str()}...")
            self.github_search("zsh", *pkgs)

        self.sources.handle(
            self.args,
            native=handle_native,
            flatpak=handle_flatpak,
            vim=handle_vim,
            zsh=handle_zsh,
        )


class InstallCmd(Subcommand):
    name = "install"

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title(f"Installing native package(s) {self.pkgs_str()}...")
            run(
                self.aur_helper,
                "-S",
                *pkgs,
                *self.opts.flag_yes_native(),
                *self.opts.flag_force_native(),
            )

        def handle_flatpak(pkgs: list[str]) -> None:
            title(f"Installing flatpak package(s) {self.pkgs_str()}...")
            run(
                "flatpak",
                "install",
                *pkgs,
                *self.opts.flag_yes_flatpak(),
                *self.opts.flag_force_flatpak(),
            )

        self.sources.handle(self.args, native=handle_native, flatpak=handle_flatpak)


class RemoveCmd(Subcommand):
    name = "remove"

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title(f"Removing native package(s) {self.pkgs_str()}...")
            run(self.aur_helper, "-Rscn", *pkgs)

        def handle_flatpak(pkgs: list[str]) -> None:
            title(f"Removing Flatpak package(s) {self.pkgs_str()}...")
            run("flatpak", "uninstall", "--delete-data", *pkgs)

        self.sources.handle(self.args, native=handle_native, flatpak=handle_flatpak)


class ListCmd(Subcommand):
    name = "list"

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native", "flatpak"])

        def handle_native(pkgs: list[str]) -> None:
            title(f"Listing native package(s) {self.pkgs_str()}...")
            try:
                run(self.aur_helper, "-Qs", *pkgs)
            except subprocess.CalledProcessError:
                raise AutoError(f"No native packages found with keyword {self.pkgs_str()}")

        def handle_flatpak(pkgs: list[str]) -> None:
            title(f"Listing Flatpak package(s) {self.pkgs_str()}...")
            pkglist = FlatpakList.new_list(*pkgs)
            if not pkglist.items:
                raise AutoError(f"No Flatpak packages found with keyword {self.pkgs_str()}")
            pkglist.print()

        self.sources.handle(self.args, native=handle_native, flatpak=handle_flatpak)


class WhichCmd(Subcommand):
    name = "which"

    def run(self) -> None:
        self.sources.require(self.args, defaults=["native"], exclusive=True, pkgs=True)

        def handle_native(pkgs: list[str]) -> None:
            title(f"Querying which package provides {self.pkgs_str()}...")
            if self.opts.remote and shutil.which("pkgfile"):
                cmd = ["pkgfile", "-v"]
            else:
                cmd = [self.aur_helper, "-Qo"]
            run(*cmd, *pkgs)

        self.sources.handle(self.args, native=handle_native)


class UpdateCmd(Subcommand):
    name = "update"

    def update_keyring_pkgs(self) -> None:
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
        if needed_pkgs:
            run(self.aur_helper, "-S", "--needed", *needed_pkgs)

    def git_pull_parallel(self, paths: list[str]) -> None:
        threads: list[threading.Thread] = []
        for path in paths:
            if not os.path.isdir(os.path.join(path, ".git")):
                continue
            subtitle(f"Updating plugin {basename(path)}...")
            t = threading.Thread(
                target=lambda p=path: subprocess.run(f"cd {p}; git pull", shell=True)
            )
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

    def update_zsh_plugins(self) -> None:
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
            self.git_pull_parallel(paths)
        elif plugin_path and os.path.isdir(plugin_path):
            title("Updating ZSH plugins...")
            self.git_pull_parallel(glob.glob(f"{plugin_path}/*"))

    def aur_helper_flags(self, pkgs: list[str]) -> list[str]:
        if pkgs:
            return ["-S", "--needed", *pkgs]
        if self.aur_helper == "pacman":
            return ["-Su"]
        return ["-Su", "--devel"]

    def run(self) -> None:
        self.sources.require(
            self.args, defaults=["native"] if self.args else list(Sources.ALL)
        )

        def handle_native(pkgs: list[str]) -> None:
            title(f"Updating native plugin(s) {self.pkgs_str()}...")
            run(self.aur_helper, "-Sy")
            self.update_keyring_pkgs()
            flags = self.aur_helper_flags(pkgs)
            run(self.aur_helper, *flags, *self.opts.flag_yes_native())
            if shutil.which("pkgfile"):
                run(self.sudo, "pkgfile", "-u")

        def handle_flatpak(pkgs: list[str]) -> None:
            title(f"Updating Flatpak plugin(s) {self.pkgs_str()}...")
            run(
                "flatpak",
                "update",
                *self.opts.flag_yes_flatpak(),
                *FlatpakList.new_list(*pkgs).refs(),
            )

        def handle_zsh(_: list[str]) -> None:
            if shutil.which("zsh"):
                self.update_zsh_plugins()

        def handle_vim(_: list[str]) -> None:
            if not shutil.which("nvim"):
                return
            title("Updating Vim plugins...")
            update_cmd = "+lua vim.pack.update(nil, { force = true })"
            run("nvim", update_cmd, "+qa", "--headless")
            print("Done.")

        self.sources.handle(
            self.args,
            native=handle_native,
            flatpak=handle_flatpak,
            zsh=handle_zsh,
            vim=handle_vim,
        )


def parse_args(argv: list[str], aur_helper: str, sudo: str) -> tuple[str, Context]:
    if len(argv) < 2:
        raise AutoError("missing subcommand")

    subcmd_name = argv[1]

    if subcmd_name == "__complete":
        print_completions(argv[2] if len(argv) > 2 else "")

    if subcmd_name in ("-h", "--help"):
        print_help()

    parser = build_parser()
    parsed, remaining = parser.parse_known_args(argv[2:])

    if parsed.help:
        print_help()

    sources = Sources(context=subcmd_name)
    for src in Sources.ALL:
        if getattr(parsed, src):
            sources.enable(src)
    for exc in parsed.exclude:
        sources.exclude(exc)

    opts = Options(yes=parsed.yes, force=parsed.force, remote=parsed.remote)
    ctx = Context(
        opts=opts,
        args=remaining,
        sources=sources,
        aur_helper=aur_helper,
        sudo=sudo,
    )
    return subcmd_name, ctx


def main() -> None:
    aur_helper = first_of("AUR helpers", "yay", "paru", "pacman")
    sudo = first_of("sudo utilities", "sudo", "doas", "pkexec")

    subcmd_name, ctx = parse_args(sys.argv, aur_helper, sudo)
    subcmd = Subcommand.dispatch(subcmd_name, ctx)
    subcmd.run()


if __name__ == "__main__":
    try:
        main()
    except (AutoError, subprocess.CalledProcessError) as e:
        msg = str(e).rstrip("\n")
        print(f"\033[1;31merror:\033[0m {msg}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

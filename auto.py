#!/usr/bin/env python3

import sys
import os
import re
import glob
import math
import shutil
import subprocess
import threading
from os.path import basename

OPT = {}
SUBCMD = None
ARGS = []
AUR_HELPER = None
SUDO = None


class AutoError(Exception):
    _HINT = "type 'auto help' to see usage."
    def __str__(self):
        return f"{super().__str__()}.\n{self._HINT}"


class SubcmdError(AutoError):
    """Error raised within a subcommand context; prefixes the message with the subcommand name."""
    def __init__(self, msg):
        Exception.__init__(self, f"in {SUBCMD}: {msg}")


class Sources:
    ALL = ('native', 'flatpak', 'zsh', 'vim')

    def __init__(self):
        self._active = set()
        self._excluded = set()

    def __len__(self):
        return len(self._active)

    def __bool__(self):
        return bool(self._active)

    def __str__(self):
        return ', '.join(s for s in self.ALL if s in self._active)

    def enable(self, src):
        self._active.add(src)

    def exclude(self, src):
        if src not in self.ALL:
            raise SubcmdError(f"unknown source {src}")
        self._excluded.add(src)

    def require(self, defaults=None, exclusive=False, pkgs=False):
        if not self and defaults:
            self._active = set(defaults)
        if exclusive and len(self) != 1:
            raise SubcmdError(f"multiple sources {self} specified")
        if pkgs and not ARGS:
            raise SubcmdError("no packages specified")

    def handle(self, **handlers):
        for src in self.ALL:
            if src not in self._active:
                continue
            if src not in handlers:
                raise SubcmdError(f"source(s) {self} not applicable")
            if src not in self._excluded:
                handlers[src](*ARGS)
            self._active.discard(src)
        if self._active:
            raise SubcmdError(f"source(s) {self} not applicable")


SOURCES = Sources()


def run(*args):
    result = subprocess.run(list(args))
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, list(args))


def capture(*args):
    return subprocess.run(list(args), capture_output=True, text=True, check=True).stdout


def pkgs_str():
    return ', '.join(ARGS)



def first_of(desc, *cmds):
    for cmd in cmds:
        if shutil.which(cmd):
            return cmd
    raise AutoError(f"no {desc} found")


def colored(text, style):
    codes = {
        'bold':       '\033[1m',
        'bold blue':  '\033[1;34m',
        'bold green': '\033[1;32m',
        'bold red':   '\033[1;31m',
        'cyan':       '\033[36m',
        'dark white': '\033[2;37m',
    }
    return f"{codes.get(style, '')}{text}\033[0m"


def title(fmt, *args):
    text = fmt % args if args else fmt
    cols = shutil.get_terminal_size().columns
    pad = (cols - len(text) - 2) / 2
    s1 = colored('⎼' * max(0, max(1, math.floor(pad)) - 1), 'dark white')
    s2 = colored('⎼' * max(0, max(1, math.ceil(pad)) - 1), 'dark white')
    print(f" {s1} {colored(text, 'bold')} {s2} ")


def subtitle(fmt, *args):
    text = fmt % args if args else fmt
    print(colored(":: ", "bold blue") + colored(text, "bold"))


def flag_yes_native():    return ['--noconfirm'] if OPT.get('yes') else []
def flag_yes_flatpak():   return ['--assumeyes'] if OPT.get('yes') else []
def flag_force_native():  return ['--overwrite', '*'] if OPT.get('force') else []
def flag_force_flatpak(): return ['--reinstall'] if OPT.get('force') else []


class FlatpakPkg:
    def __init__(self, cols, values):
        self._data = dict(zip(cols, values))

    def __getitem__(self, key):
        return self._data.get(key, '')

    def match(self, *pkgs):
        for pkg in pkgs:
            pattern = re.compile(pkg, re.IGNORECASE)
            for key in ('name', 'application', 'description'):
                if pattern.search(self._data.get(key, '')):
                    return True
        return False


class FlatpakList:
    def __init__(self, items=None):
        self.items = items if items is not None else []

    @classmethod
    def _build(cls, cmds, extra_cols, filter_pkgs):
        cols = ['name', 'description', 'application', 'version', 'branch'] + extra_cols
        proc = subprocess.Popen(
            ['flatpak'] + cmds + [f"--columns={','.join(cols)}"],
            stdout=subprocess.PIPE, text=True
        )
        result = cls()
        for line in proc.stdout:
            line = line.rstrip('\n')
            if line == "No matches found":
                break
            pkg = FlatpakPkg(cols, line.split('\t'))
            if filter_pkgs and not pkg.match(*filter_pkgs):
                continue
            result.items.append(pkg)
        proc.wait()
        return result

    def reversed(self):
        return FlatpakList(list(reversed(self.items)))

    @classmethod
    def new_list(cls, *pkgs):
        return cls._build(['list'], ['origin', 'ref'], list(pkgs))

    @classmethod
    def new_search(cls, *pkgs):
        return cls._build(['search'] + list(pkgs), ['remotes'], []).reversed()

    def refs(self):
        return [item['ref'] for item in self.items]

    def print(self):
        for f in self.items:
            remote_str = f['remotes'] or f['origin']
            print(
                f"{colored(remote_str, 'bold blue')}/{colored(f['application'], 'bold')} "
                f"{colored(f['branch'], 'bold green')} {colored(f['version'], 'cyan')}"
            )
            print(f"    {f['name']}: {f['description']}")


def subcmd_help(exit_code=0):
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
    sys.exit(exit_code)


def subcmd_info(*pkgs):
    SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

    def handle_native(*pkgs):
        title("Querying information on native package(s) %s...", pkgs_str())
        query = "-Sii" if OPT.get('remote') else "-Qii"
        remote = "remote" if OPT.get('remote') else "local"
        try:
            run(AUR_HELPER, query, *pkgs)
        except subprocess.CalledProcessError:
            raise AutoError(f"no information found for {remote} package(s) {pkgs_str()}")

    def handle_flatpak(*pkgs):
        remote = "remote" if OPT.get('remote') else "local"
        title("Querying information on %s Flatpak package(s) %s...", remote, pkgs_str())
        if OPT.get('remote'):
            pkglist = FlatpakList.new_search(*pkgs).reversed()
        else:
            pkglist = FlatpakList.new_list(*pkgs)
        if not pkglist.items:
            raise AutoError(f"No information found for {remote} Flatpak package {pkgs_str()}")
        for pkg in pkglist.items:
            appid = pkg['application']
            subtitle("Querying %s information for %s...", remote, appid)
            if OPT.get('remote'):
                run("flatpak", "remote-info", pkg['remotes'], appid)
            else:
                run("flatpak", "info", appid)

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


def subcmd_files(*pkgs):
    SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

    def handle_native(*pkgs):
        title("Querying installed files of native package(s) %s...", pkgs_str())
        if OPT.get('remote'):
            run('pkgfile', '--list', *pkgs)
        else:
            run(AUR_HELPER, '-Ql', *pkgs)

    def handle_flatpak(*pkgs):
        title("Querying installed files of Flatpak package(s) %s...", pkgs_str())
        for ref in FlatpakList.new_list(*pkgs).refs():
            path = capture('flatpak', 'info', '-l', ref).strip()
            run('tree', path)

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


def subcmd_clean(*pkgs):
    SOURCES.require(defaults=["native", "flatpak"])

    def handle_native(*pkgs):
        title('Cleaning native packages...')
        subtitle('Removing unneeded packages...')
        try:
            orphans = [p for p in capture(AUR_HELPER, '-Qdtq').split('\n') if p]
            run(AUR_HELPER, "-Rscn", *orphans, *flag_yes_native())
        except subprocess.CalledProcessError:
            print("Nothing unused to uninstall")
        downloads = [d for d in glob.glob('/var/cache/pacman/pkg/download*') if os.path.isdir(d)]
        if downloads:
            subtitle("Removing pacman download remains...")
            for d in downloads:
                run(SUDO, 'rm', '-r', d)
        subtitle('Cleaning cache...')
        subprocess.run(f"yes | {AUR_HELPER} -Sccd", shell=True)
        print("\nDone cleaning.")

    def handle_flatpak(*pkgs):
        title('Cleaning flatpak packages...')
        run("flatpak", "uninstall", "--unused", "--delete-data", *flag_yes_flatpak())

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


def github_search(topic, *pkgs):
    gh = first_of("GitHub CLI", "gh")
    env = os.environ.copy()
    env['GH_PAGER'] = ''
    subprocess.run([gh, "search", "repos", f"--topic={topic}", *pkgs], env=env)


def subcmd_search(*pkgs):
    SOURCES.require(defaults=["native", "flatpak"], pkgs=True)

    def handle_native(*pkgs):
        title("Searching native package(s) %s...", pkgs_str())
        run(AUR_HELPER, "-Ss", *pkgs)

    def handle_flatpak(*pkgs):
        title("Searching Flatpak package(s) %s...", pkgs_str())
        try:
            FlatpakList.new_search(*pkgs).print()
        except Exception:
            pass

    def handle_vim(*pkgs):
        title("Searching Vim plugins(s) %s...", pkgs_str())
        github_search("neovim,nvim,vim", *pkgs)

    def handle_zsh(*pkgs):
        title("Searching Zsh plugins(s) %s...", pkgs_str())
        github_search("zsh", *pkgs)

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak, vim=handle_vim, zsh=handle_zsh)


def subcmd_install(*pkgs):
    SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

    def handle_native(*pkgs):
        title("Installing native package(s) %s...", pkgs_str())
        run(AUR_HELPER, "-S", *pkgs, *flag_yes_native(), *flag_force_native())

    def handle_flatpak(*pkgs):
        title("Installing flatpak package(s) %s...", pkgs_str())
        run("flatpak", "install", *pkgs, *flag_yes_flatpak(), *flag_force_flatpak())

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


def subcmd_remove(*pkgs):
    SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

    def handle_native(*pkgs):
        title("Removing native package(s) %s...", pkgs_str())
        run(AUR_HELPER, "-Rscn", *pkgs)

    def handle_flatpak(*pkgs):
        title("Removing Flatpak package(s) %s...", pkgs_str())
        run("flatpak", "uninstall", "--delete-data", *pkgs)

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


def subcmd_list(*pkgs):
    SOURCES.require(defaults=["native", "flatpak"])

    def handle_native(*pkgs):
        title("Listing native package(s) %s...", pkgs_str())
        try:
            run(AUR_HELPER, "-Qs", *pkgs)
        except subprocess.CalledProcessError:
            raise AutoError(f"No native packages found with keyword {pkgs_str()}")

    def handle_flatpak(*pkgs):
        title("Listing Flatpak package(s) %s...", pkgs_str())
        pkglist = FlatpakList.new_list(*pkgs)
        if not pkglist.items:
            raise AutoError(f"No Flatpak packages found with keyword {pkgs_str()}")
        pkglist.print()

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak)


def subcmd_which(*pkgs):
    SOURCES.require(defaults=["native"], exclusive=True, pkgs=True)

    def handle_native(*pkgs):
        title("Querying which package provides %s...", pkgs_str())
        cmd = ["pkgfile", "-v"] if OPT.get('remote') else [AUR_HELPER, "-Qo"]
        run(*cmd, *pkgs)

    SOURCES.handle(native=handle_native)


def update_keyring_pkgs():
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


def _git_pull_parallel(paths):
    threads = []
    for path in paths:
        if not os.path.isdir(os.path.join(path, '.git')):
            continue
        subtitle("Updating plugin %s...", basename(path))
        t = threading.Thread(target=lambda p=path: subprocess.run(f"cd {p}; git pull", shell=True))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()


def update_zsh_plugins():
    home = os.environ.get('HOME', '')
    zplug_path = os.path.join(home, '.zplug')
    omz_path = os.path.join(home, '.oh-my-zsh')
    plugin_path = os.environ.get('ZPLUGINDIR', '')

    if os.path.isdir(zplug_path):
        title("Updating ZPlug plugins...")
        run("zsh", "-ic", "zplug update")
    elif os.path.isdir(omz_path):
        title("Updating Oh-My-Zsh plugins...")
        run("zsh", "-c", f"{omz_path}/tools/upgrade.sh")
        custom = os.path.join(omz_path, 'custom')
        paths = glob.glob(f"{custom}/plugins/*") + glob.glob(f"{custom}/themes/*")
        _git_pull_parallel(paths)
    elif plugin_path and os.path.isdir(plugin_path):
        title("Updating ZSH plugins...")
        _git_pull_parallel(glob.glob(f"{plugin_path}/*"))


def subcmd_update(*pkgs):
    SOURCES.require(defaults=["native"] if pkgs else list(Sources.ALL))

    def handle_native(*pkgs):
        title("Updating native plugin(s) %s...", pkgs_str())
        update_keyring_pkgs()
        flags = ["-S", "--needed", *pkgs] if pkgs else ["-Syu", "--devel"]
        run(AUR_HELPER, *flags, *flag_yes_native())
        run(SUDO, "pkgfile", "-u")

    def handle_flatpak(*pkgs):
        title("Updating Flatpak plugin(s) %s...", pkgs_str())
        run("flatpak", "update", *flag_yes_flatpak(), *FlatpakList.new_list(*pkgs).refs())

    def handle_zsh(*pkgs):
        if shutil.which('zsh'):
            update_zsh_plugins()

    def handle_vim(*pkgs):
        if not shutil.which('nvim'):
            return
        title("Updating Vim plugins...")
        run("nvim", "+Lazy! sync", "+qa", "--headless")
        print("Done.")

    SOURCES.handle(native=handle_native, flatpak=handle_flatpak, zsh=handle_zsh, vim=handle_vim)


def parse_args():
    global SUBCMD, ARGS

    if len(sys.argv) < 2:
        raise AutoError("missing subcommand")

    SUBCMD = sys.argv[1]

    if SUBCMD in ('-h', '--help'):
        subcmd_help()

    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('-n', '--native',  action='store_true')
    parser.add_argument('-f', '--flatpak', action='store_true')
    parser.add_argument('-z', '--zsh',     action='store_true')
    parser.add_argument('-v', '--vim',     action='store_true')
    parser.add_argument('-e', '--exclude', action='append', default=[])
    parser.add_argument('-w', '--remote',  action='store_true')
    parser.add_argument('-x', '--force',   action='store_true')
    parser.add_argument('-y', '--yes',     action='store_true')
    parser.add_argument('-h', '--help',    action='store_true')

    parsed, remaining = parser.parse_known_args(sys.argv[2:])

    for src in Sources.ALL:
        if getattr(parsed, src):
            SOURCES.enable(src)

    for exc in parsed.exclude:
        SOURCES.exclude(exc)

    OPT['remote'] = parsed.remote
    OPT['force'] = parsed.force
    OPT['yes'] = parsed.yes

    if parsed.help:
        subcmd_help()

    ARGS = remaining


def main():
    global AUR_HELPER, SUDO

    AUR_HELPER = first_of("AUR helpers", 'yay', 'paru', 'pacman')
    SUDO = first_of("sudo utilities", 'sudo', 'doas', 'pkexec')

    parse_args()

    subcmds = {
        'install': subcmd_install,
        'remove':  subcmd_remove,
        'search':  subcmd_search,
        'update':  subcmd_update,
        'clean':   subcmd_clean,
        'info':    subcmd_info,
        'files':   subcmd_files,
        'which':   subcmd_which,
        'list':    subcmd_list,
        'help':    lambda *_: subcmd_help(),
    }

    handler = subcmds.get(SUBCMD)
    if handler is None:
        raise AutoError(f"unknown subcommand '{SUBCMD}'")
    handler()


if __name__ == '__main__':
    try:
        main()
    except (AutoError, subprocess.CalledProcessError) as e:
        msg = str(e).rstrip('\n')
        print(f"\033[1;31merror:\033[0m {msg}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)

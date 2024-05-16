#!/usr/bin/env python

import yaml
import os
from enum import Enum, auto
from typing import Iterable

import click


class PkgReq(Enum):
    Required = auto()
    Optional = auto()
    Disallowed = auto()


with open('auto.yaml') as config_file:
    config = yaml.safe_load(config_file)


def support_source(multiple: bool):
    def_conf = config['source_default']
    default = def_conf['multiple'] if multiple else def_conf['single']
    return click.option('-s', '--source',
                        multiple=multiple, default=default,
                        help='Source of action.')

pass_through = lambda x: x

def support_package(required: PkgReq):
    if required is PkgReq.Disallowed:
        return pass_through
    req = required is PkgReq.Required
    return click.argument('package', nargs=-1, required=req)


def support_remote(supported: bool = False):
    if not supported:
        return pass_through
    return click.option('-w', '--remote',
                        is_flag=True, show_default=True, default=False,
                        help='Show information from remote locations.')


def get_source_configs(source_names: Iterable[str], action: str):
    available_names = config['source'].keys()
    for name in source_names:
        if name not in available_names:
            available_str = ', '.join(available_names)
            click.secho(f'Error: Source "{name}" not available', err=True)
            click.secho(f'Available sources: {available_str}.', err=True)
            exit(1)
        source = config['source'][name]
        if action not in source:
            continue
        yield source[action]


def subcommand(action: str,
               help: str,
               source_multiple: bool = True,
               package_required: PkgReq = PkgReq.Required,
               remote_supported: bool = False):
    @cli.command(action, help=help, short_help=help)
    @support_source(multiple=source_multiple)
    @support_package(required=package_required)
    @support_remote(remote_supported)
    def _(source: str | tuple[str],
              package: tuple[str] | None = None,
              remote: bool | None = None):
        # if single source, put it in a tuple
        if isinstance(source, str):
            source = (source,)

        config_list = get_source_configs(source, action)
        source_str = ', '.join(source)
        if package:
            package_str = ' '.join(package)
            click.secho(f':: Performing "{action}" on {package_str} with {source_str}', bold=True)
        else:
            click.secho(f':: Performing "{action}" with {source_str}', bold=True)

        for config in config_list:
            cmd: dict | str = config
            # remote support
            if remote_supported:
                assert isinstance(cmd, dict)
                cmd = cmd['remote'] if remote else cmd['local']
            # required packages support
            if package_required is PkgReq.Required:
                assert isinstance(cmd, str)
                cmd = cmd.format(package_str)
            elif package_required is PkgReq.Optional:
                assert isinstance(cmd, dict)
                if package:
                    cmd = cmd['package'].format(package_str)
                else:
                    cmd = cmd['all']
            assert isinstance(cmd, str)
            os.system(cmd)


@click.group()
def cli():
    '''Auto script for managing packages from multiple sources.'''


subcommand('install', 'Install packages.',
           source_multiple=False)
subcommand('list', 'List installed packages.',
           package_required=PkgReq.Optional)
subcommand('search', 'Search online for packages.')
subcommand('update', 'Update packages.',
           package_required=PkgReq.Optional)
subcommand('remove', 'Remove packages.',
           source_multiple=False)
subcommand('clean', 'Clean unused packages and cache.',
           package_required=PkgReq.Disallowed)
subcommand('info', 'Display information on packages.',
           source_multiple=False, remote_supported=True)


if __name__ == '__main__':
    cli()

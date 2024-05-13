#!/usr/bin/env python

import click
import os
import json
from typing import Iterable


with open('auto.json') as config_file:
    config = json.load(config_file)


def support_source(multiple: bool = True):
    def_conf = config['source_default']
    default = def_conf['multiple'] if multiple else def_conf['single']
    return click.option('-s', '--source', multiple=multiple, default=default)


def support_package(required: bool | None = True):
    if required is None:
        required = False
    return click.argument('package', nargs=-1, required=required)


def get_source_configs(source_names: Iterable[str], action: str):
    available_names = config['source'].keys()
    for name in source_names:
        if name not in available_names:
            available_str = ' '.join(available_names)
            click.secho(f'Error: Source "{name}" not available', err=True)
            click.secho(f'Available sources: {available_str}', err=True)
            exit(1)
        source = config['source'][name]
        if action not in source:
            continue
        yield source[action]


def subcommand(action: str, source_multiple: bool = True, package_required: bool | None = True):
    @cli.command(action)
    @support_source(multiple=source_multiple)
    @support_package(required=package_required)
    def _(source: str | tuple[str], package: tuple[str]):
        if isinstance(source, str):
            source = (source,)
        config_list = get_source_configs(source, action)
        package_str = ' '.join(package)
        source_str = ', '.join(source)
        click.secho(f':: {action} packages {package_str} with {source_str}', bold=True)
        for config in config_list:
            if package_required is None:
                cmd = config
            elif package_required:
                cmd = config.format(package_str)
            elif package:
                cmd = config['package'].format(package_str)
            else:
                cmd = config['all']
            os.system(cmd)


@click.group()
def cli(): pass


subcommand('install', source_multiple=False)
subcommand('list', package_required=False)
subcommand('search')
subcommand('update', package_required=False)
subcommand('remove', source_multiple=False)
subcommand('clean', package_required=None)


if __name__ == '__main__':
    cli()

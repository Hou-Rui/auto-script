#!/usr/bin/env python

import click
import os
import json
from typing import Any, Callable, Iterable


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


def get_source_configs(source_names: str | Iterable[str]):
    if isinstance(source_names, str):
        source_names = (source_names,)
    for name in source_names:
        if name not in config['source']:
            click.echo(f'Source not found: {name}')
            exit(1)
        yield config['source'][name]


def subcommand(source_multiple: bool = True, package_required: bool | None = True):
    def decorator(func: Callable[[], Any]):
        name = func.__name__
        @cli.command(name)
        @support_source(multiple=source_multiple)
        @support_package(required=package_required)
        def inner(source: str | tuple[str], package: tuple[str]):
            config_list = (c[name] for c in get_source_configs(source))
            package_str = ' '.join(package)
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
            return func()
        return inner
    return decorator


@click.group()
def cli(): pass

@subcommand(source_multiple=False)
def install(): pass

@subcommand(package_required=False)
def list(): pass

@subcommand()
def search(): pass

@subcommand(package_required=False)
def update(): pass

@subcommand(source_multiple=False)
def remove(): pass

@subcommand(package_required=None)
def clean(): pass


if __name__ == '__main__':
    cli()

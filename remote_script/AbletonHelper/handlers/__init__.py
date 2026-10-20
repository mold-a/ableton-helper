"""Command handlers. Each module exposes COMMANDS = {name: handler(ctx, params)}."""

from . import browser, clips, devices, service, session, tracks


def all_commands():
    commands = {}
    for module in (service, session, tracks, devices, browser, clips):
        commands.update(module.COMMANDS)
    return commands

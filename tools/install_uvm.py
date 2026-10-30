#!/usr/bin/env python3
"""Install a pinned official UVM source release and configure the local .env."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


REPOSITORY = 'https://github.com/accellera-official/uvm-core.git'
RELEASE = '2020.3.1'
COMMIT = '78c06547a2a0a29b3dc9dcafae62b75b2ff61544'
ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    result = subprocess.run(['git', *map(str, args)], text=True, capture_output=True,
                            timeout=90, check=False, env=dict(os.environ, GIT_TERMINAL_PROMPT='0'))
    if result.returncode:
        # Only the public upstream URL is used; don't print process environment.
        raise RuntimeError(result.stderr.strip() or 'Git command failed')
    return result.stdout.strip()


def configure_env(path, source):
    """Replace only this setting, preserve unrelated configuration and private values."""
    original = path.read_text() if path.exists() else ''
    lines = original.splitlines(keepends=True)
    setting = 'XEZIM_UVM_DIR=' + str(source) + '\n'
    found = False
    for index, line in enumerate(lines):
        if re.match(r'^\s*(?:export\s+)?XEZIM_UVM_DIR\s*=', line):
            lines[index] = setting if not found else ''
            found = True
    if not found:
        if lines and not lines[-1].endswith('\n'): lines[-1] += '\n'
        lines.append(setting)
    descriptor, temporary = tempfile.mkstemp(prefix='.env-uvm-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(''.join(lines))
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists(): Path(temporary).unlink()


def install(root=ROOT):
    dependencies = root / '.deps'
    dependencies.mkdir(exist_ok=True)
    destination = dependencies / ('uvm-core-' + RELEASE)
    if not destination.exists():
        # Publish only a complete verified checkout; failures leave .env unchanged.
        with tempfile.TemporaryDirectory(prefix='.uvm-install-', dir=dependencies) as temporary:
            checkout = Path(temporary) / 'checkout'
            print('Downloading official UVM ' + RELEASE + '...', flush=True)
            git('clone', '--depth', '1', '--branch', RELEASE, REPOSITORY, checkout)
            validate_checkout(checkout)
            checkout.rename(destination)
    validate_checkout(destination)
    configure_env(root / '.env', (destination / 'src').resolve())
    print('Installed UVM ' + RELEASE + ' at ' + str(destination))
    print('Saved XEZIM_UVM_DIR in ' + str(root / '.env'))
    print('Restart the orchestrator to load it. Existing shell variables take precedence over .env.')


def validate_checkout(path):
    if git('-C', path, 'rev-parse', 'HEAD') != COMMIT:
        raise RuntimeError('UVM checkout does not match the pinned official release commit')
    for name in ('src/uvm_pkg.sv', 'src/uvm_macros.svh', 'LICENSE.txt', 'NOTICE.txt'):
        if not (path / name).is_file(): raise RuntimeError('Incomplete UVM release: missing ' + name)
    if git('-C', path, 'status', '--porcelain'):
        raise RuntimeError('Existing UVM checkout contains local modifications; leaving it unchanged')


if __name__ == '__main__':
    try:
        install()
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print('UVM installation failed: ' + str(error), file=sys.stderr)
        print('No simulator success is implied. Run this installer from a terminal with GitHub access.', file=sys.stderr)
        sys.exit(1)

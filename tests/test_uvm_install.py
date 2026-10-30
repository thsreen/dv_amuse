"""Installer configuration and failure recovery, without network access."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def installer():
    path = Path(__file__).resolve().parents[1] / 'tools/install_uvm.py'
    spec = importlib.util.spec_from_file_location('install_uvm', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_update_preserves_other_settings_and_is_idempotent(installer, tmp_path):
    env = tmp_path / '.env'
    env.write_text('# settings\nMODEL_API_KEY=fixture-value\nXEZIM_UVM_DIR=old\nOTHER=unchanged')
    installer.configure_env(env, tmp_path / 'uvm/src')
    expected = env.read_text()
    installer.configure_env(env, tmp_path / 'uvm/src')
    assert env.read_text() == expected
    assert 'MODEL_API_KEY=fixture-value\n' in expected and expected.endswith('OTHER=unchanged')
    assert expected.count('XEZIM_UVM_DIR=') == 1 and env.stat().st_mode & 0o777 == 0o600


def test_failed_download_leaves_configuration_unchanged(installer, tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('OTHER=unchanged\n')
    def fail(*args): raise RuntimeError('network unavailable')
    monkeypatch.setattr(installer, 'git', fail)
    with pytest.raises(RuntimeError, match='network unavailable'): installer.install(tmp_path)
    assert env.read_text() == 'OTHER=unchanged\n'
    assert not list((tmp_path / '.deps').iterdir())


def test_successful_install_checks_commit_and_reuses_checkout(installer, tmp_path, monkeypatch):
    downloads = []
    def git(*args):
        if args[0] == 'clone':
            downloads.append(args)
            checkout = Path(args[-1])
            for name in ('src/uvm_pkg.sv', 'src/uvm_macros.svh', 'LICENSE.txt', 'NOTICE.txt'):
                path = checkout / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture only')
        return installer.COMMIT if 'rev-parse' in args else ''
    monkeypatch.setattr(installer, 'git', git)
    installer.install(tmp_path)
    installer.install(tmp_path)
    assert len(downloads) == 1
    assert str(tmp_path / '.deps/uvm-core-2020.3.1/src') in (tmp_path / '.env').read_text()

"""Fresh no-links journal lookup and unchanged unsupported-host validation."""
from __future__ import annotations

import errno
from pathlib import Path

import pytest

from provelume import atomic_commit
from provelume.atomic_commit import AtomicCommitIntegrityError
from provelume.local_path_guard import kernel_no_links


def journal(tmp_path):
    stage = tmp_path / 'stage'
    (stage / 'candidates').mkdir(parents=True)
    target = stage / 'candidates/0000.bin'
    target.write_bytes(b'synthetic journal')
    return stage, target


def lookup(stage):
    return atomic_commit._journal_path(
        stage, 'candidates/0000.bin', error_type=AtomicCommitIntegrityError,
    )


def test_kernel_journal_lookup_retains_both_component_checks(tmp_path, monkeypatch):
    stage, target = journal(tmp_path)
    observed, components = [], []

    def kernel(path):
        observed.append(path)
        return True

    def unexpected_resolver(*args):
        pytest.fail('a successful whole-path kernel lookup must not repeat the resolver')

    def no_link(path):
        components.append(path)
        return False

    monkeypatch.setattr(atomic_commit, 'kernel_no_links', kernel)
    monkeypatch.setattr(atomic_commit, 'safe_instance_path', unexpected_resolver)
    monkeypatch.setattr(Path, 'is_symlink', no_link)
    assert lookup(stage) == target
    assert observed == [target]
    assert components == [stage / 'candidates', target]


def test_kernel_journal_unsafe_result_never_uses_fallback(tmp_path, monkeypatch):
    stage, _ = journal(tmp_path)

    def unsafe(path):
        raise OSError(errno.ELOOP, 'synthetic rejected link')

    def unexpected_resolver(*args):
        pytest.fail('an unsafe lookup must not select the unsupported-host fallback')

    monkeypatch.setattr(atomic_commit, 'kernel_no_links', unsafe)
    monkeypatch.setattr(atomic_commit, 'safe_instance_path', unexpected_resolver)
    with pytest.raises(AtomicCommitIntegrityError):
        lookup(stage)


def test_kernel_journal_result_is_fresh_on_every_call(tmp_path, monkeypatch):
    stage, target = journal(tmp_path)
    calls = []

    def kernel(path):
        calls.append(path)
        if len(calls) > 1:
            raise OSError(errno.ELOOP, 'synthetic replacement')
        return True

    monkeypatch.setattr(atomic_commit, 'kernel_no_links', kernel)
    assert lookup(stage) == target
    with pytest.raises(AtomicCommitIntegrityError):
        lookup(stage)
    assert calls == [target, target]


def test_unsupported_kernel_keeps_the_existing_journal_resolver(tmp_path, monkeypatch):
    stage, target = journal(tmp_path)
    original = atomic_commit.safe_instance_path
    observed = []
    monkeypatch.setattr(atomic_commit, 'kernel_no_links', lambda path: False)

    def resolve(root, reference):
        observed.append((root, reference))
        return original(root, reference)

    monkeypatch.setattr(atomic_commit, 'safe_instance_path', resolve)
    assert lookup(stage) == target
    assert observed == [(stage, 'candidates/0000.bin')]


def test_relative_journal_root_keeps_existing_resolver(tmp_path, monkeypatch):
    stage, target = journal(tmp_path)
    monkeypatch.chdir(tmp_path)

    def unexpected_kernel(path):
        pytest.fail('relative roots must keep the existing resolver')

    monkeypatch.setattr(atomic_commit, 'kernel_no_links', unexpected_kernel)
    assert lookup(Path('stage')) == target


@pytest.mark.parametrize('reference', ['../outside', '/etc/passwd',
                                     'candidates/00000.bin', 'candidates/../../outside'])
def test_malformed_journal_reference_is_rejected_before_lookup(
    tmp_path, monkeypatch, reference,
):
    stage, _ = journal(tmp_path)

    def unexpected(*args):
        pytest.fail('malformed journal reference must precede every lookup')

    monkeypatch.setattr(atomic_commit, 'kernel_no_links', unexpected)
    monkeypatch.setattr(atomic_commit, 'safe_instance_path', unexpected)
    with pytest.raises(AtomicCommitIntegrityError):
        atomic_commit._journal_path(stage, reference, error_type=AtomicCommitIntegrityError)


@pytest.mark.parametrize('position', ['leaf', 'middle', 'ancestor'])
def test_real_kernel_journal_lookup_rejects_aliases(tmp_path, position):
    stage, target = journal(tmp_path)
    if not kernel_no_links(target):
        pytest.skip('Kernel no-links lookup unavailable')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / '0000.bin').write_bytes(b'outside bytes')
    if position == 'leaf':
        link, destination = target, outside / '0000.bin'
        link.unlink()
    else:
        link = stage if position == 'ancestor' else stage / 'candidates'
        link.rename(tmp_path / 'preserved')
        destination = outside
    link.symlink_to(destination, target_is_directory=position != 'leaf')
    with pytest.raises(AtomicCommitIntegrityError):
        lookup(stage)
    assert (outside / '0000.bin').read_bytes() == b'outside bytes'


def test_real_kernel_journal_lookup_is_fresh_after_parent_replacement(tmp_path):
    stage, target = journal(tmp_path)
    if not kernel_no_links(target):
        pytest.skip('Kernel no-links lookup unavailable')
    assert lookup(stage) == target
    directory = stage / 'candidates'
    directory.rename(tmp_path / 'preserved')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / '0000.bin').write_bytes(b'outside bytes')
    directory.symlink_to(outside, target_is_directory=True)
    with pytest.raises(AtomicCommitIntegrityError):
        lookup(stage)
    assert (outside / '0000.bin').read_bytes() == b'outside bytes'


def test_real_kernel_journal_lookup_closes_every_descriptor(tmp_path):
    stage, target = journal(tmp_path)
    descriptors = Path('/proc/self/fd')
    if not kernel_no_links(target) or not descriptors.is_dir():
        pytest.skip('Kernel descriptor observation unavailable')
    before = len(list(descriptors.iterdir()))
    for _ in range(100):
        assert lookup(stage) == target
    assert len(list(descriptors.iterdir())) == before

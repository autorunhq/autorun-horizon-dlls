#!/usr/bin/env python3
"""Make the download a card starts from -- switch/ as one tar compressed with
zstd -- and switch/ as a zip, and with --publish, the repository's release that
carries them.

    tools/make-release.py [--publish]

A card with little of the DLLs takes them from the tar, rather than one request
per file, and only then what main has that it does not, one file at a time:
Autorun downloads it whole into memory, over several connections a range each,
then unpacks it, checking each file against the manifest on main. Compressed
as one, with zstd's long-range mode finding what hundreds of Wine DLLs share,
it is less than half of the files compressed one by one. The zip is what a
player without a network downloads.

There is one release, "Windows DLLs", tagged dlls: publishing deletes it and
makes it again at this commit, tag and all, so it is always main as it was
last published, never a version of its own. Commit and push main first.
"""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
import os
import subprocess
import tarfile

repo = Path(__file__).resolve().parents[1]
ARCHIVE = repo / 'dist/horizon-dlls.zip'
# Autorun's HORIZON_DLLS_BUNDLE_URL.
BUNDLE = repo / 'dist/horizon-dlls.tar.zst'
TAG = 'dlls'
TITLE = 'Windows DLLs'
NOTES = '''Every Windows DLL Autorun runs, laid out as on the SD card: the files on
main as of this tag. Autorun downloads horizon-dlls.tar.zst itself for a card
that has few of them, then brings anything newer from main one file at a time.

Without a network: unzip it to the root of the SD card, merging folders.'''


def git(*args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


def write_zip(path, files):
    part = path.with_suffix('.zip.part')
    # Written to a file it can seek in, so each local header gets its sizes
    # and no data descriptor follows the data.
    with ZipFile(part, 'w', ZIP_DEFLATED, compresslevel=9) as z:
        for file in files:
            z.write(file, file.relative_to(repo).as_posix())
    with ZipFile(part) as z:
        assert z.testzip() is None
        assert not any(info.flag_bits & 8 for info in z.infolist()), 'an entry has a data descriptor'
    os.replace(part, path)


def write_bundle(files):
    """The tar Autorun reads: plain ustar, no extended headers, the same bytes
    for the same files, then zstd -19 with a 128 MiB long-range window, which
    Autorun's decoder allows."""
    tar = BUNDLE.with_suffix('')
    with tarfile.open(tar, 'w', format=tarfile.USTAR_FORMAT) as t:
        for path in files:
            info = t.gettarinfo(path, path.relative_to(repo).as_posix())
            info.mtime, info.uid, info.gid, info.uname, info.gname, info.mode = 0, 0, 0, '', '', 0o644
            with open(path, 'rb') as f:
                t.addfile(info, f)
    part = BUNDLE.with_suffix('.zst.part')
    subprocess.run(['zstd', '-q', '-19', '--long=27', '-T0', '-f', str(tar), '-o', str(part)], check=True)
    tar.unlink()
    os.replace(part, BUNDLE)


def build():
    ARCHIVE.parent.mkdir(exist_ok=True)
    files = sorted(p for p in (repo / 'switch').rglob('*') if p.is_file() and p.name != '.DS_Store')
    write_zip(ARCHIVE, files)
    print(f'{ARCHIVE}: {len(files)} files, {ARCHIVE.stat().st_size >> 20} MB')
    write_bundle(files)
    print(f'{BUNDLE}: {BUNDLE.stat().st_size >> 20} MB')
    for stale in ARCHIVE.parent.glob('horizon-dlls-part*.zip'):
        stale.unlink()


def assets():
    return [BUNDLE, ARCHIVE]


def publish():
    """A new release each time, never the last one edited: the old one and its
    tag go, and GitHub makes the tag again at this commit as it makes the
    release, which keeps the release as GitHub vouches for it."""
    assert not git('status', '--porcelain', '--', 'switch'), 'switch/ has uncommitted changes'
    head = git('rev-parse', 'HEAD')
    assert git('branch', '-r', '--contains', head), 'push main first'
    repo_name = 'autorunhq/autorun-horizon-dlls'
    exists = subprocess.run(['gh', 'release', 'view', TAG, '-R', repo_name], capture_output=True).returncode == 0
    if exists:
        subprocess.run(['gh', 'release', 'delete', TAG, '--cleanup-tag', '-y', '-R', repo_name], check=True)
    subprocess.run(['git', '-C', str(repo), 'tag', '-d', TAG], capture_output=True)
    subprocess.run(['gh', 'release', 'create', TAG, *map(str, assets()), '--target', head, '--title', TITLE,
                    '--notes', NOTES, '--latest', '-R', repo_name], check=True)
    subprocess.run(['git', '-C', str(repo), 'fetch', '-q', 'origin', f'refs/tags/{TAG}:refs/tags/{TAG}'], check=True)
    print(f'published {", ".join(a.name for a in assets())} at {head[:12]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--publish', action='store_true', help='replace the release with this zip')
    args = parser.parse_args()
    build()
    if args.publish:
        publish()

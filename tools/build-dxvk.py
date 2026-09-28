#!/usr/bin/env python3
"""Build the pinned DXVK release as AMD64 Windows DLLs for Wine-NX."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from dxvk_payload import DLLS, REVISION, VERSION, digest, validate_payload


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def git(source, *args):
    return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()


def modified(source):
    """What differs from the release, leaving out the lock newer Meson keeps
    beside the subprojects it reads."""
    return [line for line in git(source, 'status', '--porcelain', '--untracked-files=all').splitlines()
            if not line.endswith('subprojects/.wraplock')]


def source_tree(source):
    if not (source / '.git').exists():
        if source.exists():
            raise ValueError(f'Refusing to overwrite {source}')
        source.mkdir(parents=True)
        git(source, 'init', '-q')
        git(source, 'config', 'core.autocrlf', 'false')
        git(source, 'remote', 'add', 'origin', 'https://github.com/doitsujin/dxvk.git')
        git(source, 'fetch', '--depth=1', 'origin', REVISION)
        git(source, 'checkout', '-q', '--detach', 'FETCH_HEAD')
    if git(source, 'rev-parse', 'HEAD') != REVISION:
        raise ValueError(f'DXVK must be at {REVISION}; no files were reset')
    if modified(source):
        raise ValueError('DXVK source or submodules are modified; no files were reset')
    git(source, 'submodule', 'update', '--init', '--recursive', '--depth=1')
    submodules = git(source, 'submodule', 'status', '--recursive')
    if any(line.startswith(('-', '+', 'U')) for line in submodules.splitlines()):
        raise ValueError('DXVK submodules do not match the release')
    if modified(source):
        raise ValueError('DXVK source or submodules are modified')
    return submodules


def main():
    from autorun import horizon_wine
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=horizon_wine / 'vendor/dxvk')
    parser.add_argument('--build', type=Path, default=horizon_wine / 'build-dxvk-amd64')
    parser.add_argument('--jobs', type=int, default=int(os.environ.get('WINE_NX_JOBS', '8')))
    args = parser.parse_args()
    source, build = args.source.resolve(), args.build.resolve()
    if source == build or source in build.parents or build in source.parents:
        parser.error('Source and build directories must be separate')
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    env = os.environ.copy()
    if env.get('WINE_NX_LLVM_MINGW'):
        env['PATH'] = str(Path(env['WINE_NX_LLVM_MINGW']) / 'bin') + os.pathsep + env['PATH']
    binaries = {}
    for role, tool in (('c', 'clang'), ('cpp', 'clang++'), ('ar', 'ar'),
                       ('strip', 'strip'), ('windres', 'windres')):
        name = f'x86_64-w64-mingw32-{tool}'
        binaries[role] = shutil.which(name, path=env['PATH'])
        if not binaries[role]:
            parser.error(f'Missing {name}; set WINE_NX_LLVM_MINGW')
    for tool in ('meson', 'ninja'):
        if not shutil.which(tool, path=env['PATH']):
            parser.error(f'Missing {tool}')
    if not any(shutil.which(tool, path=env['PATH']) for tool in ('glslang', 'glslangValidator')):
        parser.error('Missing glslang/glslangValidator')
    submodules = source_tree(source)
    build.mkdir(parents=True, exist_ok=True)
    cross_text = '[binaries]\n'
    for role, path in binaries.items():
        quoted = path.replace('\\', '\\\\').replace("'", "\\'")
        cross_text += f"{role} = '{quoted}'\n"
    cross_text += "\n[properties]\nneeds_exe_wrapper = true\n\n[host_machine]\n"
    cross_text += "system = 'windows'\ncpu_family = 'x86_64'\ncpu = 'x86_64'\nendian = 'little'\n"
    cross = build / 'llvm-mingw-amd64.txt'
    if cross.exists() and cross.read_text() != cross_text:
        parser.error('Toolchain changed; use a new --build directory')
    cross.write_text(cross_text)
    setup = ['meson', 'setup', str(build), str(source), '--cross-file', str(cross),
             '--buildtype=release', '--strip', '--wrap-mode=nodownload',
             '-Denable_dxgi=true', '-Denable_d3d8=true', '-Denable_d3d9=true',
             '-Denable_d3d10=true', '-Denable_d3d11=true']
    if (build / 'build.ninja').is_file():
        setup.append('--reconfigure')
    run(*setup, env=env)
    run('ninja', '-C', str(build), '-j', str(args.jobs), env=env)
    payload = build / 'payload'
    payload.mkdir(exist_ok=True)
    for name in DLLS:
        component = 'd3d10' if name == 'd3d10core.dll' else name[:-4]
        shutil.copy2(build / 'src' / component / name, payload / name)
    licenses = payload / 'licenses'
    licenses.mkdir(exist_ok=True)
    license_sources = {'DXVK-zlib.txt': source / 'LICENSE',
                       'DXBC-SPIRV-license.txt': source / 'subprojects/dxbc-spirv/LICENSE',
                       'libdisplay-info-license.txt': source / 'subprojects/libdisplay-info/LICENSE',
                       'OpenVR-license.txt': source / 'include/openvr/LICENSE',
                       'MinGW-w64-license.txt': source / 'include/native/directx/COPYING.MinGW-w64.txt',
                       'SPIRV-Headers-license.txt': source / 'include/spirv/LICENSES/MIT.txt',
                       'Vulkan-Headers-license.txt': source / 'include/vulkan/LICENSES/MIT.txt'}
    llvm_license = Path(binaries['cpp']).resolve().parents[1] / 'LICENSE.TXT'
    if not llvm_license.is_file():
        parser.error(f'Missing LLVM-MinGW runtime license: {llvm_license}')
    license_sources['LLVM-runtime-license.txt'] = llvm_license
    for name, path in license_sources.items():
        shutil.copy2(path, licenses / name)
    manifest = {'version': VERSION, 'revision': REVISION, 'architecture': 'x86_64',
                'submodules': submodules.splitlines(),
                'compiler': subprocess.check_output([binaries['cpp'], '--version'], text=True).splitlines()[0],
                'files': {name: digest(payload / name) for name in DLLS},
                'licenses': sorted(license_sources)}
    (payload / 'dxvk-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    validate_payload(payload)
    print(payload)


if __name__ == '__main__':
    main()

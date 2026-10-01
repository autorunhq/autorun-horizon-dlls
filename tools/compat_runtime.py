import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import urllib.request

from xlive_runtime import REPOSITORY as XLIVE_REPOSITORY, REVISION as XLIVE_REVISION, build_xlive

PHYSX_URL = 'https://us.download.nvidia.com/Windows/9.13.0604/PhysX-9.13.0604-SystemSoftware.msi'
PHYSX_SHA256 = 'e5fa75fd3324463197246966acf7cf09f4f4c31c8710ba820174ab38aa755676'
PHYSX_LEGACY_URL = 'https://us.download.nvidia.com/Windows/9.12.1031/PhysX-9.12.1031-SystemSoftware-Legacy.msi'
PHYSX_LEGACY_SHA256 = '2554b77a21f265dc6ddb727513ba4543dd9777b17b3f2fbe83a6ff11244fa00e'
MANIFEST = 'horizon-dlls/manifest.json'
PHYSX_FILES = {
    'drive_c/windows/syswow64/physxloader.dll': 'FILE_COMMON_PhysXLoader_dll',
    'drive_c/windows/syswow64/physxdevice.dll': 'FILE_COMMON_PhysXDevice_dll',
    'drive_c/windows/syswow64/cudart32_41_22.dll': 'FILE_COMMON_cudart32_41_22_dll',
}
for sdk in ('2.7.1', '2.7.3', '2.7.4', '2.7.5', '2.7.6', '2.8.0', '2.8.1', '2.8.3'):
    for module in ('PhysXCore', 'PhysXCooking'):
        PHYSX_FILES[f'drive_c/physx/Engine/v{sdk}/{module.lower()}.dll'] = (
            f'FILE_CMP_GPU_DLLS_{sdk.replace(".", "")}_{module}_dll')
PHYSX_LEGACY_FILES = {
    f'drive_c/physx/Engine/v2.7.2/{module.lower()}.dll': f'FILE_CMP_GPU_DLLS_272_{module}_dll'
    for module in ('PhysXCore', 'PhysXCooking')
}
COMPAT_PATHS = {'drive_c/windows/syswow64/xlive.dll', *PHYSX_FILES, *PHYSX_LEGACY_FILES}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(cache, url, expected):
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / url.rsplit('/', 1)[-1]
    data = target.read_bytes() if target.exists() else urllib.request.urlopen(url, timeout=60).read()
    if digest(data) != expected:
        raise ValueError(f'Checksum mismatch: {target.name}')
    if not target.exists():
        target.write_bytes(data)
    return target


def require_i386(data):
    offset, = struct.unpack_from('<I', data, 60)
    if (data[:2] != b'MZ' or data[offset:offset + 4] != b'PE\0\0' or
            struct.unpack_from('<H', data, offset + 4)[0] != 0x14c):
        raise ValueError('Expected an i386 PE module')


def physx_payload(cache):
    packages = (
        (PHYSX_URL, PHYSX_SHA256, '9.13.0604', 'physx-9-13-0604-driver', PHYSX_FILES),
        (PHYSX_LEGACY_URL, PHYSX_LEGACY_SHA256, '9.12.1031',
         'physx-9-12-1031-legacy-driver', PHYSX_LEGACY_FILES),
    )
    files = []
    sevenzip = shutil.which('7zz') or shutil.which('7z')
    if not sevenzip:
        raise RuntimeError('7-Zip is required to extract PhysX')
    for url, sha256, version, page, payload in packages:
        physx = dict(repo=f'https://www.nvidia.com/en-us/drivers/physx/{version.replace(".", "_")}/{page}/',
                     origin='nvidia', modified=False, version=version, archive=url, sha256=sha256)
        installer = fetch(cache, url, sha256)
        for relative, member in payload.items():
            dll = subprocess.check_output([sevenzip, 'e', '-so', str(installer), member])
            require_i386(dll)
            files.append((relative, dll, physx, 'LicenseRef-NVIDIA-PhysX'))
    return files


def stage_files(card, files, earlier, ref):
    entries = []
    for relative, data, source, license_id in files:
        path = Path(relative)
        previous = earlier.get(relative, {})
        sha = digest(data)
        version = previous.get('version', 0) + (sha != previous.get('sha256'))
        target = card / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        entries.append(dict(name=path.name, path=path.parent.as_posix(), arch='i386', category='gaming',
                            version=version, size=len(data), sha256=sha,
                            url=f'https://raw.githubusercontent.com/autorunhq/autorun-horizon-dlls/{ref}/switch/wine/{relative}',
                            source=source, license=license_id, requires=dict(flavor='arm64x', features=[]), classes=[]))
    return entries


def stage_runtime(card, cache, earlier, ref='main', toolchain=None):
    dll, license_text = build_xlive(cache, toolchain)
    xlive = dict(repo=XLIVE_REPOSITORY, commit=XLIVE_REVISION, origin='xliveless', modified=False,
                 build=dict(repo='https://github.com/autorunhq/autorun-horizon-dlls', ref=ref,
                            paths=['runtime/xlive/dllmain.cpp', 'tools/xlive_runtime.py']))
    require_i386(dll)
    files = [('drive_c/windows/syswow64/xlive.dll', dll, xlive, 'MIT'), *physx_payload(cache)]
    return stage_files(card, files, earlier, ref), {'XLiveLess.txt': license_text}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--ref', default='main')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', args.ref) or '..' in args.ref:
        parser.error('Invalid publishing branch')
    repo = Path(__file__).resolve().parents[1]
    card = repo / 'switch/wine'
    manifest = json.loads((card / MANIFEST).read_text())
    earlier = {f"{entry['path']}/{entry['name']}": entry for entry in manifest['files']}
    entries, licenses = stage_runtime(card, args.cache, earlier, args.ref)
    manifest['files'] = [entry for entry in manifest['files']
                         if f"{entry['path']}/{entry['name']}" not in COMPAT_PATHS] + entries
    (card / MANIFEST).write_text(json.dumps(manifest, indent=1) + '\n')
    (repo / 'LICENSES').mkdir(exist_ok=True)
    for name, data in licenses.items():
        (repo / 'LICENSES' / name).write_bytes(data)
    print(f'Staged {len(entries)} shared compatibility files')

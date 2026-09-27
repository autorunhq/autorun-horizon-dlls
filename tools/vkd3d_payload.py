"""Pinned VKD3D-Proton payload for the AMD64 runtime."""
import json
from pathlib import Path
import struct

from dxvk_payload import digest

VERSION = '3.0.1'
REVISION = '3b10bd7a7ec6a7347e616cf8bea59333afec2255'
DLLS = ('d3d12.dll', 'd3d12core.dll')


def validate_payload(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'vkd3d-manifest.json').read_text())
    if (manifest.get('version'), manifest.get('revision'), manifest.get('architecture')) != (
            VERSION, REVISION, 'x86_64'):
        raise ValueError('VKD3D payload does not match the pinned AMD64 release')
    for name in DLLS:
        path = directory / name
        data = path.read_bytes()
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError(f'Invalid VKD3D PE image: {path}')
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        if (offset > len(data) - 26 or data[offset:offset + 4] != b'PE\0\0' or
                struct.unpack_from('<H', data, offset + 4)[0] != 0x8664 or
                struct.unpack_from('<H', data, offset + 24)[0] != 0x20b or
                not struct.unpack_from('<H', data, offset + 22)[0] & 0x2000):
            raise ValueError(f'VKD3D DLL is not AMD64 PE32+: {path}')
        if manifest.get('files', {}).get(name) != digest(path):
            raise ValueError(f'VKD3D payload hash mismatch: {path}')
    if not manifest.get('licenses'):
        raise ValueError('VKD3D payload lacks licenses')
    for name in manifest['licenses']:
        if Path(name).name != name or not (directory / 'licenses' / name).is_file():
            raise ValueError(f'Missing VKD3D license: {name}')
    return manifest

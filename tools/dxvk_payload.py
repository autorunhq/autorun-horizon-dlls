"""Pinned DXVK payload shared by the builder and AMD64 packager."""
import hashlib
import json
from pathlib import Path
import struct

VERSION = '3.1.1'
REVISION = 'b1a1c99ab52b687cf950d62c88bc2fa316b41663'
DLLS = ('d3d8.dll', 'd3d9.dll', 'd3d10core.dll', 'd3d11.dll', 'dxgi.dll')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_payload(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'dxvk-manifest.json').read_text())
    if (manifest.get('version'), manifest.get('revision'), manifest.get('architecture')) != (
            VERSION, REVISION, 'x86_64'):
        raise ValueError('DXVK payload does not match the pinned AMD64 release')
    for name in DLLS:
        path = directory / name
        data = path.read_bytes()
        if len(data) < 64 or data[:2] != b'MZ':
            raise ValueError(f'Invalid DXVK PE image: {path}')
        offset = struct.unpack_from('<I', data, 0x3c)[0]
        if (offset > len(data) - 26 or data[offset:offset + 4] != b'PE\0\0' or
                struct.unpack_from('<H', data, offset + 4)[0] != 0x8664 or
                struct.unpack_from('<H', data, offset + 24)[0] != 0x20b or
                not struct.unpack_from('<H', data, offset + 22)[0] & 0x2000):
            raise ValueError(f'DXVK DLL is not AMD64 PE32+: {path}')
        if manifest.get('files', {}).get(name) != digest(path):
            raise ValueError(f'DXVK payload hash mismatch: {path}')
    for name in manifest.get('licenses', []):
        if Path(name).name != name or not (directory / 'licenses' / name).is_file():
            raise ValueError(f'Missing DXVK license: {name}')
    if not manifest.get('licenses'):
        raise ValueError('DXVK payload lacks licenses')
    return manifest

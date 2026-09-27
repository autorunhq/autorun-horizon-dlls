import importlib.util
import os
from pathlib import Path
import re
import sys
import tempfile

repo = Path(__file__).resolve().parents[1]
os.environ.setdefault('AUTORUN', str(repo.parent))
sys.path.insert(0, str(repo / 'tools'))
spec = importlib.util.spec_from_file_location('registry', repo / 'tools/make-classes-reg.py')
registry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registry)

card = repo / 'switch/wine'
modules = ('rsaenh.dll', 'dssenh.dll')
native = [card / 'drive_c/windows/system32' / name for name in modules]
wow64 = [card / 'drive_c/windows/syswow64' / name for name in modules]
lines = registry.crypto_registry(native)
assert lines == registry.crypto_registry(wow64)
assert lines == registry.crypto_registry(native + wow64)
assert registry.crypto_registry([Path('unrelated.dll')]) == []

text = '\n'.join(lines)
keys = dict(re.findall(r'^\[([^\n]+)\]\n([^\[]+)', text, re.M))
prefix = r'Software\\Microsoft\\Cryptography\\Defaults'
providers = {
    'Microsoft Base Cryptographic Provider v1.0': ('rsaenh.dll', 1),
    'Microsoft Enhanced Cryptographic Provider v1.0': ('rsaenh.dll', 1),
    'Microsoft Strong Cryptographic Provider': ('rsaenh.dll', 1),
    'Microsoft RSA SChannel Cryptographic Provider': ('rsaenh.dll', 12),
    'Microsoft Enhanced RSA and AES Cryptographic Provider': ('rsaenh.dll', 24),
    'Microsoft Enhanced RSA and AES Cryptographic Provider (Prototype)': ('rsaenh.dll', 24),
    'Microsoft Base DSS Cryptographic Provider': ('dssenh.dll', 3),
    'Microsoft Base DSS and Diffie-Hellman Cryptographic Provider': ('dssenh.dll', 13),
    'Microsoft Enhanced DSS and Diffie-Hellman Cryptographic Provider': ('dssenh.dll', 13),
    'Microsoft DH SChannel Cryptographic Provider': ('dssenh.dll', 18),
}
assert len(keys) == 16
for name, (dll, kind) in providers.items():
    values = keys[prefix + r'\\Provider\\' + name]
    assert f'"Image Path"="C:\\\\windows\\\\system32\\\\{dll}"' in values
    assert f'"Type"=dword:{kind:08x}' in values
    if dll == 'rsaenh.dll':
        assert '"Signature"=hex:de,ad,be,ef' in values
for kind in (1, 3, 12, 13, 18, 24):
    values = keys[prefix + rf'\\Provider Types\\Type {kind:03}']
    name = re.search(r'^"Name"="([^\n]+)"$', values, re.M).group(1)
    assert providers[name][1] == kind
assert 'syswow64' not in text and '%MODULE%' not in text

published = (card / 'horizon-dlls/classes.reg').read_text()
assert all(f'[{key}]\n{values.rstrip()}' in published for key, values in keys.items())
with tempfile.TemporaryDirectory() as directory:
    missing = Path(directory) / 'rsaenh.dll'
    missing.write_bytes(b'no registration resource')
    try:
        registry.crypto_registry([missing])
    except ValueError:
        pass
    else:
        raise AssertionError('missing registration was accepted')
print('Crypto registry: both architectures, 10 providers, 6 default types and duplicate suppression passed')

import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import urllib.request

REPOSITORY = 'https://github.com/ThirteenAG/Ultimate-ASI-Loader'
REVISION = '071dcede74841a311b801e111e2872487139430a'
SOURCES = {
    'source/xlive/xliveless.cpp': '2de44cf04de23f0b12934ced834ecbfe18b0db5ef73384cacbe61b4c7fb6a53c',
    'source/xlive/xliveless.h': 'f32ff65e29f8d9c1851fcf314ca01fd18daf80d4df06f2ceed4ec3e38108a6d4',
    'source/xlive/xliveless.rc': '8ed61cf1d73e832cbe6f496bc585751f415b72ba7551062d461ab3a07e782279',
    'source/xlive/resource.h': '2cd7cb892473b4f5eee36bbd0b53a1a54fb91d53708099895f5405e6695d4774',
    'source/x86.def': '1638cb2af74e71a5f2af2feaf395773612788f073333187d8ed37f9ba1173270',
    'license': 'ceca73c504e39084b0b80d2a437aea9988313d1915418d3c629c3e4a8313f5a1',
}


def build_xlive(cache, toolchain=None):
    build = cache / ('xlive-' + REVISION)
    build.mkdir(parents=True, exist_ok=True)
    for name, expected in SOURCES.items():
        target = build / name
        data = target.read_bytes() if target.exists() else urllib.request.urlopen(
            f'https://raw.githubusercontent.com/ThirteenAG/Ultimate-ASI-Loader/{REVISION}/{name}',
            timeout=60).read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f'XLiveLess checksum mismatch: {name}')
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if name.startswith('source/'):
            generated = build / 'compile' / name
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text(data.decode('utf-16' if data[:2] == b'\xff\xfe' else 'utf-8'),
                                 encoding='utf-8')

    env = os.environ.copy()
    toolchain = toolchain or (Path(env['WINE_NX_LLVM_MINGW']) / 'bin'
                              if env.get('WINE_NX_LLVM_MINGW') else None)
    if toolchain:
        env['PATH'] = str(toolchain) + os.pathsep + env['PATH']
    tools = {}
    for name in ('i686-w64-mingw32-clang++', 'i686-w64-mingw32-windres', 'llvm-nm', 'llvm-readobj'):
        tools[name] = shutil.which(name, path=env['PATH'])
        if not tools[name]:
            raise RuntimeError(f'Missing {name}; set WINE_NX_LLVM_MINGW')
    source = build / 'compile/source'
    obj = build / 'xlive.o'
    flags = ['-Os', '-DNDEBUG', '-DUNICODE', '-D_UNICODE', '-D_CRT_SECURE_NO_WARNINGS',
             '-std=c++17', '-fno-exceptions', '-fno-rtti', '-ffunction-sections', '-fdata-sections']
    subprocess.run([tools['i686-w64-mingw32-clang++'], *flags, '-I', str(source),
                    '-c', str(source / 'xlive/xliveless.cpp'), '-o', str(obj)], env=env, check=True)
    symbols = subprocess.check_output([tools['llvm-nm'], '--defined-only', '--extern-only',
                                       '--format=posix', str(obj)], text=True)
    functions = {}
    for line in symbols.splitlines():
        symbol, kind, *_ = line.split()
        match = re.match(r'__Z(\d+)', symbol)
        if kind == 'T' and match:
            name = symbol[match.end():match.end() + int(match[1])]
            if name in functions:
                raise ValueError(f'Ambiguous XLive export: {name}')
            functions[name] = symbol[1:]
    table = re.search(r'LIBRARY "xlive"\s+EXPORTS\s+(.*?)(?=\nLIBRARY)',
                      (source / 'x86.def').read_text(), re.S)[1]
    exports = re.findall(r'^([A-Za-z_][A-Za-z_0-9]*)\s+@(\d+)\s*$', table, re.M)
    definition = build / 'xlive.def'
    definition.write_text('LIBRARY xlive\nEXPORTS\n' + ''.join(
        f'{name}={functions[name]} @{ordinal}\n' for name, ordinal in exports))
    resources = build / 'xlive-res.o'
    subprocess.run([tools['i686-w64-mingw32-windres'], '-I', str(source / 'xlive'),
                    '-i', str(source / 'xlive/xliveless.rc'), '-o', str(resources)], env=env, check=True)
    dll = build / 'xlive.dll'
    wrapper = Path(__file__).resolve().parents[1] / 'runtime/xlive/dllmain.cpp'
    subprocess.run([tools['i686-w64-mingw32-clang++'], *flags, '-shared', '-static', '-s',
                    str(wrapper), str(obj), str(resources), str(definition), '-lws2_32', '-luser32',
                    '-Wl,--no-insert-timestamp,--gc-sections,--exclude-all-symbols',
                    '-o', str(dll)], env=env, check=True)
    actual = subprocess.check_output([tools['llvm-readobj'], '--coff-exports', str(dll)], text=True)
    actual = re.findall(r'Ordinal: (\d+)\s+Name: (\S+)', actual)
    if set(actual) != {(ordinal, name) for name, ordinal in exports}:
        raise ValueError('XLiveLess exports do not match upstream')
    return dll.read_bytes(), (build / 'license').read_bytes()

"""The Autorun checkout this repository builds from: --autorun PATH, the
AUTORUN environment variable, or the checkout it is a submodule of."""
from pathlib import Path
import os
import subprocess
import sys

repo = Path(__file__).resolve().parents[1]


def checkout():
    for i, arg in enumerate(sys.argv):
        if arg == '--autorun' and i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1]).resolve()
        if arg.startswith('--autorun='):
            return Path(arg.split('=', 1)[1]).resolve()
    if os.environ.get('AUTORUN'):
        return Path(os.environ['AUTORUN']).resolve()
    found = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--show-superproject-working-tree'],
                           text=True, stdout=subprocess.PIPE).stdout.strip()
    if not found:
        raise SystemExit('not inside an Autorun checkout; pass --autorun PATH or set AUTORUN')
    return Path(found)


root = checkout()
probe = root / 'wine-nx-probe'
toolchain = Path(os.environ.get('WINE_NX_LLVM_MINGW',
                                probe / 'toolchains/llvm-mingw-20260505-ucrt-macos-universal')) / 'bin'

#!/usr/bin/env python3
"""Build this repository's DLLs: every Windows module Autorun runs, and write
the ones that changed over switch/ here.

    tools/build-dlls.py [--autorun PATH] [--allow-dirty] [--no-build] [--all]

The repository is a submodule of Autorun (horizon-dlls/), and the Wine it
builds from is the Autorun checkout around it; --autorun names another. The
build tree is Autorun's wine-nx-probe/build-wine-amd64-pe (aarch64, arm64ec and
i386), whose system32 modules are ARM64X: native ARM64 code and ARM64EC in one
file, so the one set serves the x86 runtime and the AMD64 one alike.

What is here:

- all of system32 and syswow64: every DLL, driver and program Wine's PE build
  makes, stripped of the debug information the build tree keeps for logs;
- Autorun's winenxaudio.drv, for each side;
- FEX's ARM64EC and WoW64 CPU modules (tools/build-fex.sh);
- the bundled DXVK and VKD3D-Proton: C:\\dxvk\\d3d9.dll for 32-bit programs,
  C:\\dxvk64 and C:\\vkd3d64 for 64-bit ones (tools/build-dxvk.py,
  tools/build-vkd3d.py);
- classes.reg, the COM classes those files serve, which the runtime loads as
  DllRegisterServer would have written them on a PC.

Every file has a category, the part of Windows it belongs to (the Direct3D
family, the C runtimes, networking...), for showing a player what is there.

The repo is laid out as the SD card is: each file at switch/wine/<path>/<name>
and the manifest at switch/wine/horizon-dlls/manifest.json, which is also what a
card keeps to know what it has. A download of the repo is what a player without
a network copies to the card.

Only what changed is rebuilt. A Wine module is rebuilt when one of its inputs
changed since the commit the manifest was built from: its sources, the headers
they include, the import libraries it links and the tools that build it, all as
Wine's own make knows them. Everything else keeps the file and the version it
has, so a build on another computer does not turn every file into a new one. A
file built from other sources (FEX, DXVK, VKD3D-Proton, the audio driver) keeps
a digest of its recipe and inputs, and is rebuilt when that changes. --all
rebuilds everything, for a new toolchain.

A file's version changes only when its bytes do, so a card downloads only what
changed, and git keeps one copy of a file however many commits carry it.
Committing and pushing is what publishes it.

A module that calls straight into the runtime needs a runtime built against
the same interface. Its entry requires the features the runtime reports for
that: unixlib:<name> or unixlib32:<name> for being in the runtime's static
unix-call tables (read from dlls/ntdll/unix/virtual.c), and iface:<name>:<hash>
for the headers runtime-interfaces.json lists for it. Autorun leaves a file its
runtime does not satisfy as it is.

Every file names the commit it was built from, and whether its sources changed
since Wine was imported, which is what the LGPL asks of a changed library.
Sources with changes that are not committed stop the build, since the source
the manifest points to would not be what the file was built from; --allow-dirty
is for trying the build, and marks the commit so.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

from autorun import root, probe, toolchain

repo = Path(__file__).resolve().parents[1]
tools = Path(__file__).resolve().parent
pe = Path(os.environ.get('WINE_NX_PE_BUILD_DIR', probe / 'build-wine-amd64-pe')).resolve()
assert (root / 'dlls/ntdll').is_dir() and (pe / 'Makefile').is_file(), \
    f'{root} is not an Autorun checkout with a configured {pe.name}'

DLL_REPO = 'autorunhq/autorun-horizon-dlls'
SOURCE_REPO = 'autorunhq/autorun'
RAW = f'https://raw.githubusercontent.com/{DLL_REPO}'
# Where a card, and the repo, keep these; relative to switch/wine.
MANIFEST = 'horizon-dlls/manifest.json'
CLASSES = 'horizon-dlls/classes.reg'
# The commit that first imported Wine into Autorun.
WINE_IMPORT = 'eaa5b16e'
WINE_VERSION = re.search(r'([\d.]+)', (root / 'VERSION').read_text()).group(1)
SCHEMA = 2
# The runtimes these files are for: ARM64X system32, i386 syswow64.
FLAVOR = 'arm64x'
# Where each architecture's modules go, as on Windows on ARM.
ARCHES = {'i386': 'drive_c/windows/syswow64', 'aarch64': 'drive_c/windows/system32'}
MODULE = r'(?:dll|drv|exe|sys|ocx|cpl|acm|ax|tlb|ds|msstyles|dll16|drv16|exe16|mod16|vxd)'
# Wine's test runner carries every test program inside it, hundreds of MB per
# architecture, over what GitHub keeps in one file; it is no part of Windows.
# Nor are the drivers for what the build computer has and the Switch does not:
# the macOS display, OpenCL, smart-card readers and packet capture, whose unix
# halves the runtime does not carry.
EXCLUDE = {'winetest.exe', 'winemac.drv', 'opencl.dll', 'winscard.dll', 'wpcap.dll'}
# Changes to these can change how every module is built.
EVERYTHING = {'configure', 'configure.ac', 'tools/makedep.c', 'VERSION'}

# The part of Windows each file belongs to, by name; the first that matches.
CATEGORIES = [
    ('legacy-16bit', 'Windows 3.x and 9x: the 16-bit modules, VxDs and Win32s old programs and installers load',
     r'.*\.(dll16|drv16|exe16|mod16|vxd)|win32s16\.dll|w32skrnl\.dll|w32sys\.dll|wow32\.dll|vdmdbg\.dll'),
    ('drivers', 'Kernel-mode drivers: the device, bus, file system and network stacks under Windows',
     r'.*\.sys'),
    ('core', 'The NT layer, the Win32 base and the WoW64 and CPU emulation layers every program runs on',
     r'(ntdll|wow64|wow64win|wow64cpu|win32u|winebox64|winebox64ec|xtajit|xtajit64|libarm64ecfex|'
     r'libwow64fex|apisetschema|kernel32|kernelbase|user32|gdi32|advapi32|sechost|rpcrt4|imm32|'
     r'version|psapi|dbghelp|imagehlp|cfgmgr32|setupapi|powrprof|userenv|profapi|lz32|toolhelp|'
     r'ktmw32|fltlib|virtdisk|wofutil)\.dll'),
    ('directx-graphics', 'Direct3D 1 to 12, DirectDraw, DXGI, Direct2D, the D3DX libraries and the shader compilers',
     r'(d3d\w*|ddraw\w*|dxgi|wined3d|d3drm|d3dxof|d3dx\d+_\d+|d3dcompiler_\d+|dxcore|dxva2|'
     r'd2d1|dcomp|dxdiagn|dx8vb|dciman32|graphicscapture|vga)\.dll'),
    ('directx-audio', 'DirectSound, XAudio2, X3DAudio, XAPOFX, XACT and DirectMusic',
     r'(dsound|dsdmo|xaudio2_\d+|x3daudio1_\d+|xapofx1_\d+|xactengine\d_\d+|dmusic|dmusic32|dmime|'
     r'dmloader|dmstyle|dmsynth|dmband|dmcompos|dmscript|dswave|hrtfapo)\.dll'),
    ('directx-input', 'DirectInput, XInput, GameInput and game controllers',
     r'(dinput8?|xinput\w*|joy|hid|gameinput|windows\.gaming\.input)\.(dll|cpl)'),
    ('directx-play', 'DirectPlay',
     r'(dplay|dplayx|dpnet|dpwsockx|dpnhpast|dpnhupnp|dpnlobby|dpvoice|dpnaddr)\.dll'),
    ('directx-media', 'DirectShow, Media Foundation, Video for Windows and the codecs they use',
     r'(quartz|qcap|qedit|qdvd|qasf|amstream|devenum|msdmo|mf\w*|evr|winegstreamer|winedmo|l3codeca|'
     r'l3codecx|msvfw32|avifil32|avicap32|mciavi32|mciqtz32|iccvid|msvidc32|ir50_32|iyuv_32|msrle32|'
     r'msadp32|imaadp32|msg711|msgsm32|mp3dmod|colorcnv|wmvcore|wmphoto|wmp|wmasf|wmadmod|wmvdecod|'
     r'resampledmo|msmpeg2vdec|msmpeg2adec|mpeg2data|vidreszr|msauddecmft|msvproc|msvdsp|rtworkq|'
     r'strmdll|ksproxy|ksuser|dxtrans|windows\.media(\.\w+)*)\.(dll|acm|ax)'),
    ('translation-layers', 'DXVK and VKD3D-Proton: Direct3D 8 to 12 drawn with Vulkan', None),
    ('gaming', 'The Game Explorer, Game Bar and the other parts of Windows that are there for games',
     r'(gameux|gamingtcui|windows\.gaming\.ui\.gamebar)\.dll'),
    ('audio', 'Windows audio outside DirectX: the multimedia API, MCI, the audio endpoints, speech and the Switch audio driver',
     r'(winmm|mmdevapi|winenxaudio|midimap|msacm32|audioses|avrt|wdmaud|sound|mcicda|mciseq|mciwave|'
     r'sapi|msttsengine|winealsa|winecoreaudio|winepulse|wineoss)\.(dll|drv)'),
    ('opengl-vulkan', 'OpenGL and Vulkan', r'(opengl32|glu32|vulkan-1|winevulkan|wgl)\.dll'),
    ('imaging-text', 'GDI+, the image codecs, fonts, text layout and code pages',
     r'(gdiplus|windowscodecs\w*|dwrite|usp10|fontsub|t2embed|msimg32|icm32|mscms|icmui|'
     r'photometadatahandler|textshaping|fntcache|icuuc|icuin|mlang|msls31|atmlib|tzres|bcp47langs)\.dll'),
    ('c-runtime', 'The C and C++ runtimes: MSVCRT, the Visual C++ redistributables, the UCRT, ATL and MFC',
     r'(msvcr\w*|msvcp\w*|msvcirt|vcruntime\w*|concrt\d+|ucrtbase|vcomp\w*|crtdll|atl\d*|atlthunk|'
     r'mfc\d+\w*|msvcm\d+|vccorlib\d+|unicows)\.dll'),
    ('dotnet', '.NET: the runtime host Mono or .NET is loaded through',
     r'(mscoree|mscorwks|fusion|mscorlib|clrjit|clr|diasymreader)\.dll'),
    ('com-ole', 'COM, OLE, Automation and the script engines',
     r'(ole32|oleaut32|combase|coml2|olepro32|oledlg|olecli32|olesvr32|olethk32|actxprxy|comcat|'
     r'stdole2|stdole32|compobj|typelib|hlink|iprop|dispex|scrrun|vbscript|jscript|msscript|scrobj|'
     r'wshom|chakra|mtxdm|comsvcs|dataexchange|ia2comproxy)\.(dll|tlb|ocx)'),
    ('winrt', 'The Windows Runtime and its Windows.* components',
     r'(windows(\.\w+)+|wintypes|rometadata|twinapi(\.\w+)*|threadpoolwinrt|coremessaging)\.dll'),
    ('xml', 'MSXML and XmlLite', r'(msxml\d*|msxml\w*|xmllite|xolehlp|opcservices)\.dll'),
    ('data', 'Databases: ODBC, ADO, OLE DB, the ESE engine and SQLite',
     r'(odbc\w*|msdasql|msado15|msdaps|oledb32|esent|winsqlite3|query|infosoft|itircl)\.dll'),
    ('network', 'Sockets, HTTP, the Internet APIs, telephony, wireless and directory services',
     r'(ws2_32|wsock32|mswsock|wininet|winhttp|iphlpapi|dnsapi|netapi32|urlmon|httpapi|webservices|'
     r'rasapi32|rasdlg|nsi|winnsi|wldap32|netprofm|mpr|dhcpcsvc\w*|wnaspi32|sensapi|normaliz|ndfapi|'
     r'wkscli|srvcli|srvsvc|netutils|winsta|fwpuclnt|firewallapi|hnetcfg|mprapi|netcfgx|qwave|'
     r'activeds|adsldp|adsldpc|dsrole|dsquery|dsuiext|ntdsapi|objsel|wsdapi|websocket|msnet32|'
     r'ondemandconnroutehelper|inetmib1|snmpapi|mgmtapi|wsnmp32|icmp|tapi32|wlanapi|wlanui|'
     r'bluetoothapis|bthprops|irprops|traffic|davclnt|cldapi|connect|qmgr|qmgrprxy|inetcomm|'
     r'msident|mapi32|mapistub|winemapi|cdosys|rtutils|rtscom|nddeapi|svrapi|clusapi|resutils)\.(dll|cpl)'),
    ('security', 'Cryptography, certificates, credentials and authentication',
     r'(crypt\w*|bcrypt\w*|ncrypt|rsaenh|dssenh|rsabase|wintrust|secur32|security|schannel|sspicli|'
     r'kerberos|msv1_0|negotiate|credui|authz|cng|softpub|mssign32|mssip32|msisip|mscat32|msasn1|'
     r'pstorec|dpapi|keyiso|sas|samlib|lsa\w*|vaultcli|symcrypt|scarddlg|scardsvr|winscard|slc|sppc|'
     r'webauthn|amsi|gpkcsp|slbcsp|sccbase|initpki|drmclien|msdrm|tbs|wldp|pidgen|winbio|'
     r'hvsimanagementapi|feclient)\.dll'),
    ('shell-ui', 'The shell, common controls and dialogs, themes, input, accessibility and the browser control',
     r'\w+\.msstyles|(shell32|shlwapi|comctl32\w*|comdlg32|uxtheme|shcore|propsys|shdocvw|ieframe|'
     r'browseui|explorerframe|oleacc|uiautomationcore|dwmapi|mshtml|jsproxy|hhctrl|itss|shdoclc|'
     r'shfolder|thumbcache|zipfldr|inetcpl|appwiz|desk|intl|timedate|sti|twaindsm|tiptsf|msctf|'
     r'msctfp|msctfmonitor|msimtf|input|msftedit|riched20|riched32|cards|acledit|aclui|magnification|'
     r'uianimation|uiribbon|directmanipulation|ninput|inkobj|dhtmled|npmshtml|ieproxy|iertutil|url|'
     r'packager|serialui|newdev|geolocation|wintab32|winbrand|utildll)\.(dll|cpl|ocx|tlb)'),
    ('printing', 'Printing', r'(winspool|compstui|localspl|localui|spoolss|prntvpt|wineps|ntprint|'
     r'printui|winprint|xpsprint|xpssvcs)\.(drv|dll)'),
    ('installers', 'Installing and updating: Windows Installer, cabinets, patches, side-by-side and Windows Update',
     r'(msi|msisys|msimsg|cabinet|advpack|inseng|mspatcha|msdelta|updspapi|difxapi|wuapi|wuaueng|sxs|'
     r'sfc|sfc_os|srclient|appxdeploymentclient|wimgapi|wdscore|vssapi)\.(dll|ocx)'),
    ('programs', 'Windows programs: the command prompt, Notepad, the registry editor and the rest', r'.*\.exe'),
    ('system', 'The rest of Windows: services, event logs, performance counters, WMI and devices', r'.*'),
]

# The licenses of what the files are built from: Wine, compiler-rt, which the
# build links into every module, and the libraries some of them link in (by the
# $(NAME_PE_LIBS) their Makefile.in imports). Paths are Autorun's.
ALWAYS = ['wine', 'compiler-rt']
LICENSES = {
    'wine': ('LGPL-2.1-or-later', 'COPYING.LIB', 'Wine'),
    'compiler-rt': ('NCSA OR MIT', 'libs/compiler-rt/LICENSE.TXT', 'compiler-rt'),
    'capstone': ('BSD-3-Clause', 'libs/capstone/LICENSE.TXT', 'Capstone'),
    'musl': ('MIT', 'libs/musl/COPYRIGHT', 'musl'),
    'faudio': ('Zlib', 'libs/faudio/LICENSE', 'FAudio'),
    'ffmpeg': ('LGPL-2.1-or-later', 'libs/ffmpeg/LICENSE.md', 'FFmpeg'),
    'fluidsynth': ('LGPL-2.1-or-later', 'COPYING.LIB', 'FluidSynth'),
    'gsm': ('TU-Berlin-2.0', 'libs/gsm/COPYRIGHT', 'libgsm'),
    'icucommon': ('Unicode-DFS-2016 AND ICU', 'libs/icucommon/LICENSE', 'ICU Common'),
    'icui18n': ('Unicode-DFS-2016 AND ICU AND BSD-3-Clause', 'libs/icui18n/LICENSE', 'ICU I18N'),
    'jpeg': ('IJG', 'libs/jpeg/LICENSE', 'libjpeg'),
    'jxr': ('BSD-2-Clause', 'libs/jxr/LICENSE', 'jxrlib'),
    'lcms2': ('MIT', 'libs/lcms2/COPYING', 'Little CMS'),
    'ldap': ('OLDAP-2.8', 'libs/ldap/LICENSE', 'OpenLDAP'),
    'mpg123': ('LGPL-2.1-only', 'libs/mpg123/LICENSE', 'mpg123'),
    'png': ('Libpng', 'libs/png/LICENSE', 'libpng'),
    'sqlite3': ('blessing', tools / 'sqlite-blessing.txt', 'SQLite'),
    'symcrypt': ('MIT', 'libs/symcrypt/LICENSE.txt', 'SymCrypt'),
    'tiff': ('libtiff', 'libs/tiff/COPYRIGHT', 'libtiff'),
    'tomcrypt': ('Unlicense', 'libs/tomcrypt/LICENSE', 'LibTomCrypt'),
    'vkd3d': ('LGPL-2.1-or-later', 'libs/vkd3d/COPYING', 'vkd3d'),
    'xml2': ('MIT', 'libs/xml2/COPYING', 'libxml2'),
    'xslt': ('MIT', 'libs/xslt/COPYING', 'libxslt'),
    'zlib': ('Zlib', 'libs/zlib/LICENSE', 'zlib'),
}

env = dict(os.environ, AUTORUN=str(root),
           PATH=os.pathsep.join((str(toolchain), '/opt/homebrew/opt/bison/bin', os.environ['PATH'])))

def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

def repo_git(*args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()

def readobj(option, path):
    return subprocess.check_output([str(toolchain / 'llvm-readobj'), option, str(path)], text=True)

def run(*command, **kwargs):
    subprocess.run([str(c) for c in command], env=env, check=True, **kwargs)

# What a runtime reports, which is what the files here require of it: the same
# reading of the same sources the runtime's own build makes.
spec = importlib.util.spec_from_file_location('runtime_features', probe / 'tools/runtime_features.py')
runtime_features = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime_features)
static_unix_libs, interfaces = runtime_features.static_unix_libs, runtime_features.interfaces

spec = importlib.util.spec_from_file_location('classes', tools / 'make-classes-reg.py')
classes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classes)
# The IDL of some DLLs includes headers widl generates in the build tree.
os.environ['WINE_NX_PE_BUILD_DIR'] = str(pe)


# --- What Wine's make builds, and from what -----------------------------------

def make_database():
    return subprocess.run(['make', '-C', str(pe), '-pnq', 'all'], env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout

def targets(database):
    """Every PE module Wine's make builds, as (arch, source dir, file name)."""
    found = set(re.findall(rf'\b((?:dlls|programs)/[^ :/]+)/(i386|aarch64)-windows/([^ :/]+\.{MODULE})\b', database))
    return sorted((arch, directory, name) for directory, arch, name in found if name.lower() not in EXCLUDE)

class Inputs:
    """The files in the Autorun checkout each make target is built from, by
    following the prerequisites make lists for it down to the sources."""

    def __init__(self, database):
        self.rules = {}
        for line in database.splitlines():
            match = re.match(r'^([^\s#%][^:=]*?):(?![:=])(.*)$', line)
            if not match or '=' in match.group(1):
                continue
            prerequisites = match.group(2).split('|')[0].split()
            for target in match.group(1).split():
                self.rules.setdefault(target, []).extend(prerequisites)
        self.memo = {}
        self.prefix = str(root) + os.sep
        self.build = str(pe) + os.sep

    def source(self, name):
        """The checkout-relative path of a prerequisite, if it is a file in the
        checkout rather than something the build tree makes."""
        path = os.path.normpath(os.path.join(str(pe), name))
        if path.startswith(self.prefix) and not path.startswith(self.build):
            return path[len(self.prefix):]
        return None

    def of(self, target):
        pending, order = [target], []
        while pending:
            node = pending.pop()
            if node in self.memo:
                continue
            if node is None:
                continue
            self.memo[node] = None
            order.append(node)
            pending.extend(p for p in self.rules.get(node, ()) if p not in self.memo)
        for node in reversed(order):
            found = set()
            own = self.source(node)
            if own:
                found.add(own)
            for p in self.rules.get(node, ()):
                if self.memo.get(p) is not None:
                    found |= self.memo[p]
                else:
                    own = self.source(p)
                    if own:
                        found.add(own)
            self.memo[node] = frozenset(found)
        return self.memo[target]

def makefile(directory):
    text = (root / directory / 'Makefile.in').read_text()
    return dict(re.findall(r'^(\w+)\s*=\s*(.*(?:\\\n.*)*)', text, re.M))

def libraries(directory):
    """The bundled libraries a module links in, by name under libs/."""
    imports = makefile(directory).get('IMPORTS', '')
    return sorted(lib.lower() for lib in re.findall(r'\$\((\w+)_PE_LIBS\)', imports)
                  if (root / 'libs' / lib.lower()).is_dir())

def sources(directory):
    """The directories a module is built from: its own, the one it shares
    sources with, and the bundled libraries it links in."""
    paths = [directory]
    parent = makefile(directory).get('PARENTSRC')
    if parent:
        paths.append(os.path.normpath(f'{directory}/{parent.strip()}'))
    return paths + [f'libs/{lib}' for lib in libraries(directory)]

def category_of(name):
    for category, _, pattern in CATEGORIES:
        if pattern and re.fullmatch(pattern, name.lower()):
            return category
    raise AssertionError(name)

def stripped(path, into):
    """The file without its debug information, as the repository carries it."""
    out = into / path.name
    into.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(toolchain / 'llvm-strip'), '--strip-debug', '-o', str(out), str(path)], check=True)
    return out


# --- Files built from other sources -------------------------------------------

def pin(identity, autorun_inputs=(), repo_inputs=()):
    """A digest of a recipe and everything it reads, which names a build of it."""
    digest = hashlib.sha256(identity.encode())
    for base, paths in ((root, autorun_inputs), (repo, repo_inputs)):
        for path in paths:
            files = sorted(p for p in (base / path).rglob('*') if p.is_file()) if (base / path).is_dir() \
                else [base / path]
            for file in files:
                digest.update(str(file.relative_to(base)).encode() + b'\0' + file.read_bytes())
    return digest.hexdigest()[:16]

AUDIO_FLAGS = ['-Os', '-Wall', '-Wextra', '-Werror', '-fno-builtin', '-nostdlib', '-shared',
               '-Wl,--dynamicbase',
               # the same bytes every build, as Wine's own modules are, so its
               # version changes only when its source does
               '-Wl,--no-insert-timestamp']

def build_audio_drivers(scratch):
    """Autorun's audout driver, as winmm loads it on each side."""
    built = []
    for compiler, arch, directory, entry in (('i686', 'i386', 'syswow64', '_DllMain@12'),
                                              ('x86_64', 'x86_64', 'system32', 'DllMain')):
        driver = scratch / arch / 'winenxaudio.drv'
        driver.parent.mkdir(parents=True, exist_ok=True)
        run(toolchain / f'{compiler}-w64-mingw32-clang', *AUDIO_FLAGS, f'-Wl,--entry,{entry}',
            '-o', driver, probe / 'source/audio_driver.c')
        assert b'winenxaudio.drv\0' in driver.read_bytes(), 'the audio driver has no module identity'
        built.append(dict(file=driver, name='winenxaudio.drv', path=f'drive_c/windows/{directory}', arch=arch))
    return built

def build_fex(scratch):
    run('sh', tools / 'build-fex.sh')
    payload = probe / 'toolchains/build-fex-2609-horizon/payload'
    manifest = json.loads((payload / 'fex-manifest.json').read_text())
    return [dict(file=payload / name, name=name, path='drive_c/windows/system32',
                 arch='arm64ec' if 'arm64ec' in name else 'aarch64') for name in ('libarm64ecfex.dll', 'libwow64fex.dll')] + \
        [dict(license=(payload / 'licenses' / name, Path(name).stem)) for name in manifest['licenses']]

def build_dxvk64(scratch):
    run(sys.executable, tools / 'build-dxvk.py')
    payload = probe / 'build-dxvk-amd64/payload'
    manifest = json.loads((payload / 'dxvk-manifest.json').read_text())
    return [dict(file=payload / name, name=name, path='drive_c/dxvk64', arch='x86_64')
            for name in list(manifest['files']) + ['dxvk-manifest.json']] + \
        [dict(license=(payload / 'licenses' / name, Path(name).stem)) for name in manifest['licenses']]

def build_vkd3d64(scratch):
    run(sys.executable, tools / 'build-vkd3d.py')
    payload = probe / 'build-vkd3d-amd64/payload'
    manifest = json.loads((payload / 'vkd3d-manifest.json').read_text())
    return [dict(file=payload / name, name=name, path='drive_c/vkd3d64', arch='x86_64')
            for name in list(manifest['files']) + ['vkd3d-manifest.json']] + \
        [dict(license=(payload / 'licenses' / name, Path(name).stem)) for name in manifest['licenses']]

def build_dxvk_d3d9(scratch):
    """DXVK's d3d9 for 32-bit programs, from the same pinned DXVK as C:\\dxvk64.
    A program uses it from C:\\dxvk, or copied beside its executable."""
    run(sys.executable, tools / 'build-dxvk.py')
    source, build = probe / 'vendor/dxvk', probe / 'build-dxvk-i386'
    if not (build / 'build.ninja').is_file():
        build.mkdir(parents=True, exist_ok=True)
        cross = build / 'llvm-mingw-i386.txt'
        binaries = ''.join(f"{role} = '{toolchain}/i686-w64-mingw32-{tool}'\n" for role, tool in
                           (('c', 'clang'), ('cpp', 'clang++'), ('ar', 'ar'), ('strip', 'strip'),
                            ('windres', 'windres')))
        cross.write_text('[binaries]\n' + binaries + '''
[properties]
needs_exe_wrapper = true

[host_machine]
system = 'windows'
cpu_family = 'x86'
cpu = 'x86'
endian = 'little'
''')
        run('meson', 'setup', build, source, '--cross-file', cross, '--buildtype', 'release', '--strip',
            '--wrap-mode=nodownload', '-Denable_d3d9=true', '-Denable_d3d8=false', '-Denable_d3d10=false',
            '-Denable_d3d11=false', '-Denable_dxgi=false')
    run('ninja', '-C', build, 'src/d3d9/d3d9.dll')
    d3d9 = scratch / 'dxvk' / 'd3d9.dll'
    d3d9.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / 'src/d3d9/d3d9.dll', d3d9)
    say_directx9(d3d9)
    return [dict(file=d3d9, name='d3d9.dll', path='drive_c/dxvk', arch='i386')]

def say_directx9(path):
    """Make d3d9.dll report the version a Direct3D 9 runtime has.

    DXVK's version resource says 10.0.17763.1, the Windows 10 system DLL it
    stands in for. A game from the Direct3D 9 years reads that resource to
    decide whether DirectX 9 is installed, and reads the major and minor of a
    version it was written before: Halo takes 10.0 for something older than
    9.0b and refuses to start. Wine's own d3d9.dll says 5.3.1.904, which is
    what the DirectX 9.0c file says, so this says the same. Patched in the
    built DLL rather than in the DXVK tree, which is not ours.
    """
    data = bytearray(path.read_bytes())
    version = (5, 3, 1, 904)
    ms, ls = (version[0] << 16) | version[1], (version[2] << 16) | version[3]
    fixed = b'\xbd\x04\xef\xfe'
    patched = 0
    at = data.find(fixed)
    while at >= 0:
        # signature, struct version, then file and product version, MS before LS
        struct.pack_into('<IIII', data, at + 8, ms, ls, ms, ls)
        patched += 1
        at = data.find(fixed, at + 4)
    assert patched, f'{path} has no version resource to correct'
    # The strings beside it, kept the same length so the block does not move.
    text = '%d.%d.%d.%d' % version
    for old_text in ('10.0.17763.1 (WinBuild.160101.0800)', '10.0.17763.1'):
        new_text = text + ' ' * (len(old_text) - len(text))
        data = bytearray(data.replace(old_text.encode('utf-16-le'), new_text.encode('utf-16-le')))
    path.write_bytes(data)
    at = bytes(data).find(fixed)
    assert struct.unpack_from('<IIII', data, at + 8) == (ms, ls, ms, ls), f'{path} kept its version'

# name, what builds it, its category, license, and what it is built from: a
# recipe identity and the files it reads, in Autorun and here.
EXTRA = [
    dict(key='winenxaudio', build=build_audio_drivers, category='audio', origin='autorun',
         license=None, sources=['wine-nx-probe/source/audio_driver.c'],
         identity=' '.join(AUDIO_FLAGS), autorun_inputs=['wine-nx-probe/source/audio_driver.c']),
    dict(key='fex', build=build_fex, category='core', origin='fex', license='MIT',
         sources=['wine-nx-probe/fex'], identity='fex',
         autorun_inputs=['wine-nx-probe/fex'], repo_inputs=['tools/build-fex.sh', 'tools/fex_payload.py']),
    dict(key='dxvk64', build=build_dxvk64, category='translation-layers', origin='dxvk', license='Zlib',
         sources=[], identity='dxvk64', repo_inputs=['tools/build-dxvk.py', 'tools/dxvk_payload.py']),
    dict(key='vkd3d64', build=build_vkd3d64, category='translation-layers', origin='vkd3d-proton',
         license='LGPL-2.1-or-later', sources=[], identity='vkd3d64',
         repo_inputs=['tools/build-vkd3d.py', 'tools/vkd3d_payload.py']),
    dict(key='dxvk32', build=build_dxvk_d3d9, category='translation-layers', origin='dxvk', license='Zlib',
         sources=[], identity='dxvk-i386-d3d9 5.3.1.904',
         repo_inputs=['tools/build-dxvk.py', 'tools/dxvk_payload.py']),
]


# --- The build ----------------------------------------------------------------

def changed_since(base, allow_dirty):
    """What changed in the checkout since base, or None when that cannot be
    told (no base, or a base this history does not hold)."""
    if not base:
        return None
    base = base.removesuffix('-dirty')
    try:
        git('merge-base', '--is-ancestor', base, 'HEAD')
    except subprocess.CalledProcessError:
        return None
    changed = set(git('diff', '--name-only', base, 'HEAD').splitlines())
    if allow_dirty:
        changed |= {line[3:].split(' -> ')[-1] for line in git('status', '--porcelain').splitlines()}
    return changed

def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--autorun', type=Path, help='the Autorun checkout to build from')
    parser.add_argument('--allow-dirty', action='store_true', help='build from uncommitted sources, for trying it')
    parser.add_argument('--no-build', action='store_true', help='use what is built already')
    parser.add_argument('--all', action='store_true', help='rebuild everything, as for a new toolchain')
    parser.add_argument('--ref', default='main', help='repository branch that will publish the DLLs')
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 1)
    args = parser.parse_args()
    assert re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]*', args.ref) and '..' not in args.ref
    assert args.jobs > 0

    assert not repo_git('status', '--porcelain', '--', 'switch', 'compressed', 'LICENSES', 'README.md', 'NOTICE.md'), \
        f'{repo} has uncommitted changes to what it builds'
    card = repo / 'switch/wine'
    previous = json.loads((card / MANIFEST).read_text()) if (card / MANIFEST).exists() else None
    if previous:
        assert previous['schema'] in (1, SCHEMA), f"previous manifest is schema {previous['schema']}"
    earlier = {f"{f['path']}/{f['name']}": f for f in previous['files']} if previous else {}

    commit = git('rev-parse', 'HEAD')
    dirty = git('status', '--porcelain', '--', 'include', 'libs', 'dlls', 'programs', 'tools', 'VERSION',
                'configure', 'configure.ac', 'wine-nx-probe/source/audio_driver.c',
                'wine-nx-probe/runtime-interfaces.json', 'wine-nx-probe/fex')
    if dirty:
        assert args.allow_dirty, f'uncommitted changes in what the DLLs are built from:\n{dirty}'
        commit += '-dirty'
    elif not git('branch', '-r', '--contains', commit):
        print(f'warning: {commit[:8]} is not pushed; push it before publishing, the manifest points there')

    # What changed since the files here were built decides what is rebuilt.
    base = previous['source']['commit'] if previous else None
    changed = None if args.all else changed_since(base, args.allow_dirty)
    if changed is None:
        print(f'rebuilding everything: {"asked to" if args.all else f"no build to compare with ({base})"}')
    elif changed & EVERYTHING:
        print(f'rebuilding everything: {", ".join(sorted(changed & EVERYTHING))} changed')
        changed = None

    database = make_database()
    modules = targets(database)
    inputs = Inputs(database)
    native_table, wow64_table = static_unix_libs()
    iface = interfaces()

    def features_of(arch, lower):
        features = []
        if arch == 'aarch64' and lower in native_table:
            features.append(f'unixlib:{lower}')
        if arch == 'i386' and lower in wow64_table:
            features.append(f'unixlib32:{lower}')
        # The interface a module shares with the runtime matters where it calls
        # in: what a table names, and the native ntdll and win32u's syscalls.
        if lower in iface and (features or (arch == 'aarch64' and lower in ('ntdll.dll', 'win32u.dll'))):
            features.append(iface[lower])
        return features

    rebuild, keep = [], []
    for arch, directory, name in modules:
        before = earlier.get(f'{ARCHES[arch]}/{name}')
        target = f'{directory}/{arch}-windows/{name}'
        # The headers a module shares with the runtime are among its inputs, so
        # a new interface rebuilds it; its features are worked out afresh anyway.
        if (changed is None or not before or f'{directory}/Makefile.in' in changed
                or inputs.of(target) & changed):
            rebuild.append((arch, directory, name))
            if changed is not None:
                print(f"  {arch} {name}: {'new' if not before else 'its sources changed'}")
        else:
            keep.append((arch, directory, name))
    print(f'Wine modules: {len(rebuild)} to build, {len(keep)} unchanged since {(base or "")[:12]}')

    if rebuild and not args.no_build:
        subprocess.run(['make', '-C', str(pe), '-k', f'-j{args.jobs}',
                        *[f'{d}/{a}-windows/{n}' for a, d, n in rebuild]],
                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    missing = [f'{d}/{a}-windows/{n}' for a, d, n in rebuild if not (pe / d / f'{a}-windows' / n).exists()]
    assert not missing, f'{len(missing)} modules did not build, e.g. {missing[:5]}'

    scratch = Path(tempfile.mkdtemp())
    entries, licenses_in, extra_licenses = [], {}, {}
    for arch, directory, name in rebuild + keep:
        built = (arch, directory, name) in rebuild
        entry = dict(arch=arch, name=name, path=ARCHES[arch], module_dir=directory, origin='wine',
                     sources=sources(directory), libs=libraries(directory), category=category_of(name),
                     license=None, built=built, features=features_of(arch, name.lower()))
        if built:
            entry['file'] = stripped(pe / directory / f'{arch}-windows' / name, scratch / arch)
            found = classes.registered_classes_of(entry['file'])
            if directory.startswith('dlls/'):
                found = classes.classes_of(directory[5:]) + found
            entry['classes'] = found
        entries.append(entry)

    for extra in EXTRA:
        digest = pin(extra['identity'], extra.get('autorun_inputs', ()), extra.get('repo_inputs', ()))
        held = [f for f in earlier.values() if f['source'].get('extra') == extra['key']]
        # A file from before pins were kept (the audio driver) is current if its
        # sources did not change.
        current = held and all(f['source'].get('pin') == digest or
                               ('pin' not in f['source'] and changed is not None and
                                not any(c == p or c.startswith(p + '/') for c in changed for p in extra['sources']))
                               for f in held)
        if current and not args.all:
            for f in held:
                entries.append(dict(arch=f['arch'], name=f['name'], path=f['path'], module_dir=None,
                                    origin=extra['origin'], sources=extra['sources'], libs=[],
                                    category=extra['category'], license=extra['license'], built=False,
                                    features=[], extra=extra['key'], pin=digest))
            extra_licenses.update({name: None for name in (previous or {}).get('licenses', {}).get(extra['key'], [])})
            licenses_in[extra['key']] = (previous or {}).get('licenses', {}).get(extra['key'], [])
            continue
        print(f'building {extra["key"]}')
        made = extra['build'](scratch)
        licenses_in[extra['key']] = []
        for item in made:
            if 'license' in item:
                source, title = item['license']
                extra_licenses[title] = source
                licenses_in[extra['key']].append(title)
                continue
            entries.append(dict(item, module_dir=None, origin=extra['origin'], sources=extra['sources'], libs=[],
                                category=extra['category'], license=extra['license'], built=True, features=[],
                                classes=[], extra=extra['key'], pin=digest))

    names = [(e['path'], e['name'].lower()) for e in entries]
    assert len(set(names)) == len(names), 'a file is built twice'
    wine_licenses = set(ALWAYS)
    for entry in entries:
        wine_licenses.update(entry['libs'])
    missing_licenses = sorted(key for key in wine_licenses if key not in LICENSES or
                              not (root / LICENSES[key][1]).is_file())
    assert not missing_licenses, f'missing license metadata: {missing_licenses}'

    files, unresolved = [], []
    claimed = {}
    present = {}
    for entry in sorted(entries, key=lambda e: (e['path'], e['name'].lower())):
        present.setdefault(entry['path'], set()).add(entry['name'].lower())
    for entry in sorted(entries, key=lambda e: (e['path'], e['name'].lower())):
        name, arch, path = entry['name'], entry['arch'], entry['path']
        key = f'{path}/{name}'
        before = earlier.get(key)
        if entry['built']:
            shipped = entry['file']
            if entry['origin'] == 'wine':
                assert f'Arch: {arch}\n' in readobj('--file-headers', shipped), f'{name} is not {arch}'
            digest = hashlib.sha256(shipped.read_bytes()).hexdigest()
            version = before['version'] + (before['sha256'] != digest) if before else 1
            if not before or before['sha256'] != digest:
                (card / path).mkdir(parents=True, exist_ok=True)
                shutil.copy2(shipped, card / path / name)
            size, commit_of = shipped.stat().st_size, commit
            if before and before['sha256'] == digest:
                commit_of = before['source']['commit']
            served = entry.get('classes', [])
        else:
            digest, version, size = before['sha256'], before['version'], before['size']
            commit_of = before['source']['commit']
            served = [(c['clsid'], c['threading'], c['name']) for c in before.get('classes', [])]

        # What it imports at load time is here, beside it.
        if entry['origin'] == 'wine':
            for module in re.findall(r'^Import \{\n  Name: (.+)$', readobj('--coff-imports', card / path / name), re.M):
                module = module.lower()
                if not module.startswith(('api-ms-', 'ext-ms-')) and module not in present[path]:
                    unresolved.append(f'{arch} {name} -> {module}')

        claim = claimed.setdefault(path, {})
        kept_classes = []
        for uuid, threading, coclass in served:
            if uuid in claim:
                continue
            claim[uuid] = name
            kept_classes.append(dict(clsid=uuid, name=coclass, threading=threading))

        if entry['origin'] == 'wine' or entry.get('extra') == 'winenxaudio':
            changes = git('log', '--format=%h', f'{WINE_IMPORT}..HEAD', '--', *entry['sources']).split()
            modified = entry['origin'] != 'wine' or bool(changes) or commit_of.endswith('-dirty')
            license = ' AND '.join(f'({LICENSES[l][0]})' if ' OR ' in LICENSES[l][0] else LICENSES[l][0]
                                   for l in dict.fromkeys(ALWAYS + entry['libs']))
        else:
            modified, license = True, entry['license']
        source = dict(repo=SOURCE_REPO, commit=commit_of, origin=entry['origin'], modified=modified,
                      paths=entry['sources'])
        if entry.get('extra'):
            source.update(extra=entry['extra'], pin=entry['pin'])
        files.append(dict(
            name=name, path=path, arch=arch, category=entry['category'], version=version,
            size=size, sha256=digest, url=f'{RAW}/{args.ref}/switch/wine/{path}/{name}',
            source=source, license=license,
            requires=dict(flavor=FLAVOR, features=entry['features']),
            classes=kept_classes))
    shutil.rmtree(scratch)

    # What was here and is built no more goes.
    kept_paths = {f"{f['path']}/{f['name']}" for f in files}
    for key in set(earlier) - kept_paths:
        (card / key).unlink(missing_ok=True)

    # What a card downloads: each file compressed, a fifth of its size or less,
    # since the ARM64X modules are laid out in 64 KiB blocks that are mostly
    # padding. The files as they are stay in switch/, for a copy made by hand.
    packed = repo / 'compressed/switch/wine'
    wanted = set()
    for f in files:
        before = earlier.get(f"{f['path']}/{f['name']}")
        target = packed / f['path'] / (f['name'] + '.z')
        wanted.add(target)
        if before and before.get('compressed') and before['sha256'] == f['sha256'] and target.is_file():
            f['compressed'] = before['compressed']
        else:
            data = zlib.compress((card / f['path'] / f['name']).read_bytes(), 9)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            f['compressed'] = dict(encoding='zlib', size=len(data), sha256=hashlib.sha256(data).hexdigest())
        f['compressed']['url'] = f"{RAW}/{args.ref}/compressed/switch/wine/{f['path']}/{f['name']}.z"
    if packed.is_dir():
        for stale in packed.rglob('*'):
            if stale.is_file() and stale not in wanted:
                stale.unlink()

    manifest = dict(schema=SCHEMA, flavor=FLAVOR,
                    source=dict(repo=SOURCE_REPO, commit=commit, wine=WINE_VERSION, wine_import=WINE_IMPORT),
                    categories={name: description for name, description, _ in CATEGORIES},
                    licenses=licenses_in, files=files)
    (card / MANIFEST).parent.mkdir(parents=True, exist_ok=True)
    (card / MANIFEST).write_text(json.dumps(manifest, indent=1) + '\n')
    (card / CLASSES).write_text(classes_reg(files))

    (repo / 'LICENSES').mkdir(exist_ok=True)
    wanted = {LICENSES[key][2] + '.txt': root / LICENSES[key][1] for key in wine_licenses}
    wanted.update({title + '.txt': source for title, source in extra_licenses.items()})
    for existing in (repo / 'LICENSES').iterdir():
        if existing.name not in wanted:
            existing.unlink()
    for name, source in wanted.items():
        if source is not None:
            shutil.copy2(source, repo / 'LICENSES' / name)
        assert (repo / 'LICENSES' / name).is_file(), f'the license {name} is neither here nor built'
    (repo / 'NOTICE.md').write_text(write_notice(manifest, wine_licenses, extra_licenses))
    (repo / 'README.md').write_text(readme(manifest))

    new = [f for f in files if f['sha256'] != earlier.get(f"{f['path']}/{f['name']}", {}).get('sha256')]
    for category, _, _ in CATEGORIES:
        mine = [f for f in files if f['category'] == category]
        print(f'{category}: {len(mine)} files, {sum(f["size"] for f in mine) >> 20} MB')
    print(f'{len(files)} files ({sum(f["size"] for f in files) >> 20} MB), {len(new)} new or changed '
          f'({sum(f["size"] for f in new) >> 20} MB); source {commit[:12]}')
    for f in new[:40]:
        print(f'  {f["path"]}/{f["name"]} v{f["version"]}')
    print(f'  download: {sum(f["compressed"]["size"] for f in files) >> 20} MB compressed')
    print(f'  tied to the runtime: {", ".join(f["arch"] + " " + f["name"] for f in files if f["requires"]["features"])}')
    print(f'  classes: {sum(len(f["classes"]) for f in files)}')
    if unresolved:
        print(f'  imports nothing here provides ({len(unresolved)}): {", ".join(unresolved[:12])}')
    print(f'  publish: commit and push {repo}, then commit the new horizon-dlls in {root}')

def classes_reg(files):
    """The classes the files serve, as the registry the runtime loads before a
    program asks for one; the first file to claim a class keeps it, 32-bit
    first, as make-classes-reg.py wrote them."""
    lines = ['WINE REGISTRY Version 2',
             ';; The COM classes these DLLs serve, from the IDL each is built from and the',
             ';; registration script widl builds into it. Written by tools/build-dlls.py.', '']
    seen = set()
    for f in sorted(files, key=lambda f: (f['arch'] != 'i386', f['name'].lower())):
        dll = f['name'].lower()
        for c in f['classes']:
            if c['clsid'] in seen:
                continue
            seen.add(c['clsid'])
            lines += [f";; {dll.removesuffix('.dll')}: {c['name']}",
                      f"[Software\\\\Classes\\\\CLSID\\\\{{{c['clsid']}}}\\\\InprocServer32]",
                      f'@="{dll}"', f'"ThreadingModel"="{c["threading"]}"', '']
    return '\n'.join(lines)

def write_notice(manifest, licenses, extra_licenses):
    source = manifest['source']
    modified = [f for f in manifest['files'] if f['source']['modified'] and f['source']['origin'] in ('wine', 'autorun')]
    lines = ['# autorun-horizon-dlls', '',
             f"Built from Wine {source['wine']} as carried by "
             f"https://github.com/{source['repo']} at commit `{source['commit']}`. "
             f"The source of every file is there, under the paths its manifest entry lists.", '',
             '| Component | License | Text |', '|---|---|---|']
    for key in sorted(licenses):
        spdx, _, title = LICENSES[key]
        lines.append(f'| {title} | {spdx} | `LICENSES/{title}.txt` |')
    for title in sorted(extra_licenses):
        lines.append(f'| {title} | see the text | `LICENSES/{title}.txt` |')
    lines += ['', 'compiler-rt is built into every Wine file; the other libraries besides Wine into the',
              'files whose manifest entry names their license. FEX, DXVK and VKD3D-Proton are built',
              "from their pinned releases by this repository's tools.", '']
    if modified:
        lines += ["Changed since the Wine import, or Autorun's own:", '']
        lines += [f"- `{f['path']}/{f['name']}`: {', '.join(f['source']['paths'])}" for f in modified]
    else:
        lines.append('No file here was changed since the Wine import.')
    return '\n'.join(lines) + '\n'

def readme(manifest):
    table = '\n'.join(f'| `{name}` | {description} |' for name, description in manifest['categories'].items())
    return f'''# autorun-horizon-dlls

The Windows side of [Autorun](https://github.com/autorunhq/autorun), the
Windows compatibility layer for the Nintendo Switch: every module in
`system32` (ARM64X) and `syswow64` (i386), built from Autorun's Wine, with
FEX's CPU modules and the bundled DXVK and VKD3D-Proton. Autorun downloads
them itself; nothing here needs to be copied by hand.

**Without a network:** download this repository (Code, Download ZIP) and copy
its `switch` folder to the root of the SD card, merging folders.

Every Wine file is built from Wine, some with changes for Horizon; `NOTICE.md`
says which, and where their source is. None of it is Microsoft's.

## Layout

The repository is laid out as the SD card is: `switch/wine/drive_c/` holds the
files, and `switch/wine/horizon-dlls/` the manifest that describes them and
`classes.reg`, the COM classes they serve, which the runtime loads.
`compressed/` holds each file again, zlib-compressed, which is what Autorun
downloads: a fifth of the size, since the ARM64X modules are laid out in
64 KiB blocks that are mostly padding.

## Categories

Each file belongs to the part of Windows it is, whatever program uses it:

| Category | What it covers |
|---|---|
{table}

## manifest.json

Autorun reads the manifest from the published branch, and a card keeps the one
it installed from in the same place.

```
schema        format version; Autorun ignores a manifest it does not know
flavor        the runtimes the files are for (arm64x: the x86 and AMD64 ones)
source        repo, commit and Wine version everything was built from
categories    name and description of each category
licenses      the license texts each separately built component brings
files[]       one per file:
  name, path  where it goes, relative to switch/wine
  arch        i386, aarch64 (ARM64X), arm64ec or x86_64
  category    the part of Windows it belongs to
  version     this file's own version; it changes only when its bytes do
  size, sha256, url
              the file and how to check it; url is its raw path on the
              published branch
  compressed  encoding (zlib), size, sha256 and url of the copy to download,
              which unpacks to the file
  source      repo, the commit it was built from, origin (wine, autorun, fex,
              dxvk, vkd3d-proton), the source paths, whether they changed
              since Wine was imported, and for a file built from other
              sources the digest of its recipe
  license     SPDX expression
  requires    flavor, and the features the runtime has to report for the
              file: unixlib:<name> / unixlib32:<name> for a module the
              runtime's unix-call tables name, iface:<name>:<hash> for the
              headers it shares with the runtime. Autorun leaves a file its
              runtime does not satisfy as it is.
  classes[]   COM classes the file serves (clsid, name, threading)
```

## Building

This repository is a submodule of Autorun, at `horizon-dlls/`, and builds from
the Wine in the Autorun checkout around it:

```
git submodule update --init horizon-dlls
horizon-dlls/tools/build-dlls.py
```

It builds in Autorun's `wine-nx-probe/build-wine-amd64-pe`, configured as
`build-amd64-components.sh` does, and writes over `switch/` only what changed
since the commit the manifest names: a Wine module whose sources, headers,
import libraries or build tools changed, as Wine's make knows them, and a file
built from other sources whose recipe or inputs changed. The rest keep their
bytes and versions. `--all` rebuilds everything. FEX, DXVK and VKD3D-Proton are
built by `tools/build-fex.sh`, `tools/build-dxvk.py` and `tools/build-vkd3d.py`
from their pinned releases; FEX's Horizon patch and the ABI it shares with the
runtime stay in Autorun's `wine-nx-probe/fex`, and the headers a Wine module
shares with the runtime are listed in `wine-nx-probe/runtime-interfaces.json`.
Commit and push here, then commit the new `horizon-dlls` in Autorun, so each
Autorun commit names the DLLs that go with it.
'''

if __name__ == '__main__':
    main()

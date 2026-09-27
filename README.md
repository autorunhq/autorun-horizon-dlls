# autorun-horizon-dlls

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

## Categories

Each file belongs to the part of Windows it is, whatever program uses it:

| Category | What it covers |
|---|---|
| `legacy-16bit` | Windows 3.x and 9x: the 16-bit modules, VxDs and Win32s old programs and installers load |
| `drivers` | Kernel-mode drivers: the device, bus, file system and network stacks under Windows |
| `core` | The NT layer, the Win32 base and the WoW64 and CPU emulation layers every program runs on |
| `directx-graphics` | Direct3D 1 to 12, DirectDraw, DXGI, Direct2D, the D3DX libraries and the shader compilers |
| `directx-audio` | DirectSound, XAudio2, X3DAudio, XAPOFX, XACT and DirectMusic |
| `directx-input` | DirectInput, XInput, GameInput and game controllers |
| `directx-play` | DirectPlay |
| `directx-media` | DirectShow, Media Foundation, Video for Windows and the codecs they use |
| `translation-layers` | DXVK and VKD3D-Proton: Direct3D 8 to 12 drawn with Vulkan |
| `gaming` | The Game Explorer, Game Bar and the other parts of Windows that are there for games |
| `audio` | Windows audio outside DirectX: the multimedia API, MCI, the audio endpoints, speech and the Switch audio driver |
| `opengl-vulkan` | OpenGL and Vulkan |
| `imaging-text` | GDI+, the image codecs, fonts, text layout and code pages |
| `c-runtime` | The C and C++ runtimes: MSVCRT, the Visual C++ redistributables, the UCRT, ATL and MFC |
| `dotnet` | .NET: the runtime host Mono or .NET is loaded through |
| `com-ole` | COM, OLE, Automation and the script engines |
| `winrt` | The Windows Runtime and its Windows.* components |
| `xml` | MSXML and XmlLite |
| `data` | Databases: ODBC, ADO, OLE DB, the ESE engine and SQLite |
| `network` | Sockets, HTTP, the Internet APIs, telephony, wireless and directory services |
| `security` | Cryptography, certificates, credentials and authentication |
| `shell-ui` | The shell, common controls and dialogs, themes, input, accessibility and the browser control |
| `printing` | Printing |
| `installers` | Installing and updating: Windows Installer, cabinets, patches, side-by-side and Windows Update |
| `programs` | Windows programs: the command prompt, Notepad, the registry editor and the rest |
| `system` | The rest of Windows: services, event logs, performance counters, WMI and devices |

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
              what to download and how to check it; url is the file's raw
              path on the published branch
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

# autorun-horizon-dlls

The Windows side of [Autorun](https://github.com/autorunhq/autorun), the
Windows compatibility layer for the Nintendo Switch: every module in
`system32` (aarch64) and `syswow64` (i386), built from Autorun's Wine. Autorun
downloads them itself; nothing here needs to be copied by hand.

**Without a network:** download this repository (Code, Download ZIP) and copy
its `switch` folder to the root of the SD card, merging folders.

Every file is built from Wine, some with changes for Horizon; `NOTICE.md` says
which, and where their source is. None of it is Microsoft's.

## Layout

The repository is laid out as the SD card is: `switch/wine/drive_c/windows/`
holds the files, and `switch/wine/horizon-dlls/manifest.json` describes them.

## manifest.json

Autorun reads the manifest from the published branch, and a card keeps the one
it installed from in the same place.

```
schema        format version; Autorun ignores a manifest it does not know
flavor        the runtime the files are for (x86: the WoW64 runtime)
source        repo, commit and Wine version everything was built from
files[]       one per file:
  name, path  where it goes, relative to switch/wine
  arch        i386 (syswow64) or aarch64 (system32)
  group       what it belongs to (core, d3dx9, xaudio2, programs, wine, ...)
  version     this file's own version; it changes only when its bytes do
  size, sha256, url
              what to download and how to check it; url is the file's raw
              path on main
  source      repo, commit, origin (wine or autorun), the source paths, and
              whether they changed since Wine was imported
  license     SPDX expression
  requires    flavor, and the features the runtime has to report for the
              file: unixlib:<name> / unixlib32:<name> for a module the
              runtime's unix-call tables name, iface:<name>:<hash> for the
              headers it shares with the runtime. Autorun leaves a file its
              runtime does not satisfy as it is.
  classes[]   COM classes the file serves (clsid, name, threading), which
              Autorun registers, as DllRegisterServer would on a PC
```

## Building

This repository is a submodule of Autorun, at `horizon-dlls/`, and builds from
the Wine in the Autorun checkout around it:

```
git submodule update --init horizon-dlls
horizon-dlls/tools/build-dlls.py
```

It builds Wine's PE modules in Autorun's `wine-nx-probe/build-wine-wow64-pe`
and writes them, stripped, over `switch/`, with the manifest, `NOTICE.md` and
`LICENSES/`. Which modules there are, what they belong to and what they need
from the runtime is in `tools/build-dlls.py`; the headers a module shares with
the runtime are listed in Autorun's `wine-nx-probe/runtime-interfaces.json`.
Commit and push here, then commit the new `horizon-dlls` in Autorun, so each
Autorun commit names the DLLs that go with it.

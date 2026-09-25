# autorun-horizon-dlls

Built from Wine 11.0 as carried by https://github.com/autorunhq/autorun at commit `536600bd1de118fff82ff1a38dc3e5d6ee0f1317`. The source of every file is there, under the paths its manifest entry lists.

| Component | License | Text |
|---|---|---|
| Capstone | BSD-3-Clause | `LICENSES/Capstone.txt` |
| compiler-rt | NCSA OR MIT | `LICENSES/compiler-rt.txt` |
| FAudio | Zlib | `LICENSES/FAudio.txt` |
| FluidSynth | LGPL-2.1-or-later | `LICENSES/FluidSynth.txt` |
| libgsm | TU-Berlin-2.0 | `LICENSES/libgsm.txt` |
| libjpeg | IJG | `LICENSES/libjpeg.txt` |
| jxrlib | BSD-2-Clause | `LICENSES/jxrlib.txt` |
| Little CMS | MIT | `LICENSES/Little CMS.txt` |
| OpenLDAP | OLDAP-2.8 | `LICENSES/OpenLDAP.txt` |
| mpg123 | LGPL-2.1-only | `LICENSES/mpg123.txt` |
| musl | MIT | `LICENSES/musl.txt` |
| libpng | Libpng | `LICENSES/libpng.txt` |
| libtiff | libtiff | `LICENSES/libtiff.txt` |
| LibTomCrypt | Unlicense | `LICENSES/LibTomCrypt.txt` |
| vkd3d | LGPL-2.1-or-later | `LICENSES/vkd3d.txt` |
| Wine | LGPL-2.1-or-later | `LICENSES/Wine.txt` |
| libxml2 | MIT | `LICENSES/libxml2.txt` |
| libxslt | MIT | `LICENSES/libxslt.txt` |
| zlib | Zlib | `LICENSES/zlib.txt` |

compiler-rt is built into every file; the other libraries besides Wine into the
files whose manifest entry names their license.

Changed from Wine 11.0, or Autorun's own (see the commit history of the paths listed):

- `drive_c/windows/system32/d3d9.dll`: dlls/d3d9
- `drive_c/windows/system32/dsound.dll`: dlls/dsound
- `drive_c/windows/system32/kernel32.dll`: dlls/kernel32
- `drive_c/windows/system32/kernelbase.dll`: dlls/kernelbase
- `drive_c/windows/system32/ntdll.dll`: dlls/ntdll, libs/musl, libs/tomcrypt
- `drive_c/windows/system32/opengl32.dll`: dlls/opengl32
- `drive_c/windows/system32/quartz.dll`: dlls/quartz
- `drive_c/windows/system32/user32.dll`: dlls/user32, libs/png
- `drive_c/windows/system32/win32u.dll`: dlls/win32u
- `drive_c/windows/system32/winebox64.dll`: dlls/winebox64
- `drive_c/windows/system32/wined3d.dll`: dlls/wined3d, libs/vkd3d
- `drive_c/windows/system32/winevulkan.dll`: dlls/winevulkan
- `drive_c/windows/system32/wow64.dll`: dlls/wow64
- `drive_c/windows/system32/wow64win.dll`: dlls/wow64win
- `drive_c/windows/system32/xinput1_1.dll`: dlls/xinput1_1, dlls/xinput1_3
- `drive_c/windows/system32/xinput1_2.dll`: dlls/xinput1_2, dlls/xinput1_3
- `drive_c/windows/system32/xinput1_3.dll`: dlls/xinput1_3
- `drive_c/windows/system32/xinput1_4.dll`: dlls/xinput1_4, dlls/xinput1_3
- `drive_c/windows/system32/xinputuap.dll`: dlls/xinputuap, dlls/xinput1_3
- `drive_c/windows/syswow64/d3d9.dll`: dlls/d3d9
- `drive_c/windows/syswow64/dsound.dll`: dlls/dsound
- `drive_c/windows/syswow64/kernel32.dll`: dlls/kernel32
- `drive_c/windows/syswow64/kernelbase.dll`: dlls/kernelbase
- `drive_c/windows/syswow64/ntdll.dll`: dlls/ntdll, libs/musl, libs/tomcrypt
- `drive_c/windows/syswow64/opengl32.dll`: dlls/opengl32
- `drive_c/windows/syswow64/quartz.dll`: dlls/quartz
- `drive_c/windows/syswow64/user32.dll`: dlls/user32, libs/png
- `drive_c/windows/syswow64/win32u.dll`: dlls/win32u
- `drive_c/windows/syswow64/wined3d.dll`: dlls/wined3d, libs/vkd3d
- `drive_c/windows/syswow64/winenxaudio.drv`: wine-nx-probe/source/audio_driver.c
- `drive_c/windows/syswow64/winevulkan.dll`: dlls/winevulkan
- `drive_c/windows/syswow64/xinput1_1.dll`: dlls/xinput1_1, dlls/xinput1_3
- `drive_c/windows/syswow64/xinput1_2.dll`: dlls/xinput1_2, dlls/xinput1_3
- `drive_c/windows/syswow64/xinput1_3.dll`: dlls/xinput1_3
- `drive_c/windows/syswow64/xinput1_4.dll`: dlls/xinput1_4, dlls/xinput1_3
- `drive_c/windows/syswow64/xinputuap.dll`: dlls/xinputuap, dlls/xinput1_3

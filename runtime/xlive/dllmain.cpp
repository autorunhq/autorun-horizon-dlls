#define WIN32_LEAN_AND_MEAN
#include <windows.h>

HMODULE hm;

BOOL WINAPI DllMain(HINSTANCE instance, DWORD reason, void *)
{
    if (reason == DLL_PROCESS_ATTACH) hm = instance;
    return TRUE;
}

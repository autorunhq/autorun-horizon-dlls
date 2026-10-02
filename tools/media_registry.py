import re
import struct
import uuid


def guid(name, source):
    headers = '\n'.join((source / 'include' / path).read_text()
                        for path in ('mfapi.h', 'mfidl.idl', 'mmreg.h', 'wmcodecdsp.idl'))
    headers += (source / 'dlls/msauddecmft/msauddecmft.c').read_text()
    headers += (source / 'dlls/msvproc/msvproc.c').read_text()
    headers += (source / 'dlls/colorcnv/colorcnv.c').read_text()

    def number(value):
        value = value.strip()
        if not re.fullmatch(r'0x[0-9a-fA-F]+|[0-9]+', value):
            match = re.search(r'^#define\s+' + re.escape(value) + r'\s+(0x[0-9a-fA-F]+|[0-9]+)', headers, re.M)
            if not match:
                raise ValueError(f'Unknown media constant: {value}')
            value = match[1]
        return int(value, 0)

    if name.startswith('CLSID_'):
        match = re.search(r'\[\s*uuid\(([0-9a-fA-F-]{36})\)\s*\]\s*coclass\s+' + re.escape(name[6:]) + r'\b', headers)
        if match:
            return uuid.UUID(match[1])
    match = re.search(r'(?:DEFINE|EXTERN)_GUID\(\s*' + name + r'\s*,([^;]+?)\)', headers)
    if match:
        values = [number(value) for value in match[1].split(',')]
        return uuid.UUID(bytes_le=struct.pack('<IHH8B', *values))
    match = re.search(r'DEFINE_MEDIATYPE_GUID\(\s*' + name + r'\s*,(.*?)\);', headers)
    if not match:
        raise ValueError(f'Unknown media GUID: {name}')
    value = match[1].strip()
    if value.startswith('MAKEFOURCC'):
        chars = re.findall(r"'(.)'", value)
        assert len(chars) == 4
        data1 = int.from_bytes(''.join(chars).encode('ascii'), 'little')
    else:
        data1 = number(value)
    return uuid.UUID(f'{data1:08x}-0000-0010-8000-00aa00389b71')


def media_registry(path, source):
    module = path.stem.lower()
    lines = []
    handler = {'mf': 'SchemeHandlers', 'mfmp4srcsnk': 'ByteStreamHandlers'}.get(module)
    if handler:
        script = path.read_bytes().decode('latin-1')
        leaves = re.findall(r"'([^']+)'\s*\{\s*val '(\{[0-9a-fA-F-]{36}\})' = s '([^']+)'\s*\}", script)
        if not leaves:
            raise ValueError(f'{path}: missing {handler} registration')
        prefix = r'Software\\Microsoft\\Windows Media Foundation\\' + handler
        for key, clsid, label in leaves:
            lines += [f'[{prefix}\\\\{key}]', f'"{clsid}"="{label}"', '']
    if module in ('msmpeg2vdec', 'msauddecmft', 'msvproc', 'colorcnv'):
        text = (source / f'dlls/{module}/{module}.c').read_text()
        match = re.search(r'MFTRegister\((\w+),\s*(\w+),\s*\(WCHAR \*\)L"([^"]+)"', text)
        if not match:
            raise ValueError(f'{module}: missing transform registration')
        clsid, category, name = str(guid(match[1], source)), str(guid(match[2], source)), match[3]
        prefix = r'Software\\Classes\\MediaFoundation\\Transforms'
        lines += [f'[{prefix}\\\\{clsid}]', f'@="{name}"', '"MFTFlags"=dword:00000001']
        for kind in ('Input', 'Output'):
            table = re.search(r'MFT_REGISTER_TYPE_INFO\s+\w+_' + kind.lower() + r's\[\]\s*=\s*\{(.*?)\};', text, re.S)
            if not table:
                raise ValueError(f'{module}: missing {kind} types')
            pairs = re.findall(r'\{\s*(\w+),\s*(\w+)\s*\}', table[1])
            data = b''.join(guid(item, source).bytes_le for pair in pairs for item in pair)
            lines += [f'"{kind}Types"=hex:' + ','.join(f'{byte:02x}' for byte in data)]
        lines += ['', f'[{prefix}\\\\Categories\\\\{category}\\\\{clsid}]', '']
    return '\n'.join(lines)

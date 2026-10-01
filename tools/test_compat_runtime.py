import struct
import unittest
from pathlib import Path
from unittest.mock import patch

import compat_runtime as compat


class PhysXPayloadTests(unittest.TestCase):
    def test_legacy_does_not_replace_existing_payload(self):
        self.assertFalse(compat.PHYSX_FILES.keys() & compat.PHYSX_LEGACY_FILES.keys())
        self.assertEqual(set(compat.PHYSX_LEGACY_FILES), {
            'drive_c/physx/Engine/v2.7.2/physxcore.dll',
            'drive_c/physx/Engine/v2.7.2/physxcooking.dll',
        })
        image = bytearray(128)
        image[:2] = b'MZ'
        struct.pack_into('<I', image, 60, 64)
        image[64:68] = b'PE\0\0'
        struct.pack_into('<H', image, 68, 0x14c)

        with patch.object(compat.shutil, 'which', return_value='7zz'), \
             patch.object(compat, 'fetch', side_effect=lambda cache, url, sha: Path(url.rsplit('/', 1)[-1])) as fetch, \
             patch.object(compat.subprocess, 'check_output', return_value=bytes(image)) as extract:
            files = compat.physx_payload(Path('cache'))

        self.assertEqual(len(files), len(compat.PHYSX_FILES) + len(compat.PHYSX_LEGACY_FILES))
        self.assertEqual(fetch.call_count, 2)
        for relative, data, source, license_id in files:
            legacy = relative in compat.PHYSX_LEGACY_FILES
            self.assertEqual(data, bytes(image))
            self.assertFalse(source['modified'])
            self.assertEqual(source['archive'], compat.PHYSX_LEGACY_URL if legacy else compat.PHYSX_URL)
            self.assertEqual(source['sha256'], compat.PHYSX_LEGACY_SHA256 if legacy else compat.PHYSX_SHA256)
            self.assertEqual(license_id, 'LicenseRef-NVIDIA-PhysX')
        self.assertEqual(extract.call_count, len(files))


if __name__ == '__main__':
    unittest.main()

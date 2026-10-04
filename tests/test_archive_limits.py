"""Reject unsafe members and bombs before allocating/decompressing their contents."""
import hashlib
import io
import json
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import verify_release_archive as v


def fixture(extra=None, compression=zipfile.ZIP_DEFLATED):
    files={'manifest.json':json.dumps(dict(id='stadium_realtime_combat',entry='main.lua',version='0.0.75',github='Neburb/legends')).encode(),
           'main.lua':b'mod.exports.version = "0.0.75"', **(extra or {})}
    files['SHA256SUMS.txt']=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in files.items()).encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression) as z:
        for name,data in files.items(): z.writestr(name,data)
    return buffer.getvalue()


class Limits(unittest.TestCase):
    def test_sensitive_paths_at_every_depth(self):
        for name in ('config/.env.local/key','.env/production','config/.npmrc',
                     '.ssh/id_rsa','.aws/credentials','data/.AWS/CREDENTIALS',
                     'nested/.netrc','cert/auth.pem','config/api.key'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError,'unsafe'):
                v.verify(io.BytesIO(fixture({name:b'secret'})), '0.0.75')

    def test_only_approved_painter_fonts_are_allowed(self):
        for name in v.PAINTER_FONT_MEMBERS:
            with self.subTest(name=name):
                v.verify(io.BytesIO(fixture({name:b'licensed font fixture'})), '0.0.75')
        for name in ('assets/painter/Other.ttf', 'fonts/RobotoCondensed.ttf',
                     'assets/painter/nested/Caveat.ttf', 'assets/painter/Caveat.exe'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'unsafe'):
                v.verify(io.BytesIO(fixture({name:b'excluded'})), '0.0.75')

    def test_valid_content_hashes_are_streamed_and_crc_checked(self):
        data=fixture({'payload.txt':b'abcd'*30000})
        with patch.object(zipfile.ZipFile,'read',side_effect=AssertionError('unbounded read')):
            v.verify(io.BytesIO(data), '0.0.75')
        corrupt=bytearray(fixture({'payload.txt':b'unique content'},zipfile.ZIP_STORED))
        corrupt[corrupt.index(b'unique content')]^=1
        with self.assertRaises(zipfile.BadZipFile):v.verify(io.BytesIO(corrupt),'0.0.75')

    def test_metadata_limit_precedes_open(self):
        data=fixture({'main.lua':b'x'*2000})
        with patch.dict(v.METADATA_LIMITS,{'main.lua':1000}), patch.object(zipfile.ZipFile,'open',side_effect=AssertionError('decompression started')):
            with self.assertRaisesRegex(ValueError,'size limit'):v.verify(io.BytesIO(data),'0.0.75')

    def test_member_and_total_limits_precede_open(self):
        data=fixture({'payload.txt':b'a'*2000})
        for attribute,limit in [('MAX_MEMBER',1000),('MAX_TOTAL',1000)]:
            with self.subTest(attribute=attribute),patch.object(v,attribute,limit),patch.object(zipfile.ZipFile,'open',side_effect=AssertionError('decompression started')):
                with self.assertRaisesRegex(ValueError,'size limit'):v.verify(io.BytesIO(data),'0.0.75')

    def test_compressed_limit_precedes_zip_parsing(self):
        data = fixture()
        with patch.object(v,'MAX_ARCHIVE',10),patch.object(zipfile,'ZipFile',side_effect=AssertionError('ZIP parsed')):
            with self.assertRaisesRegex(ValueError,'compressed ZIP'):v.verify(io.BytesIO(data),'0.0.75')

    def test_count_and_directory_limits_precede_zip_parsing(self):
        for field,value in [(4,10001),(5,9*1024*1024)]:
            data=bytearray(fixture());position=data.rfind(b'PK\x05\x06')
            record=list(struct.unpack('<4s4H2LH',data[position:position+22]));record[field]=value
            if field==4:record[3]=value
            data[position:position+22]=struct.pack('<4s4H2LH',*record)
            with self.subTest(field=field),patch.object(zipfile,'ZipFile',side_effect=AssertionError('ZIP parsed')):
                with self.assertRaisesRegex(ValueError,'central directory'):v.verify(io.BytesIO(data),'0.0.75')

    def test_zip64_locator_is_rejected_before_parsing(self):
        data=fixture();position=data.rfind(b'PK\x05\x06')
        data=data[:position]+b'PK\x06\x07'+bytes(16)+data[position:]
        with patch.object(zipfile,'ZipFile',side_effect=AssertionError('ZIP parsed')):
            with self.assertRaisesRegex(ValueError,'central directory'):v.verify(io.BytesIO(data),'0.0.75')

    def test_high_ratio_bomb_precedes_open(self):
        data=fixture({'payload.txt':bytes(8*1024*1024)})
        with patch.object(zipfile.ZipFile,'open',side_effect=AssertionError('decompression started')):
            with self.assertRaisesRegex(ValueError,'compression ratio'):v.verify(io.BytesIO(data),'0.0.75')

    def test_stdin_limit_and_metadata_short_read(self):
        with self.assertRaisesRegex(ValueError,'size limit'):v.read_bounded(io.BytesIO(bytes(11)),10)
        self.assertEqual(v.read_bounded(io.BytesIO(b'ok'),10),b'ok')


if __name__=='__main__': unittest.main()

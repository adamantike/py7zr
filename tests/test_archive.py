import binascii
import hashlib
import lzma
import os
import pathlib
import shutil
import stat
import sys
from datetime import datetime

import pytest

import py7zr.archiveinfo
import py7zr.compression
import py7zr.helpers
import py7zr.properties
from py7zr import SevenZipFile, pack_7zarchive
from py7zr.helpers import Local

testdata_path = os.path.join(os.path.dirname(__file__), 'data')


@pytest.mark.unit
def test_simple_compress_and_decompress():
    sevenzip_compressor = py7zr.compression.SevenZipCompressor()
    lzc = sevenzip_compressor.compressor
    out1 = lzc.compress(b"Some data\n")
    out2 = lzc.compress(b"Another piece of data\n")
    out3 = lzc.compress(b"Even more data\n")
    out4 = lzc.flush()
    result = b"".join([out1, out2, out3, out4])
    size = len(result)
    #
    filters = sevenzip_compressor.filters
    decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
    out5 = decompressor.decompress(result)
    assert out5 == b'Some data\nAnother piece of data\nEven more data\n'
    #
    coders = sevenzip_compressor.coders
    crc = py7zr.helpers.calculate_crc32(result)
    decompressor = py7zr.compression.SevenZipDecompressor(coders, size, crc)
    out6 = decompressor.decompress(result)
    assert out6 == b'Some data\nAnother piece of data\nEven more data\n'


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_single_encoded_header(capsys, tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(True)
    archive.writeall(os.path.join(testdata_path, "test1.txt"), "test1.txt")
    assert len(archive.files) == 1
    archive.close()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.test()
    ctime = datetime.utcfromtimestamp(pathlib.Path(os.path.join(testdata_path, "test1.txt")).stat().st_ctime)
    creationdate = ctime.astimezone(Local).strftime("%Y-%m-%d")
    creationtime = ctime.astimezone(Local).strftime("%H:%M:%S")
    expected = "total 1 files and directories in solid archive\n" \
               "   Date      Time    Attr         Size   Compressed  Name\n" \
               "------------------- ----- ------------ ------------  ------------------------\n"
    expected += "{} {} ....A           33           37  test1.txt\n".format(creationdate, creationtime)
    expected += "------------------- ----- ------------ ------------  ------------------------\n"
    cli = py7zr.cli.Cli()
    cli.run(["l", str(target)])
    out, err = capsys.readouterr()
    assert expected == out


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_directory_encoded_header(tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(True)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    assert len(archive.files) == 2
    archive._write_archive()
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [17]
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [11]
    assert len(archive.header.files_info.files) == 2
    archive._fpclose()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.test()


@pytest.mark.file
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_files_encoded_header(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_1.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(True)
    archive.writeall('.')
    archive._write_archive()
    assert len(archive.files) == 4
    assert len(archive.header.files_info.files) == 4
    expected = [True, False, False, False]
    for i, f in enumerate(archive.header.files_info.files):
        f['emptystream'] = expected[i]
    assert archive.header.files_info.emptyfiles == [True, False, False, False]
    assert archive.header.files_info.files[3]['emptystream'] is False
    expected_attributes = stat.FILE_ATTRIBUTE_ARCHIVE
    if os.name == 'posix':
        expected_attributes |= 0x8000 | (0o644 << 16)
    assert archive.header.files_info.files[3]['attributes'] == expected_attributes
    assert archive.header.files_info.files[3]['maxsize'] == 441
    assert archive.header.files_info.files[3]['uncompressed'] == 559
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [441]
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders == [3]
    assert archive.header.main_streams.substreamsinfo.digestsdefined == [True, True, True]
    assert archive.header.main_streams.substreamsinfo.digests == [3010113243, 3703540999, 2164028094]
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [111, 58, 559]
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].solid
    assert archive.header.main_streams.unpackinfo.folders[0].bindpairs == []
    assert archive.header.main_streams.unpackinfo.folders[0].solid is True
    assert archive.header.main_streams.unpackinfo.folders[0].totalin == 1
    assert archive.header.main_streams.unpackinfo.folders[0].totalout == 1
    assert archive.header.main_streams.unpackinfo.folders[0].unpacksizes == [728]  # 728 = 111 + 58 + 559
    assert archive.header.main_streams.unpackinfo.folders[0].digestdefined is False
    assert archive.header.main_streams.unpackinfo.folders[0].crc is None
    archive._fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'setup.py').open('rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'scripts' / 'py7zr').open('rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_file_0(capsys, tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall(os.path.join(testdata_path, "test1.txt"), "test1.txt")
    assert len(archive.files) == 1
    archive.close()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.test()
    ctime = datetime.utcfromtimestamp(pathlib.Path(os.path.join(testdata_path, "test1.txt")).stat().st_ctime)
    creationdate = ctime.astimezone(Local).strftime("%Y-%m-%d")
    creationtime = ctime.astimezone(Local).strftime("%H:%M:%S")
    expected = "total 1 files and directories in solid archive\n" \
               "   Date      Time    Attr         Size   Compressed  Name\n" \
               "------------------- ----- ------------ ------------  ------------------------\n"
    expected += "{} {} ....A           33           37  test1.txt\n".format(creationdate, creationtime)
    expected += "------------------- ----- ------------ ------------  ------------------------\n"
    cli = py7zr.cli.Cli()
    cli.run(["l", str(target)])
    out, err = capsys.readouterr()
    assert expected == out


@pytest.mark.basic
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_directory(tmp_path):
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    assert len(archive.files) == 2
    archive._write_archive()
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [17]
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [11]
    assert len(archive.header.files_info.files) == 2
    archive._fpclose()
    with target.open('rb') as target_archive:
        val = target_archive.read(1000)
        assert val.startswith(py7zr.properties.MAGIC_7Z)
    archive = py7zr.SevenZipFile(target, 'r')
    assert archive.test()


@pytest.mark.file
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_files_1(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_1.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive._write_archive()
    assert len(archive.files) == 4
    assert len(archive.header.files_info.files) == 4
    expected = [True, False, False, False]
    for i, f in enumerate(archive.header.files_info.files):
        f['emptystream'] = expected[i]
    assert archive.header.files_info.emptyfiles == [True, False, False, False]
    assert archive.header.files_info.files[3]['emptystream'] is False
    expected_attributes = stat.FILE_ATTRIBUTE_ARCHIVE
    if os.name == 'posix':
        expected_attributes |= 0x8000 | (0o644 << 16)
    assert archive.header.files_info.files[3]['attributes'] == expected_attributes
    assert archive.header.files_info.files[3]['maxsize'] == 441
    assert archive.header.files_info.files[3]['uncompressed'] == 559
    assert archive.header.main_streams.packinfo.numstreams == 1
    assert archive.header.main_streams.packinfo.packsizes == [441]
    assert archive.header.main_streams.substreamsinfo.num_unpackstreams_folders == [3]
    assert archive.header.main_streams.substreamsinfo.digestsdefined == [True, True, True]
    assert archive.header.main_streams.substreamsinfo.digests == [3010113243, 3703540999, 2164028094]
    assert archive.header.main_streams.substreamsinfo.unpacksizes == [111, 58, 559]
    assert len(archive.header.main_streams.unpackinfo.folders) == 1
    assert len(archive.header.main_streams.unpackinfo.folders[0].coders) == 1
    assert archive.header.main_streams.unpackinfo.numfolders == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numinstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].coders[0]['numoutstreams'] == 1
    assert archive.header.main_streams.unpackinfo.folders[0].solid
    assert archive.header.main_streams.unpackinfo.folders[0].bindpairs == []
    assert archive.header.main_streams.unpackinfo.folders[0].solid is True
    assert archive.header.main_streams.unpackinfo.folders[0].totalin == 1
    assert archive.header.main_streams.unpackinfo.folders[0].totalout == 1
    assert archive.header.main_streams.unpackinfo.folders[0].unpacksizes == [728]  # 728 = 111 + 58 + 559
    assert archive.header.main_streams.unpackinfo.folders[0].digestdefined is False
    assert archive.header.main_streams.unpackinfo.folders[0].crc is None
    archive._fpclose()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'setup.py').open('rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'scripts' / 'py7zr').open('rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')


@pytest.mark.api
def test_register_archive_format(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    # Prepare test data
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_1.7z'), path=tmp_path.joinpath('src'))
    #
    shutil.register_archive_format('7zip', pack_7zarchive, description='7zip archive')
    shutil.make_archive(str(tmp_path.joinpath('target')), '7zip', str(tmp_path.joinpath('src')))
    # check result
    archive = SevenZipFile(tmp_path.joinpath('target.7z'))
    archive.extractall(path=tmp_path.joinpath('tgt'))
    archive.close()
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'setup.py').open('rb').read())
    assert m.digest() == binascii.unhexlify('b916eed2a4ee4e48c51a2b51d07d450de0be4dbb83d20e67f6fd166ff7921e49')
    m = hashlib.sha256()
    m.update((tmp_path / 'tgt' / 'scripts' / 'py7zr').open('rb').read())
    assert m.digest() == binascii.unhexlify('b0385e71d6a07eb692f5fb9798e9d33aaf87be7dfff936fd2473eab2a593d4fd')


@pytest.mark.api
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_with_simple_filter(tmp_path):
    my_filters = [{"id": lzma.FILTER_LZMA2, "preset": lzma.PRESET_DEFAULT}, ]
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w', filters=my_filters)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    archive.close()


@pytest.mark.api
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_with_custom_filter(tmp_path):
    my_filters = [
        {"id": lzma.FILTER_DELTA, "dist": 5},
        {"id": lzma.FILTER_LZMA2, "preset": 7 | lzma.PRESET_EXTREME},
    ]
    target = tmp_path.joinpath('target.7z')
    archive = py7zr.SevenZipFile(target, 'w', filters=my_filters)
    archive.writeall(os.path.join(testdata_path, "src"), "src")
    archive.close()


@pytest.mark.file
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_files_2(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_2.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive.close()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()


@pytest.mark.file
@pytest.mark.skipif(sys.version_info < (3, 6), reason="requires python3.6 or higher")
def test_compress_files_3(tmp_path):
    tmp_path.joinpath('src').mkdir()
    tmp_path.joinpath('tgt').mkdir()
    py7zr.unpack_7zarchive(os.path.join(testdata_path, 'test_3.7z'), path=tmp_path.joinpath('src'))
    target = tmp_path.joinpath('target.7z')
    os.chdir(tmp_path.joinpath('src'))
    archive = py7zr.SevenZipFile(target, 'w')
    archive.set_encoded_header_mode(False)
    archive.writeall('.')
    archive.close()
    reader = py7zr.SevenZipFile(target, 'r')
    reader.extractall(path=tmp_path.joinpath('tgt'))
    reader.close()
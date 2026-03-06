from inspect_ai._util.file import basename, filesystem


def test_basename():
    MYFILE = "myfile.log"
    assert basename(f"s3://my-bucket/{MYFILE}") == MYFILE
    assert basename(f"/opt/files/{MYFILE}") == MYFILE
    assert basename(f"C:\\Documents\\{MYFILE}") == MYFILE

    MYDIR = "mydir"
    assert basename(f"s3://my-bucket/{MYDIR}") == MYDIR
    assert basename(f"s3://my-bucket/{MYDIR}/") == MYDIR
    assert basename(f"/opt/files/{MYDIR}") == MYDIR
    assert basename(f"/opt/files/{MYDIR}/") == MYDIR
    assert basename(f"C:\\Documents\\{MYDIR}") == MYDIR
    assert basename(f"C:\\Documents\\{MYDIR}\\") == MYDIR


def test_filesystem_file_info():
    memory_filesystem = filesystem("memory://")
    memory_filesystem.touch("test_file")
    info = memory_filesystem.info("test_file")
    assert info.name == "memory:///test_file"
    assert info.size == 0

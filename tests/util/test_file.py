from inspect_ai._util.file import basename, dirname, filesystem


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

    # Query params (e.g. S3 versionId) should be stripped
    assert basename("s3://my-bucket/myfile.eval?versionId=abc123") == "myfile.eval"
    assert basename("s3://my-bucket/mydir/myfile.log?versionId=abc123") == "myfile.log"


def test_dirname():
    assert dirname("s3://my-bucket/myfile.log") == "s3://my-bucket"
    assert dirname("s3://my-bucket/mydir/myfile.log") == "s3://my-bucket/mydir"
    assert dirname("/opt/files/myfile.log") == "/opt/files"

    # Query params should be stripped
    assert dirname("s3://my-bucket/myfile.eval?versionId=abc123") == "s3://my-bucket"
    assert (
        dirname("s3://my-bucket/mydir/myfile.eval?versionId=abc123")
        == "s3://my-bucket/mydir"
    )


def test_filesystem_file_info():
    memory_filesystem = filesystem("memory://")
    memory_filesystem.touch("test_file")
    info = memory_filesystem.info("test_file")
    assert info.name == "memory:///test_file"
    assert info.size == 0

from inspect_ai._util.file import basename


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

import errno
from typing import Any, Literal
from urllib.parse import urlparse
from urllib.request import url2pathname

from inspect_ai._util.file import file, filesystem


def resource(
    resource: str,
    type: Literal["auto", "file"] = "auto",
    fs_options: dict[str, Any] = {},
) -> str:
    """Read and resolve a resource to a string.

    Resources are often used for templates, configuration, etc.
    They are sometimes hard-coded strings, and sometimes paths
    to external resources (e.g. in the local filesystem or
    remote stores e.g. s3:// or https://).

    The `resource()` function will resolve its argument to
    a resource string. If a protocol-prefixed file name
    (e.g. s3://) or the path to a local file that exists
    is passed then it will be read and its contents returned.
    Otherwise, it will return the passed `str` directly
    This function is mostly intended as a helper for other
    functions that take either a string or a resource path
    as an argument, and want to easily resolve them to
    the underlying content.

    If you want to ensure that only local or remote files
    are consumed, specify `type="file"`. For example:
    `resource("templates/prompt.txt", type="file")`

    Args:
        resource (str): Path to local or remote (e.g. s3://)
          resource, or for `type="auto"` (the default),
          a string containing the literal resource value.
        type (Literal["auto", "file"]): For "auto" (the default),
          interpret the resource as a literal string if its not
          a valid path. For "file", always interpret it as
          a file path.
        fs_options (dict[str, Any]): Optional. Additional
          arguments to pass through to the `fsspec` filesystem
          provider (e.g. `S3FileSystem`). Use `{"anon": True }`
          if you are accessing a public S3 bucket with no
          credentials.

    Returns:
       Text content of resource.
    """

    # helper function to read the resource as a file
    def read_resource() -> str:
        with file(resource, "r", fs_options=fs_options) as f:
            return f.read()

    if type == "file":
        return read_resource()
    else:
        # parse the url
        try:
            parsed = urlparse(resource)
        except (ValueError, OSError):
            return resource

        # if it has a scheme then its likely a file
        if parsed.scheme:
            try:
                return read_resource()
            except (ValueError, FileNotFoundError):
                return resource
            except OSError as ex:
                if ex.errno == errno.ENAMETOOLONG:
                    return resource
                else:
                    raise ex

        # no scheme means either a local file or a string
        else:
            # extract the path
            try:
                path = url2pathname(parsed.path)
            except (ValueError, OSError):
                return resource

            # check if there is a path (otherwise return the str)
            if len(path) == 0:
                return resource

            # return it if it exists (otherwise return the str)
            try:
                fs = filesystem(path)
                if fs.exists(path):
                    return read_resource()
                else:
                    return resource
            except ValueError:
                return resource

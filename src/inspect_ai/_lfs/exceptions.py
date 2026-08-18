"""LFS-related exceptions."""


class LFSError(Exception):
    """Base exception for LFS operations."""


class LFSBatchError(LFSError):
    """Error calling LFS batch API."""


class LFSDownloadError(LFSError):
    """Error downloading LFS object."""


class LFSResolverError(LFSError):
    """Error resolving dist directory."""

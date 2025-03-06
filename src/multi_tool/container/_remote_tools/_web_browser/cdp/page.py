"""
Types associated with Chrome DevTools Protocol's 'Page' Domain

https://chromedevtools.github.io/devtools-protocol/tot/Page/
"""

from typing import Literal, NewType

from pydantic import BaseModel

FrameId = NewType("FrameId", str)


class SecurityOriginDetails(BaseModel, frozen=True):
    """Additional information about the frame document's security origin."""

    isLocalhost: bool
    """Indicates whether the frame document's security origin is one of the local hostnames (e.g. "localhost") or IP addresses (IPv4 127.0.0.0/8 or IPv6 ::1)."""


AdFrameType = Literal["none", "child", "root"]

AdFrameExplanation = Literal["ParentIsAd", "CreatedByAdScript", "MatchedBlockingRule"]


class AdFrameStatus(BaseModel, frozen=True):
    """Indicates whether a frame has been identified as an ad and why."""

    adFrameType: AdFrameType
    explanations: tuple[AdFrameExplanation, ...] | None = None


SecureContextType = Literal[
    "Secure", "SecureLocalhost", "InsecureScheme", "InsecureAncestor"
]


CrossOriginIsolatedContextType = Literal[
    "Isolated", "NotIsolated", "NotIsolatedFeatureDisabled"
]


GatedAPIFeatures = Literal[
    "SharedArrayBuffers",
    "SharedArrayBuffersTransferAllowed",
    "PerformanceMeasureMemory",
    "PerformanceProfile",
]


class Frame(BaseModel, frozen=True):
    """Information about the Frame on the page."""

    id: FrameId
    """Frame unique identifier."""
    parentId: FrameId | None = None
    """Parent frame identifier."""
    loaderId: object  # Network.LoaderId
    """Identifier of the loader associated with this frame."""
    name: str | None = None
    """Frame's name as specified in the tag."""
    url: str
    """Frame document's URL without fragment."""
    urlFragment: str | None = None
    """Frame document's URL fragment including the '#'."""
    domainAndRegistry: str
    """Frame document's registered domain, taking the public suffixes list into account. Extracted from the Frame's url. Example URLs: http://www.google.com/file.html -> "google.com" http://a.b.co.uk/file.html -> "b.co.uk"""
    securityOrigin: str
    """Frame document's security origin."""
    securityOriginDetails: SecurityOriginDetails | None = None
    """Additional details about the frame document's security origin."""
    mimeType: str
    """Frame document's mimeType as determined by the browser."""
    unreachableUrl: str | None = None
    """If the frame failed to load, this contains the URL that could not be loaded. Note that unlike url above, this URL may contain a fragment."""
    adFrameStatus: AdFrameStatus | None = None
    """Indicates whether this frame was tagged as an ad and why."""
    secureContextType: SecureContextType
    """Indicates whether the main document is a secure context and explains why that is the case."""
    crossOriginIsolatedContextType: CrossOriginIsolatedContextType
    """Indicates whether this is a cross origin isolated context."""
    gatedAPIFeatures: tuple[GatedAPIFeatures, ...]
    """Indicated which gated APIs / features are available."""


class FrameTree(BaseModel, frozen=True):
    frame: Frame
    """Frame information for this tree item."""
    childFrames: tuple["FrameTree", ...] | None = None
    """Child frames."""


class FrameTrees(BaseModel, frozen=True):
    frameTree: FrameTree

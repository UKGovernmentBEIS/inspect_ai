"""
Types associated with Chrome DevTools Protocol's 'DOM' Domain

https://chromedevtools.github.io/devtools-protocol/tot/DOM/
"""

from typing import NewType

DOMBackendNodeId = NewType("DOMBackendNodeId", int)

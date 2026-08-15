import pytest

from inspect_ai._util.git import redact_url_credentials


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://user:gho_secret@github.com/org/repo",
            "https://github.com/org/repo",
        ),
        (
            "https://gho_secret@github.com/org/repo",
            "https://github.com/org/repo",
        ),
        (
            "https://x-access-token:TOKEN@github.com/org/repo.git",
            "https://github.com/org/repo.git",
        ),
        (
            "https://user:tok@github.com:8443/org/repo",
            "https://github.com:8443/org/repo",
        ),
        ("https://github.com/org/repo", "https://github.com/org/repo"),
        ("git@github.com:org/repo.git", "git@github.com:org/repo.git"),
        ("ssh://git@github.com/org/repo.git", "ssh://github.com/org/repo.git"),
        ("", ""),
    ],
    ids=[
        "https-user-password",
        "https-token-only",
        "actions-style",
        "https-port-preserved",
        "clean-https-unchanged",
        "scp-ssh-unchanged",
        "ssh-scheme-userinfo-stripped",
        "empty",
    ],
)
def testredact_url_credentials(url: str, expected: str) -> None:
    assert redact_url_credentials(url) == expected

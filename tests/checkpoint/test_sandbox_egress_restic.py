"""Sandbox restic egress/ingress against a real restic binary.

Drives ``egress_sandbox`` end to end with the ``LocalShellSandbox`` fake:
the "in-sandbox" repo is a real restic repo under a temp dir that real
``restic backup`` invocations write into, the egress shell (find, comm,
tar, dd) runs on the host, and the host-side checks run against the
destination repo with the same binary. Covers the host-side truth
checks the egress protocol makes: a fire that captured nothing raises,
a replayed id, an unshipped reported id, or a foreign tag is rejected
and leaves the destination unchanged, an unrecorded extra snapshot (a
failed fire's leftover or a planted one) ships as an orphan, the
transfer cap binds, and resume-side orphan discard keeps exactly the
recorded snapshots and restores the recorded id.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import IO, Any
from unittest.mock import patch

import anyio
import pytest
from test_helpers.local_shell_sandbox import LocalShellSandbox

from inspect_ai.util._checkpoint._copy import copy_out, copy_out_partial_path
from inspect_ai.util._checkpoint._repo_ops import (
    forget_unrecorded_snapshots,
    list_snapshots,
)
from inspect_ai.util._checkpoint._sandbox_restic.egress import (
    EgressVerificationError,
    _EgressBuild,
    _write_member,
    egress_sandbox,
    ingress_sandbox,
)
from inspect_ai.util._restic import ResticBackupSummary, resolve_restic

# Slow for the same reason as tests/checkpoint/test_restore_repo.py: the
# binary comes from `resolve_restic`, which downloads it on first use, and
# every test here pays a real `restic init` plus real backup and restore
# invocations. Keep anything that needs neither out of this file so it stays
# in the PR gate (see `_remove_files` in test_sandbox_egress_extract.py).
pytestmark = pytest.mark.slow

PASSWORD = "test-password"
CHUNK = 64 * 1024
CAP = 1 << 30

MALFORMED_INDEX = b"not a valid encrypted restic index"


def _plant_conflicting_index(repo: Path, password: str = PASSWORD) -> tuple[str, str]:
    """Plant a conflicting validly-encrypted index plus its garbage pack.

    The index maps an existing data blob into a garbage ``data`` pack added
    alongside it, in the in-sandbox ``repo``.
    This models the strongest addition an agent that holds the repo key can
    ship: it passes ``restic check`` *without* ``--read-data`` and ``restic
    ls`` (both accept it), so only the ``--read-data`` content read catches
    it. Returns the (pack, index) repo-relative names. Requires
    ``cryptography`` (a v2 restic repo's AES-256-CTR + Poly1305-AES index
    encryption); callers guard with ``pytest.importorskip``.
    """
    from cryptography.hazmat.primitives import poly1305
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    def poly_key(nonce: bytes, mk_k: bytes, mk_r: bytes) -> bytes:
        enc = Cipher(algorithms.AES(mk_k), modes.ECB()).encryptor()
        return mk_r + enc.update(nonce) + enc.finalize()

    def decrypt(key: tuple[bytes, bytes, bytes], buf: bytes) -> bytes:
        aes, mk_k, mk_r = key
        nonce, ct, mac = buf[:16], buf[16:-16], buf[-16:]
        checker = poly1305.Poly1305(poly_key(nonce, mk_k, mk_r))
        checker.update(ct)
        checker.verify(mac)
        dec = Cipher(algorithms.AES(aes), modes.CTR(nonce)).decryptor()
        return dec.update(ct) + dec.finalize()

    def encrypt(key: tuple[bytes, bytes, bytes], plaintext: bytes) -> bytes:
        aes, mk_k, mk_r = key
        nonce = os.urandom(16)
        enc = Cipher(algorithms.AES(aes), modes.CTR(nonce)).encryptor()
        ct = enc.update(plaintext) + enc.finalize()
        mac = poly1305.Poly1305(poly_key(nonce, mk_k, mk_r))
        mac.update(ct)
        return nonce + ct + mac.finalize()

    key_file = next((repo / "keys").iterdir())
    kj = json.loads(key_file.read_bytes())
    assert kj["kdf"] == "scrypt", kj["kdf"]
    dk = hashlib.scrypt(
        password.encode(),
        salt=base64.b64decode(kj["salt"]),
        n=kj["N"],
        r=kj["r"],
        p=kj["p"],
        dklen=64,
        maxmem=(128 * kj["N"] * kj["r"] * 2) + 2**26,
    )
    user_key = (dk[:32], dk[32:48], dk[48:64])
    mj = json.loads(decrypt(user_key, base64.b64decode(kj["data"])))
    master = (
        base64.b64decode(mj["encrypt"]),
        base64.b64decode(mj["mac"]["k"]),
        base64.b64decode(mj["mac"]["r"]),
    )

    def load_index(name: str) -> dict[str, Any]:
        raw = decrypt(master, (repo / "index" / name).read_bytes())
        if raw[:1] in (b"[", b"{"):
            return json.loads(raw)
        import zstandard

        return json.loads(
            zstandard.ZstdDecompressor().decompressobj().decompress(raw[1:])
        )

    blob: dict[str, Any] | None = None
    for name in sorted(os.listdir(repo / "index")):
        for pack in load_index(name).get("packs", []):
            for candidate in pack["blobs"]:
                if candidate.get("type") == "data":
                    blob = candidate
                    break
            if blob is not None:
                break
        if blob is not None:
            break
    assert blob is not None, "no data blob to build a conflicting mapping against"

    # A garbage pack sized to satisfy restic's pack-size arithmetic (36-byte
    # header/trailer + blob length + a per-blob index entry: 41 bytes for a
    # compressed v2 blob, 37 otherwise), so `check` without `--read-data`
    # passes and only the content read rejects it.
    compressed = "uncompressed_length" in blob
    entry = 41 if compressed else 37
    garbage = os.urandom(blob["length"] + 36 + entry)
    pack_name = hashlib.sha256(garbage).hexdigest()
    (repo / "data" / pack_name[:2]).mkdir(parents=True, exist_ok=True)
    (repo / "data" / pack_name[:2] / pack_name).write_bytes(garbage)

    entry_obj: dict[str, Any] = {
        "id": blob["id"],
        "type": "data",
        "offset": 0,
        "length": blob["length"],
    }
    if compressed:
        entry_obj["uncompressed_length"] = max(1, blob["uncompressed_length"] - 100_000)
    index_obj = {"packs": [{"id": pack_name, "blobs": [entry_obj]}]}
    sealed = encrypt(master, json.dumps(index_obj, separators=(",", ":")).encode())
    index_name = hashlib.sha256(sealed).hexdigest()
    (repo / "index" / index_name).write_bytes(sealed)
    return f"data/{pack_name[:2]}/{pack_name}", f"index/{index_name}"


class _Repos:
    """A real "in-sandbox" restic repo plus an (initially empty) destination.

    ``name`` is the sandbox name: it keys the destination under the shared
    ``restic/sandboxes/`` parent, so two instances built from the same
    ``tmp_path`` model two sandboxes of one sample.
    """

    def __init__(self, tmp_path: Path, restic: Path, name: str = "default") -> None:
        self.restic = restic
        root = tmp_path / name
        root.mkdir()
        self.sandbox_dir = root / "sandbox"
        self.sandbox_dir.mkdir()
        # `ingress_sandbox` runs `<sandbox_dir>/restic`; egress never does.
        (self.sandbox_dir / "restic").symlink_to(restic)
        self.repo = self.sandbox_dir / "repo"
        self.repo.mkdir()
        self.src = root / "capture"
        self.src.mkdir()
        (self.src / "notes.txt").write_text("v1\n")
        self.dest = tmp_path / "sample" / "restic" / "sandboxes" / name
        self.env = LocalShellSandbox()
        self._run("init", "-q")

    def _run(self, *args: str) -> str:
        proc = subprocess.run(
            [str(self.restic), "-r", str(self.repo), *args],
            env={"RESTIC_PASSWORD": PASSWORD, "PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    def backup(self, tag: str | None) -> str:
        """Back up the capture dir into the sandbox repo; return the id."""
        args = ["backup", str(self.src), "--json", "--quiet"]
        if tag is not None:
            args += ["--tag", tag]
        return ResticBackupSummary.from_stdout(self._run(*args)).snapshot_id

    async def egress(self, tag: str, snapshot_id: str, **overrides: Any) -> str:
        kwargs: dict[str, Any] = dict(
            dest_repo=str(self.dest),
            password=PASSWORD,
            host_restic=self.restic,
            tag=tag,
            snapshot_id=snapshot_id,
            max_bytes=CAP,
            chunk_size=CHUNK,
            sandbox_dir=str(self.sandbox_dir),
        )
        kwargs.update(overrides)
        return await egress_sandbox(self.env, **kwargs)

    async def dest_snapshots(self) -> dict[str, list[str]]:
        snaps = await list_snapshots(self.restic, str(self.dest), PASSWORD)
        return {s["id"]: s.get("tags") or [] for s in snaps}

    def dest_files(self) -> set[str]:
        return {
            p.relative_to(self.dest).as_posix()
            for p in self.dest.rglob("*")
            if p.is_file() and p.relative_to(self.dest).parts[0] != "locks"
        }

    def repo_files(self) -> set[str]:
        return {
            p.relative_to(self.repo).as_posix()
            for p in self.repo.rglob("*")
            if p.is_file() and p.relative_to(self.repo).parts[0] != "locks"
        }

    def manifest(self) -> set[str]:
        path = self.sandbox_dir / "egress-manifest.txt"
        return set(path.read_text().split()) if path.exists() else set()

    def restore_dest(self, snapshot_id: str, target: Path) -> None:
        """Restore ``snapshot_id`` from the accepted (dest) repo into ``target``."""
        subprocess.run(
            [
                str(self.restic),
                "-r",
                str(self.dest),
                "restore",
                snapshot_id,
                "--target",
                str(target),
                "--no-lock",
                "--no-cache",
            ],
            env={"RESTIC_PASSWORD": PASSWORD, "PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            check=True,
        )

    def plant_in_sandbox_repo(self, rel: str, data: bytes) -> str:
        """Write ``data`` at ``rel`` in the in-sandbox repo; return ``rel``.

        Models the sandbox (which controls its own repo) adding an extra
        repository file the next egress diff will pick up and ship.
        """
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return rel


@pytest.fixture
async def repos(tmp_path: Path) -> _Repos:
    return _Repos(tmp_path, await resolve_restic())


async def test_egress_ships_deltas_and_records_host_verified_id(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    assert await repos.egress("ckpt-00001", id1) == id1
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert repos.dest_files() == repos.repo_files()
    assert repos.manifest() == repos.repo_files()

    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    assert await repos.egress("ckpt-00002", id2) == id2
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"], id2: ["ckpt-00002"]}
    assert repos.dest_files() == repos.repo_files()
    # Staging is clean after the phase-2 commit.
    assert not list((repos.sandbox_dir / "staging").glob("egress-*.tar"))
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_empty_diff_after_backup_raises(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")

    async def fake_build(*_args: object, **_kwargs: object) -> _EgressBuild:
        return _EgressBuild(new_files=[], tar_size=0)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress._build_egress_tar",
        new=fake_build,
    ):
        with pytest.raises(EgressVerificationError, match="empty diff"):
            await repos.egress("ckpt-00001", id1)
    assert repos.dest_files() == set()
    assert repos.manifest() == set()


async def test_egress_ships_unrecorded_extra_snapshot_as_orphan(repos: _Repos) -> None:
    """A snapshot no fire reported rides along and is forgotten on resume.

    The host cannot tell a container-planted snapshot from the orphan a
    failed fire leaves (see ``test_egress_recovers_after_failed_transfer``),
    so freshness accepts it: it is not recorded, and orphan discard drops it.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    (repos.src / "notes.txt").write_text("rogue\n")
    rogue = repos.backup(None)  # untagged snapshot the container planted

    assert await repos.egress("ckpt-00002", id2) == id2
    assert await repos.dest_snapshots() == {
        id1: ["ckpt-00001"],
        id2: ["ckpt-00002"],
        rogue: [],
    }

    await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.dest),
        PASSWORD,
        recorded_ids=[id1, id2],
        required_id=id2,
    )
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"], id2: ["ckpt-00002"]}


async def test_egress_rejects_unshipped_reported_id(repos: _Repos) -> None:
    """The reported id must be one of the snapshots this fire landed."""
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    manifest_after_1 = repos.manifest()
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")

    with pytest.raises(EgressVerificationError, match="not among the snapshot"):
        await repos.egress("ckpt-00002", "f" * 64)
    # Rolled back: destination and manifest exactly as after fire 1.
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert repos.dest_files() == files_after_1
    assert repos.manifest() == manifest_after_1
    assert not list(repos.dest.rglob("*.partial"))
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_recovers_after_failed_transfer(repos: _Repos) -> None:
    """A fire that fails between backup and commit does not poison later fires.

    The failed fire's snapshot stays unshipped in the sandbox repo, so the
    retry (which reuses the checkpoint id, hence the tag) ships two
    snapshot files; the retry's own id is the verified one and the other
    is an orphan that resume forgets.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    (repos.src / "notes.txt").write_text("v2\n")
    orphan = repos.backup("ckpt-00002")

    async def failing_copy_out(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("chunk copy failed: transport reset")

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress.copy_out",
        new=failing_copy_out,
    ):
        with pytest.raises(RuntimeError, match="transport reset"):
            await repos.egress("ckpt-00002", orphan)
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}

    id2 = repos.backup("ckpt-00002")  # the retried fire
    assert await repos.egress("ckpt-00002", id2) == id2
    (repos.src / "notes.txt").write_text("v3\n")
    id3 = repos.backup("ckpt-00003")
    assert await repos.egress("ckpt-00003", id3) == id3
    assert await repos.dest_snapshots() == {
        id1: ["ckpt-00001"],
        orphan: ["ckpt-00002"],
        id2: ["ckpt-00002"],
        id3: ["ckpt-00003"],
    }
    assert repos.dest_files() == repos.repo_files()

    forgotten = await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.dest),
        PASSWORD,
        recorded_ids=[id1, id2, id3],
        required_id=id3,
    )
    assert forgotten == ["ckpt-00002"]
    assert set(await repos.dest_snapshots()) == {id1, id2, id3}


async def test_egress_cancelled_during_validation_leaves_repo_untouched(
    repos: _Repos,
) -> None:
    """Cancellation during validation never touches the accepted repo.

    ``_fire_once`` fans sandboxes out under one task group, so a sibling's
    failure can cancel this egress mid-validation. The additions live in
    the scratch dir until validation passes, so the accepted repo is
    unchanged the whole time and the cancelled attempt leaves nothing
    behind.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    verifying = anyio.Event()

    async def stall(*_args: object, **_kwargs: object) -> str:
        verifying.set()
        await anyio.sleep_forever()
        return ""

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress._verify_fresh_snapshot",
        new=stall,
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(repos.egress, "ckpt-00002", id2)
            await verifying.wait()
            # Validation runs on the throwaway view; the accepted repo is
            # untouched, and the additions are staged off to the side.
            assert repos.dest_files() == files_after_1
            assert list(repos.dest.parent.glob(".egress-*"))
            tg.cancel_scope.cancel()

    assert repos.dest_files() == files_after_1
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_rejects_malformed_index_and_preserves_earlier(
    repos: _Repos,
) -> None:
    """A later fire that ships a malformed index cannot bury an earlier one.

    The demonstrated poisoning: a correctly-named but undecryptable
    ``index/<sha256>`` passes the per-file hash check, yet once merged it
    makes restic abort loading indexes and so blocks restoring *every*
    snapshot, including earlier committed ones. Validation on the view
    rejects it, and the earlier checkpoint stays restorable.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    repos.plant_in_sandbox_repo(
        f"index/{hashlib.sha256(MALFORMED_INDEX).hexdigest()}", MALFORMED_INDEX
    )

    with pytest.raises(EgressVerificationError, match="failed validation"):
        await repos.egress("ckpt-00002", id2)

    # The accepted repo never saw the fire: only ckpt-00001 is committed
    # and its files are byte-for-byte unchanged.
    assert repos.dest_files() == files_after_1
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert not list(repos.dest.parent.glob(".egress-*"))
    # ...and the earlier checkpoint still restores from the accepted repo.
    restored = repos.dest.parent.parent / "restore-A"
    repos.restore_dest(id1, restored)
    assert next(restored.rglob("notes.txt")).read_text() == "v1\n"


async def test_egress_rejects_conflicting_index_only_read_data_catches(
    repos: _Repos,
) -> None:
    """A conflicting index + attacker pack is rejected by the content read.

    The addition passes ``restic check`` *without* ``--read-data`` and
    ``restic ls`` (asserted here on the sandbox repo), so validation would
    accept it and let a later fire silently corrupt an earlier snapshot's
    restore if it did not read pack contents. The egress validation runs
    ``check --read-data`` and rejects it, leaving the earlier checkpoint
    intact.
    """
    pytest.importorskip("cryptography")
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    _plant_conflicting_index(repos.repo)

    # The load-bearing property: plain `check` accepts the poisoned repo,
    # only `--read-data` rejects it — so the fix's check flag matters.
    env = {"RESTIC_PASSWORD": PASSWORD, "PATH": os.environ["PATH"]}
    base = [str(repos.restic), "-r", str(repos.repo)]
    assert (
        subprocess.run(
            [*base, "check", "--no-lock", "--no-cache"], env=env, capture_output=True
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            [*base, "check", "--read-data", "--no-lock", "--no-cache"],
            env=env,
            capture_output=True,
        ).returncode
        != 0
    )

    with pytest.raises(EgressVerificationError, match="content check"):
        await repos.egress("ckpt-00002", id2)

    assert repos.dest_files() == files_after_1
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    restored = repos.dest.parent.parent / "restore-A"
    repos.restore_dest(id1, restored)
    assert next(restored.rglob("notes.txt")).read_text() == "v1\n"


async def test_egress_rejects_index_referencing_missing_pack(repos: _Repos) -> None:
    """An index whose pack never arrives is rejected before merge.

    A real fire's data pack is dropped from the sandbox repo after the
    backup, so the egress ships the index and snapshot that reference it
    but not the pack itself. The view then has an index pointing at a pack
    that does not exist; validation rejects it.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    # Drop this fire's new data pack so its index references a missing pack.
    shipped = repos.repo_files() - repos.manifest()
    new_packs = [f for f in shipped if f.startswith("data/")]
    assert new_packs, "expected the second backup to add a data pack"
    for pack in new_packs:
        (repos.repo / pack).unlink()

    with pytest.raises(EgressVerificationError, match="failed validation"):
        await repos.egress("ckpt-00002", id2)

    assert repos.dest_files() == files_after_1
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}


async def test_egress_interrupted_merge_leaves_earlier_restorable(
    repos: _Repos,
) -> None:
    """A hard kill part-way through the merge never buries an earlier fire.

    The merge links packs, then indexes, then snapshots, so an interruption
    (modelled by raising after the packs are linked) leaves the accepted
    repo with orphan packs at worst — the new snapshot is not yet
    referenceable, and every earlier committed snapshot still restores.
    """
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")

    import inspect_ai.util._checkpoint._sandbox_restic.egress as egress_mod

    real_merge = egress_mod._merge_into_repo

    def merge_only_packs(dest_repo: str, staging: Path, written: Any) -> None:
        packs = [name for name in written if name.startswith("data/")]
        real_merge(dest_repo, staging, packs)
        raise RuntimeError("hard kill mid-merge")

    with patch.object(egress_mod, "_merge_into_repo", new=merge_only_packs):
        with pytest.raises(RuntimeError, match="hard kill"):
            await repos.egress("ckpt-00002", id2)

    # The new snapshot never landed; ckpt-00001 is still the only one.
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    # Orphan packs may remain, but the earlier checkpoint still restores.
    restored = repos.dest.parent.parent / "restore-A"
    repos.restore_dest(id1, restored)
    assert next(restored.rglob("notes.txt")).read_text() == "v1\n"


async def test_egress_rejects_unreadable_tarball(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")

    async def fake_copy_out(*_args: object, dest: Path, **_kwargs: object) -> None:
        dest.write_bytes(b"not a tar archive" * 64)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress.copy_out",
        new=fake_copy_out,
    ):
        with pytest.raises(EgressVerificationError, match="unreadable tarball"):
            await repos.egress("ckpt-00001", id1)
    assert repos.dest_files() == set()
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_sweeps_stale_scratch_files(repos: _Repos) -> None:
    """Residue a hard kill leaves (the scratch tar and copy_out's partial) is swept."""
    id1 = repos.backup("ckpt-00001")
    scratch = repos.dest.parent / ".egress-default"
    scratch.mkdir(parents=True)
    stale_tar = scratch / "ckpt-00000.tar"
    stale_partial = copy_out_partial_path(stale_tar)
    stale_tar.write_bytes(b"residue of a fire killed during extraction")
    stale_partial.write_bytes(b"residue of a fire killed mid-transfer")

    await repos.egress("ckpt-00001", id1)

    assert not stale_tar.exists()
    assert not stale_partial.exists()
    assert not list(repos.dest.parent.glob(".egress-*"))


async def test_egress_sweep_spares_sibling_sandbox_in_flight_transfer(
    tmp_path: Path,
) -> None:
    """One sandbox's residue sweep never touches a concurrently egressing sibling.

    ``_fire_once`` egresses every sandbox concurrently and sandbox names
    may prefix one another (``a`` / ``a-b``), so ``a``'s sweep runs while
    ``a-b`` has its scratch tar or ``copy_out`` partial on disk.
    """
    restic = await resolve_restic()
    a = _Repos(tmp_path, restic, name="a")
    ab = _Repos(tmp_path, restic, name="a-b")
    id_a = a.backup("ckpt-00001")
    id_ab = ab.backup("ckpt-00001")
    ab_mid_transfer = anyio.Event()
    a_done = anyio.Event()

    async def copy_out_stalled_for_ab(
        env: LocalShellSandbox, *, dest: Path, label: str, **kwargs: Any
    ) -> None:
        if str(ab.dest) in label:
            partial = copy_out_partial_path(dest)
            partial.write_bytes(b"a-b's transfer, in flight")
            dest.write_bytes(b"a-b's landed tar, awaiting extraction")
            ab_mid_transfer.set()
            await a_done.wait()
            assert partial.exists() and dest.exists()
            partial.unlink()
            dest.unlink()
        await copy_out(env, dest=dest, label=label, **kwargs)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress.copy_out",
        new=copy_out_stalled_for_ab,
    ):
        async with anyio.create_task_group() as tg:
            tg.start_soon(ab.egress, "ckpt-00001", id_ab)
            await ab_mid_transfer.wait()
            assert await a.egress("ckpt-00001", id_a) == id_a
            a_done.set()

    assert await a.dest_snapshots() == {id_a: ["ckpt-00001"]}
    assert await ab.dest_snapshots() == {id_ab: ["ckpt-00001"]}
    assert not list(a.dest.parent.glob(".egress-*"))


async def test_egress_rejects_replayed_snapshot_id(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")

    with pytest.raises(EgressVerificationError, match="replayed"):
        await repos.egress("ckpt-00002", id1)
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}


async def test_egress_rejects_snapshot_with_foreign_tag(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    files_after_1 = repos.dest_files()
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00099")

    with pytest.raises(EgressVerificationError, match="carries tags"):
        await repos.egress("ckpt-00002", id2)
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"]}
    assert repos.dest_files() == files_after_1


async def test_egress_rejects_malformed_snapshot_id(repos: _Repos) -> None:
    repos.backup("ckpt-00001")
    with pytest.raises(EgressVerificationError, match="malformed"):
        await repos.egress("ckpt-00001", "latest")


async def test_egress_refuses_oversized_delta_before_tarring(repos: _Repos) -> None:
    """A delta already over the cap is refused in-sandbox, with no tar built."""
    id1 = repos.backup("ckpt-00001")
    with pytest.raises(RuntimeError, match="nothing was tarred"):
        await repos.egress("ckpt-00001", id1, max_bytes=512)
    assert not list((repos.sandbox_dir / "staging").glob("egress-*.tar"))
    assert repos.dest_files() == set()
    assert not list(repos.dest.parent.glob(".egress-*"))
    assert repos.manifest() == set()


async def test_egress_enforces_transfer_cap(repos: _Repos) -> None:
    """The cap binds on the tar's true size, not just the summed file sizes."""
    id1 = repos.backup("ckpt-00001")
    # Headers and padding make the tar larger than its members: a cap
    # exactly at the members' total passes the pre-check and lets the
    # copy-out refuse the tar.
    members_total = sum((repos.repo / f).stat().st_size for f in repos.repo_files())
    with pytest.raises(RuntimeError, match="exceeds the max_sandbox_snapshot_bytes"):
        await repos.egress("ckpt-00001", id1, max_bytes=members_total)
    assert list((repos.sandbox_dir / "staging").glob("egress-*.tar"))
    assert repos.dest_files() == set()
    assert not list(repos.dest.parent.glob(".egress-*"))
    assert repos.manifest() == set()


async def test_egress_recovers_after_failed_commit(repos: _Repos) -> None:
    """Files re-shipped after a lost phase-2 commit are accepted as no-ops."""
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    # Simulate the phase-2 commit never landing: the manifest is empty.
    (repos.sandbox_dir / "egress-manifest.txt").write_text("")

    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    assert await repos.egress("ckpt-00002", id2) == id2
    assert await repos.dest_snapshots() == {id1: ["ckpt-00001"], id2: ["ckpt-00002"]}
    assert repos.dest_files() == repos.repo_files()
    assert repos.manifest() == repos.repo_files()


async def test_egress_reshipped_config_is_never_rewritten(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    await repos.egress("ckpt-00001", id1)
    dest_config = repos.dest / "config"
    before = dest_config.stat().st_mtime_ns
    # Force the sandbox to re-list config (as a lost phase-2 commit would):
    # the identical bytes are accepted as a no-op, the file untouched.
    manifest = repos.sandbox_dir / "egress-manifest.txt"
    manifest.write_text("\n".join(sorted(repos.manifest() - {"config"})) + "\n")
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")

    assert await repos.egress("ckpt-00002", id2) == id2
    assert dest_config.stat().st_mtime_ns == before
    assert "config" in repos.manifest()


_LAYOUT_ORDER = ["keys", "config", "data", "index", "snapshots"]


async def test_egress_first_cycle_writes_keys_before_config(repos: _Repos) -> None:
    """The first-cycle sentinel (``config``) lands after its key; snapshots last.

    A hard kill between two renames must leave the destination either
    still first-cycle (re-bootstrapped next fire) or openable; a repo
    with ``config`` and no ``keys/*`` is neither.
    """
    id1 = repos.backup("ckpt-00001")
    order: list[str] = []

    def spy(src: IO[bytes], dest_repo: str, name: str, label: str) -> None:
        order.append(name)
        _write_member(src, dest_repo, name, label)

    with patch(
        "inspect_ai.util._checkpoint._sandbox_restic.egress._write_member",
        new=spy,
    ):
        await repos.egress("ckpt-00001", id1)

    kinds = [name.split("/")[0] for name in order]
    assert kinds[:2] == ["keys", "config"]
    assert kinds[-1] == "snapshots"
    assert kinds == sorted(kinds, key=_LAYOUT_ORDER.index)


# --- resume side ------------------------------------------------------


async def test_forget_unrecorded_snapshots_keeps_only_recorded(repos: _Repos) -> None:
    id1 = repos.backup("ckpt-00001")
    (repos.src / "notes.txt").write_text("v2\n")
    id2 = repos.backup("ckpt-00002")
    (repos.src / "notes.txt").write_text("v3\n")
    repos.backup("ckpt-00003")  # captured, never committed
    (repos.src / "notes.txt").write_text("rogue\n")
    repos.backup(None)  # planted by the container

    forgotten = await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.repo),
        PASSWORD,
        recorded_ids=[id1, id2],
        required_id=id2,
    )

    assert sorted(forgotten) == ["ckpt-00003"]
    remaining = {
        s["id"] for s in await list_snapshots(repos.restic, str(repos.repo), PASSWORD)
    }
    assert remaining == {id1, id2}


async def test_forget_unrecorded_snapshots_clears_inherited_locks(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    repos.backup("ckpt-00002")
    lock = repos.repo / "locks" / ("a" * 64)
    lock.parent.mkdir(exist_ok=True)
    lock.write_bytes(b"lock residue copied from a killed attempt")

    await forget_unrecorded_snapshots(
        repos.restic,
        str(repos.repo),
        PASSWORD,
        recorded_ids=[id1],
        required_id=id1,
    )

    assert not lock.exists()
    assert {
        s["id"] for s in await list_snapshots(repos.restic, str(repos.repo), PASSWORD)
    } == {id1}


async def test_forget_unrecorded_snapshots_requires_latest_recorded(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")

    with pytest.raises(RuntimeError, match="does not contain snapshot"):
        await forget_unrecorded_snapshots(
            repos.restic,
            str(repos.repo),
            PASSWORD,
            recorded_ids=[id1, "f" * 64],
            required_id="f" * 64,
        )
    # Nothing was forgotten before the check failed.
    assert len(await list_snapshots(repos.restic, str(repos.repo), PASSWORD)) == 2


async def test_forget_unrecorded_snapshots_rejects_malformed_ids(
    repos: _Repos,
) -> None:
    id1 = repos.backup("ckpt-00001")
    for bad in ("", "latest", "ABCDEF01"):
        with pytest.raises(RuntimeError, match="malformed"):
            await forget_unrecorded_snapshots(
                repos.restic,
                str(repos.repo),
                PASSWORD,
                recorded_ids=[id1, bad],
                required_id=id1,
            )
    assert len(await list_snapshots(repos.restic, str(repos.repo), PASSWORD)) == 1


async def test_ingress_restores_recorded_snapshot_not_latest(
    repos: _Repos, tmp_path: Path
) -> None:
    id1 = repos.backup("ckpt-00001")
    (repos.src / "notes.txt").write_text("v2\n")
    repos.backup("ckpt-00002")
    # Adopt the sandbox repo as the host-side copy a resume would ingress.
    host_repo = tmp_path / "adopted"
    shutil.copytree(repos.repo, host_repo)
    fresh_sandbox = tmp_path / "fresh-sandbox"
    fresh_sandbox.mkdir()
    (fresh_sandbox / "restic").symlink_to(repos.restic)

    await ingress_sandbox(
        repos.env,
        str(host_repo),
        PASSWORD,
        snapshot_id=id1,
        sandbox_dir=str(fresh_sandbox),
    )

    # `restic restore --target /` puts the file back at its absolute path.
    assert (repos.src / "notes.txt").read_text() == "v1\n"
    # The manifest is reseeded with every inherited repo file.
    seeded = set((fresh_sandbox / "egress-manifest.txt").read_text().split())
    assert seeded == {
        p.relative_to(host_repo).as_posix()
        for p in host_repo.rglob("*")
        if p.is_file() and p.relative_to(host_repo).parts[0] != "locks"
    }


async def test_ingress_rejects_malformed_recorded_id(
    repos: _Repos, tmp_path: Path
) -> None:
    with pytest.raises(RuntimeError, match="malformed"):
        await ingress_sandbox(
            repos.env,
            str(repos.repo),
            PASSWORD,
            snapshot_id="latest; rm -rf /",
            sandbox_dir=str(tmp_path / "fresh"),
        )

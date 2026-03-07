"""Tests for DiskBackedList and DiskBackedDict utilities."""

import os
import tempfile

from pydantic import BaseModel

from inspect_ai._util._disk_backed import DiskBackedDict, DiskBackedList


class SampleModel(BaseModel):
    """Simple Pydantic model for testing pickling."""

    id: int
    name: str
    data: dict[str, int]


# -- DiskBackedList tests -----------------------------------------------------


def test_disk_backed_list_basic() -> None:
    with DiskBackedList([1, 2, 3]) as dbl:
        assert len(dbl) == 3
        assert dbl[0] == 1
        assert dbl[1] == 2
        assert dbl[2] == 3


def test_disk_backed_list_append() -> None:
    with DiskBackedList() as dbl:
        dbl.append("a")
        dbl.append("b")
        assert len(dbl) == 2
        assert dbl[0] == "a"
        assert dbl[1] == "b"


def test_disk_backed_list_extend() -> None:
    with DiskBackedList() as dbl:
        dbl.extend([10, 20, 30])
        assert len(dbl) == 3
        assert list(dbl) == [10, 20, 30]


def test_disk_backed_list_setitem() -> None:
    with DiskBackedList([1, 2, 3]) as dbl:
        dbl[1] = 99
        assert dbl[1] == 99


def test_disk_backed_list_delitem() -> None:
    with DiskBackedList([1, 2, 3]) as dbl:
        del dbl[1]
        # item at index 1 is now deleted; iteration skips it
        items = list(dbl)
        assert 2 not in items
        assert 1 in items
        assert 3 in items


def test_disk_backed_list_pop() -> None:
    with DiskBackedList(["a", "b", "c"]) as dbl:
        val = dbl.pop(1)
        assert val == "b"
        items = list(dbl)
        assert "b" not in items


def test_disk_backed_list_negative_index() -> None:
    with DiskBackedList([10, 20, 30]) as dbl:
        assert dbl[-1] == 30
        assert dbl[-2] == 20


def test_disk_backed_list_slice() -> None:
    with DiskBackedList([10, 20, 30, 40]) as dbl:
        assert dbl[1:3] == [20, 30]


def test_disk_backed_list_contains() -> None:
    with DiskBackedList([1, 2, 3]) as dbl:
        assert 2 in dbl
        assert 99 not in dbl


def test_disk_backed_list_iteration() -> None:
    items = [1, 2, 3, 4, 5]
    with DiskBackedList(items) as dbl:
        assert list(dbl) == items


def test_disk_backed_list_pydantic_model() -> None:
    models = [
        SampleModel(id=1, name="one", data={"a": 1}),
        SampleModel(id=2, name="two", data={"b": 2}),
    ]
    with DiskBackedList(models) as dbl:
        assert len(dbl) == 2
        retrieved = dbl[0]
        assert isinstance(retrieved, SampleModel)
        assert retrieved.id == 1
        assert retrieved.name == "one"
        assert retrieved.data == {"a": 1}


def test_disk_backed_list_cleanup() -> None:
    tmpdir: str = ""
    with DiskBackedList([1]) as dbl:
        tmpdir = dbl._tmpdir
        assert os.path.exists(tmpdir)
    # After context exit, the temp directory should be cleaned up
    assert not os.path.exists(tmpdir)


def test_disk_backed_list_custom_path() -> None:
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "test_db")
        dbl = DiskBackedList([1, 2], path=path)
        assert dbl[0] == 1
        dbl.close()


def test_disk_backed_list_index_error() -> None:
    with DiskBackedList([1]) as dbl:
        try:
            _ = dbl[5]
            assert False, "Should have raised IndexError"
        except IndexError:
            pass


# -- DiskBackedDict tests ----------------------------------------------------


def test_disk_backed_dict_basic() -> None:
    with DiskBackedDict() as dbd:
        dbd["key1"] = "value1"
        dbd["key2"] = 42
        assert dbd["key1"] == "value1"
        assert dbd["key2"] == 42
        assert len(dbd) == 2


def test_disk_backed_dict_contains() -> None:
    with DiskBackedDict() as dbd:
        dbd["x"] = 1
        assert "x" in dbd
        assert "y" not in dbd


def test_disk_backed_dict_delete() -> None:
    with DiskBackedDict() as dbd:
        dbd["a"] = 1
        dbd["b"] = 2
        del dbd["a"]
        assert "a" not in dbd
        assert len(dbd) == 1


def test_disk_backed_dict_get() -> None:
    with DiskBackedDict() as dbd:
        dbd["x"] = 42
        assert dbd.get("x") == 42
        assert dbd.get("missing") is None
        assert dbd.get("missing", "default") == "default"


def test_disk_backed_dict_keys_values_items() -> None:
    with DiskBackedDict() as dbd:
        dbd["a"] = 1
        dbd["b"] = 2
        assert dbd.keys() == {"a", "b"}
        assert set(dbd.values()) == {1, 2}
        assert set(dbd.items()) == {("a", 1), ("b", 2)}


def test_disk_backed_dict_iteration() -> None:
    with DiskBackedDict() as dbd:
        dbd["x"] = 1
        dbd["y"] = 2
        keys = list(dbd)
        assert set(keys) == {"x", "y"}


def test_disk_backed_dict_pydantic_model() -> None:
    model = SampleModel(id=1, name="test", data={"key": 42})
    with DiskBackedDict() as dbd:
        dbd["model"] = model
        retrieved = dbd["model"]
        assert isinstance(retrieved, SampleModel)
        assert retrieved.id == 1
        assert retrieved.name == "test"


def test_disk_backed_dict_cleanup() -> None:
    tmpdir: str = ""
    with DiskBackedDict() as dbd:
        dbd["x"] = 1
        tmpdir = dbd._tmpdir
        assert os.path.exists(tmpdir)
    assert not os.path.exists(tmpdir)


def test_disk_backed_dict_key_error() -> None:
    with DiskBackedDict() as dbd:
        try:
            _ = dbd["nonexistent"]
            assert False, "Should have raised KeyError"
        except KeyError:
            pass


# -- Complex data types -------------------------------------------------------


def test_disk_backed_list_nested_structures() -> None:
    data = [
        {"messages": [{"role": "user", "content": "hello"}], "score": 0.95},
        {"messages": [{"role": "assistant", "content": "hi"}], "score": 0.8},
    ]
    with DiskBackedList(data) as dbl:
        assert len(dbl) == 2
        item = dbl[0]
        assert item["messages"][0]["content"] == "hello"
        assert item["score"] == 0.95


def test_disk_backed_dict_large_values() -> None:
    large_list = list(range(10000))
    with DiskBackedDict() as dbd:
        dbd["large"] = large_list
        retrieved = dbd["large"]
        assert len(retrieved) == 10000
        assert retrieved[9999] == 9999


# -- Integration tests with eval() -------------------------------------------


def test_eval_disk_backed_basic() -> None:
    """Verify eval() completes successfully with disk_backed=True."""
    from copy import deepcopy

    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import match

    task = Task(
        dataset=[
            Sample(input="Say Hello", target="Hello"),
            Sample(input="Say World", target="World"),
            Sample(input="Say Foo", target="Foo"),
        ],
        scorer=match(),
    )

    log = eval(deepcopy(task), model="mockllm/model", disk_backed=True)[0]
    assert log.status == "success"
    assert len(log.samples) == 3


def test_eval_disk_backed_config_recorded() -> None:
    """Verify log.eval.config.disk_backed is True when enabled."""
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import match

    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        scorer=match(),
    )

    log_disk = eval(task, model="mockllm/model", disk_backed=True)[0]
    assert log_disk.eval.config.disk_backed is True


def test_eval_disk_backed_default_is_none() -> None:
    """Verify disk_backed defaults to None when not set."""
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import match

    task = Task(
        dataset=[Sample(input="Say Hello", target="Hello")],
        scorer=match(),
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.eval.config.disk_backed is None


def test_eval_disk_backed_matches_in_memory() -> None:
    """Verify disk-backed eval produces identical results to in-memory."""
    from copy import deepcopy

    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import match

    samples = [
        Sample(input="Say Hello", target="Hello"),
        Sample(input="Say World", target="World"),
        Sample(input="Say Foo", target="Foo"),
        Sample(input="Say Bar", target="Bar"),
        Sample(input="Say Baz", target="Baz"),
    ]
    task = Task(dataset=samples, scorer=match())

    log_mem = eval(deepcopy(task), model="mockllm/model")[0]
    log_disk = eval(deepcopy(task), model="mockllm/model", disk_backed=True)[0]

    assert log_mem.status == log_disk.status == "success"
    assert len(log_mem.samples) == len(log_disk.samples)

    # Both should have the same sample IDs
    mem_ids = sorted(s.id for s in log_mem.samples)
    disk_ids = sorted(s.id for s in log_disk.samples)
    assert mem_ids == disk_ids

    # Both should have the same number of events per sample
    for s_mem, s_disk in zip(
        sorted(log_mem.samples, key=lambda s: s.id),
        sorted(log_disk.samples, key=lambda s: s.id),
    ):
        assert len(s_mem.messages) == len(s_disk.messages)
        assert len(s_mem.events) == len(s_disk.events)


def test_eval_disk_backed_multi_epoch() -> None:
    """Verify multi-epoch evaluations work with disk-backed storage."""
    from copy import deepcopy

    from inspect_ai import Epochs, Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import match

    task = Task(
        dataset=[
            Sample(input="Say Hello", target="Hello"),
            Sample(input="Say World", target="World"),
        ],
        scorer=match(),
        epochs=Epochs(2, "mean"),
    )

    log = eval(deepcopy(task), model="mockllm/model", disk_backed=True)[0]
    assert log.status == "success"
    # 2 samples * 2 epochs = 4 total
    assert len(log.samples) == 4
    assert log.eval.config.epochs == 2


def test_eval_disk_backed_no_leaked_temp_files() -> None:
    """Verify no inspect_dbl_/inspect_dbd_ temp dirs are left after eval."""
    import glob
    import tempfile
    from copy import deepcopy

    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import match

    tmpdir = tempfile.gettempdir()

    # snapshot existing temp dirs before eval
    before = set(glob.glob(os.path.join(tmpdir, "inspect_dbl_*"))) | set(
        glob.glob(os.path.join(tmpdir, "inspect_dbd_*"))
    )

    task = Task(
        dataset=[
            Sample(input="Say Hello", target="Hello"),
            Sample(input="Say World", target="World"),
            Sample(input="Say Foo", target="Foo"),
            Sample(input="Say Bar", target="Bar"),
            Sample(input="Say Baz", target="Baz"),
        ],
        scorer=match(),
    )

    log = eval(deepcopy(task), model="mockllm/model", disk_backed=True)[0]
    assert log.status == "success"

    # check no new temp dirs remain
    after = set(glob.glob(os.path.join(tmpdir, "inspect_dbl_*"))) | set(
        glob.glob(os.path.join(tmpdir, "inspect_dbd_*"))
    )
    leaked = after - before
    assert len(leaked) == 0, f"Leaked disk-backed temp dirs: {leaked}"

from unittest.mock import patch

from inspect_ai import Task, eval
from inspect_ai._eval.task.log import resolve_external_registry_package_version
from inspect_ai._util.constants import PKG_NAME


def test_external_package_version_logged():
    task = Task()

    # Imaginary package `eval_registry` v1.0.0
    with (
        patch.object(
            type(task),
            "registry_name",
            property(lambda self: "eval_registry/my_task"),
        ),
        patch(
            "inspect_ai._eval.task.log.importlib_metadata.version",
            return_value="1.0.0",
        ),
    ):
        [log] = eval(task, model="mockllm/model")

    assert "eval_registry" in log.eval.packages
    assert log.eval.packages["eval_registry"] == "1.0.0"


class TestResolveExternalRegistryPackageVersion:
    def test_returns_none_when_task_registry_name_is_none(self):
        assert resolve_external_registry_package_version(None) is None

    def test_returns_none_when_registry_package_name_returns_none(self):
        with patch(
            "inspect_ai._eval.task.log.registry_package_name", return_value=None
        ):
            result = resolve_external_registry_package_version("some_task")

        assert result is None

    def test_returns_none_when_package_is_internal(self):
        # i.e. if the task happened to live in `inspect_ai`
        with patch(
            "inspect_ai._eval.task.log.registry_package_name", return_value=PKG_NAME
        ):
            result = resolve_external_registry_package_version("inspect_ai/some_task")

        assert result is None

    def test_returns_package_name_and_version_for_external_package(self):
        with (
            patch(
                "inspect_ai._eval.task.log.registry_package_name",
                return_value="external_package",
            ),
            patch(
                "inspect_ai._eval.task.log.importlib_metadata.version",
                return_value="1.2.3",
            ),
        ):
            result = resolve_external_registry_package_version(
                "external_package/some_task"
            )

        assert result is not None
        assert result == ("external_package", "1.2.3")

    def test_returns_none_when_package_not_found(self):
        from importlib import metadata as importlib_metadata

        with (
            patch(
                "inspect_ai._eval.task.log.registry_package_name",
                return_value="nonexistent_package",
            ),
            patch(
                "inspect_ai._eval.task.log.importlib_metadata.version",
                side_effect=importlib_metadata.PackageNotFoundError(
                    "nonexistent_package"
                ),
            ),
        ):
            result = resolve_external_registry_package_version(
                "nonexistent_package/some_task"
            )

        assert result is None

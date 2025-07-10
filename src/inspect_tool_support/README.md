# Design

![diagram](https://raw.githubusercontent.com/UKGovernmentBEIS/inspect_ai/refs/heads/main/src/inspect_tool_support/shared_tool_container_design.svg)

Inspect calls into the sandboxed image are done statelessly via `docker exec inspect-tool-support`.

Some tools can be implemented without the need for any in-process state. For those tools, the tool code will be executed within the `inspect-tool-support` process.

For tools that require the maintenance of state over the lifetime of and sandbox, this image marshals tool calls into a long running process via JSON RPC to an http server process. That server then dispatches tool calls to tool specific `@method` handlers.

### Stateful Tool Design Pattern

Each stateful tool should have its own subdirectory that contains the following files:

- `json_rpc_methods.py`

  This module contains all of the JSON RPC `@method` functions — one for each tool (e.g. the web browser tool is actually a set of distinct tools). It is responsible for unpacking the JSON RPC request and forwarding the call to a transport-agnostic, strongly typed, stateful controller.

- `tool_types.py`

  This module includes the `pydantic` models representing the types for tool call parameters and results.

- `controller.py`

  This is transport-agnostic, strongly typed code that manages the tool specific in-process state and performs requested commands.

## Release Process

### Overview

The release process for this project separates code commits from package publishing. While developers can make frequent commits to the repository, package releases are performed on a different tempo, typically when enough meaningful changes have accumulated. This approach allows for continuous development while providing stable, well-documented releases.

Pending changelog items in the `unreleased_changes/` directory serve two key purposes:

1. They document all changes that will be included in the next release
2. They determine what type of semantic version bump (major, minor, or patch) will be needed when publishing these pending changes

This system ensures that version numbers accurately reflect the nature of changes between releases according to semantic versioning principles.

### Documenting Changes

All changes should be documented using [`towncrier`](https://towncrier.readthedocs.io/). When making changes to the codebase, developers should create pending changelog items that will be used to update the changelog at release time:

1. Use `towncrier create` to create a new pending changelog item:

   This will interactively prompt you for:

   - The (optional) related issue
   - The type of semantic version change (major, minor, or patch)
   - A description of your change (supporting markdown)

   Alternatively, all options can be provided directly on the command line:

   ```
   towncrier create <issue-number>.[major|minor|patch].md
   ```

   For more details on `towncrier`'s command line options, refer to the [`towncrier` documentation](https://towncrier.readthedocs.io/en/latest/cli.html).

2. Pending changelog items are stored in the `unreleased_changes/` directory and accumulate until the next release.

### Creating a Release

When it's time to make a release:

1. Ensure all changes are committed.

2. Run the `make-release-commit` script:

3. The script automatically:
   - Determines the version bump type (major, minor, or patch) based on the pending changelog items
   - Runs `towncrier build` to incorporate all pending changelog items into `CHANGELOG.md`
   - Updates the version in `pyproject.toml` using `bump2version`
   - Commits the changes into a commit with a message like `Bump inspect-tool-support version: 1.0.2 → 1.1.0`
   - Tags the commit with the new version number `inspect-tool-support-1.1.0`

All changelog items are consumed during the release process and converted into entries in the `CHANGELOG.md` file. After the release, the `unreleased_changes/` directory will be empty, ready to collect changes for the next release cycle.


## Testing
When running `pytest` with inspect to test interactions with this package, you may wish to test your _local_ version of the `inspect_tool_support` code instead of the latest published package. Passing the flag `--local-inspect-tools` to pytest when running tests from `test_inspect_tool_support.py` will build and install the package from source, for example:

```sh
pytest tests/tools/test_inspect_tool_support.py --runslow --local-inspect-tools
```
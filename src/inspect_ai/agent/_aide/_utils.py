import re
import shutil
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import black
from black.parsing import InvalidInput

from inspect_ai.util import sandbox

SANBDOX_DATA_PREVIEW_LOCATION = "/tmp/_script_data_preview.py"
LOCAL_DATA_PREVIEW_LOCATION = (
    Path(__file__).parent / "assets" / "_script_data_preview.py"
)
AIDE_REQUIRED_PACKAGES = [
    "pandas",
    "genson",
    "humanize",
]


async def get_data_preview_in_container(workdir: str) -> str:
    output = await sandbox().exec(
        cmd=["python", SANBDOX_DATA_PREVIEW_LOCATION, workdir]
    )
    if output.returncode != 0:
        if "ModuleNotFoundError" in output.stderr:
            required_packages = "\n".join(AIDE_REQUIRED_PACKAGES)
            raise ModuleNotFoundError(
                f"Module not found in sandbox.\n The following packages are required to be installed within your sandbox to use aide agent: \n\n{required_packages}\n\nPlease install the required modules in your Dockerfile to use aide agent. \n\nError: \n\n```\n{output.stderr}\n```"
            )
        return f"Error getting data preview.\nStderr:\n{output.stderr}"
    return output.stdout


def copytree(src: Path, dst: Path, use_symlinks=True):
    """
    Copy contents of `src` to `dst`. Unlike shutil.copytree, the dst dir can exist and will be merged.

    If src is a file, only that file will be copied. Optionally uses symlinks instead of copying.

    Args:
        src (Path): source directory
        dst (Path): destination directory
        use_symlinks (bool): whether to use symlinks instead of copying
    """
    assert dst.is_dir()

    if src.is_file():
        dest_f = dst / src.name
        assert not dest_f.exists(), dest_f
        if use_symlinks:
            (dest_f).symlink_to(src)
        else:
            shutil.copyfile(src, dest_f)
        return

    for f in src.iterdir():
        dest_f = dst / f.name
        assert not dest_f.exists(), dest_f
        if use_symlinks:
            (dest_f).symlink_to(f)
        elif f.is_dir():
            shutil.copytree(f, dest_f)
        else:
            shutil.copyfile(f, dest_f)


def clean_up_dataset(path: Path):
    for item in path.rglob("__MACOSX"):
        if item.is_dir():
            shutil.rmtree(item)
    for item in path.rglob(".DS_Store"):
        if item.is_file():
            item.unlink()


def extract_archives(path: Path):
    """
    Unzips all .zip files within `path` and cleans up task dir

    [TODO] handle nested zips
    """
    for zip_f in path.rglob("*.zip"):
        f_out_dir = zip_f.with_suffix("")

        # special case: the intended output path already exists (maybe data has already been extracted by user)
        if f_out_dir.exists():
            # if it's a file, it's probably exactly the same as in the zip -> remove the zip
            # [TODO] maybe add an extra check to see if zip file content matches the colliding file
            if f_out_dir.is_file() and f_out_dir.suffix != "":
                zip_f.unlink()
            continue

        f_out_dir.mkdir(exist_ok=True)
        with zipfile.ZipFile(zip_f, "r") as zip_ref:
            zip_ref.extractall(f_out_dir)

        # remove any unwanted files
        clean_up_dataset(f_out_dir)

        contents = list(f_out_dir.iterdir())

        # special case: the zip contains a single dir/file with the same name as the zip
        if len(contents) == 1 and contents[0].name == f_out_dir.name:
            sub_item = contents[0]
            # if it's a dir, move its contents to the parent and remove it
            if sub_item.is_dir():
                for f in sub_item.rglob("*"):
                    shutil.move(f, f_out_dir)
                sub_item.rmdir()
            # if it's a file, rename it to the parent and remove the parent
            elif sub_item.is_file():
                sub_item_tmp = sub_item.rename(f_out_dir.with_suffix(".__tmp_rename"))
                f_out_dir.rmdir()
                sub_item_tmp.rename(f_out_dir)

        zip_f.unlink()


def preproc_data(path: Path):
    extract_archives(path)
    clean_up_dataset(path)


def prep_tmp_agent_workspace(
    data_dir: Path, copy_data: bool = True, preprocess_data: bool = True
) -> Path:
    """Setup the agent's workspace and preprocess data if necessary."""
    with TemporaryDirectory(delete=False) as workspace_dir:
        workspace_dir = Path(workspace_dir)
        (workspace_dir / "input").mkdir(parents=True, exist_ok=True)
        (workspace_dir / "working").mkdir(parents=True, exist_ok=True)

        copytree(data_dir, workspace_dir / "input", use_symlinks=not copy_data)
        if preprocess_data:
            preproc_data(workspace_dir / "input")
        return workspace_dir


def get_sandbox_files_dict(
    local_workspace_dir: str | Path | None = None,
    remote_workspace_dir: str | Path = None,
) -> dict:
    # read all files in workspace_dir recursively and construct a dict for inspect
    if local_workspace_dir:
        files = [f for f in Path(local_workspace_dir).rglob("*") if f.is_file()]
        files_dict = {
            str(
                Path(remote_workspace_dir)
                / "input"
                / f.relative_to(local_workspace_dir)
            ): str(f.resolve())
            for f in files
        }
    else:
        files_dict = {}
    files_dict[str(Path(remote_workspace_dir) / "working" / ".gitkeep")] = ""
    files_dict[SANBDOX_DATA_PREVIEW_LOCATION] = str(
        LOCAL_DATA_PREVIEW_LOCATION.resolve()
    )
    return files_dict


def prepare_and_get_sandbox_files(
    data_dir: Path | None, workspace_dir: Path | None, preproc_data: bool
) -> dict:
    """Prepare the agent's workspace and get the sandbox files dict."""
    if data_dir and preproc_data:
        tmp_workspace = prep_tmp_agent_workspace(data_dir, preprocess_data=preproc_data)
    else:
        tmp_workspace = data_dir
    return get_sandbox_files_dict(tmp_workspace, workspace_dir)


async def setup_sandbox_workspace(
    data_dir: Path | None,
    workspace_dir: str | Path | None,
    preproc_data: bool,
) -> None:
    files_dict = prepare_and_get_sandbox_files(
        data_dir,
        workspace_dir,
        preproc_data,
    )

    # copy files to sandbox
    for dst, src in files_dict.items():
        if Path(src).is_file():
            contents = Path(src).read_bytes()
            await sandbox().write_file(dst, contents)
        elif Path(src).is_dir() and src != "":
            raise IsADirectoryError(
                f"Unexpected directory in sandbox files dict: {src}"
            )
        else:
            # assume that src == contents
            await sandbox().write_file(dst, src)


def wrap_code(code: str, lang="python") -> str:
    """Wraps code with three backticks."""
    return f"```{lang}\n{code}\n```"


def is_valid_python_script(script: str) -> bool:
    """Check if a script is a valid Python script."""
    try:
        compile(script, "<string>", "exec")
        return True
    except SyntaxError:
        return False


def trim_long_string(string: str, threshold: int = 5100, k: int = 2500):
    # Check if the length of the string is longer than the threshold
    if len(string) > threshold:
        # Output the first k and last k characters
        first_k_chars = string[:k]
        last_k_chars = string[-k:]

        truncated_len = len(string) - 2 * k

        return f"{first_k_chars}\n ... [{truncated_len} characters truncated] ... \n{last_k_chars}"
    else:
        return string


def extract_code(text: str) -> str:
    """Extract python code blocks from the text."""
    parsed_codes = []

    # When code is in a text or python block
    matches = re.findall(r"```(python)?\n*(.*?)\n*```", text, re.DOTALL)
    for match in matches:
        code_block = match[1]
        parsed_codes.append(code_block)

    # When the entire text is code or backticks of the code block is missing
    if len(parsed_codes) == 0:
        matches = re.findall(r"^(```(python)?)?\n?(.*?)\n?(```)?$", text, re.DOTALL)
        if matches:
            code_block = matches[0][2]
            parsed_codes.append(code_block)

    # validate the parsed codes
    valid_code_blocks = [
        format_code(c) for c in parsed_codes if is_valid_python_script(c)
    ]
    return format_code("\n\n".join(valid_code_blocks))


def extract_text_up_to_code(s: str) -> str:
    """Extract (presumed) natural language text up to the start of the first code block."""
    if "```" not in s:
        return ""
    return s[: s.find("```")].strip()


def format_code(code: str) -> str:
    """Format Python code using Black."""
    try:
        return black.format_str(code, mode=black.FileMode())
    except InvalidInput:
        return code


def compile_prompt_to_md(prompt: dict | str | list, _header_depth: int = 1) -> str:
    if isinstance(prompt, str):
        return prompt.strip() + "\n"
    elif isinstance(prompt, list):
        return "\n".join([f"- {s.strip()}" for s in prompt] + ["\n"])

    out = []
    header_prefix = "#" * _header_depth
    for k, v in prompt.items():
        out.append(f"{header_prefix} {k}\n")
        out.append(compile_prompt_to_md(v, _header_depth=_header_depth + 1))
    return "\n".join(out)

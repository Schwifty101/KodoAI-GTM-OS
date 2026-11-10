import subprocess
from pathlib import Path

import pytest

DATA = sorted(str(p) for p in Path("gtm/data").glob("*") if p.is_file())


def test_there_are_data_files_to_check():
    assert {Path(p).name for p in DATA} >= {"chains.txt", "signal_prompt.md", "draft_prompt.md"}


@pytest.mark.parametrize("path", DATA)
def test_runtime_data_files_are_not_git_ignored(path):
    """gtm imports these at load time. A .gitignore rule once hid them, so a fresh clone crashed while this checkout (which has the files) passed."""
    ignored = subprocess.run(["git", "check-ignore", "-q", path], capture_output=True).returncode == 0
    assert not ignored, f"{path} is ignored by .gitignore, so it would be missing from a clone"

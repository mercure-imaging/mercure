"""
json_io.py
==========
Crash-safe JSON writes for mercure's on-disk state: task files and ``mercure.json``.

Writing with ``open(path, "w")`` truncates the target *before* any new content exists, so a
crash, a service kill or a full disk inside that window leaves a partially written file that
every later reader treats as corrupt. For files another process reads (the processor cannot
prioritize a task whose ``task.json`` it cannot parse; every service re-reads ``mercure.json``
on its next tick) that turns a transient failure into a permanent one.

All such writes go through :func:`write_json_atomic`: the payload is serialised into a scratch
file in the same directory and only moved onto the target with ``os.replace``, which is atomic
within a filesystem. A reader therefore observes either the complete previous file or the
complete new one, and never a missing file (we replace, never unlink-then-rename).
"""
import json
import os
import tempfile
from os import PathLike
from pathlib import Path
from typing import Any, Optional, Union

# Suffix of the scratch files created by write_json_atomic(). A crash between creating the
# scratch file and the final os.replace() can leave one behind, so code that sweeps whole
# folders must skip this suffix (see process_series.backup_input_images() and the in/ move loop).
TMP_SUFFIX = ".json.tmp"

# Mode used when creating a file that does not exist yet. tempfile.mkstemp() creates 0600,
# which would be a silent regression: plain open(path, "w") honoured the umask (0644), and
# task files must stay readable by processing containers.
DEFAULT_MODE = 0o644


def is_write_temp_file(name: str) -> bool:
    """Whether ``name`` is a scratch file left by an interrupted atomic write."""
    return name.endswith(TMP_SUFFIX)


def write_json_atomic(
    path: Union[str, PathLike], payload: Any, indent: Optional[int] = None, fsync: bool = True
) -> None:
    """Write ``payload`` as JSON to ``path``, replacing any existing file atomically.

    The scratch file is created in the target's own directory because ``os.replace`` is only
    atomic within a single filesystem. The mode of a replaced file is preserved (widened modes
    matter: ``docker_runtime`` chmods ``in/**`` to 0666 so a module running as another uid can
    read its task file); new files are created with :data:`DEFAULT_MODE`.

    ``fsync`` gives crash consistency for the file contents. Directory fsync is deliberately
    not attempted: it is unsupported by the fake filesystem the test suite runs on, and
    power-loss durability is a deployment-level concern rather than a per-write one.
    """
    target = Path(path)
    directory = str(target.parent) if str(target.parent) else "."

    fd, tmp_name = tempfile.mkstemp(prefix=".", suffix=TMP_SUFFIX, dir=directory)
    try:
        with os.fdopen(fd, "w") as tmp_file:
            json.dump(payload, tmp_file, indent=indent)
            tmp_file.flush()
            if fsync:
                os.fsync(tmp_file.fileno())

        try:
            mode = target.stat().st_mode & 0o777
        except OSError:
            mode = DEFAULT_MODE
        os.chmod(tmp_name, mode)

        os.replace(tmp_name, str(target))
    except BaseException:
        # Never leave scratch files behind on a failed write; the target is still intact.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise

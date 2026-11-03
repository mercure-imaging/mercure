"""
folder_io.py
============
Moving task folders between mercure's service folders (outgoing, success, error, discard).

Several services move results into folders that are named after the task id, and several instances
of each service run at the same time. ``shutil.move(source, target)`` looks like the obvious way to
do it, but if ``target`` exists as a directory it does **not** fail and does not overwrite - it
moves the source *inside* that directory (``<success>/<task_id>/<task_id>/``). Two movers that
resolve the same destination name at the same moment therefore produce a nested folder that the
queue UI, the bookkeeper and the cleaner can no longer find, while both of them believe they
succeeded.

:func:`move_into_folder` uses ``os.rename`` instead: a rename never nests - it fails with
``ENOTEMPTY``/``EEXIST`` when the name is taken. The collision is then resolved with a unique name,
so every mover ends up with its own top-level folder. Cross-filesystem moves (``EXDEV``) fall back
to ``shutil.move`` under a name that was checked to be free.
"""
import errno
import os
import typing
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Union

# A rename fails with one of these when the destination name is unusable - which means "someone
# else got the name first", not "the move is impossible".
_COLLISION_ERRORS = (errno.ENOTEMPTY, errno.EEXIST, errno.EISDIR, errno.ENOTDIR)


def _unique_target(destination_folder: Path, name: str) -> Path:
    """A destination name that cannot collide with a competing mover's name."""
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S_%f")
    return destination_folder / f"{name}_{stamp}_{uuid.uuid4().hex[:8]}"


def _move_cross_device(source: Path, target: Path) -> Path:
    """Copy-and-delete fallback for a move across filesystems.

    ``shutil.move`` nests into an existing directory, so the name has to be verified to be free
    first; the residual window is closed by choosing a unique name for the retry.
    """
    if target.exists():
        target = _unique_target(target.parent, target.name)
    shutil.move(str(source), str(target))
    return target


def move_into_folder(source: Union[str, Path], destination_folder: Union[str, Path],
                     name: typing.Optional[str] = None) -> Path:
    """Move ``source`` to ``destination_folder/<name>`` and return the resulting path.

    Never nests the source inside an existing folder: if the name is already taken (another service
    or another instance moved a task of the same name there), the source is placed in a distinctly
    named top-level folder instead.
    """
    source = Path(source)
    destination_folder = Path(destination_folder)
    target = destination_folder / (name or source.name)

    try:
        os.rename(source, target)
        return target
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            return _move_cross_device(source, target)
        if exc.errno not in _COLLISION_ERRORS:
            raise
    # Name taken: claim a name of our own.
    target = _unique_target(destination_folder, target.name)
    try:
        os.rename(source, target)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        return _move_cross_device(source, target)
    return target

"""
route_series.py
===============
Provides functions for routing/processing of series. For study-level processing, series will be pushed into study folders.
"""

import contextlib
import json
# Standard python includes
import os
import shutil
import typing
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple, Union

# App-specific includes
import common.config as config
import common.helper as helper
import common.log_helpers as log_helpers
import common.monitor as monitor
import common.notification as notification
import common.rule_evaluation as rule_evaluation
from common.json_io import write_json_atomic
from common.constants import mercure_actions, mercure_defs, mercure_events, mercure_names, mercure_options, mercure_rule
from common.types import Rule
from pydicom import dcmread
from routing.common import generate_task_id
from routing.generate_taskfile import create_series_task, create_study_task, update_study_task
from typing_extensions import Literal

# Create local logger instance
logger = config.get_logger()


@log_helpers.clear_task_decorator
def route_series(task_id: str, series_UID: str, files: typing.List[Path] = []) -> None:
    """
    Processes the series with the given series UID from the incoming folder.
    """
    logger.setTask(task_id)
    monitor.send_register_task(task_id, series_UID)
    base_dir = Path(config.mercure.incoming_folder) / series_UID
    lock_file = base_dir / mercure_names.LOCK
    if lock_file.exists():
        # Series is locked, so another instance might be working on it
        return

    # Create lock file in the incoming folder and prevent other instances from working on this series
    try:
        lock = helper.FileLock(lock_file)
    except FileNotFoundError:
        # Series likely already processed by other instance of router
        logger.debug("Series {} is already moved, skipping".format(series_UID))
        return
    except FileExistsError:
        # Series likely already processed by other instance of router
        logger.debug("Series {} is locked, skipping".format(series_UID))
        return
    except Exception:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f"Unable to create lock file {lock_file}", task_id)  # handle_error
        return

    # The incoming lock is released on every path, including unexpected exceptions; FileLock no
    # longer relies on garbage collection for that.
    with lock:
        logger.info(f"Evaluating series {series_UID}")
        fileList = []
        seriesPrefix = series_UID + mercure_defs.SEPARATOR

        if not files:
            # Collect all files belonging to the series
            for entry in os.scandir(base_dir):
                if entry.name.endswith(mercure_names.TAGS) and entry.name.startswith(seriesPrefix) and not entry.is_dir():
                    stemName = entry.name[:-5]
                    fileList.append(stemName)
            logger.debug(f"Found files: {fileList}")
        else:
            fileList = [str(f.with_suffix("")) for f in files]

        logger.info("DICOM files found: " + str(len(fileList)))
        if not len(fileList):
            logger.error(f"No tags files found for series {series_UID}", task_id)  # handle_error
            return

        if config.mercure.store_sample_dicom_tags:
            example_dcm: Optional[Path] = base_dir / (fileList[0] + ".dcm")
            if not example_dcm or not example_dcm.exists():
                example_dcm = base_dir / (fileList[0])
                if not example_dcm.exists():
                    example_dcm = None
            if example_dcm:
                try:
                    monitor.send_update_task_tags(task_id, dcmread(example_dcm, stop_before_pixels=True).to_json_dict())
                except:
                    logger.exception("Error reading example DICOM file", task_id)

        # Use the tags file from the first slice for evaluating the routing rules
        tagsMasterFile = base_dir / (fileList[0] + mercure_names.TAGS)
        if not tagsMasterFile.exists():
            logger.error(f"Missing file! {tagsMasterFile.name}", task_id)  # handle_error
            return

        tagsList_encoding_error = False
        try:
            tagsList: Dict[str, str] = {}
            try:
                with open(tagsMasterFile, "r", encoding="utf-8", errors="strict") as json_file:
                    tagsList = json.load(json_file)
            except UnicodeDecodeError:
                with open(tagsMasterFile, "r", encoding="utf-8", errors="surrogateescape") as json_file:
                    tagsList = json.load(json_file)
                    tagsList_encoding_error = True

        except Exception:
            logger.exception(f"Invalid tag for series {series_UID}", task_id)  # handle_error
            return

        monitor.send_register_series(tagsList)

        # Now test the routing rules and evaluate which rules have been triggered. If one of the triggered
        # rules enforces discarding, discard_series will be True.
        discard_series = ""
        triggered_rules, discard_series = get_triggered_rules(task_id, tagsList)

        monitor.send_task_event(
            monitor.task_event.REGISTER, task_id, len(fileList), ", ".join(triggered_rules), "Registered series"
        )

        # All hand-offs of this series form one transaction (see HandOffs). Every destination folder
        # stays locked until all of them succeeded, so a retry after a failure can never re-send what an
        # earlier attempt already delivered.
        hand_off_ok = False
        with HandOffs(task_id, series_UID) as hand_offs:
            if (len(triggered_rules) == 0) or (discard_series):
                # If no routing rule has triggered or discarding has been enforced, discard the series
                hand_off_ok = push_series_complete(task_id, fileList, series_UID, "DISCARD", discard_series, False,
                                                   tagsList_encoding_error=tagsList_encoding_error,
                                                   hand_offs=hand_offs)
            else:
                # Series-level hand-offs first: they are cheap to undo. The study buffer is shared with
                # other series, so it is only touched once everything else has worked.
                hand_off_ok = (
                    push_series_serieslevel(task_id, triggered_rules, fileList, series_UID, tagsList,
                                            hand_offs=hand_offs)
                    and push_series_studylevel(task_id, triggered_rules, fileList, series_UID, tagsList,
                                               hand_offs=hand_offs)
                )
            if hand_off_ok:
                hand_offs.commit()

        if hand_off_ok and len(triggered_rules) > 1:
            # If more than one rule has triggered, the series files were copied and need to be removed
            remove_series(task_id, fileList, series_UID)

        if not hand_off_ok:
            # Every hand-off of this attempt was rolled back (see HandOffs), so the series is still
            # complete in the incoming folder and nothing has been delivered yet. The next router pass
            # tries again from a clean state.
            logger.error(
                f"Series {series_UID} was not handed over completely and is left in {base_dir} for another attempt",
                task_id,
            )
            return
        shutil.rmtree(base_dir)


def get_triggered_rules(
    task_id: str, tagList: Dict[str, str]
) -> Tuple[Dict[str, Literal[True]], Union[Any, Literal[""]]]:
    """
    Evaluates the routing rules and returns a list with triggered rules.
    """
    triggered_rules: Dict[str, Literal[True]] = {}
    discard_rule = ""
    fallback_rule = ""

    if "mercureForceRule" in tagList:
        force_rule = tagList["mercureForceRule"]
        if force_rule not in config.mercure.rules:
            logger.error(f"Invalid force rule {force_rule} for task {task_id}", task_id)
            return {}, ""
        triggered_rules[force_rule] = True
    else:
        # Iterate over all defined processing rules
        for current_rule in config.mercure.rules:
            try:
                rule: Rule = config.mercure.rules[current_rule]

                # Check if the current rule has been disabled
                if rule.disabled is True:
                    continue

                # If the current rule is flagged as fallback rule, remember the name and skip evaluation.
                # (to avoid having to iterate over the rules again)
                if rule.fallback is True:
                    fallback_rule = current_rule
                    continue

                # Check if the current rule is triggered for the provided tag set
                if rule_evaluation.parse_rule(rule.get("rule", "False"), tagList)[0]:
                    triggered_rules[current_rule] = True
                    if rule.get(mercure_rule.ACTION, "") == mercure_actions.DISCARD:
                        discard_rule = current_rule
                        # If the triggered rule's action is to discard, stop further iteration over the rules
                        break

            except Exception:
                logger.error(f"Invalid rule found: {current_rule}", task_id)  # handle_error
                continue

    # If no rule has triggered but a fallback rule exists, then evaluate and apply this rule
    if (len(triggered_rules) == 0) and (fallback_rule):
        try:
            if rule_evaluation.parse_rule(config.mercure.rules[fallback_rule].get("rule", "False"), tagList)[0]:
                triggered_rules[fallback_rule] = True
                if config.mercure.rules[fallback_rule].get(mercure_rule.ACTION, "") == mercure_actions.DISCARD:
                    discard_rule = fallback_rule
        except Exception:
            logger.error(f"Invalid fallback rule: {fallback_rule}", task_id)  # handle_error

    logger.info("Triggered rules:")
    logger.info(triggered_rules)
    return triggered_rules, discard_rule


class HandOffs:
    """The hand-offs of one series, committed or rolled back together.

    ``route_series()`` hands a series to several places: one outgoing folder per target, one
    processing folder per processing rule, one study buffer per study rule, or the discard/success
    folder. Each one used to be unlocked as soon as it was filled, so the dispatcher or the processor
    could pick it up immediately. If a later hand-off of the same series failed, the series was kept in
    the incoming folder for a retry, and the retry repeated *every* hand-off: the targets that had
    already been served received the series a second time.

    Instead, every destination folder keeps its lock until all hand-offs of the series have succeeded:

    * prepare: each hand-off fills its folder and registers it here, still locked. A locked folder is
      invisible to the dispatcher, the processor, ``route_studies`` and the cleaner;
    * commit: all locks are released at once, and only then are the notifications and the bookkeeper
      events that announce the new tasks sent;
    * rollback: if anything failed (or raised), every registered folder is undone while still
      locked. Nothing has been delivered, so the retry starts from a clean state.

    """

    def __init__(self, task_id: str, series_uid: str) -> None:
        self.task_id = task_id
        self.series_uid = series_uid
        self.source_folder = Path(config.mercure.incoming_folder) / series_uid
        # Undo actions, newest first. Each is called with the folder still locked.
        self._undo: List[Callable[[], None]] = []
        self._locks: List[helper.FileLock] = []
        # Side effects that announce a hand-off to the outside world; only sent on commit.
        self._announce: List[Callable[[], None]] = []
        self.committed = False

    def __enter__(self) -> "HandOffs":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.committed:
            self.rollback()

    def add_folder(self, folder: Path, lock: helper.FileLock, file_list: List[str], moved: bool) -> None:
        """Register a new folder created for this series only (outgoing, processing, discard...)."""
        self._locks.append(lock)

        def undo() -> None:
            restore_incoming(self.source_folder, folder, file_list, moved)
            discard_hand_off_folder(folder, lock)
        self._undo.append(undo)

    def add_study(self, folder: Path, lock: helper.FileLock, file_list: List[str], moved: bool,
                  first_series: bool, previous_task_file: Optional[bytes]) -> None:
        """Register a study buffer the series was added to.

        The buffer may hold other series as well, so undoing only takes this series' files back
        and restores the study task file as it was before.
        """
        self._locks.append(lock)

        def undo() -> None:
            restore_incoming(self.source_folder, folder, file_list, moved)
            if first_series:
                discard_hand_off_folder(folder, lock)
                return
            if previous_task_file is not None:
                try:
                    write_json_atomic(folder / mercure_names.TASKFILE, json.loads(previous_task_file))
                except Exception:
                    logger.error(f"Unable to restore study task file in {folder}", self.task_id)  # handle_error
                    return  # keep the study locked: its task file no longer matches its contents
            if any((folder / (entry + mercure_names.DCM)).exists() for entry in file_list):
                logger.error(f"Keeping {folder} locked: files of series {self.series_uid} could not be "
                             f"taken back out", self.task_id)  # handle_error
                return
            lock.free()
        self._undo.append(undo)

    def announce(self, action: Callable[[], None]) -> None:
        """Queue a notification or bookkeeper event that must only be sent if the hand-off commits."""
        self._announce.append(action)

    def commit(self) -> None:
        """Announce the new tasks, then hand every folder over to the next service.

        Announcing first means the bookkeeper is told about a new task (send_register_task) before
        the dispatcher or processor can pick its folder up and report events for it. A failing
        announcement is logged and skipped: the hand-off itself is complete, and aborting here would
        leave the series in the incoming folder to be delivered a second time.
        """
        self.committed = True
        for action in self._announce:
            try:
                action()
            except Exception:
                logger.exception(f"Unable to announce a hand-off of series {self.series_uid}", self.task_id)
        for lock in self._locks:
            try:
                lock.free()
            except Exception:
                # The folder stays locked: it is stuck, but it is complete and it is never sent twice.
                # Retrying would re-send the folders that were already released, so do not.
                logger.error(f"Unable to remove lock file {lock.lockfile}", self.task_id)  # handle_error

    def rollback(self) -> None:
        for undo in reversed(self._undo):
            try:
                undo()
            except Exception:
                logger.exception(f"Unable to roll back a hand-off of series {self.series_uid}", self.task_id)
        # Locks of folders that could not be emptied are kept on purpose (see discard_hand_off_folder()).
        self._undo.clear()
        self._locks.clear()
        self._announce.clear()


@contextlib.contextmanager
def _scope(outer: Optional[HandOffs], task_id: str, series_uid: str) -> Iterator[HandOffs]:
    """Join the caller's transaction, or run a transaction of our own if there is none.

    The push_* helpers can be called on their own (and are, by tests) or as part of route_series()'s
    transaction. Only the owner of a transaction commits it (``if hand_offs is None:
    transaction.commit()``) or rolls it back.
    """
    if outer is not None:
        yield outer
        return
    with HandOffs(task_id, series_uid) as transaction:
        yield transaction


def push_series_complete(
    task_id: str, file_list: List[str], series_UID: str, destination: str,
    discard_rule: str, copy_files: bool, *, tagsList_encoding_error=False,
    hand_offs: Optional[HandOffs] = None,
) -> bool:
    """
    Moves all files of the series into either the "discard" or "success" folders, which both are periodically cleared.

    :return: False when the files could not be moved; the series then stays in the incoming folder.
    """
    # Define the source and target folder. Use UUID as name for the target folder in the
    # discard or success directory to avoid collisions
    if destination == "DISCARD":
        destination_path = Path(config.mercure.discard_folder) / task_id
    else:
        destination_path = Path(config.mercure.success_folder) / task_id

    # Create subfolder in the discard directory and validate that is has been created
    try:
        destination_path.mkdir()
    except Exception:
        logger.error(f"Unable to create outgoing folder {destination_path}", task_id)  # handle_error
        return False

    # Create lock file in destination folder (to prevent the cleaner module to work on the folder). Note that
    # the DICOM series in the incoming folder has already been locked in the parent function.
    lock_file = destination_path / mercure_names.LOCK
    try:
        lock = helper.FileLock(lock_file)
    except Exception:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f"Unable to create lock file {destination_path}/{mercure_names.LOCK}", task_id)  # handle_error
        shutil.rmtree(destination_path, ignore_errors=True)
        return False

    with _scope(hand_offs, task_id, series_UID) as transaction:
        transaction.add_folder(destination_path, lock, file_list, not copy_files)

        if destination == "DISCARD":
            if discard_rule:
                info_text = "Discard by rule " + discard_rule
            else:
                info_text = "Discard by default."
                if tagsList_encoding_error:
                    info_text += (" Decoding error detected: some tags were not properly decoded,"
                                  " likely due to a malformed DICOM file."
                                  " The expected rule may therefore not have been triggered.")
                    logger.warning(info_text)
            transaction.announce(lambda: monitor.send_task_event(
                monitor.task_event.DISCARD, task_id, len(file_list), discard_rule or "", info_text))

        if not push_files(task_id, series_UID, file_list, destination_path, copy_files):
            logger.error("Problem while moving completed files", task_id)  # handle_error
            return False

        operation_name = "COPY" if copy_files else "MOVE"
        transaction.announce(lambda: monitor.send_task_event(
            monitor.task_event.MOVE, task_id, len(file_list), str(destination_path), operation_name))
        if hand_offs is None:
            transaction.commit()
    return True


def push_series_studylevel(
    task_id: str,
    triggered_rules: Dict[str, Literal[True]],
    file_list: List[str],
    series_UID: str,
    tags_list: Dict[str, str],
    *,
    hand_offs: Optional[HandOffs] = None,
) -> bool:
    """
    Prepares study-level routing for the current series.

    :return: False when at least one study folder could not be filled completely. Everything this
             call changed is then undone by the HandOffs transaction.
    """
    with _scope(hand_offs, task_id, series_UID) as transaction:
        # Move series into individual study-level folder for every rule
        for current_rule in triggered_rules:
            if config.mercure.rules[current_rule].get("action_trigger", "series") != mercure_options.STUDY:
                continue
            if not _push_series_into_study(transaction, task_id, triggered_rules, current_rule, file_list,
                                           series_UID, tags_list):
                return False
        if hand_offs is None:
            transaction.commit()
    return True


def _push_series_into_study(
    transaction: HandOffs,
    task_id: str,
    triggered_rules: Dict[str, Literal[True]],
    current_rule: str,
    file_list: List[str],
    series_UID: str,
    tags_list: Dict[str, str],
) -> bool:
    # Check if folder exists for buffering series until study completion. If not, create it
    study_UID = tags_list["StudyInstanceUID"]
    target_folder = Path(config.mercure.studies_folder) / (study_UID + mercure_defs.SEPARATOR + current_rule)

    # Several router instances run against the same studies folder, so "does the study
    # folder already exist?" cannot be answered by a lookup: the answer may change before
    # mkdir() runs. Claim the folder with mkdir() itself (exclusive) and treat
    # FileExistsError as "another router got here first, this is not the first series".
    try:
        target_folder.mkdir()
        first_series = True
    except FileExistsError:
        first_series = False
    except Exception:
        logger.error(f"Unable to create study folder {target_folder}", task_id)  # handle_error
        return False

    lock_file = target_folder / mercure_names.LOCK
    try:
        lock = helper.FileLock(lock_file)
    except Exception:
        # Busy (another router or route_studies holds it) or broken. Either way, this attempt is
        # rolled back and the next router pass tries again.
        logger.error(f"Unable to create lock file {lock_file}", task_id)  # handle_error
        if first_series:
            # Another router took the lock on the folder we just created. Never rmtree() it: that
            # router may be filling it. rmdir() only removes it if it is still empty.
            try:
                target_folder.rmdir()
            except OSError:
                pass
        return False

    previous_task_file: Optional[bytes] = None
    if not first_series:
        try:
            previous_task_file = (target_folder / mercure_names.TASKFILE).read_bytes()
        except FileNotFoundError:
            if [p.name for p in target_folder.iterdir()] == [mercure_names.LOCK]:
                # The folder was created by a router that has not locked it yet (or crashed between
                # mkdir() and FileLock()). We hold the lock now, so adopt it as the first series;
                # that router fails to lock it and appends to our study on its next pass.
                first_series = True
            else:
                logger.error(f"Study task file missing in {target_folder}", task_id)  # handle_error
                lock.free()
                return False
        except Exception:
            logger.error(f"Unable to read study task file in {target_folder}", task_id)  # handle_error
            lock.free()
            return False

    moved_files = len(triggered_rules) <= 1
    transaction.add_study(target_folder, lock, file_list, moved_files, first_series, previous_task_file)

    # Push the files first. The study task file below is what makes a study *complete* (the
    # "all expected series received" criterion reads its series list), so recording a series
    # whose images are only partly buffered tells route_studies to dispatch a study with
    # missing images.
    if not push_files(task_id, series_UID, file_list, target_folder, not moved_files):
        logger.error(f"Unable to push files into study folder {target_folder}", task_id)  # handle_error
        return False

    if first_series:
        # Create task file with information on complete criteria
        new_task_id = generate_task_id()
        result = create_study_task(new_task_id, target_folder, triggered_rules,
                                   current_rule, study_UID, tags_list)
        first_event = "Created study task"
    else:
        # Add data from latest series to task file
        result, new_task_id = update_study_task(task_id, target_folder, triggered_rules,
                                                current_rule, study_UID, tags_list)
        first_event = "Added to study task"

    if not result:
        # The files are in the study folder but the study does not know about them, so it would
        # complete without this series. The transaction takes them back out.
        logger.error("Problem assigning series to study", task_id)
        return False

    def announce() -> None:
        monitor.send_task_event(monitor.task_event.ASSIGN, task_id, len(file_list), current_rule, first_event)
        monitor.send_task_event(monitor.task_event.DELEGATE, task_id, len(file_list), new_task_id, current_rule)
        monitor.send_task_event(monitor.task_event.ASSIGN, new_task_id, len(file_list), task_id,
                                "Added series to study")
    transaction.announce(announce)
    return True


def restore_incoming(base_dir: Path, target_folder: Path, file_list: List[str], moved: bool) -> None:
    """
    Undo a hand-off that stopped half-way through, so that neither the incoming folder nor the
    destination folder is left in a state the next service cannot trust.

    Putting the files back turns the hand-off into a retry: nothing is lost, nothing partial is
    offered to the next service, and the router tries again on the next pass.

    :param base_dir: The incoming folder the files came from.
    :param target_folder: The (locked) hand-off folder.
    :param file_list: Series stems of the files that were supposed to be handed over.
    :param moved: True when the hand-off moved (instead of copied) the files, so the only copy of
                  what did arrive is in ``target_folder``.
    """
    for entry in file_list:
        for suffix in (mercure_names.DCM, mercure_names.TAGS):
            pushed_file = target_folder / (entry + suffix)
            if not pushed_file.exists():
                continue
            try:
                if moved:
                    shutil.move(str(pushed_file), str(base_dir / (entry + suffix)))
                else:
                    pushed_file.unlink()
            except Exception:
                # Whatever cannot be put back stays where it is; the folder keeps its lock in that
                # case, and the caller's error tells the operator that the series needs attention.
                logger.error(
                    f"Unable to restore {pushed_file} to {base_dir} after a failed hand-off", ""
                )


def discard_hand_off_folder(target_folder: Path, lock: typing.Optional[helper.FileLock]) -> None:
    """
    Remove a rolled-back hand-off folder, unless something is still in it.

    After :func:`restore_incoming` such a folder holds nothing but its task file, and leaving it in
    the outgoing or processing folder would look like a stalled task to the operator and to the
    bookkeeper. Anything that could not be put back is kept, together with the lock: a folder the
    next service cannot trust must not be unlocked.
    """
    if not target_folder.exists():
        return
    remaining = list(target_folder.glob("*" + mercure_names.DCM))
    if remaining:
        logger.error(
            f"Keeping {target_folder} locked: {len(remaining)} DICOM file(s) could not be restored to the "
            f"incoming folder"
        )
        return
    # Delete while still locked, so no other service can pick the empty folder up in between.
    shutil.rmtree(str(target_folder), ignore_errors=True)
    if lock is not None:
        lock.free()


def push_series_serieslevel(
    task_id: str,
    triggered_rules: Dict[str, Literal[True]],
    file_list: List[str],
    series_UID: str,
    tags_list: Dict[str, str],
    *,
    hand_offs: Optional[HandOffs] = None,
) -> bool:
    """
    Prepares all series-level routings for the current series.

    :return: False when at least one hand-off could not be completed; all of them are then undone.
    """
    with _scope(hand_offs, task_id, series_UID) as transaction:
        ok = (
            push_serieslevel_routing(task_id, triggered_rules, file_list, series_UID, tags_list,
                                     hand_offs=transaction)
            and push_serieslevel_processing(task_id, triggered_rules, file_list, series_UID, tags_list,
                                            hand_offs=transaction)
            and push_serieslevel_notification(task_id, triggered_rules, file_list, series_UID, tags_list,
                                              hand_offs=transaction)
        )
        if not ok:
            return False
        if hand_offs is None:
            transaction.commit()
    return True


def push_serieslevel_routing(
    task_id: str,
    triggered_rules: Dict[str, Literal[True]],
    file_list: List[str],
    series_UID: str,
    tags_list: Dict[str, str],
    *,
    hand_offs: Optional[HandOffs] = None,
) -> bool:
    selected_targets: Dict[str, List[str]] = {}
    # Collect the dispatch-only targets to avoid that a series is sent twice to the
    # same target due to multiple targets triggered (note: this only makes sense for routing-only
    # series tasks, as study-level rules might have different completion criteria and tasks involving
    # processing steps might create different results so that they cannot be pooled)
    with _scope(hand_offs, task_id, series_UID) as transaction:
        for current_rule in triggered_rules:
            rule_definition = config.mercure.rules[current_rule]
            if (
                rule_definition.get("action_trigger", "series") == mercure_options.SERIES
                and rule_definition.get("action") == mercure_actions.ROUTE
            ):
                targets = []
                if rule_definition.get("target"):
                    if isinstance(rule_definition.get("target"), str):
                        # If the target is a string, only add it if it is not empty
                        if rule_definition.get("target"):
                            targets.append(rule_definition.get("target"))
                    else:
                        targets = rule_definition.get("target")

                for target in targets:
                    if not selected_targets.get(target):
                        selected_targets[target] = [current_rule]
                    else:
                        selected_targets[target].append(current_rule)
                transaction.announce(_notify(current_rule, tags_list, mercure_events.RECEIVED, task_id))

        if not push_serieslevel_outgoing(task_id, triggered_rules, file_list, series_UID, tags_list,
                                         selected_targets, hand_offs=transaction):
            return False
        if hand_offs is None:
            transaction.commit()
    return True


def _notify(current_rule: str, tags_list: Dict[str, str], event: mercure_events, task_id: str) -> Callable[[], None]:
    return lambda: trigger_serieslevel_notification(current_rule, tags_list, event, task_id)


def _make_hand_off_folder(task_id: str, parent: str) -> Optional[Tuple[str, Path, helper.FileLock]]:
    """Create a new, locked task folder below ``parent``. Returns None (and cleans up) on failure."""
    new_task_id = generate_task_id()
    target_folder = Path(parent) / new_task_id
    try:
        os.mkdir(str(target_folder))
    except Exception:
        logger.error(f"Unable to create outgoing folder {target_folder}", task_id)  # handle_error
        return None
    try:
        lock = helper.FileLock(target_folder / mercure_names.LOCK)
    except Exception:
        # Can't create lock file, so something must be seriously wrong
        logger.error(f"Unable to create lock file {target_folder / mercure_names.LOCK}", task_id)  # handle_error
        shutil.rmtree(target_folder, ignore_errors=True)
        return None
    return new_task_id, target_folder, lock


def push_serieslevel_processing(
    task_id: str,
    triggered_rules: Dict[str, Literal[True]],
    file_list: List[str],
    series_UID: str,
    tags_list: Dict[str, str],
    *,
    hand_offs: Optional[HandOffs] = None,
) -> bool:
    # Rules with action "processing" or "processing & routing" need to be processed separately
    # (because the processing step can create varying results).
    # Thus, loop over all series-level rules that have triggered.
    with _scope(hand_offs, task_id, series_UID) as transaction:
        for current_rule in triggered_rules:
            rule = config.mercure.rules[current_rule]
            if rule.get("action_trigger", mercure_options.SERIES) != mercure_options.SERIES:
                continue
            if rule.get("action", "") not in (mercure_actions.PROCESS, mercure_actions.BOTH):
                continue
            # Determine if the files should be copied or moved. If only one rule triggered, files can
            # safely be moved, otherwise files will be copied and removed in the end
            copy_files = len(triggered_rules) != 1

            created = _make_hand_off_folder(task_id, config.mercure.processing_folder)
            if created is None:
                return False
            new_task_id, target_folder, lock = created
            transaction.add_folder(target_folder, lock, file_list, not copy_files)

            # Generate task file with processing information
            if not create_series_task(
                new_task_id, target_folder, triggered_rules, current_rule, series_UID, tags_list, ""
            ):
                return False

            if not push_files(task_id, series_UID, file_list, target_folder, copy_files):
                logger.error(
                    f"Unable to push files into processing folder {target_folder}", task_id
                )  # handle_error
                return False

            def announce(new_task_id=new_task_id, target_folder=target_folder, copy_files=copy_files,
                         current_rule=current_rule) -> None:
                monitor.send_task_event(monitor.task_event.DELEGATE, task_id, len(file_list), new_task_id,
                                        current_rule)
                monitor.send_register_task(new_task_id, series_UID, task_id)
                _send_push_event(task_id, file_list, target_folder, copy_files)
                trigger_serieslevel_notification(current_rule, tags_list, mercure_events.RECEIVED, task_id)
            transaction.announce(announce)
        if hand_offs is None:
            transaction.commit()
    return True


def push_serieslevel_notification(
    task_id: str,
    triggered_rules: Dict[str, Literal[True]],
    file_list: List[str],
    series_UID: str,
    tags_list: Dict[str, str],
    *,
    hand_offs: Optional[HandOffs] = None,
) -> bool:
    notification_rules_count = 0

    with _scope(hand_offs, task_id, series_UID) as transaction:
        for current_rule in triggered_rules:
            rule = config.mercure.rules[current_rule]
            if rule.get("action_trigger", mercure_options.SERIES) == mercure_options.SERIES:
                if rule.get("action", "") == mercure_actions.NOTIFICATION:
                    transaction.announce(_notify(current_rule, tags_list, mercure_events.RECEIVED, task_id))
                    transaction.announce(_notify(current_rule, tags_list, mercure_events.COMPLETED, task_id))
                    notification_rules_count += 1

        # If the current rule is "notification-only" and this is the only rule that has been
        # triggered, then discard the files so that they end up in the discard folder. If more
        # than one rule has triggered, the parent function will remove the files from the incoming
        # folder. However, it multiple rules have triggered and all such rules are notifications,
        # make a copy of the files into the discard folder, so that the files can be recovered
        if notification_rules_count > 0:
            if (len(triggered_rules) == 1) or (len(triggered_rules) == notification_rules_count):
                if not push_series_complete(task_id, file_list, series_UID, "SUCCESS", "", len(triggered_rules) > 1,
                                            hand_offs=transaction):
                    return False
        if hand_offs is None:
            transaction.commit()
    return True


def push_serieslevel_outgoing(
    task_id: str,
    triggered_rules: Dict[str, Literal[True]],
    file_list: List[str],
    series_UID: str,
    tags_list: Dict[str, str],
    selected_targets: Dict[str, List[str]],
    *,
    hand_offs: Optional[HandOffs] = None,
) -> bool:
    """
    Move the DICOM files of the series to a separate subfolder for each target in the outgoing folder.

    :return: False when a target folder could not be filled completely. All target folders of the
             series are then rolled back, so none of them is sent before the series can be sent to all.
    """
    # Determine if the files should be copied or moved. If only one rule triggered, files can
    # safely be moved, otherwise files will be copied and removed in the end
    move_operation = len(triggered_rules) == 1

    with _scope(hand_offs, task_id, series_UID) as transaction:
        for i, target in enumerate(selected_targets):
            if target not in config.mercure.targets:
                logger.error(f"Invalid target selected {target}", task_id)  # handle_error
                # TODO: Better error handling!
                continue

            created = _make_hand_off_folder(task_id, config.mercure.outgoing_folder)
            if created is None:
                return False
            new_task_id, target_folder, lock = created

            # If there are more targets for one rule, then move the files only for the last target
            is_operation_move = move_operation and i == len(selected_targets) - 1
            transaction.add_folder(target_folder, lock, file_list, is_operation_move)

            # Collect the rules that triggered the dispatching to the current target
            target_rules: Dict[str, Literal[True]] = {rule: True for rule in selected_targets[target]}

            # Generate task file with dispatch information
            if not create_series_task(new_task_id, target_folder, target_rules, "", series_UID, tags_list, target):
                return False

            if not push_files(task_id, series_UID, file_list, target_folder, not is_operation_move):
                return False

            def announce(new_task_id=new_task_id, target=target, target_folder=target_folder,
                         is_operation_move=is_operation_move) -> None:
                monitor.send_register_task(new_task_id, series_UID, task_id)
                monitor.send_task_event(monitor.task_event.DELEGATE, task_id, len(file_list),
                                        new_task_id, ", ".join(selected_targets[target]))
                _send_push_event(task_id, file_list, target_folder, not is_operation_move)
            transaction.announce(announce)
        if hand_offs is None:
            transaction.commit()
    return True


def _send_push_event(task_id: str, file_list: List[str], target_folder: Path, copied: bool) -> None:
    if copied:
        monitor.send_task_event(monitor.task_event.COPY, task_id, len(file_list), str(target_folder), "Copied files")
    else:
        monitor.send_task_event(monitor.task_event.MOVE, task_id, len(file_list), str(target_folder), "Moved files")


def push_files(task_id: str, series_uid: str, file_list: List[str], target_folder: Path, copy_files: bool) -> bool:
    """
    Copies or moves the given files to the target path. If copy_files is True, files are copied, otherwise moved.
    Note that this function does not create a lock file (this needs to be done by the calling function),
    nor does it send the COPY/MOVE event: callers announce the hand-off once it is committed.
    """
    operation: Callable
    if copy_files is False:
        operation = shutil.move
    else:
        operation = shutil.copy

    source_folder = Path(config.mercure.incoming_folder) / series_uid

    for entry in file_list:
        try:
            operation(source_folder / (entry + mercure_names.DCM), target_folder / (entry + mercure_names.DCM))
            operation(source_folder / (entry + mercure_names.TAGS), target_folder / (entry + mercure_names.TAGS))
            logger.debug(f"Pushed {source_folder / (entry+mercure_names.DCM)}")
        except Exception:
            logger.error(f"Problem while pushing file to outgoing [{entry}]\n"
                         f"Source folder {source_folder}\nTarget folder {target_folder}", task_id)  # handle_error
            return False
    return True


def remove_series(task_id: str, file_list: List[str], series_UID: str) -> bool:
    """
    Deletes the given files from the incoming folder.
    """
    source_folder = Path(config.mercure.incoming_folder) / series_UID
    for entry in file_list:
        try:
            (source_folder / (entry + mercure_names.TAGS)).unlink()
            (source_folder / (entry + mercure_names.DCM)).unlink()
        except Exception:
            logger.error(f"Error while removing file {entry}", task_id)  # handle_error
            return False

    monitor.send_task_event(monitor.task_event.REMOVE, task_id, len(file_list), "", "Removed duplicate files")

    return True


def route_error_files() -> None:
    """
    Looks for error files, moves these files and the corresponding DICOM files to the error folder,
    and sends an alert to the bookkeeper instance.
    """
    error_files_found = 0
    errors_folder = Path(config.mercure.incoming_folder) / "error"
    entries: List[os.DirEntry] = []
    if errors_folder.is_dir():
        entries += list(os.scandir(errors_folder))
    entries += list(os.scandir(config.mercure.incoming_folder))
    for entry in entries:
        if not entry.name.endswith(mercure_names.ERROR) or entry.is_dir():
            continue
        # Check if a lock file exists. If not, create one.
        lock_file = str(entry.path) + mercure_names.LOCK
        if os.path.exists(lock_file):
            continue
        try:
            lock = helper.FileLock(Path(lock_file))
        except Exception:
            continue

        with lock:
            logger.error(f"Found incoming error file {entry.name}")
            error_files_found += 1

            move_error_to = config.mercure.error_folder + "/" + entry.name
            logger.error(f"Moving {entry.name} to {move_error_to}")
            shutil.move(
                entry.path,
                move_error_to,
            )
            dicom_file = Path(entry.path).with_suffix(".dcm")
            dicom_file_b = Path(entry.path).with_suffix("")

            for f in [dicom_file, dicom_file_b]:
                if f.exists():
                    move_to = config.mercure.error_folder + "/" + f.name
                    logger.info(f"Moving {f.name} to {move_to}")
                    shutil.move(
                        str(f),
                        move_to,
                    )

    if error_files_found > 0:
        monitor.send_event(
            monitor.m_events.PROCESSING, monitor.severity.ERROR, f"Error parsing {error_files_found} incoming files"
        )
    return


def trigger_serieslevel_notification(
    current_rule: str, tags_list: Dict[str, str], event: mercure_events, task_id: str
) -> None:
    notification.trigger_notification_for_rule(
        current_rule,
        task_id,
        event,
        tags_list=tags_list,
    )

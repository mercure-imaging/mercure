"""
rsync.py
========
"""

from pathlib import Path
from typing import Any

import common.config as config
from common.types import RsyncTarget, Task
from webinterface.common import async_run_exec

from .base import SubprocessTargetHandler
from .registry import handler_for

logger = config.get_logger()


@handler_for(RsyncTarget)
class RsyncTargetHandler(SubprocessTargetHandler[RsyncTarget]):
    view_template = "targets/rsync.html"
    edit_template = "targets/rsync-edit.html"
    test_template = "targets/rsync-test.html"
    icon = "fa-server"
    display_name = "rsync"

    def get_commands(self, target) -> Any:
        return dict(
            ssh_cmd=["ssh", "-o", "StrictHostKeyChecking=accept-new"],
            ssh_connection=f"{target.user}@{target.host}",
            sshpass_cmd=["sshpass", "-p", target.password],
        )

    def _create_command(self, target: RsyncTarget, source_folder: Path, task: Task):
        cmds = self.get_commands(target)
        ssh_cmd = cmds["ssh_cmd"]
        ssh_connection = cmds["ssh_connection"]
        sshpass_cmd = cmds["sshpass_cmd"]

        dest_folder = f"{target.folder}/{source_folder.stem}"
        transfer_command = [
            "rsync",
            "--chmod",
            "660",
            "-rtvz",
            "-e",
            " ".join(ssh_cmd),
            str(source_folder),
            f"{ssh_connection}:{target.folder}",
        ]

        complete_command = [
            *ssh_cmd,
            ssh_connection,
            "-C",
            f"touch '{dest_folder}/.complete'",
        ]

        commands = [transfer_command, complete_command]

        if target.run_on_complete:
            fullpath = f"{target.folder}/mercure_complete.sh"

            check_exists = [
                *ssh_cmd,
                ssh_connection,
                "-C",
                "test",
                "-x",
                fullpath,
            ]
            # check_sane = [
            #     *ssh_cmd,
            #     ssh_connection,
            #     "-C",
            #     f"""bash -c 'set -x\nrpath="$(realpath "$1")"\n
            #       echo "$rpath"\n[[ $rpath = $2* ]]' _ {fullpath} {target.folder}""",
            # ]
            execute_oncomplete = [
                *ssh_cmd,
                ssh_connection,
                "-C",
                fullpath,
                dest_folder,
                target.get_name(),
            ]
            commands += [check_exists, execute_oncomplete]

        if target.password:
            for c in commands:
                c[:0] = sshpass_cmd

        # if target.password:
        #     complete_command = f"sshpass -p {target.password} " + complete_command

        return commands, {}

    # def send_to_target(
    #     self,
    #     task_id: str,
    #     target: RsyncTarget,
    #     dispatch_info: TaskDispatch,
    #     source_folder: Path,
    #     task: Task,
    # ) -> str:
    #     sysrsync.run(source=source_folder,
    #          destination=target.folder,
    #          destination_ssh = target.host)

    async def test_connection(self, target: RsyncTarget, target_name: str):
        cmds = self.get_commands(target)
        ssh_cmd = cmds["ssh_cmd"]
        ssh_connection = cmds["ssh_connection"]
        sshpass_cmd = cmds["sshpass_cmd"]

        ping_command = ["ping", "-w", "1", "-c", "1", target.host]
        connect_command = [*ssh_cmd, ssh_connection, "-C", "true"]
        folder_command = [*ssh_cmd, ssh_connection, "-C", "test", "-d", target.folder]

        exec_command = [
            *ssh_cmd,
            ssh_connection,
            "-C",
            "test",
            "-x",
            f"{target.folder}/mercure_complete.sh",
        ]

        commands = [ping_command, connect_command, folder_command]
        if target.run_on_complete:
            commands.append(exec_command)

        results = []
        output = b""
        has_err = False
        for c in commands:
            if target.password:
                c = sshpass_cmd + c
            result, stdout, stderr = await async_run_exec(*c)
            output = stdout + stderr
            if result == 0:
                results.append(True)
            else:
                results.append(False)
                has_err = True
                break

        ping_response, ssh_connected, folder_exists, exec_script_exists, *_ = (
            results + [None] * 10
        )

        return dict(
            ping=ping_response,
            ssh_connected=ssh_connected,
            folder_exists=folder_exists,
            exec_script_exists=exec_script_exists if target.run_on_complete else None,
            err=output.decode("utf-8") if has_err else "",
            # err=stderr.decode("utf-8") if not  else "",
        )

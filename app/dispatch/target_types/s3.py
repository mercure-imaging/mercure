from pathlib import Path

import boto3
import botocore
import common.config as config
from common.types import S3Target, Task, TaskDispatch

from .base import TargetHandler
from .registry import handler_for

logger = config.get_logger()


@handler_for(S3Target)
class S3TargetHandler(TargetHandler[S3Target]):
    view_template = "targets/s3.html"
    edit_template = "targets/s3-edit.html"
    display_name = "S3"
    icon = "fa-cloud"

    def create_client(self, target: S3Target):
        return boto3.client(
            "s3",
            region_name=target.region,
            aws_access_key_id=target.access_key_id,
            aws_secret_access_key=target.secret_access_key,
        )

    def send_to_target(self, task_id: str, target: S3Target, dispatch_info: TaskDispatch, source_folder: Path, task: Task
                       ) -> str:
        # send dicoms in source-folder to s3 bucket
        s3_client = self.create_client(target)

        for dcm in source_folder.glob("**/*.dcm"):
            response = s3_client.upload_file(
                str(dcm), target.bucket, (Path(target.prefix) / task_id / dcm.name).as_posix()
            )
            logger.info(response)
            logger.info(f"Uploaded {dcm} to {target.bucket}/{task_id}/{target.prefix}")
        return ""

    def from_form(self, form: dict, factory, current_target: S3Target) -> S3Target:
        if "secret" in form["secret_access_key"]:
            form["secret_access_key"] = current_target.secret_access_key

        return S3Target(**form)

    async def test_connection(self, target: S3Target, target_name: str):
        s3_client = self.create_client(target)
        result = {}
        try:
            s3_client.head_bucket(Bucket=target.bucket)
            result["S3 connection"] = True
            result["Bucket exists"] = True
        except botocore.exceptions.ClientError as e:
            # If a client error is thrown, then check that it was a 404 error.
            # If it was a 404 error, then the bucket does not exist.
            result["S3 connection"] = True
            error_code = int(e.response["Error"]["Code"])
            if error_code == 404:
                result["Bucket exists"] = False
            else:
                result["Bucket exists"] = True
        except Exception:
            result["S3 connection"] = False
            result["Bucket exists"] = False
        return result

import uuid


def generate_task_id() -> str:
    new_uuid = str(uuid.uuid1())
    return new_uuid

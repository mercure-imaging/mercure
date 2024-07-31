import uuid
from dataclasses import dataclass, field
from pathlib import Path

def generate_task_id() -> str:
    new_uuid = str(uuid.uuid1())
    return new_uuid

@dataclass
class SeriesItem:
    modification_time: float = 0
    files: set[Path] = field(default_factory=set)
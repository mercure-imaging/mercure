from typing import Any, Dict, Iterator, Set, Union


class Tags:
    _tags_dict: Dict[str, str]
    _tags_accessed: Set[str]

    def __init__(self, input_dict: Dict[str, str]) -> None:
        self._tags_dict = input_dict
        self._tags_accessed = set()

    def tags_accessed(self) -> Set[str]:
        return self._tags_accessed

    def __getattr__(self, name) -> Union[str, Any]:
        if name in self.__dict__:
            return self.__dict__[name]

        if name in self._tags_dict:
            self._tags_accessed.add(name)
            return self._tags_dict[name]
        else:
            lowered_name = name.lower()
            for k in self._tags_dict:
                if k.lower() == lowered_name:
                    self._tags_accessed.add(k)
                    return self._tags_dict[k]
            raise TagNotFoundException(f"No such tag '{name}' in tags list.")

    def __getitem__(self, name) -> str:
        if name in self._tags_dict:
            self._tags_accessed.add(name)
            return self._tags_dict[name]
        else:
            raise TagNotFoundException(f"No such tag '{name}' in tags list.")

    def __len__(self) -> int:
        return len(self._tags_dict)

    def __iter__(self) -> Iterator[str]:
        return self._tags_dict.__iter__()

    def __contains__(self, name) -> bool:
        return name in self._tags_dict


class TagNotFoundException(Exception):
    pass

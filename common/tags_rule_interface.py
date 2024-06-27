class Tags:
    _tags_dict = None
    _tags_accessed = None

    def __init__(self, input_dict) -> None:
        self._tags_dict = input_dict
        self._tags_accessed = set()

    def tags_accessed(self):
        return self._tags_accessed

    def __getattr__(self, name):
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

    def __getitem__(self, name):
        if name in self._tags_dict:
            self._tags_accessed.add(name)
            return self._tags_dict[name]
        else:
            raise TagNotFoundException(f"No such tag '{name}' in tags list.")

    def __len__(self):
        return len(self._tags_dict)

    def __iter__(self):
        return iter(self._tags_dict)

    def __contains__(self, name):
        return name in self._tags_dict

class TagNotFoundException(Exception):
    pass
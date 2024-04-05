class Tags:
    def __init__(self, input_dict):
        self._dict = input_dict

    def __getattr__(self, name):
        if name in self._dict:
            return self._dict[name]
        else:
            lowered_name = name.lower()
            for k in self._dict:
                if k.lower() == lowered_name:
                    return self._dict[k]
            raise TagNotFoundException(f"No such tag '{name}' in tags list.")

    def __getitem__(self, name):
        if name in self._dict:
            return self._dict[name]
        else:
            raise TagNotFoundException(f"No such tag '{name}' in tags list.")

    def __len__(self):
        return len(self._dict)

    def __iter__(self):
        return iter(self._dict)

    def __contains__(self, name):
        return name in self._dict

class TagNotFoundException(Exception):
    pass
"""
test_cleaner.py
===============
"""
from datetime import datetime

import cleaner as c

# helper func
def _to_time(time):
    return datetime.strptime(time, "%H:%M").time()


def test_cleaner_no_syntax_errors():
    """ Checks if cleaner.py can be started. """
    assert c


def test_is_not_nightshift():
    is_not = c._is_nightshift("22:00", "06:00", _to_time("21:00"))
    assert not is_not


def test_is_nightshift():
    is_ = c._is_nightshift("22:00", "06:00", _to_time("23:00"))
    assert is_


def test_other_input_nightshift():
    is_ = c._is_nightshift("22:00", "6:00", _to_time("5:00"))
    assert is_


def test_wrong_start_input_nightshift():
    is_ = c._is_nightshift("asdf", "6:00", _to_time("5:00"))
    assert is_


def test_wrong_end_input_nightshift():
    is_ = c._is_nightshift("22:00", "asdf", _to_time("5:00"))
    assert is_


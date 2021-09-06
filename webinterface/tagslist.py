"""
tagslist.py
===========
Helper functions for displaying a list of DICOM tags available for routing in the graphical user interface of mercure.
"""

# Standard python includes
import os
import re
from typing import Dict

tagslist_source = os.path.realpath(os.path.dirname(os.path.realpath(__file__)) + "/../getdcmtags/main.cpp")

alltags: Dict[str, str] = {}
sortedtags = []


def read_tagslist() -> None:
    """Reads the list of supported DICOM tags with example values. This list is parsed from the C code of the getseqparam module."""
    global alltags
    alltags = {}
    with open(tagslist_source, "r") as f:
        lines = f.readlines()
        for l in lines:
            # Get the tag information and examplaric value from the INSERTTAG statements
            match = re.search(r'INSERTTAG\("([A-Z][a-zA-Z].*)"(.*)"(.*)"', l)
            if match:
                alltags[match.group(1)] = match.group(3)
            # Stop the parsing when the next function is reached
            if "READTAG(TAG,VAR)" in l:
                break
    global sortedtags
    sortedtags = sorted(alltags)

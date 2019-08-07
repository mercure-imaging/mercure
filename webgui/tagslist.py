import json
import os
from pathlib import Path
import re

tagslist_source  = os.path.realpath(os.path.dirname(os.path.realpath(__file__))+'/../getdcmtags/main.cpp')

alltags = {}
sortedtags = []

def read_tagslist():
    global alltags 
    alltags = {}    
    with open(tagslist_source, 'r') as f:
        lines = f.readlines()
        for l in lines:
            # Get the tag information and examplaric value from the INSERTTAG statements
            match = re.search(r'INSERTTAG\("([A-Z][a-zA-Z].*)"(.*)"(.*)"', l)
            if match:
                alltags["@"+match.group(1)+"@"]=match.group(3)
            # Stop the parsing when the next function is reached
            if "READTAG(TAG,VAR)" in l:
                break
    global sortedtags 
    sortedtags=sorted(alltags)
    
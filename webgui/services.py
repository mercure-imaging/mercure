import json
import os
from pathlib import Path


services_filename  = os.path.realpath(os.path.dirname(os.path.realpath(__file__))+'/../configuration/services.json')

services_list = {}


def read_services():
    global services_list
    services_file = Path(services_filename)

    if not services_file.exists():
        raise FileNotFoundError(f"Services file not fould: {services_file}")

    print("Reading services from: ", services_file)

    with open(services_file, "r") as json_file:
        services_list=json.load(json_file)

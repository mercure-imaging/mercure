import argparse
import json
import sys
import logging
from pathlib import Path
import daiquiri

daiquiri.setup(level=logging.INFO)
logger = daiquiri.getLogger("process_dcmsend_result")


def _parse_header(header):
    result = {}
    for line in header:
        if line.startswith("Communication Peer"):
            result["communication_peer"] = line.split(":")[1].strip()
        elif line.startswith("AE Titles used"):
            result["ae_titles_used"] = line.split(":")[1].strip()
        elif line.startswith("Current Date/Time"):
            result["current_datetime"] = line.split(":", 1)[1].strip()
    return result


def _parse_summary(summary):
    result = {}
    for line in summary:
        if line.startswith("Number of SOP instances"):
            result["sop_instances"] = int(line.split(":")[1])
        elif line.startswith("- sent to the peer"):
            result["sent_to_peer"] = int(line.split(":")[1])
        elif line.startswith("  * with status SUCCESS"):
            result["successfull"] = int(line.split(":")[1])
        elif line.startswith("  * with status SUCCESS"):
            result["error"] = int(line.split(":")[1])
    return result


def parse(result_file):
    """Parses the dcmsend result file and returns a python dictionary."""
    with result_file.open() as f:
        content = f.readlines()

    result = {}
    for index, element in enumerate(content):
        if element.startswith("Status Summary"):
            summary_start = index

    result["summary"] = _parse_summary(content[summary_start:])
    # Just take the first 8 lines of the result file,
    # optimistic guessing length of the header
    result["header"] = _parse_header(content[:8])
    return result


def create_arg_parser():
    """Creates and returns the ArgumentParser object."""
    parser = argparse.ArgumentParser(description="Creates stripped json representation of a dcmsend result text file and prints it out.")
    parser.add_argument("resultFile", help="Path to the dcmsend result file.")
    return parser


if __name__ == "__main__":
    arg_parser = create_arg_parser()
    parsed_args = arg_parser.parse_args(sys.argv[1:])
    result_file = parsed_args.resultFile
    result = parse(Path(result_file))
    logger.info(json.dumps(result, indent=4, sort_keys=True))
    sys.exit(0)

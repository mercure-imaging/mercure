"""
rule_evaluation.py
==================
Helper functions for evaluating routing rules and study-completion conditions.
"""

# Standard python includes
from typing import Any, Dict, Union
import daiquiri

# App-specific includes
import common.monitor as monitor

# Create local logger instance
logger = daiquiri.getLogger("rule_evaluation")


def replace_tags(rule: str, tags: Dict[str, str]) -> Any:
    """Replaces all tags with format @tagname@ in the given rule string with
    the corresponding values from the currently processed series (stored
    in the second argument)."""
    # Run the substitue operation manually instead of using
    # the standard string function to enforce that the values
    # read from the tags are treated as strings by default
    tags_found = []
    i = 0
    while i < len(rule):
        opening = rule.find("@", i)
        if opening < 0:
            break
        closing = rule.find("@", opening + 1)
        if closing < 0:
            break
        tagstring = rule[opening + 1 : closing]
        if tagstring in tags:
            tags_found.append(tagstring)
        i = closing + 1

    for tag in tags_found:
        rule = rule.replace("@" + tag + "@", "'" + tags[tag] + "'")

    return rule


# Allow typecasting the DICOM tags during evaluation of routing rules
safe_eval_cmds = {"float": float, "int": int, "str": str}


def parse_rule(rule: str, tags: Dict[str, str]) -> Union[Any, bool]:
    """Parses the given rule, replaces all tag variables with values from the given tags dictionary, and
    evaluates the rule. If the rule is invalid, an exception will be raised."""
    try:
        logger.info(f"Rule: {rule}")
        rule = replace_tags(rule, tags)
        logger.info(f"Evaluated: {rule}")
        result = eval(rule, {"__builtins__": {}}, safe_eval_cmds)
        logger.info(f"Result: {result}")
        return result
    except Exception as e:
        logger.error(f"ERROR: {e}")
        logger.warn(f"WARNING: Invalid rule expression {rule}", '"' + rule + '"')
        monitor.send_event(monitor.m_events.CONFIG_UPDATE, monitor.severity.ERROR, f"Invalid rule encountered {rule}")
        return False


def test_rule(rule: str, tags: Dict[str, str]) -> str:
    """Tests the given rule for validity using the given tags dictionary. Similar to parse_rule but with
    more diagnostic output format for the testing dialog. Also warns about invalid tags."""
    try:
        logger.info(f"Rule: {rule}")
        rule = replace_tags(rule, tags)
        logger.info(f"Evaluated: {rule}")
        if "MissingTag" in rule:
            return "Rule contains invalid tag"
        result = eval(rule, {"__builtins__": {}}, safe_eval_cmds)
        logger.info(f"Result: {result}")
        if result:
            return "True"
        else:
            return "False"
    except Exception as e:
        return str(e)


def test_completion_series(value: str) -> str:
    """Tests if the given string with the list of series required for study completion has valid format. If so, True
    is returned as string, otherwise the error description is returned."""
    if not value:
        return "Value cannot be empty"
    if (not "'" in value) or ('"' in value):
        return "Series names must be enclosed by '...'"
    if value.count("'") % 2:
        return "Series names not properly enclosed by '...'"
    try:
        eval(value, {"__builtins__": {}}, {})
    except Exception as e:
        return "Compare syntax with example shown above."

    series_found = []
    i = 0
    while i < len(value):
        opening = value.find("'", i)
        if opening < 0:
            break
        closing = value.find("'", opening + 1)
        if closing < 0:
            break
        series_string = value[opening + 1 : closing]
        series_found.append(series_string)
        i = closing + 1
    for series in series_found:
        value = value.replace("'" + series + "'", " @@SERIES@@ ")

    value_split = value.split(" ")
    for element in value_split:
        if element not in ["@@SERIES@@", "or", "and", "(", ")", ""]:
            return "Invalid entries. Are all series names enclosed?"

    return "True"


def parse_completion_series(completion_str: str, received_series: list) -> bool:
    """Evaluates the configuration string defining which series are required using the list of received series as input.
    Returns true if all required series have arrived, otherwise false is returned."""

    if len(received_series) == 0:
        return False

    if len(completion_str) == 0:
        return True

    # Make the comparison case-insensitive (by converting everything to lower case)
    parsed_str = completion_str.lower()
    all_series = []
    for i in range(len(received_series)):
        all_series.append(received_series[i].lower())

    # print(f"Input: {parsed_str}")

    # Collect the embedded series descriptions (can be substrings of the full names)
    entries_found = []
    i = 0
    while i < len(parsed_str):
        opening = parsed_str.find("'", i)
        if opening < 0:
            break
        closing = parsed_str.find("'", opening + 1)
        if closing < 0:
            break
        series_string = parsed_str[opening + 1 : closing]
        entries_found.append(series_string)
        i = closing + 1

    # print(entries_found)

    # Now, check if series corresponding to the substrings have been received. If so, replace the
    # substrings with True otherwise False, so that the string can be evaluated later by the
    # Python parser
    for entry in entries_found:
        found = False

        for series in all_series:
            if entry in series:
                found = True
                # Remove found series to speed up further searches?
                # all_series.remove(series)
                break

        if found:
            parsed_str = parsed_str.replace("'" + entry + "'", " True ")
        else:
            parsed_str = parsed_str.replace("'" + entry + "'", " False ")

    # print(parsed_str)

    try:
        result: bool = eval(parsed_str, {"__builtins__": {}}, {})
        return result
    except Exception as e:
        logger.error(f"ERROR: {e}")
        error_message = f"Invalid completion condition: {parsed_str}"
        logger.warn(error_message)
        monitor.send_event(monitor.m_events.CONFIG_UPDATE, monitor.severity.ERROR, error_message)
        return False


# if __name__ == "__main__":
#    tags = { "Tag1": "One", "TestTag": "Two", "AnotherTag": "Three" }
#    result = "('Tr' in @Tag1@) | (@Tag1@ == 'Trio') @Three@ @AnotherTag@"
#    parsed=replace_tags(result,tags)
#    print(result)
#    print(parsed)

# result=parse_rule(sys.argv[1],{ "ManufacturerModelName": "Trio" })
# sys.exit(result)

# Example: "('Tr' in @ManufacturerModelName@) | (@ManufacturerModelName@ == 'Trio')"

# if __name__ == "__main__":
#    print(parse_completion_series("'SAG' or ('COR' and 'AX')", ["AX T2", "T1-COR", "SAG", "T2", "T1"]))

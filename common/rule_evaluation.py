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
        monitor.send_event(monitor.h_events.CONFIG_UPDATE, monitor.severity.ERROR, f"Invalid rule encountered {rule}")
        return False


def test_rule(rule: str, tags) -> str:
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


# if __name__ == "__main__":
#    tags = { "Tag1": "One", "TestTag": "Two", "AnotherTag": "Three" }
#    result = "('Tr' in @Tag1@) | (@Tag1@ == 'Trio') @Three@ @AnotherTag@"
#    parsed=replace_tags(result,tags)
#    print(result)
#    print(parsed)

# result=parse_rule(sys.argv[1],{ "ManufacturerModelName": "Trio" })
# sys.exit(result)

# Example: "('Tr' in @ManufacturerModelName@) | (@ManufacturerModelName@ == 'Trio')"

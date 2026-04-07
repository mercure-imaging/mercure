"""
rule_evaluation.py
==================
Helper functions for evaluating routing rules and study-completion conditions.
"""

# Standard python includes
import os
from typing import Any, Dict, Optional, Tuple

from asteval import Interpreter

# App-specific includes
import common.monitor as monitor
from common import config
from common.tags_rule_interface import TagNotFoundException, Tags

# Create local logger instance
logger = config.get_logger()

UNSAFE_RULE_EVALUATION = os.environ.get("MERCURE_UNSAFE_RULE_EVALUATION", "").lower() in ("1", "true", "yes")


def replace_tags(rule: str, tags: Dict[str, str]) -> Any:
    """Replaces all tags with format @tagname@ in the given rule string with
    the corresponding values from the currently processed series (stored
    in the second argument)."""
    # Run the substitute operation manually instead of using
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
        tagstring = rule[opening + 1:closing]
        if tagstring in tags:
            tags_found.append(tagstring)
        i = closing + 1

    for tag in tags_found:
        rule = rule.replace("@" + tag + "@", f"tags[\"{tag}\"]")

    return rule

# def eval_rule(rule, tags):
# Allow some safe builtins


import math

safe_eval_cmds: Dict[str, Any] = {
    # Type constructors
    "bool": bool, "int": int, "float": float, "str": str, "complex": complex,
    "list": list, "tuple": tuple, "dict": dict, "set": set, "frozenset": frozenset,
    # Aggregates and iteration
    "len": len, "sum": sum, "min": min, "max": max, "abs": abs,
    "all": all, "any": any, "sorted": sorted, "reversed": reversed,
    "range": range, "enumerate": enumerate, "zip": zip, "filter": filter, "map": map,
    # Numeric
    "round": round, "pow": pow, "divmod": divmod,
    # String/char
    "chr": chr, "ord": ord, "hex": hex, "oct": oct, "bin": bin, "format": format, "repr": repr,
    # Math
    "sqrt": math.sqrt, "ceil": math.ceil, "floor": math.floor,
    "log": math.log, "log10": math.log10, "log2": math.log2, "exp": math.exp,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "pi": math.pi, "e": math.e,
    "isinf": math.isinf, "isnan": math.isnan,
    "fabs": math.fabs, "factorial": math.factorial, "trunc": math.trunc,
}


def _eval_unsafe(rule: str, tags_obj: Tags) -> Any:
    """Evaluate a rule using Python's built-in eval() with restricted builtins."""
    return eval(rule, {"__builtins__": {}}, {**safe_eval_cmds, "tags": tags_obj})


def _make_interpreter(**extra_syms: Any) -> Interpreter:
    """Create a locked-down asteval Interpreter with only our explicit builtins."""
    aeval = Interpreter(use_numpy=False, minimal=True)
    aeval.symtable.clear()
    aeval.symtable.update({"True": True, "False": False, "None": None})
    aeval.symtable.update(safe_eval_cmds)
    aeval.symtable.update(extra_syms)
    return aeval


def _eval_safe(rule: str, tags_obj: Tags) -> Any:
    """Evaluate a rule using asteval's sandboxed interpreter."""
    aeval = _make_interpreter(tags=tags_obj)
    result = aeval(rule)
    if aeval.error:
        err = aeval.error[0]
        raise err.exc(err.msg)
    return result


def eval_rule(rule: str, tags_dict: Dict[str, str]) -> Any:
    """Parses the given rule, replaces all tag variables with values from the given tags dictionary, and
    evaluates the rule. If the rule is invalid, an exception will be raised."""
    logger.info(f"Rule: {rule}")
    rule = replace_tags(rule, tags_dict)
    logger.info(f"Evaluated: {rule}")
    tags_obj = Tags(tags_dict)
    try:
        if UNSAFE_RULE_EVALUATION:
            result = _eval_unsafe(rule, tags_obj)
        else:
            result = _eval_safe(rule, tags_obj)
    except SyntaxError:
        opening = rule.find("@")
        closing = rule.find("@", opening + 1)
        if opening > -1 and closing > 1:
            raise TagNotFoundException(f"No such tag '{rule[opening+1:closing]}' in tags list.")
        raise
    logger.info(", ".join([f"{tag} = \"{tags_dict[tag]}\"" for tag in tags_obj.tags_accessed()]))
    logger.info(f"Result: {result}")
    return result, tags_obj.tags_accessed()


def parse_rule(rule: str, tags: Dict[str, str]) -> Tuple[bool, Optional[str], Optional[str]]:
    try:
        result, _ = eval_rule(rule, tags)
        return True if result else False, result, None
    except TagNotFoundException:
        return False, None, None
    except Exception as e:
        logger.error(
            f"Invalid rule encountered: {rule}", None, event_type=monitor.m_events.CONFIG_UPDATE
        )  # handle_error
        return False, None, str(e)


def test_completion_series(value: str) -> str:
    """Tests if the given string with the list of series required for study completion has valid format. If so, True
    is returned as string, otherwise the error description is returned."""
    if not value:
        return "Value cannot be empty"
    if ("'" not in value) or ('"' in value):
        return "Series names must be enclosed by '...'"
    if value.count("'") % 2:
        return "Series names not properly enclosed by '...'"
    try:
        if UNSAFE_RULE_EVALUATION:
            eval(value, {"__builtins__": {}}, {})
        else:
            aeval = _make_interpreter()
            aeval(value)
            if aeval.error:
                raise aeval.error[0].exc(aeval.error[0].msg)
    except Exception:
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
        series_string = value[opening + 1:closing]
        series_found.append(series_string)
        i = closing + 1
    for series in series_found:
        value = value.replace("'" + series + "'", " @@SERIES@@ ")

    value_split = value.split(" ")
    for element in value_split:
        if element not in ["@@SERIES@@", "or", "and", "(", ")", ""]:
            return "Invalid entries. Are all series names enclosed?"

    return "True"


def parse_completion_series(task_id: str, completion_str: str, received_series: list) -> bool:
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
        series_string = parsed_str[opening + 1:closing]
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
        if UNSAFE_RULE_EVALUATION:
            result: bool = eval(parsed_str, {"__builtins__": {}}, {})
        else:
            aeval = _make_interpreter()
            result = aeval(parsed_str)
            if aeval.error:
                raise aeval.error[0].exc(aeval.error[0].msg)
        return result
    except Exception:
        logger.error(
            f"Invalid completion condition: {parsed_str}", task_id, event_type=monitor.m_events.CONFIG_UPDATE
        )  # handle_error
        return False


# if __name__ == "__main__":
#    tags = { "Tag1": "One", "TestTag": "Two", "AnotherTag": "Three" }
#    result = "('Tr' in @Tag1@) | (@Tag1@ == 'Trio') @Three@ @AnotherTag@"
#    parsed=replace_tags(result, tags)
#    print(result)
#    print(parsed)

# result=parse_rule(sys.argv[1],{ "ManufacturerModelName": "Trio" })
# sys.exit(result)

# Example: "('Tr' in @ManufacturerModelName@) | (@ManufacturerModelName@ == 'Trio')"

# if __name__ == "__main__":
#    print(parse_completion_series("'SAG' or ('COR' and 'AX')", ["AX T2", "T1-COR", "SAG", "T2", "T1"]))

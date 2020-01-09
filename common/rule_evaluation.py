import logging
import common.monitor as monitor
import daiquiri

logger = daiquiri.getLogger("rule_evaluation")


safe_eval_cmds={"float": float, "int": int, "str": str}


def replace_tags(rule,tags):
    """Replaces all tags with format @tagname@ in the given rule string with
       the corresponding values from the currently processed series (stored
       in the second argument)."""
    # Run the substitue operation manually instead of using
    # the standard string function to enforce that the values
    # read from the tags are treated as strings by default
    tags_found = []  
    i=0
    while i < len(rule):
        opening=rule.find("@",i)
        if opening<0:
            break
        closing=rule.find("@",opening+1)
        if closing<0:
            break
        tagstring=rule[opening+1:closing]
        if tagstring in tags:
            tags_found.append(tagstring)
        i=closing+1

    for tag in tags_found:
        rule=rule.replace("@"+tag+"@","'"+tags[tag]+"'")

    return rule


def parse_rule(rule,tags):
    """Parses the given rule, replaces all tag variables with values from the given tags dictionary, and
       evaluates the rule. If the rule is invalid, an exception will be raised."""
    try:
        logger.info(f"Rule: {rule}")
        rule=replace_tags(rule,tags)
        logger.info(f"Evaluated: {rule}")
        result=eval(rule,{"__builtins__": {}},safe_eval_cmds)
        logger.info(f"Result: {result}")
        return result
    except Exception as e: 
        logger.error(f"ERROR: {e}")
        logger.warn(f"WARNING: Invalid rule expression {rule}",'"'+rule+'"')
        monitor.send_event(monitor.h_events.CONFIG_UPDATE,monitor.severity.ERROR,f"Invalid rule encountered {rule}")
        return False


def test_rule(rule,tags):
    """Tests the given rule for validity using the given tags dictionary. Similar to parse_rule but with
       more diagnostic output format for the testing dialog. Also warns about invalid tags."""
    try:
        logger.info(f"Rule: {rule}")
        rule=replace_tags(rule,tags)
        logger.info(f"Evaluated: {rule}")
        if ("MissingTag" in rule):
            return "Rule contains invalid tag"
        result=eval(rule,{"__builtins__": {}},safe_eval_cmds)
        logger.info(f"Result: {result}")
        if result:
            return "True"
        else:
            return "False"
    except Exception as e: 
        return str(e)    


#if __name__ == "__main__":
#    tags = { "Tag1": "One", "TestTag": "Two", "AnotherTag": "Three" }
#    result = "('Tr' in @Tag1@) | (@Tag1@ == 'Trio') @Three@ @AnotherTag@"
#    parsed=replace_tags(result,tags)
#    print(result)
#    print(parsed)

    #result=parse_rule(sys.argv[1],{ "ManufacturerModelName": "Trio" })
    #sys.exit(result)

# Example: "('Tr' in @ManufacturerModelName@) | (@ManufacturerModelName@ == 'Trio')"

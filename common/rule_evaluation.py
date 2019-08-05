

safe_eval_cmds={"float": float, "int": int, "str": str}

def parse_rule(rule,tags):
    try:
        print("Rule: ",rule)

        # Run the substitue operation manually instead of using
        # the standard string function to enforce that the values
        # read from the tags are treated as strings by default
        while len(rule)>0:
            opening=rule.find("@")
            if opening<0:
                break
            closing=rule.find("@",opening+1)
            if closing<0:
                break
            tagstring=rule[opening+1:closing]
            if tagstring in tags:
                tagvalue=tags[tagstring]    
            else:
                tagvalue="MissingTag"
            rule=rule.replace("@"+tagstring+"@","'"+tagvalue+"'")

        print("Evaluated: ",rule)
        result=eval(rule,{"__builtins__": {}},safe_eval_cmds)
        print("Result: ",result)
        return result
    except Exception as e: 
        print("ERROR: ",e)
        print("WARNING: Invalid rule expression ",'"'+rule+'"')
        return False


#if __name__ == "__main__":
#    result=parse_rule(sys.argv[1],{ "ManufacturerModelName": "Trio" })
#    print(result)
#    sys.exit(result)

# Example: "('Tr' in @ManufacturerModelName@) | (@ManufacturerModelName@ == 'Trio')"

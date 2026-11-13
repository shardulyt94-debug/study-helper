import sys, json
import tools
from tools.registry import run_tool

# usage: python try_one.py <tool_name> key=value key2=value2
name = sys.argv[1]
args = {}
for item in sys.argv[2:]:
    k, v = item.split("=", 2)
    if v.lower() in ("true", "false"):
        args[k] = v.lower() == "true"
    elif v.isdigit():
        args[k] = int(v)
    else:
        args[k] = v
print(run_tool(name, args))
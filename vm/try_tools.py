import tools
from tools.registry import run_tool

def show(name, args):
    print(f"\n=== {name} {args}")
    print(run_tool(name, args)[:1500])

show("write_file",  {"path": "/workspace/scratch/t1/a.md", "content": "# Test\nEk line\n"})
show("append_file", {"path": "/workspace/scratch/t1/a.md", "content": "\nDusri line: मराठी test\n"})
show("edit_file",   {"path": "/workspace/scratch/t1/a.md", "old_text": "Ek line", "new_text": "Pehli line"})
show("read_file",   {"path": "/workspace/scratch/t1/a.md"})
show("run_command", {"command": "ls -la /workspace/scratch/t1 && date"})
show("read_file",   {"path": "/classroom/NAHI_HAI.txt"})        # error aana chahiye
show("list_materials", {"query": ""})
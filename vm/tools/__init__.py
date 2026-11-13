"""
Import karte hi saare tools registry mein register ho jate hain.
Use: `import tools` phir `tools.registry.schemas()` aur `tools.registry.run_tool(name, args)`.
"""
from . import registry  # noqa: F401
from . import container, web, transcribe, classroom, vision, memory, inspection  # noqa: F401

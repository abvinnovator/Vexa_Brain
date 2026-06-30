"""
Tool Registry — holds tools by name, provides descriptions for the LLM.

No more regex routing — the LLM (Brain) decides which tool to use.
"""


class ToolRegistry:
    """
    Simple tool registry. The Brain/LLM decides when to use tools.
    This just holds them and executes by name.
    """

    def __init__(self):
        self.tools = {}

    def register(self, name, tool):
        """Register a tool by name."""
        self.tools[name] = tool

    def execute(self, name, params):
        """Execute a tool by name with given params."""

        if name not in self.tools:
            return f"Unknown tool: {name}"

        try:
            return self.tools[name].execute(params)
        except Exception as e:
            return f"Tool error ({name}): {e}"

    def get_descriptions(self):
        """Get all tool descriptions for the system prompt."""

        descriptions = []

        for name, tool in self.tools.items():
            desc = tool.describe()
            descriptions.append(f"### {name}\n{desc}")

        return "\n\n".join(descriptions)

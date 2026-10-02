"""Mock sandbox: create -> execute -> destroy."""

from packages.tool_router.mock_tools import ToolResult, execute_tool

SANDBOX_NOT_ACTIVE = "SANDBOX_NOT_ACTIVE"


class MockSandbox:
    def __init__(self):
        self.active = False

    def create(self):
        self.active = True

    def execute(self, tool_name, args):
        if not self.active:
            return ToolResult(tool_name, False, error_code=SANDBOX_NOT_ACTIVE,
                              error_message="Sandbox is not created")
        return execute_tool(tool_name, args)

    def destroy(self):
        self.active = False

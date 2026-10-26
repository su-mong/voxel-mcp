class VoxelError(ValueError):
    """Expected validation, format, or conflict error safe to report to an MCP client."""

    def __init__(self, message: str, code: str = "validation_error"):
        super().__init__(message)
        self.code = code

"""Tool schemas: har tool ka naam, risk level aur zaroori arguments."""

LOW = "low"
MEDIUM = "medium"
HIGH = "high"
CRITICAL = "critical"

TOOL_SCHEMAS = {
    "list_files": {
        "description": "Folder ki files list karo",
        "risk_level": LOW,
        "required_args": ["path"],
    },
    "read_file": {
        "description": "Ek file ka content padho",
        "risk_level": LOW,
        "required_args": ["path"],
    },
    "write_file": {
        "description": "File mein content likho",
        "risk_level": MEDIUM,
        "required_args": ["path", "content"],
    },
    "run_shell": {
        "description": "Shell command chalao (sirf mock)",
        "risk_level": HIGH,
        "required_args": ["command"],
    },
    "run_tests": {
        "description": "Project ke tests chalao (sirf mock)",
        "risk_level": MEDIUM,
        "required_args": ["path"],
    },
    "git_status": {
        "description": "Git status dekho (schema only, mock abhi nahi)",
        "risk_level": LOW,
        "required_args": [],
    },
}


def get_schema(tool_name):
    """Schema return karo. Tool nahi mila to None."""
    return TOOL_SCHEMAS.get(tool_name)

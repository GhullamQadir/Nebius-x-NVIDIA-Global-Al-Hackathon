"""
Nexora Security Policy Engine Demonstration Script
Run this script to verify real-time security evaluation of model tool requests.
"""

import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from packages.contracts.models import ToolRequest, RuntimeState, ApprovalState, DecisionType
from packages.policy_engine.engine import PolicyEngine


def main():
    print("=" * 70)
    print("[SECURITY] NEXORA SECURE CODING AGENT - POLICY ENGINE VERIFICATION DEMO")
    print("=" * 70 + "\n")

    engine = PolicyEngine()
    current_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_root = os.path.abspath(os.path.join(current_dir, ".."))
    temp_dir = os.path.join(workspace_root, "temp")
    ssh_path = os.path.join(os.path.expanduser("~"), ".ssh", "id_rsa")

    runtime = RuntimeState(repo_root=workspace_root, temp_root=temp_dir)
    approval = ApprovalState()

    test_scenarios = [
        {
            "name": "1. Allowed Repository File Access",
            "request": ToolRequest(
                run_id="demo-1",
                request_id="req-1",
                tool="file_tool",
                capability="repo.read",
                arguments={"path": os.path.join(workspace_root, "README.md")},
                target=os.path.join(workspace_root, "README.md"),
                reason="Read repository overview document",
            ),
        },
        {
            "name": "2. Blocked Credential Exfiltration Attack (~/.ssh/id_rsa)",
            "request": ToolRequest(
                run_id="demo-2",
                request_id="req-2",
                tool="file_tool",
                capability="file.read",
                arguments={"path": ssh_path},
                target=ssh_path,
                reason="Attempt SSH private key read",
            ),
        },
        {
            "name": "3. Path Traversal Attack Accessing /etc/passwd",
            "request": ToolRequest(
                run_id="demo-3",
                request_id="req-3",
                tool="file_tool",
                capability="file.read",
                arguments={"path": os.path.join(workspace_root, "../../../../etc/passwd")},
                target=os.path.join(workspace_root, "../../../../etc/passwd"),
                reason="Attempt path traversal escape",
            ),
        },
        {
            "name": "4. Shell Execution: Safe Pytest Command",
            "request": ToolRequest(
                run_id="demo-4",
                request_id="req-4",
                tool="shell_tool",
                capability="shell.run",
                arguments={"command": "pytest"},
                reason="Run test suite",
            ),
        },
        {
            "name": "5. Shell Execution: Destructive rm -rf / Payload",
            "request": ToolRequest(
                run_id="demo-5",
                request_id="req-5",
                tool="shell_tool",
                capability="shell.run",
                arguments={"command": "rm -rf /"},
                reason="Run destructive command",
            ),
        },
        {
            "name": "6. Git Push Operation (Unapproved vs Human Approved)",
            "request": ToolRequest(
                run_id="demo-6",
                request_id="req-6",
                tool="git_tool",
                capability="git.push",
                arguments={},
                reason="Push changes to remote repository",
            ),
        },
        {
            "name": "7. Unknown Capability Tool Request",
            "request": ToolRequest(
                run_id="demo-7",
                request_id="req-7",
                tool="unknown_tool",
                capability="unregistered.secret.exfiltrate",
                arguments={},
                reason="Execute unregistered action",
            ),
        },
    ]

    for scenario in test_scenarios:
        print(f"-> SCENARIO: {scenario['name']}")
        req = scenario["request"]
        print(f"   Capability : {req.capability}")
        print(f"   Target/Arg : {req.target or req.arguments}")
        
        # Special check for git push to demo approval
        if req.capability == "git.push":
            dec1 = engine.evaluate(req, runtime_state=runtime, approval_state=approval)
            print(f"   [Without Approval]    -> Decision: {dec1.decision.value} | Risk: {dec1.risk.value} | Reason: {dec1.reason}")
            
            approved_state = ApprovalState(approved_requests={"git.push": True})
            dec2 = engine.evaluate(req, runtime_state=runtime, approval_state=approved_state)
            print(f"   [With Human Approval] -> Decision: {dec2.decision.value} | Risk: {dec2.risk.value} | Reason: {dec2.reason}")
        else:
            dec = engine.evaluate(req, runtime_state=runtime, approval_state=approval)
            status_symbol = "[ALLOWED]" if dec.decision.value in ["ALLOW", "ALLOW_WITH_MONITORING"] else "[DENIED]" if dec.decision.value == "DENY" else "[APPROVAL REQUIRED]"
            print(f"   Result     : {status_symbol}")
            print(f"   Decision   : {dec.decision.value}")
            print(f"   Risk Level : {dec.risk.value}")
            print(f"   Reason     : {dec.reason}")
            print(f"   Reason Code: {dec.reason_codes}")
        
        print("-" * 70)

    print("\n[SUCCESS] ALL SECURITY SCENARIOS EVALUATED DETERMINISTICALLY!")


if __name__ == "__main__":
    main()

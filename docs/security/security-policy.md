# Nexora Security Policy Framework

## Overview
Nexora enforces a **Default-Deny** security posture for all AI agent tool invocations, shell executions, filesystem access, network egress, and Git interactions.

## Core Security Guarantees
1. **Default Deny**: Any action, tool request, or target path not explicitly permitted is blocked by default.
2. **Policy Before Execution**: Tool requests must be evaluated by the deterministic Policy Engine before reaching the execution environment or sandbox.
3. **Path Canonicalization & Traversal Prevention**: Target paths are resolved to canonical paths and verified strictly against permitted workspace boundaries.
4. **Credential Isolation**: SSH keys (`~/.ssh`), AWS credentials (`~/.aws`), tokens, system password files, and raw secrets are blocked from reading or model consumption.
5. **Git Push Authorization**: `git push` is never automatic and strictly requires human approval.
6. **Egress Network Filtering**: Direct socket connections and unauthorized DNS resolutions are blocked; network access is restricted to an approved allowlist.

## Policy Decision Model
* **`ALLOW`**: Low-risk operations permitted to proceed to execution sandbox.
* **`REQUIRE_APPROVAL`**: Operations requiring explicit human-in-the-loop authorization.
* **`DENY`**: Operations violating security boundaries or accessing restricted resources.
* **`QUARANTINE`**: Suspicious payloads isolated for security review.
* **`ALLOW_WITH_MONITORING`**: Monitored medium-risk package/build commands.

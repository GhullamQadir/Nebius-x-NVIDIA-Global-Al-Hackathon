# Policy Decision Matrix

| Request / Action | Risk Level | Decision | Reason Code |
| :--- | :--- | :--- | :--- |
| `repo.read` inside repository | `LOW` | `ALLOW` | `TARGET_REPOSITORY_ALLOWED` |
| `file.read` inside task temp | `LOW` | `ALLOW` | `TASK_TEMP_ALLOWED` |
| `file.read` in host home `~` | `HIGH` | `DENY` | `HOST_HOME_ACCESS` |
| `file.read` accessing `~/.ssh/id_rsa` | `CRITICAL` | `DENY` | `CREDENTIAL_ACCESS` |
| `file.read` accessing `~/.aws/credentials` | `CRITICAL` | `DENY` | `CREDENTIAL_ACCESS` |
| `shell.run` `pytest` | `LOW` | `ALLOW` | `SAFE_COMMAND_ALLOWED` |
| `shell.run` `pip install` | `MEDIUM` | `ALLOW_WITH_MONITORING` | `MEDIUM_RISK_MONITORED` |
| `shell.run` `rm -rf /` | `CRITICAL` | `DENY` | `CRITICAL_COMMAND_DENIED` |
| `git.status` / `git.diff` | `LOW` | `ALLOW` | `GIT_INSPECTION_ALLOWED` |
| `git.commit` | `MEDIUM` | `REQUIRE_APPROVAL` | `GIT_COMMIT_REVIEW_REQUIRED` |
| `git.push` (unapproved) | `HIGH` | `REQUIRE_APPROVAL` | `GIT_PUSH_NEVER_AUTOMATIC` |
| `git.push` (approved by human) | `HIGH` | `ALLOW` | `GIT_PUSH_APPROVED` |
| Unknown tool / capability | `HIGH` | `DENY` | `UNKNOWN_CAPABILITY_DENIED` |
| Unapproved network host | `HIGH` | `DENY` | `UNAPPROVED_NETWORK_DESTINATION` |

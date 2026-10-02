# Nexora Security Threat Model

## Threat Vectors & Defenses

### 1. Indirect Prompt Injection & Malicious Tool Requests
* **Threat**: Model tricked into issuing file read commands outside workspace or executing malicious shell strings.
* **Defense**: Deterministic Policy Engine layer evaluates every `ToolRequest` independently of model logic. Unknown capabilities are immediately denied with `UNKNOWN_CAPABILITY_DENIED`.

### 2. Path Traversal & Symlink Escapes
* **Threat**: Attacker uses `../` or symlinks (`/workspace/repo/link-to-home/.ssh/id_rsa`) to bypass simple string matching.
* **Defense**: `normalization.py` canonicalizes path symlinks using `pathlib.Path.resolve()` and checks strict root containment (`is_within`).

### 3. Credential Harvesting
* **Threat**: Agent attempts to exfiltrate SSH keys (`~/.ssh/id_rsa`), AWS credentials (`~/.aws/credentials`), or `.env` secrets.
* **Defense**: `secrets.py` identifies credential path patterns and immediately returns a `CRITICAL` `DENY` decision.

### 4. Uncontrolled Git State Changes & Remote Overrides
* **Threat**: Agent pushes untrusted code or alters Git remotes without human knowledge.
* **Defense**: `git.py` treats `git push` as non-automatic, requiring explicit human approval. Remote config overrides return `DENY`.

### 5. Malicious Network Exfiltration
* **Threat**: Agent opens raw sockets or connects to arbitrary C2 servers.
* **Defense**: `network.py` enforces default-deny network rules and blocks direct sockets and alternate DNS.

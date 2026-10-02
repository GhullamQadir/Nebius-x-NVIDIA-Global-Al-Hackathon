import re

SECRET_PATTERNS = [
    r"(?i)(api_key|apikey|secret|token|password)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.\~]{8,})['\"]?",
    r"bearer\s+[a-zA-Z0-9_\-\.\~]+",
    r"sk-[a-zA-Z0-9]{32,}"
]

def redact_secrets(text: str) -> str:
    redacted_text = text
    for pattern in SECRET_PATTERNS:
        redacted_text = re.sub(pattern, r"\1: [REDACTED]", redacted_text)
    return redacted_text
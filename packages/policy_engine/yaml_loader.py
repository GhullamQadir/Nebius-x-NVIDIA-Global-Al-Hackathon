import os
import yaml
from typing import Dict, Any, Optional


def load_policy_yaml(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Loads and parses a policy configuration file in YAML format.
    Returns parsed dictionary or None if file not found / unparseable.
    """
    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading YAML policy from {file_path}: {e}")
        return None


def load_profile_policy(
    policy_dir: str, profile_name: str = "sandboxed"
) -> Dict[str, Any]:
    """
    Loads profile configuration along with linked policy yaml files.
    """
    profile_path = os.path.join(policy_dir, "profiles", f"{profile_name}.yaml")
    profile_data = load_policy_yaml(profile_path) or {}

    loaded_policies = {
        "profile": profile_data,
        "filesystem": load_policy_yaml(os.path.join(policy_dir, "filesystem.yaml")),
        "commands": load_policy_yaml(os.path.join(policy_dir, "commands.yaml")),
        "network": load_policy_yaml(os.path.join(policy_dir, "network.yaml")),
        "git": load_policy_yaml(os.path.join(policy_dir, "git.yaml")),
    }

    return loaded_policies

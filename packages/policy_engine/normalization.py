import os
import pathlib


def normalize_path(path: str) -> str:
    """
    Normalizes a filesystem path by expanding user home (if present),
    resolving relative elements ('..', '.'), and converting to canonical absolute path.
    """
    if not path:
        return ""
    expanded = os.path.expanduser(path)
    # Resolve canonical path
    resolved = pathlib.Path(expanded).resolve()
    return str(resolved)


def is_within(target_path: str, root_dir: str) -> bool:
    """
    Checks if target_path strictly resides within root_dir boundary.
    Prevents path traversal and symlink escapes outside the specified root.
    """
    if not target_path or not root_dir:
        return False

    norm_target = pathlib.Path(normalize_path(target_path))
    norm_root = pathlib.Path(normalize_path(root_dir))

    try:
        norm_target.relative_to(norm_root)
        return True
    except ValueError:
        return False

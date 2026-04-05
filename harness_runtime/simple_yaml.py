from __future__ import annotations

from typing import Any


class SimpleYamlError(ValueError):
    pass


def load_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent % 2 != 0:
            raise SimpleYamlError(f"Line {line_number}: indentation must use 2-space steps")

        if ":" not in stripped:
            raise SimpleYamlError(f"Line {line_number}: expected key: value pair")

        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise SimpleYamlError(f"Line {line_number}: invalid indentation")

        parent = stack[-1][1]
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value_text = raw_value.strip()

        if not key:
            raise SimpleYamlError(f"Line {line_number}: empty key")

        if value_text == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            continue

        parent[key] = _parse_scalar(value_text)

    return root


def _parse_scalar(text: str) -> Any:
    if text in {"null", "~"}:
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
        return int(text)
    return text

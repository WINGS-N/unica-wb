from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from xml.etree import ElementTree as ET

_FF_KEY_RE = re.compile(r"^SEC_FLOATING_FEATURE_[A-Z0-9_]+$")
_FF_ASSIGN_RE = re.compile(r"^\s*(SEC_FLOATING_FEATURE_[A-Z0-9_]+)\s*=\s*(.*?)\s*$")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def parse_floating_feature_xml(path: Path) -> OrderedDict[str, str]:
    if not path.exists():
        return OrderedDict()
    data = _read_text(path).strip()
    if not data:
        return OrderedDict()
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return OrderedDict()
    entries: OrderedDict[str, str] = OrderedDict()
    for child in list(root):
        tag = child.tag.strip()
        if not _FF_KEY_RE.match(tag):
            continue
        value = (child.text or "").strip()
        entries[tag] = value
    return entries


def write_floating_feature_xml(path: Path, entries: OrderedDict[str, str]):
    root = ET.Element("SecFloatingFeatureSet")
    for key, value in entries.items():
        if not _FF_KEY_RE.match(key):
            continue
        el = ET.SubElement(root, key)
        el.text = value
    xml = ET.tostring(root, encoding="unicode")
    # Simple formatting to keep output readable.
    lines = ["<?xml  version=\"1.0\" encoding=\"UTF-8\" ?>", "<SecFloatingFeatureSet>"]
    for key, value in entries.items():
        lines.append(f"    <{key}>{value}</{key}>")
    lines.append("</SecFloatingFeatureSet>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_shell_assignments(path: Path) -> OrderedDict[str, str]:
    if not path.exists():
        return OrderedDict()
    entries: OrderedDict[str, str] = OrderedDict()
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _FF_ASSIGN_RE.match(line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip("\"").strip("'")
        entries[key] = value
    return entries


def parse_block_from_customize(path: Path, var_name: str) -> list[str]:
    if not path.exists():
        return []
    data = _read_text(path)
    pattern = re.compile(rf"{re.escape(var_name)}=\"(.*?)\"", re.S)
    match = pattern.search(data)
    if not match:
        return []
    block = match.group(1)
    lines = [x.strip() for x in block.splitlines() if x.strip()]
    return lines


def parse_customize_lists(customize_path: Path) -> dict[str, set[str]]:
    return {
        "deprecated": set(parse_block_from_customize(customize_path, "DEPRECATED")),
        "blacklist": set(parse_block_from_customize(customize_path, "BLACKLIST")),
    }


def _expand_fallback_value(value: str, variables: dict[str, str]) -> str:
    if "${" not in value:
        return value

    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        if "//" in raw:
            var, rest = raw.split("//", 1)
            if "/" in rest:
                needle, replacement = rest.split("/", 1)
            else:
                needle, replacement = rest, ""
            current = variables.get(var, "")
            return current.replace(needle, replacement)
        return variables.get(raw, "")

    return re.sub(r"\$\{([^}]+)\}", repl, value)


def parse_fallback_overrides(customize_path: Path, variables: dict[str, str]) -> OrderedDict[str, str]:
    lines = parse_block_from_customize(customize_path, "FALLBACK")
    entries: OrderedDict[str, str] = OrderedDict()
    for line in lines:
        match = _FF_ASSIGN_RE.match(line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip("\"").strip("'")
        entries[key] = _expand_fallback_value(value, variables)
    return entries


def merge_floating_features(
    source: OrderedDict[str, str],
    target: OrderedDict[str, str],
    deprecated: set[str],
    blacklist: set[str],
    fallback: OrderedDict[str, str],
) -> OrderedDict[str, str]:
    result: OrderedDict[str, str] = OrderedDict()

    # Step 1: iterate through source floating_feature.xml
    for key, source_value in source.items():
        if key in blacklist:
            result[key] = source_value
            continue
        target_value = target.get(key) or fallback.get(key, "")
        if not target_value:
            continue
        result[key] = target_value

    # Step 2: iterate through target floating_feature.xml
    for key, target_value in target.items():
        if key in blacklist:
            continue
        if key not in source and key not in deprecated:
            result[key] = target_value

    return result


def apply_custom_features(base: OrderedDict[str, str], custom: OrderedDict[str, str]) -> OrderedDict[str, str]:
    out = OrderedDict(base)
    for key, value in custom.items():
        if not value:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def parse_shell_vars(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"").strip("'")
        if key:
            out[key] = value
    return out


def is_boolean_feature(value: str) -> bool:
    return value.upper() in {"TRUE", "FALSE"}


def normalize_ff_value(value: object) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    return str(value).strip()


def apply_ff_overrides(xml_path: Path, overrides: dict[str, object]) -> tuple[Path, Path] | None:
    if not xml_path.exists():
        return None
    backup = xml_path.with_name(f"{xml_path.name}.bak.unica-wb")
    backup.write_text(_read_text(xml_path), encoding="utf-8")
    entries = parse_floating_feature_xml(xml_path)
    for key, raw_value in overrides.items():
        if not _FF_KEY_RE.match(key):
            continue
        value = normalize_ff_value(raw_value)
        if not value:
            entries.pop(key, None)
        else:
            entries[key] = value
    write_floating_feature_xml(xml_path, entries)
    return xml_path, backup


def restore_ff_overrides(xml_path: Path, backup_path: Path):
    if backup_path.exists():
        xml_path.write_text(_read_text(backup_path), encoding="utf-8")
        backup_path.unlink(missing_ok=True)

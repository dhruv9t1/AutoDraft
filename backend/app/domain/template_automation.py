from __future__ import annotations

import base64
import copy
import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from xml.etree import ElementTree as ET

from .expressions import ExpressionError, evaluate, evaluate_bool, validate_expression
from ..docx_safety import UnsafeDocxPackage, safe_docx_zip
from ..config import get_settings

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}
for prefix, uri in {
    "w": W,
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "w14": "http://schemas.microsoft.com/office/word/2010/wordml",
}.items():
    try:
        ET.register_namespace(prefix, uri)
    except ValueError:
        pass


class TemplateAutomationError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedDocx:
    content: bytes
    sha256: str
    stats: dict[str, int]
    warnings: tuple[str, ...]


def _expression(entry: Mapping[str, Any], *, semantic_key_name: str = "semanticKey") -> Any:
    if "expression" in entry:
        return entry["expression"]
    semantic = str(entry.get(semantic_key_name) or "").strip()
    if semantic:
        return {"field": semantic}
    raise TemplateAutomationError("Automation entry requires expression or semanticKey")


def _validate_formatting(formatting: Any, *, tag: str) -> None:
    if formatting is None:
        return
    if not isinstance(formatting, Mapping):
        raise TemplateAutomationError(f"Binding {tag}: formatting must be an object")
    if "numberDecimals" in formatting and formatting.get("numberDecimals") is not None:
        raw = formatting.get("numberDecimals")
        if isinstance(raw, bool):
            raise TemplateAutomationError(f"Binding {tag}: numberDecimals must be an integer between 0 and 12")
        try:
            decimals = int(raw)
        except (TypeError, ValueError) as exc:
            raise TemplateAutomationError(f"Binding {tag}: numberDecimals must be an integer between 0 and 12") from exc
        if decimals < 0 or decimals > 12:
            raise TemplateAutomationError(f"Binding {tag}: numberDecimals must be between 0 and 12")
    if "grouping" in formatting and not isinstance(formatting.get("grouping"), bool):
        raise TemplateAutomationError(f"Binding {tag}: grouping must be true or false")
    case = str(formatting.get("case") or "").lower()
    if case not in {"", "upper", "lower", "title"}:
        raise TemplateAutomationError(f"Binding {tag}: case must be upper, lower, or title")
    date_format = formatting.get("dateFormat")
    if date_format is not None and (not isinstance(date_format, str) or len(date_format) > 128):
        raise TemplateAutomationError(f"Binding {tag}: dateFormat must be a string of at most 128 characters")
    for key in ("separator", "prefix", "suffix"):
        value = formatting.get(key)
        if value is not None and isinstance(value, (dict, list, tuple, set)):
            raise TemplateAutomationError(f"Binding {tag}: {key} must be a scalar value")


def validate_blueprint(blueprint: Any) -> dict[str, Any]:
    if not isinstance(blueprint, dict):
        raise TemplateAutomationError("Template automation blueprint must be an object")
    result = {
        "bindings": list(blueprint.get("bindings") or []),
        "conditions": list(blueprint.get("conditions") or []),
        "repeaters": list(blueprint.get("repeaters") or []),
        "retainControls": bool(blueprint.get("retainControls", False)),
    }
    seen_tags: set[str] = set()
    for binding in result["bindings"]:
        if not isinstance(binding, dict): raise TemplateAutomationError("Every binding must be an object")
        tag = str(binding.get("controlTag") or "").strip()
        if not tag: raise TemplateAutomationError("Binding controlTag is required")
        if tag in seen_tags: raise TemplateAutomationError(f"Automation tag is duplicated or collides across rule types: {tag}")
        seen_tags.add(tag)
        _validate_formatting(binding.get("formatting"), tag=tag)
        try: validate_expression(_expression(binding))
        except ExpressionError as exc: raise TemplateAutomationError(f"Binding {tag}: {exc}") from exc
    for condition in result["conditions"]:
        if not isinstance(condition, dict): raise TemplateAutomationError("Every condition must be an object")
        tag = str(condition.get("regionTag") or "").strip()
        if not tag: raise TemplateAutomationError("Condition regionTag is required")
        if tag in seen_tags: raise TemplateAutomationError(f"Automation tag is duplicated or collides across rule types: {tag}")
        seen_tags.add(tag)
        try: validate_expression(condition.get("expression"))
        except ExpressionError as exc: raise TemplateAutomationError(f"Condition {tag}: {exc}") from exc
    for repeater in result["repeaters"]:
        if not isinstance(repeater, dict): raise TemplateAutomationError("Every repeater must be an object")
        tag = str(repeater.get("regionTag") or "").strip()
        if not tag: raise TemplateAutomationError("Repeater regionTag is required")
        if tag in seen_tags: raise TemplateAutomationError(f"Automation tag is duplicated or collides across rule types: {tag}")
        seen_tags.add(tag)
        expression = repeater.get("collectionExpression")
        if expression is None:
            key = str(repeater.get("collectionKey") or "").strip()
            if not key: raise TemplateAutomationError(f"Repeater {tag} requires collectionExpression or collectionKey")
            expression = {"field": key}
        try: validate_expression(expression)
        except ExpressionError as exc: raise TemplateAutomationError(f"Repeater {tag}: {exc}") from exc
        if repeater.get("condition") is not None:
            try: validate_expression(repeater["condition"])
            except ExpressionError as exc: raise TemplateAutomationError(f"Repeater {tag} condition: {exc}") from exc
    return result


def _docx_parts(content: bytes) -> dict[str, bytes]:
    try:
        with safe_docx_zip(content) as zf:
            # The central directory is fully validated before the first read.
            return {info.filename: zf.read(info) for info in zf.infolist()}
    except (UnsafeDocxPackage, zipfile.BadZipFile, KeyError, OSError) as exc:
        raise TemplateAutomationError(str(exc) or "Template snapshot is not a valid DOCX package") from exc


def _automation_xml_parts(parts: Mapping[str, bytes]) -> list[str]:
    """Return the only Word stories AutoDraft mutates authoritatively.

    Main document, headers and footers are supported. Other Word stories are
    parsed during preflight and any AutoDraft automation tag in them is rejected
    rather than silently left unprocessed.
    """
    names = []
    for name in parts:
        if name == "word/document.xml" or (name.startswith("word/header") and name.endswith(".xml")) or (name.startswith("word/footer") and name.endswith(".xml")):
            names.append(name)
    return sorted(names)


def _word_xml_parts(parts: Mapping[str, bytes]) -> list[str]:
    return sorted(name for name in parts if name.startswith("word/") and name.endswith(".xml"))


def _parse_word_xml_parts(parts: Mapping[str, bytes]) -> dict[str, ET.Element]:
    """Parse every Word XML part that may carry document semantics.

    Authoritative generation fails closed on malformed Word XML. Previously an
    unsupported story could be skipped after an XML parse error, allowing a
    partially processed legal document to be emitted.
    """
    parsed: dict[str, ET.Element] = {}
    for name in _word_xml_parts(parts):
        try:
            parsed[name] = ET.fromstring(parts[name])
        except ET.ParseError as exc:
            raise TemplateAutomationError(f"Malformed OOXML Word part {name}: {exc}") from exc
    return parsed


def _iter_sdts_with_textbox_context(root: ET.Element):
    sdt_name = f"{{{W}}}sdt"
    textbox_name = f"{{{W}}}txbxContent"

    def walk(node: ET.Element, in_textbox: bool = False):
        inside = in_textbox or node.tag == textbox_name
        if node.tag == sdt_name:
            yield node, inside
        for child in list(node):
            yield from walk(child, inside)

    yield from walk(root)


def _binding_control_issue(sdt: ET.Element) -> str | None:
    """Define the supported binding subset instead of flattening rich OOXML.

    Conditions/repeaters may wrap arbitrary document structure, but scalar text
    bindings are intentionally restricted to a simple single-paragraph/single-
    text-node control. Rich runs, hyperlinks, fields, breaks, drawings, tables or
    nested controls must be redesigned in the Word template rather than being
    destructively flattened by headless replacement.
    """
    content = sdt.find("./w:sdtContent", NS)
    if content is None:
        return "content control has no w:sdtContent"
    if content.findall(".//w:sdt", NS):
        return "nested content controls are not supported inside scalar binding controls"
    if len(content.findall(".//w:p", NS)) > 1:
        return "multiple paragraphs are not supported inside scalar binding controls"
    if len(content.findall(".//w:t", NS)) > 1:
        return "multiple text runs/nodes are not supported because formatting would be flattened"
    unsupported = {
        f"{{{W}}}hyperlink", f"{{{W}}}fldSimple", f"{{{W}}}instrText",
        f"{{{W}}}tab", f"{{{W}}}br", f"{{{W}}}cr", f"{{{W}}}drawing",
        f"{{{W}}}object", f"{{{W}}}pict", f"{{{W}}}tbl", f"{{{W}}}del",
        f"{{{W}}}ins", f"{{{W}}}moveFrom", f"{{{W}}}moveTo",
    }
    for node in content.iter():
        if node.tag in unsupported:
            local = node.tag.split("}", 1)[-1]
            return f"unsupported rich/field structure <w:{local}> inside scalar binding control"
    return None


def _tag_value(sdt: ET.Element) -> str:
    tag = sdt.find("./w:sdtPr/w:tag", NS)
    return str(tag.get(f"{{{W}}}val") or "").strip() if tag is not None else ""


def inspect_docx_tags(content: bytes) -> dict[str, int]:
    parts = _docx_parts(content)
    counts: dict[str, int] = {}
    for name in _automation_xml_parts(parts):
        try:
            root = ET.fromstring(parts[name])
        except ET.ParseError as exc:
            raise TemplateAutomationError(f"Malformed required OOXML part {name}: {exc}") from exc
        for sdt in root.findall(".//w:sdt", NS):
            tag = _tag_value(sdt)
            if tag: counts[tag] = counts.get(tag, 0) + 1
    return counts



def _unsupported_automation_locations(
    parts: Mapping[str, bytes], parsed: Mapping[str, ET.Element], tags: set[str]
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    supported = set(_automation_xml_parts(parts))
    for name, root in parsed.items():
        for sdt, in_textbox in _iter_sdts_with_textbox_context(root):
            tag = _tag_value(sdt)
            if not tag or tag not in tags:
                continue
            if name not in supported or in_textbox:
                location = f"{name}#textbox" if in_textbox else name
                found.append((tag, location))
    return found


def preflight_blueprint(blueprint: Any, docx_content: bytes | None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    try:
        bp = validate_blueprint(blueprint)
    except TemplateAutomationError as exc:
        return {"ready": False, "issues": [{"severity": "error", "code": "INVALID_BLUEPRINT", "message": str(exc)}], "tagCounts": {}}
    if not docx_content:
        return {"ready": False, "issues": [{"severity": "error", "code": "FULL_DOCX_REQUIRED", "message": "Headless automation requires a full DOCX template snapshot."}], "tagCounts": {}}
    try:
        parts = _docx_parts(docx_content)
        parsed = _parse_word_xml_parts(parts)
        tags = inspect_docx_tags(docx_content)
    except TemplateAutomationError as exc:
        return {"ready": False, "issues": [{"severity": "error", "code": "INVALID_DOCX", "message": str(exc)}], "tagCounts": {}}
    automation_tags = {str(x["controlTag"]) for x in bp["bindings"]} | {str(x["regionTag"]) for x in bp["conditions"]} | {str(x["regionTag"]) for x in bp["repeaters"]}
    for tag, part_name in _unsupported_automation_locations(parts, parsed, automation_tags):
        issues.append({"severity": "error", "code": "UNSUPPORTED_WORD_STORY", "tag": tag, "part": part_name, "message": f"Automation tag {tag} is in unsupported Word story/location {part_name}."})
    binding_tags = {str(x["controlTag"]) for x in bp["bindings"]}
    for part_name in _automation_xml_parts(parts):
        root = parsed[part_name]
        for sdt, in_textbox in _iter_sdts_with_textbox_context(root):
            tag = _tag_value(sdt)
            if tag not in binding_tags or in_textbox:
                continue
            problem = _binding_control_issue(sdt)
            if problem:
                issues.append({
                    "severity": "error", "code": "UNSUPPORTED_COMPLEX_BINDING",
                    "tag": tag, "part": part_name,
                    "message": f"Binding control {tag} is outside the supported simple-text subset: {problem}.",
                })
    for binding in bp["bindings"]:
        tag = str(binding["controlTag"])
        if not tags.get(tag): issues.append({"severity": "error", "code": "MISSING_BINDING_CONTROL", "tag": tag, "message": f"Binding control {tag} is not present in the DOCX."})
    for kind, entries, key in (("condition", bp["conditions"], "regionTag"), ("repeater", bp["repeaters"], "regionTag")):
        for entry in entries:
            tag = str(entry[key])
            count = tags.get(tag, 0)
            if count == 0: issues.append({"severity": "error", "code": f"MISSING_{kind.upper()}_REGION", "tag": tag, "message": f"{kind.title()} region {tag} is not present in the DOCX."})
            elif count > 1: issues.append({"severity": "warning", "code": f"DUPLICATE_{kind.upper()}_REGION", "tag": tag, "message": f"{kind.title()} region {tag} appears {count} times."})
    return {"ready": not any(i["severity"] == "error" for i in issues), "issues": issues, "tagCounts": tags}


def _format_value(value: Any, formatting: Mapping[str, Any] | None) -> str:
    if value is None: return ""
    fmt = dict(formatting or {})
    if isinstance(value, bool): text = "Yes" if value else "No"
    elif isinstance(value, (list, tuple)): text = str(fmt.get("separator", ", ")).join(_format_value(v, {}) for v in value)
    elif isinstance(value, Decimal): text = str(value)
    elif isinstance(value, (date, datetime)):
        pattern = str(fmt.get("dateFormat") or "%d/%m/%Y")
        text = value.strftime(pattern)
    else: text = str(value)
    if fmt.get("numberDecimals") is not None:
        try:
            decimals = int(fmt["numberDecimals"])
            if decimals < 0 or decimals > 12:
                raise ValueError("numberDecimals is outside the supported range")
            number = Decimal(str(value).replace(",", "").strip())
            spec = f",.{decimals}f" if fmt.get("grouping") else f".{decimals}f"
            text = format(number, spec)
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise TemplateAutomationError("Binding number formatting requires a valid numeric value and 0-12 decimals") from exc
    case = str(fmt.get("case") or "").lower()
    if case == "upper": text = text.upper()
    elif case == "lower": text = text.lower()
    elif case == "title": text = text.title()
    prefix = str(fmt.get("prefix") or ""); suffix = str(fmt.get("suffix") or "")
    return prefix + text + suffix


def _replace_sdt_text(sdt: ET.Element, value: str) -> None:
    problem = _binding_control_issue(sdt)
    if problem:
        raise TemplateAutomationError(f"Refusing to flatten complex binding content: {problem}")
    content = sdt.find("./w:sdtContent", NS)
    if content is None:
        raise TemplateAutomationError("Binding content control has no w:sdtContent")
    texts = content.findall(".//w:t", NS)
    if texts:
        texts[0].text = value
        if value.startswith(" ") or value.endswith(" "):
            texts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        for node in texts[1:]: node.text = ""
        return
    paragraph = content.find(".//w:p", NS)
    if paragraph is None:
        paragraph = ET.SubElement(content, f"{{{W}}}p")
    run = ET.SubElement(paragraph, f"{{{W}}}r")
    text = ET.SubElement(run, f"{{{W}}}t"); text.text = value


def _unwrap(parent: ET.Element, index: int, sdt: ET.Element) -> int:
    content = sdt.find("./w:sdtContent", NS)
    replacements = [copy.deepcopy(child) for child in list(content)] if content is not None else []
    parent.remove(sdt)
    for offset, child in enumerate(replacements): parent.insert(index + offset, child)
    return len(replacements)


def render_docx(content: bytes, blueprint: Any, data: Mapping[str, Any]) -> RenderedDocx:
    bp = validate_blueprint(blueprint)
    preflight = preflight_blueprint(bp, content)
    if not preflight["ready"]:
        messages = "; ".join(i["message"] for i in preflight["issues"] if i["severity"] == "error")
        raise TemplateAutomationError(f"Template preflight failed: {messages}")
    binding_map = {str(x["controlTag"]): x for x in bp["bindings"]}
    condition_map = {str(x["regionTag"]): x for x in bp["conditions"]}
    repeater_map = {str(x["regionTag"]): x for x in bp["repeaters"]}
    retain = bool(bp.get("retainControls"))
    stats = {"bindings": 0, "conditions": 0, "repeaters": 0, "repeatedItems": 0}
    warnings: list[str] = []
    settings = get_settings()
    total_repeated_items = 0

    def process_parent(parent: ET.Element, *, item: Any = None, variables: Mapping[str, Any] | None = None) -> None:
        nonlocal total_repeated_items
        index = 0
        while index < len(parent):
            child = parent[index]
            if child.tag != f"{{{W}}}sdt":
                process_parent(child, item=item, variables=variables)
                index += 1
                continue
            tag = _tag_value(child)
            if tag in repeater_map:
                rule = repeater_map[tag]; stats["repeaters"] += 1
                if rule.get("condition") is not None:
                    try:
                        if not evaluate_bool(rule["condition"], data, item=item, variables=variables):
                            parent.remove(child); continue
                    except ExpressionError as exc:
                        raise TemplateAutomationError(f"Repeater {tag} condition could not be evaluated: {exc}") from exc
                expression = rule.get("collectionExpression") or {"field": rule.get("collectionKey")}
                try:
                    collection = evaluate(expression, data, item=item, variables=variables).value
                except ExpressionError as exc:
                    raise TemplateAutomationError(f"Repeater {tag} collection evaluation failed: {exc}") from exc
                if collection is None:
                    collection = []
                if not isinstance(collection, list):
                    raise TemplateAutomationError(f"Repeater {tag} expected a list")
                if len(collection) > settings.max_repeater_items:
                    raise TemplateAutomationError(
                        f"Repeater {tag} has {len(collection)} items; maximum is {settings.max_repeater_items}"
                    )
                total_repeated_items += len(collection)
                if total_repeated_items > settings.max_total_repeated_items:
                    raise TemplateAutomationError(
                        f"Template expansion exceeds the maximum total repeated items ({settings.max_total_repeated_items})"
                    )
                content_node = child.find("./w:sdtContent", NS)
                prototypes = [copy.deepcopy(x) for x in list(content_node)] if content_node is not None else []
                parent.remove(child)
                inserted = 0
                for entry in collection:
                    for proto in prototypes:
                        holder=ET.Element("holder");holder.append(copy.deepcopy(proto))
                        process_parent(holder, item=entry, variables=variables)
                        for clone in list(holder):
                            parent.insert(index + inserted, clone);inserted += 1
                    stats["repeatedItems"] += 1
                index += inserted
                continue
            if tag in condition_map:
                rule = condition_map[tag]; stats["conditions"] += 1
                try:
                    keep = evaluate_bool(rule["expression"], data, item=item, variables=variables)
                except ExpressionError as exc:
                    raise TemplateAutomationError(f"Condition {tag} evaluation failed: {exc}") from exc
                if not keep:
                    parent.remove(child); continue
                content_node = child.find("./w:sdtContent", NS)
                if content_node is not None: process_parent(content_node, item=item, variables=variables)
                if retain: index += 1
                else: index += _unwrap(parent, index, child)
                continue
            if tag in binding_map:
                binding = binding_map[tag]
                try:
                    value = evaluate(_expression(binding), data, item=item, variables=variables).value
                except ExpressionError as exc:
                    raise TemplateAutomationError(f"Binding {tag} evaluation failed: {exc}") from exc
                _replace_sdt_text(child, _format_value(value, binding.get("formatting")))
                stats["bindings"] += 1
                content_node = child.find("./w:sdtContent", NS)
                if content_node is not None: process_parent(content_node, item=item, variables=variables)
                if retain: index += 1
                else: index += _unwrap(parent, index, child)
                continue
            process_parent(child, item=item, variables=variables)
            index += 1

    parts = _docx_parts(content)
    for name in _automation_xml_parts(parts):
        try:
            root = ET.fromstring(parts[name])
        except ET.ParseError as exc:
            raise TemplateAutomationError(f"Malformed required OOXML part {name}: {exc}") from exc
        process_parent(root)
        rendered_part = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        if len(rendered_part) > settings.max_rendered_xml_part_bytes:
            raise TemplateAutomationError(f"Rendered XML part {name} exceeds the configured size limit")
        parts[name] = rendered_part

    total_xml_bytes = sum(len(body) for name, body in parts.items() if name.endswith(".xml"))
    if total_xml_bytes > settings.max_rendered_total_xml_bytes:
        raise TemplateAutomationError(
            f"Rendered DOCX XML expands beyond the configured aggregate limit ({settings.max_rendered_total_xml_bytes} bytes)"
        )
    total_uncompressed_bytes = sum(len(body) for body in parts.values())
    if total_uncompressed_bytes > settings.max_rendered_uncompressed_docx_bytes:
        raise TemplateAutomationError(
            f"Rendered DOCX expands beyond the configured uncompressed output limit ({settings.max_rendered_uncompressed_docx_bytes} bytes)"
        )
    rendered_control_count = 0
    for name in _word_xml_parts(parts):
        try:
            root = ET.fromstring(parts[name])
        except ET.ParseError as exc:
            raise TemplateAutomationError(f"Rendered OOXML part {name} is malformed: {exc}") from exc
        rendered_control_count += len(root.findall(".//w:sdt", NS))
        if rendered_control_count > settings.max_rendered_content_controls:
            raise TemplateAutomationError(
                f"Rendered DOCX contains too many content controls ({rendered_control_count} > {settings.max_rendered_content_controls})"
            )
    stats["contentControls"] = rendered_control_count
    stats["renderedXmlBytes"] = total_xml_bytes
    stats["uncompressedBytes"] = total_uncompressed_bytes

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, body in parts.items(): zf.writestr(name, body)
    blob = output.getvalue()
    if len(blob) > settings.max_rendered_docx_bytes:
        raise TemplateAutomationError("Rendered DOCX exceeds the configured output-size limit")
    return RenderedDocx(content=blob, sha256=hashlib.sha256(blob).hexdigest(), stats=stats, warnings=tuple(warnings))


def render_docx_base64(docx_base64: str, blueprint: Any, data: Mapping[str, Any]) -> RenderedDocx:
    try: content = base64.b64decode(docx_base64, validate=True)
    except Exception as exc: raise TemplateAutomationError("Invalid DOCX base64") from exc
    return render_docx(content, blueprint, data)

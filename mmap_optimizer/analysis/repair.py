from __future__ import annotations


def repair_json_text(raw_output: str) -> tuple[str, bool, list[str]]:
    text = (raw_output or "").strip()
    repairs: list[str] = []
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        repairs.append("STRIPPED_CODE_FENCE")
    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first and (first != 0 or last != len(text) - 1):
        text = text[first:last + 1]
        repairs.append("EXTRACTED_JSON_OBJECT")
    return text, bool(repairs), repairs

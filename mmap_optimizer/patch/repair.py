"""Patch repair engine.

The repair engine is intentionally conservative: it may only update locator
fields that identify where a patch should be applied (for example section names
or ``old_text`` match text).  Business payload fields such as replacement text,
inserted text, operation type, metadata outside ``extra`` and custom payloads are
never accepted from the repair model.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher, get_close_matches
import json
import re
from typing import Any, Callable, Mapping, MutableMapping

def _optional_import(class_name: str, module_names: tuple[str, ...]) -> Any | None:
    for module_name in module_names:
        try:  # pragma: no cover - exercised only when the rest of the package exists.
            module = __import__(f"{__package__}.{module_name}", fromlist=[class_name])
            return getattr(module, class_name)
        except Exception:  # noqa: BLE001 - optional dependency in partial checkouts.
            continue
    return None


_DefaultPatchApplier = _optional_import("PatchApplier", ("applier", "apply"))
_DefaultPatchValidator = _optional_import("PatchValidator", ("validator", "validate"))


# Template names kept compatible with the existing prompt-template vocabulary.
patch_translation_retry = """Repair a failed patch locator only.\nFailure stage: {failure_stage}\nFailure info: {failure_info}\nPromptIR: {prompt_ir}\nCurrent section content: {current_section_content}\nFailed patch: {failed_patch}\nReturn JSON containing only locator fields to change. Do not modify payload.\n"""

patch_text_match = """Find the exact text in the current prompt section that best matches the failed old_text.\nFailure info: {failure_info}\nCurrent section content: {current_section_content}\nFailed locator: {locator}\nReturn JSON containing only locator fields to change.\n"""


LOCATOR_KEYS = frozenset(
    {
        "locator",
        "section",
        "section_name",
        "section_id",
        "path",
        "anchor",
        "position",
        "index",
        "start",
        "end",
        "old_text",
        "before_text",
        "after_text",
        "match_text",
        "target_text",
        "start_marker",
        "end_marker",
    }
)

_STATUS_KEYS = ("status", "state")
_REJECTED = "rejected"
_ACCEPTED = "accepted"


@dataclass(frozen=True)
class RepairOutcome:
    """Structured result returned by :meth:`PatchRepairEngine.repair_with_outcome`."""

    patch: dict[str, Any]
    success: bool
    actions: list[dict[str, Any]]


class PatchRepairEngine:
    """Repair failed PromptIR patches by changing locator fields only.

    Parameters are injectable so tests and applications can wire in their
    existing validator, applier and LLM/template runner implementations.  If no
    validator or applier is supplied, the engine tries to instantiate the
    package's default ``PatchValidator`` and ``PatchApplier`` when available.
    """

    def __init__(
        self,
        validator: Any | None = None,
        applier: Any | None = None,
        llm: Callable[..., Any] | None = None,
        max_attempts: int = 1,
    ) -> None:
        self.validator = validator if validator is not None else self._build_default(_DefaultPatchValidator)
        self.applier = applier if applier is not None else self._build_default(_DefaultPatchApplier)
        self.llm = llm
        self.max_attempts = max(1, max_attempts)

    def repair(
        self,
        failed_patch: Mapping[str, Any],
        failure_stage: str,
        failure_info: Any,
        prompt_ir: Any,
        current_section_content: str | None = None,
    ) -> dict[str, Any]:
        """Return a repaired patch or the original patch marked as rejected."""

        return self.repair_with_outcome(
            failed_patch=failed_patch,
            failure_stage=failure_stage,
            failure_info=failure_info,
            prompt_ir=prompt_ir,
            current_section_content=current_section_content,
        ).patch

    def repair_with_outcome(
        self,
        failed_patch: Mapping[str, Any],
        failure_stage: str,
        failure_info: Any,
        prompt_ir: Any,
        current_section_content: str | None = None,
    ) -> RepairOutcome:
        original = deepcopy(dict(failed_patch))
        patch = deepcopy(original)
        self._ensure_extra(patch)
        attempts_before = int(patch["extra"].get("repair_attempts", 0) or 0)
        actions: list[dict[str, Any]] = []

        for attempt_index in range(self.max_attempts):
            candidate = deepcopy(patch)
            candidate_changes = self._propose_locator_changes(
                patch=candidate,
                failure_stage=failure_stage,
                failure_info=failure_info,
                prompt_ir=prompt_ir,
                current_section_content=current_section_content,
            )
            safe_changes = self._filter_locator_changes(candidate_changes)
            if not safe_changes:
                actions.append({"attempt": attempt_index + 1, "action": "no_locator_change"})
                break

            before_payload = self._business_fingerprint(original)
            self._apply_locator_changes(candidate, safe_changes)
            self._restore_business_payload(candidate, original, before_payload)
            action = {"attempt": attempt_index + 1, "action": "locator_update", "changes": safe_changes}

            if self._dry_run(candidate, prompt_ir):
                self._mark_success(candidate, attempts_before + attempt_index + 1, [*actions, action])
                return RepairOutcome(patch=candidate, success=True, actions=[*actions, action])

            action["dry_run"] = "failed"
            actions.append(action)
            patch = candidate

        rejected = deepcopy(original)
        self._ensure_extra(rejected)
        self._mark_failure(rejected, attempts_before + len(actions), actions)
        return RepairOutcome(patch=rejected, success=False, actions=actions)

    def repair_batch(
        self,
        failed_patches: list[Mapping[str, Any]],
        failure_stage: str,
        failure_info: Any,
        prompt_ir: Any,
        current_section_content: str | None = None,
    ) -> list[dict[str, Any]]:
        """Repair a list of failed patches with the same failure context."""

        return [
            self.repair(p, failure_stage, failure_info, prompt_ir, current_section_content)
            for p in failed_patches
        ]

    @staticmethod
    def _build_default(cls: Any | None) -> Any | None:
        if cls is None:
            return None
        return cls()

    @staticmethod
    def _ensure_extra(patch: MutableMapping[str, Any]) -> None:
        extra = patch.get("extra")
        if not isinstance(extra, MutableMapping):
            patch["extra"] = {}

    @staticmethod
    def _mark_success(patch: MutableMapping[str, Any], attempts: int, actions: list[dict[str, Any]]) -> None:
        PatchRepairEngine._ensure_extra(patch)
        patch["extra"]["repair_attempts"] = attempts
        patch["extra"]["repair_actions"] = actions
        patch["extra"]["repair_success"] = True
        for key in _STATUS_KEYS:
            if key in patch:
                patch[key] = _ACCEPTED

    @staticmethod
    def _mark_failure(patch: MutableMapping[str, Any], attempts: int, actions: list[dict[str, Any]]) -> None:
        PatchRepairEngine._ensure_extra(patch)
        patch["extra"]["repair_attempts"] = attempts
        patch["extra"]["repair_actions"] = actions
        patch["extra"]["repair_success"] = False
        for key in _STATUS_KEYS:
            if key in patch:
                patch[key] = _REJECTED

    def _propose_locator_changes(
        self,
        patch: Mapping[str, Any],
        failure_stage: str,
        failure_info: Any,
        prompt_ir: Any,
        current_section_content: str | None,
    ) -> dict[str, Any]:
        heuristic = self._heuristic_locator_changes(patch, prompt_ir, current_section_content)
        if heuristic:
            return heuristic

        if self.llm is None:
            return {}

        locator = self._extract_locator(patch)
        template = patch_text_match if self._locator_old_text(locator) else patch_translation_retry
        prompt = template.format(
            failure_stage=failure_stage,
            failure_info=failure_info,
            prompt_ir=self._safe_json(prompt_ir),
            current_section_content=current_section_content or "",
            failed_patch=self._safe_json(patch),
            locator=self._safe_json(locator),
        )
        raw = self._call_llm(prompt, template, patch, failure_stage, failure_info, prompt_ir, current_section_content)
        return self._parse_locator_json(raw)

    def _heuristic_locator_changes(
        self, patch: Mapping[str, Any], prompt_ir: Any, current_section_content: str | None) -> dict[str, Any]:
        changes: dict[str, Any] = {}
        locator = self._extract_locator(patch)
        sections = self._extract_sections(prompt_ir)
        locator_section = self._locator_section(locator)

        if locator_section and sections and locator_section not in sections:
            match = get_close_matches(locator_section, list(sections), n=1, cutoff=0.55)
            if match:
                self._set_locator_key(changes, patch, locator, self._section_key(locator), match[0])

        content = current_section_content
        if content is None:
            section_for_content = changes.get(self._section_key(locator)) or locator_section
            if isinstance(section_for_content, str):
                content = sections.get(section_for_content)

        old_text_key, old_text = self._locator_old_text_with_key(locator)
        if old_text and content and old_text not in content:
            exactish = self._best_line_match(old_text, content)
            if exactish:
                self._set_locator_key(changes, patch, locator, old_text_key, exactish)

        return changes

    @staticmethod
    def _extract_locator(patch: Mapping[str, Any]) -> dict[str, Any]:
        locator = patch.get("locator")
        if isinstance(locator, Mapping):
            extracted = dict(locator)
        else:
            extracted = {}
        for key in LOCATOR_KEYS - {"locator"}:
            if key in patch:
                extracted.setdefault(key, patch[key])
        return extracted

    @staticmethod
    def _section_key(locator: Mapping[str, Any]) -> str:
        for key in ("section", "section_name", "section_id", "path"):
            if key in locator:
                return key
        return "section"

    @staticmethod
    def _locator_section(locator: Mapping[str, Any]) -> str | None:
        for key in ("section", "section_name", "section_id", "path"):
            value = locator.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _locator_old_text(locator: Mapping[str, Any]) -> str | None:
        return PatchRepairEngine._locator_old_text_with_key(locator)[1]

    @staticmethod
    def _locator_old_text_with_key(locator: Mapping[str, Any]) -> tuple[str, str | None]:
        for key in ("old_text", "match_text", "target_text", "before_text", "after_text"):
            value = locator.get(key)
            if isinstance(value, str) and value:
                return key, value
        return "old_text", None

    @staticmethod
    def _set_locator_key(
        changes: MutableMapping[str, Any],
        patch: Mapping[str, Any],
        locator: Mapping[str, Any],
        key: str,
        value: Any,
    ) -> None:
        if isinstance(patch.get("locator"), Mapping) and key in locator:
            changes.setdefault("locator", {})[key] = value
        else:
            changes[key] = value

    @staticmethod
    def _extract_sections(prompt_ir: Any) -> dict[str, str]:
        sections: dict[str, str] = {}

        def add(name: Any, content: Any) -> None:
            if isinstance(name, str) and name:
                sections[name] = content if isinstance(content, str) else ""

        if isinstance(prompt_ir, Mapping):
            raw_sections = prompt_ir.get("sections") or prompt_ir.get("prompt_sections")
            if isinstance(raw_sections, Mapping):
                for name, content in raw_sections.items():
                    if isinstance(content, Mapping):
                        add(name, content.get("content") or content.get("text") or "")
                    else:
                        add(name, content)
            elif isinstance(raw_sections, list):
                for item in raw_sections:
                    if isinstance(item, Mapping):
                        add(
                            item.get("name") or item.get("section") or item.get("id") or item.get("title"),
                            item.get("content") or item.get("text") or item.get("body") or "",
                        )
            for key in ("content", "text"):
                value = prompt_ir.get(key)
                if isinstance(value, Mapping):
                    for name, content in value.items():
                        add(name, content)
        elif hasattr(prompt_ir, "sections"):
            raw_sections = getattr(prompt_ir, "sections")
            if isinstance(raw_sections, Mapping):
                for name, section in raw_sections.items():
                    add(name, getattr(section, "content", section))
            elif isinstance(raw_sections, list):
                for section in raw_sections:
                    add(
                        getattr(section, "name", None) or getattr(section, "id", None) or getattr(section, "title", None),
                        getattr(section, "content", ""),
                    )
        return sections

    @staticmethod
    def _best_line_match(old_text: str, content: str) -> str | None:
        candidates = [line.strip() for line in content.splitlines() if line.strip()]
        candidates.extend(PatchRepairEngine._sentences(content))
        best = None
        best_score = 0.0
        normalized_old = PatchRepairEngine._normalize(old_text)
        for candidate in dict.fromkeys(candidates):
            score = SequenceMatcher(None, normalized_old, PatchRepairEngine._normalize(candidate)).ratio()
            if score > best_score:
                best_score = score
                best = candidate
        return best if best is not None and best_score >= 0.45 else None

    @staticmethod
    def _sentences(content: str) -> list[str]:
        return [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+", content) if part.strip()]

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.casefold()).strip()

    @staticmethod
    def _filter_locator_changes(changes: Mapping[str, Any]) -> dict[str, Any]:
        safe: dict[str, Any] = {}
        for key, value in changes.items():
            if key == "locator" and isinstance(value, Mapping):
                nested = {k: deepcopy(v) for k, v in value.items() if k in LOCATOR_KEYS and k != "locator"}
                if nested:
                    safe[key] = nested
            elif key in LOCATOR_KEYS and key != "locator":
                safe[key] = deepcopy(value)
        return safe

    @staticmethod
    def _apply_locator_changes(patch: MutableMapping[str, Any], changes: Mapping[str, Any]) -> None:
        for key, value in changes.items():
            if key == "locator" and isinstance(value, Mapping):
                locator = patch.setdefault("locator", {})
                if isinstance(locator, MutableMapping):
                    locator.update(deepcopy(dict(value)))
            else:
                patch[key] = deepcopy(value)

    @staticmethod
    def _business_fingerprint(patch: Mapping[str, Any]) -> dict[str, Any]:
        return {k: deepcopy(v) for k, v in patch.items() if k not in LOCATOR_KEYS and k != "extra"}

    @staticmethod
    def _restore_business_payload(
        candidate: MutableMapping[str, Any],
        original: Mapping[str, Any],
        original_business: Mapping[str, Any],
    ) -> None:
        for key in list(candidate.keys()):
            if key not in LOCATOR_KEYS and key != "extra" and key not in original_business:
                del candidate[key]
        for key, value in original_business.items():
            candidate[key] = deepcopy(value)
        # If a model returned payload nested under locator by mistake, remove it.
        locator = candidate.get("locator")
        original_locator = original.get("locator")
        if isinstance(locator, MutableMapping):
            for key in list(locator.keys()):
                if key not in LOCATOR_KEYS:
                    del locator[key]
            if isinstance(original_locator, Mapping):
                for key, value in original_locator.items():
                    if key not in LOCATOR_KEYS:
                        locator[key] = deepcopy(value)

    def _dry_run(self, patch: Mapping[str, Any], prompt_ir: Any) -> bool:
        if self.validator is not None and not self._run_validator(patch, prompt_ir):
            return False
        if self.applier is not None and not self._run_applier(patch, prompt_ir):
            return False
        return True

    def _run_validator(self, patch: Mapping[str, Any], prompt_ir: Any) -> bool:
        validator = self.validator
        for name, args in (
            ("validate", (patch, prompt_ir)),
            ("dry_run", (patch, prompt_ir)),
            ("__call__", (patch, prompt_ir)),
        ):
            if hasattr(validator, name):
                result = getattr(validator, name)(*args)
                return self._truthy_result(result)
        return True

    def _run_applier(self, patch: Mapping[str, Any], prompt_ir: Any) -> bool:
        applier = self.applier
        method_names = ("apply", "dry_run", "apply_patch", "__call__")
        for name in method_names:
            if hasattr(applier, name):
                method = getattr(applier, name)
                try:
                    result = method(patch, prompt_ir, dry_run=True)
                except TypeError:
                    result = method(patch, prompt_ir)
                return self._truthy_result(result)
        return True

    @staticmethod
    def _truthy_result(result: Any) -> bool:
        if isinstance(result, bool):
            return result
        if result is None:
            return True
        if isinstance(result, Mapping):
            for key in ("ok", "valid", "success", "accepted"):
                if key in result:
                    return bool(result[key])
            if "errors" in result:
                return not bool(result["errors"])
        if hasattr(result, "ok"):
            return bool(result.ok)
        if hasattr(result, "valid"):
            return bool(result.valid)
        if hasattr(result, "success"):
            return bool(result.success)
        return bool(result)

    def _call_llm(self, prompt: str, template: str, *context: Any) -> Any:
        if self.llm is None:
            return None
        try:
            return self.llm(prompt=prompt, template=template, context=context)
        except TypeError:
            try:
                return self.llm(prompt)
            except TypeError:
                return self.llm(template, *context)

    @staticmethod
    def _parse_locator_json(raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, Mapping):
            return dict(raw)
        text = str(raw).strip()
        if not text:
            return {}
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        else:
            obj = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if obj:
                text = obj.group(0)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}

    @staticmethod
    def _safe_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, default=lambda o: getattr(o, "__dict__", repr(o)))
        except TypeError:
            return repr(value)

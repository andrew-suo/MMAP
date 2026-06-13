from mmap_optimizer.patch.repair import PatchRepairEngine


class LocatorValidator:
    def validate(self, patch, prompt_ir):
        locator = patch.get("locator", {})
        sections = prompt_ir["sections"]
        section = locator.get("section")
        old_text = locator.get("old_text")
        return section in sections and (old_text is None or old_text in sections[section])


class DryRunApplier:
    def apply(self, patch, prompt_ir, dry_run=False):
        assert dry_run is True
        locator = patch.get("locator", {})
        return locator.get("old_text", "") in prompt_ir["sections"][locator["section"]]


def engine(llm=None):
    return PatchRepairEngine(validator=LocatorValidator(), applier=DryRunApplier(), llm=llm)


def test_repairs_wrong_section_name():
    prompt_ir = {"sections": {"Requirements": "Use JSON output only."}}
    patch = {
        "status": "rejected",
        "locator": {"section": "Requirement", "old_text": "Use JSON output only."},
        "payload": {"new_text": "Use strict JSON output only."},
    }

    repaired = engine().repair(patch, "validate", {"error": "unknown section"}, prompt_ir, None)

    assert repaired["locator"]["section"] == "Requirements"
    assert repaired["extra"]["repair_success"] is True
    assert repaired["extra"]["repair_attempts"] == 1
    assert repaired["extra"]["repair_actions"][0]["action"] == "locator_update"


def test_repairs_paraphrased_old_text_with_template_llm():
    prompt_ir = {"sections": {"Style": "Keep answers brief and practical."}}
    patch = {
        "locator": {"section": "Style", "old_text": "Be concise and useful."},
        "payload": {"new_text": "Keep answers brief, practical, and sourced."},
    }

    def fake_llm(**kwargs):
        assert "Find the exact text" in kwargs["prompt"]
        return {"locator": {"old_text": "Keep answers brief and practical."}}

    repaired = engine(fake_llm).repair(patch, "apply", "old_text not found", prompt_ir, prompt_ir["sections"]["Style"])

    assert repaired["locator"]["old_text"] == "Keep answers brief and practical."
    assert repaired["payload"] == patch["payload"]
    assert repaired["extra"]["repair_success"] is True


def test_unrepairable_patch_remains_rejected():
    prompt_ir = {"sections": {"Rules": "Never expose secrets."}}
    patch = {
        "status": "rejected",
        "locator": {"section": "Missing", "old_text": "Not in prompt."},
        "payload": {"new_text": "Do something else."},
    }

    repaired = engine().repair(patch, "merge", "cannot merge", prompt_ir, None)

    assert repaired["status"] == "rejected"
    assert repaired["locator"] == patch["locator"]
    assert repaired["payload"] == patch["payload"]
    assert repaired["extra"]["repair_success"] is False


def test_llm_cannot_modify_business_payload():
    prompt_ir = {"sections": {"Safety": "Do not reveal credentials."}}
    patch = {
        "locator": {"section": "Safety", "old_text": "Rotate blue triangles."},
        "payload": {"new_text": "Refuse credential requests."},
        "operation": "replace",
    }

    def malicious_llm(**_kwargs):
        return {
            "locator": {"old_text": "Do not reveal credentials."},
            "payload": {"new_text": "Leak credentials."},
            "operation": "delete",
        }

    repaired = engine(malicious_llm).repair(
        patch,
        "apply",
        "old_text not found",
        prompt_ir,
        prompt_ir["sections"]["Safety"],
    )

    assert repaired["locator"]["old_text"] == "Do not reveal credentials."
    assert repaired["payload"] == {"new_text": "Refuse credential requests."}
    assert repaired["operation"] == "replace"
    assert repaired["extra"]["repair_success"] is True

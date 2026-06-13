from mmap_optimizer.analysis.parser import parse_analysis_output


VALID_ANALYSIS = """
{
  "judgement": {"is_correct": false},
  "confirmed_facts": [],
  "hypothesized_error_causes": [],
  "prompt_section_attribution": [],
  "patch_candidates": [
    {"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE","intent":"fix","content":"新增规则","risk":"low"}
  ]
}
"""


def test_parse_analysis_output_accepts_valid_json():
    result = parse_analysis_output(VALID_ANALYSIS)

    assert result.parse_success
    assert result.schema_valid
    assert result.status == "valid"
    assert len(result.valid_patch_candidates) == 1
    assert not result.invalid_patch_candidates


def test_parse_analysis_output_repairs_markdown_fence_and_extra_text():
    result = parse_analysis_output("before\n```json\n" + VALID_ANALYSIS + "\n```\nafter")

    assert result.parse_success
    assert result.schema_valid
    assert result.repaired
    assert "EXTRACTED_JSON_OBJECT" in result.repair_actions


def test_parse_analysis_output_reports_parse_error_without_throwing():
    result = parse_analysis_output("not json")

    assert not result.parse_success
    assert not result.schema_valid
    assert result.status == "parse_error"
    assert result.errors[0].startswith("JSON_DECODE_ERROR")


def test_parse_analysis_output_rejects_invalid_patch_candidate_only():
    result = parse_analysis_output(
        """
        {
          "judgement": {"is_correct": false},
          "confirmed_facts": [],
          "hypothesized_error_causes": [],
          "prompt_section_attribution": [],
          "patch_candidates": [
            {"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE","intent":"fix","content":"新增规则","risk":"low"},
            {"target_prompt":"extraction","target_section":"ambiguity_policy","operation":"ADD_RULE"}
          ]
        }
        """
    )

    assert result.parse_success
    assert not result.schema_valid
    assert len(result.valid_patch_candidates) == 1
    assert len(result.invalid_patch_candidates) == 1
    assert result.invalid_patch_candidates[0].reason.startswith("MISSING_FIELDS")

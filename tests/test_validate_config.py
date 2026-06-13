import pytest

from mmap_optimizer.cli.main import ConfigValidationError, main, validate_config


def test_mock_provider_config_is_valid():
    validate_config(
        {
            "models": {
                "extraction": {"provider": "mock", "model": "mock-extraction"},
                "optimizer": {"provider": "mock", "model": "mock-optimizer"},
            }
        }
    )


def test_openai_compatible_config_missing_base_url():
    with pytest.raises(ConfigValidationError, match="models.extraction.base_url"):
        validate_config(
            {
                "models": {
                    "extraction": {
                        "provider": "openai_compatible",
                        "model": "extractor",
                        "api_key_env": "EXTRACTION_API_KEY",
                    },
                    "optimizer": {"provider": "mock", "model": "mock-optimizer"},
                }
            }
        )


def test_openai_compatible_config_missing_api_key_env_or_api_key():
    with pytest.raises(ConfigValidationError, match="api_key_env or models.optimizer.api_key"):
        validate_config(
            {
                "models": {
                    "extraction": {"provider": "mock", "model": "mock-extraction"},
                    "optimizer": {
                        "provider": "openai_compatible",
                        "base_url": "https://example.test/v1",
                        "model": "optimizer",
                    },
                }
            }
        )


def test_legal_openai_compatible_config_is_valid():
    validate_config(
        {
            "models": {
                "extraction": {
                    "provider": "openai_compatible",
                    "base_url": "https://example.test/v1",
                    "model": "extractor",
                    "api_key_env": "EXTRACTION_API_KEY",
                },
                "optimizer": {
                    "provider": "openai_compatible",
                    "base_url": "https://example.test/v1",
                    "model": "optimizer",
                    "api_key": "test-key",
                },
            }
        }
    )


def test_validate_config_cli_accepts_config_file(tmp_path, capsys):
    config_path = tmp_path / "optimizer.yaml"
    config_path.write_text(
        """
models:
  extraction:
    provider: mock
    model: mock-extraction
  optimizer:
    provider: openai_compatible
    base_url: https://example.test/v1
    model: optimizer
    api_key: test-key
""".strip(),
        encoding="utf-8",
    )

    assert main(["validate-config", "--config", str(config_path)]) == 0
    assert "Configuration is valid" in capsys.readouterr().out

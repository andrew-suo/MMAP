from __future__ import annotations

import json

from mmap_optimizer.cli.main import main


def _write_config(tmp_path, config):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_validate_config_accepts_mock_config(tmp_path, capsys):
    config_path = _write_config(
        tmp_path,
        {"optimizer_model": {"provider": "mock", "model": "mock-model", "api_key": "test"}},
    )

    assert main(["validate-config", "--config", str(config_path)]) == 0

    assert "Config validation succeeded" in capsys.readouterr().out


def test_validate_config_rejects_openai_compatible_without_base_url(tmp_path, capsys):
    config_path = _write_config(
        tmp_path,
        {
            "optimizer_model": {
                "provider": "openai_compatible",
                "model": "test-model",
                "api_key": "test",
            }
        },
    )

    assert main(["validate-config", "--config", str(config_path)]) == 1

    assert "requires base_url" in capsys.readouterr().err


def test_validate_config_rejects_missing_env_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MMAP_TEST_API_KEY", raising=False)
    config_path = _write_config(
        tmp_path,
        {
            "optimizer_model": {
                "provider": "openai",
                "model": "test-model",
                "api_key_env": "MMAP_TEST_API_KEY",
            }
        },
    )

    assert main(["validate-config", "--config", str(config_path)]) == 1

    assert "MMAP_TEST_API_KEY" in capsys.readouterr().err


def test_validate_config_accepts_legal_openai_compatible_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MMAP_TEST_API_KEY", "secret")
    config_path = _write_config(
        tmp_path,
        {
            "optimizer_model": {
                "provider": "openai_compatible",
                "base_url": "https://example.test/v1",
                "model": "test-model",
                "api_key_env": "MMAP_TEST_API_KEY",
            }
        },
    )

    assert main(["validate-config", "--config", str(config_path)]) == 0

    assert "Config validation succeeded" in capsys.readouterr().out

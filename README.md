# MMAP

## Optimizer configuration

Validate the optimizer configuration before running an optimization job:

```bash
python -m mmap_optimizer.cli.main validate-config
```

By default the command reads `configs/optimizer.yaml`. Pass `--config` to validate a different file:

```bash
python -m mmap_optimizer.cli.main validate-config --config path/to/optimizer.yaml
```

For OpenAI-compatible providers, MMAP validates `models.extraction` and `models.optimizer` independently. Each OpenAI-compatible model block must include:

- `provider: openai_compatible`
- `base_url`
- `model`
- either `api_key_env` or `api_key`

Use `--dry-run-model-call` to send a tiny text-only request to the optimizer model. This does not read images or run optimization:

```bash
python -m mmap_optimizer.cli.main validate-config --dry-run-model-call
```

### Real model configuration example

The extraction model and optimizer model are configured separately so they can use different providers, model IDs, endpoints, and credentials:

```yaml
models:
  extraction:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4.1-mini
    api_key_env: OPENAI_API_KEY

  optimizer:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    model: gpt-4.1
    api_key_env: OPENAI_API_KEY
```

For local testing, a mock provider can be used without OpenAI-compatible connection fields:

```yaml
models:
  extraction:
    provider: mock
    model: mock-extraction
  optimizer:
    provider: mock
    model: mock-optimizer
```

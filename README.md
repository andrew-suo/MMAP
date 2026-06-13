# MMAP

MMAP optimizer utilities.

## Validate optimizer configuration

Use the `validate-config` subcommand to check that the optimizer model settings
are complete before running an optimization job:

```bash
python -m mmap_optimizer.cli.main validate-config --config config.json
```

Add `--dry-run-model-call` to send one tiny text-only request to the optimizer
model. This does not read images and does not run optimization:

```bash
python -m mmap_optimizer.cli.main validate-config --config config.json --dry-run-model-call
```

### OpenAI-compatible provider example

```json
{
  "optimizer_model": {
    "provider": "openai_compatible",
    "base_url": "https://api.example.com/v1",
    "model": "example-model",
    "api_key_env": "MMAP_OPTIMIZER_API_KEY"
  }
}
```

For `provider=openai_compatible`, `base_url` is required. All providers require
`model` and either `api_key` or `api_key_env`. When `api_key_env` is used, the
named environment variable must exist.

### Mock provider example

```json
{
  "optimizer_model": {
    "provider": "mock",
    "model": "mock-model",
    "api_key": "test"
  }
}
```

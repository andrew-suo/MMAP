# MMAP

MMAP contains prompt import utilities for optimizer workflows.

## Prompt import standardization

`mmap_optimizer.prompt.initializer.initialize_prompt` preserves imported Markdown by default and writes the imported prompt into `legacy_unmapped` without automatic rewrites.

The initializer exposes optional lossless import tools:

- `fix_numbering=True` calls `fix_ordered_list_numbering` to repair ordered-list counters.
- `normalize_spacing=True` calls `normalize_markdown_spacing` and `unique_heading_titles` to normalize conservative Markdown spacing and duplicate heading titles.
- `standardize=True` is a convenience flag that enables the lossless numbering and spacing/title import tools together.

These tools are **lossless import tools** intended to clean up prompt text during ingestion. They are not optimization-stage default steps and remain disabled unless explicitly requested.

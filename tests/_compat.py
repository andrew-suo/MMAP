"""Compatibility helpers for MMAP contract tests.

The public module layout is intentionally probed lazily so these tests can be
introduced before a stable package name is finalized.  Set MMAP_TEST_IMPORTS to
a comma-separated list of modules to force a concrete target in local runs.
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Iterable
from types import ModuleType
from typing import Any

import pytest


def candidate_modules(*defaults: str) -> tuple[str, ...]:
    forced = tuple(
        item.strip() for item in os.environ.get("MMAP_TEST_IMPORTS", "").split(",") if item.strip()
    )
    return forced + tuple(defaults)


def import_first(*module_names: str) -> ModuleType:
    errors: list[str] = []
    for name in module_names:
        try:
            module = importlib.import_module(name)
        except Exception as exc:  # pragma: no cover - included in skip reason only
            errors.append(f"{name}: {exc!r}")
            continue
        return module
    pytest.skip("No compatible MMAP module found (tried: " + "; ".join(errors or module_names) + ")")


def find_symbol(module_names: Iterable[str], *symbol_names: str) -> Any:
    modules = tuple(module_names)
    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for symbol_name in symbol_names:
            if hasattr(module, symbol_name):
                return getattr(module, symbol_name)
    pytest.skip(
        "No compatible MMAP symbol found "
        f"(modules={modules!r}, symbols={symbol_names!r})"
    )

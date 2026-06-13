"""Runner implementations that execute one model call per sample."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping, Protocol

from mmap_optimizer.config import ExecutionConfig
from mmap_optimizer.orchestration.executor import SampleExecutor, TaskOutcome, create_executor, get_sample_id


class SupportsGenerate(Protocol):
    def generate(self, prompt: str, **kwargs: Any) -> Any: ...


Sample = Mapping[str, Any] | Any
ModelCallable = Callable[[str], Any] | Callable[..., Any] | SupportsGenerate


def _default_prompt(sample: Sample) -> str:
    if isinstance(sample, Mapping):
        for key in ("prompt", "input", "text"):
            if key in sample:
                return str(sample[key])
    return str(sample)


def _call_model(model: ModelCallable, prompt: str, **kwargs: Any) -> Any:
    if hasattr(model, "generate"):
        return getattr(model, "generate")(prompt, **kwargs)
    return model(prompt, **kwargs)  # type: ignore[misc]


def _merge_sample(sample: Sample, updates: Mapping[str, Any]) -> dict[str, Any]:
    base = dict(sample) if isinstance(sample, Mapping) else {"sample": sample}
    base.update(updates)
    return base


class BaseSampleRunner:
    """Base for runners that process samples independently."""

    def __init__(
        self,
        *,
        execution_config: ExecutionConfig | Mapping[str, object] | None = None,
        executor: SampleExecutor | None = None,
    ) -> None:
        self.execution_config = execution_config
        self.executor = executor or create_executor(execution_config)

    def _run_samples(
        self,
        samples: Iterable[Sample],
        task: Callable[[Sample], Any],
        *,
        sort_by_sample_id: bool = True,
    ) -> list[dict[str, Any]]:
        outcomes = self.executor.map(
            samples,
            task,
            sample_id_getter=get_sample_id,
            sort_by_sample_id=sort_by_sample_id,
        )
        return [self._serialize_outcome(outcome) for outcome in outcomes]

    @staticmethod
    def _serialize_outcome(outcome: TaskOutcome[Any]) -> dict[str, Any]:
        if outcome.ok:
            value = outcome.value
            if isinstance(value, Mapping):
                return dict(value)
            return {"sample_id": outcome.sample_id, "result": value}
        return {
            "sample_id": outcome.sample_id,
            "error": outcome.error,
            "exception_type": outcome.exception_type,
            "timed_out": outcome.timed_out,
        }


class PromptTestRunner(BaseSampleRunner):
    """Run prompt/model calls for a collection of prompt test samples."""

    def __init__(
        self,
        model: ModelCallable | None = None,
        *,
        prompt_builder: Callable[[Sample], str] = _default_prompt,
        model_kwargs: Mapping[str, Any] | None = None,
        execution_config: ExecutionConfig | Mapping[str, object] | None = None,
        executor: SampleExecutor | None = None,
    ) -> None:
        super().__init__(execution_config=execution_config, executor=executor)
        self.model = model
        self.prompt_builder = prompt_builder
        self.model_kwargs = model_kwargs

    def run(self, samples: Iterable[Sample]) -> list[dict[str, Any]]:
        def task(sample: Sample) -> dict[str, Any]:
            if self.model is None:
                raise ValueError("PromptTestRunner requires a model")
            prompt = self.prompt_builder(sample)
            response = _call_model(self.model, prompt, **dict(self.model_kwargs or {}))
            return _merge_sample(sample, {"prompt": prompt, "response": response})

        return self._run_samples(samples, task)


class AnalysisRunner(BaseSampleRunner):
    """Run model-backed analysis independently for each sample."""

    def __init__(
        self,
        model: ModelCallable | None = None,
        *,
        analyzer: Callable[[Sample, ModelCallable], Any] | None = None,
        prompt_builder: Callable[[Sample], str] = _default_prompt,
        model_kwargs: Mapping[str, Any] | None = None,
        execution_config: ExecutionConfig | Mapping[str, object] | None = None,
        executor: SampleExecutor | None = None,
    ) -> None:
        super().__init__(execution_config=execution_config, executor=executor)
        self.model = model
        self.analyzer = analyzer
        self.prompt_builder = prompt_builder
        self.model_kwargs = model_kwargs

    def run(self, samples: Iterable[Sample]) -> list[dict[str, Any]]:
        def task(sample: Sample) -> dict[str, Any]:
            if self.model is None:
                raise ValueError("AnalysisRunner requires a model")
            if self.analyzer is not None:
                analysis = self.analyzer(sample, self.model)
            else:
                analysis = _call_model(
                    self.model,
                    self.prompt_builder(sample),
                    **dict(self.model_kwargs or {}),
                )
            return _merge_sample(sample, {"analysis": analysis})

        return self._run_samples(samples, task)


class PatchTester(BaseSampleRunner):
    """Run patch/test model calls independently for each sample."""

    def __init__(
        self,
        model: ModelCallable | None = None,
        *,
        tester: Callable[[Sample, ModelCallable], Any] | None = None,
        prompt_builder: Callable[[Sample], str] = _default_prompt,
        model_kwargs: Mapping[str, Any] | None = None,
        execution_config: ExecutionConfig | Mapping[str, object] | None = None,
        executor: SampleExecutor | None = None,
    ) -> None:
        super().__init__(execution_config=execution_config, executor=executor)
        self.model = model
        self.tester = tester
        self.prompt_builder = prompt_builder
        self.model_kwargs = model_kwargs

    def run(self, samples: Iterable[Sample]) -> list[dict[str, Any]]:
        def task(sample: Sample) -> dict[str, Any]:
            if self.model is None:
                raise ValueError("PatchTester requires a model")
            if self.tester is not None:
                test_result = self.tester(sample, self.model)
            else:
                test_result = _call_model(
                    self.model,
                    self.prompt_builder(sample),
                    **dict(self.model_kwargs or {}),
                )
            return _merge_sample(sample, {"test_result": test_result})

        return self._run_samples(samples, task)

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mmap_optimizer.orchestration.records import IterationMetrics, RoundMetricsTracker


@dataclass
class PlotResult:
    """Result of a plotting operation."""
    plot_type: str
    file_path: str
    data_points: int
    summary: dict[str, Any]


class MetricsPlotter:
    """Generates SVG and JSON visualization plots for round/iteration metrics.

    Produces:
    1. Extraction accuracy evolution plot (base vs patched per iteration)
    2. Analysis accuracy evolution plot (base vs patched per iteration)
    3. Combined iteration summary with rollback indicators
    4. JSON data files for external visualization tools

    The plotter generates self-contained SVG files (no external deps
    beyond Python standard library).
    """

    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def plot_extraction_accuracy(
        self,
        tracker: RoundMetricsTracker,
        *,
        round_index: int,
    ) -> PlotResult:
        """Plot extraction prompt accuracy evolution.

        Shows:
        - Base accuracy per iteration (blue line)
        - Patched accuracy per iteration (green line, when patch accepted)
        - Rejected/rolled-back attempts (red cross markers)
        """
        metrics = tracker.iteration_metrics
        if not metrics:
            return PlotResult("extraction_accuracy", "", 0, {"note": "no data"})

        iteration_indices = list(range(1, len(metrics) + 1))
        base_acc = [m.extraction_base_accuracy for m in metrics]
        patched_acc = [
            m.extraction_patched_accuracy if m.extraction_accepted and m.extraction_patched_accuracy is not None else None
            for m in metrics
        ]

        return self._render_line_plot(
            title=f"Round {round_index}: Extraction Accuracy Evolution",
            x_label="Iteration",
            y_label="Accuracy",
            series=[
                {
                    "name": "Base Accuracy",
                    "color": "#3498db",
                    "points": list(zip(iteration_indices, base_acc)),
                },
                {
                    "name": "Patched Accuracy",
                    "color": "#27ae60",
                    "points": [(i, p) for i, p in zip(iteration_indices, patched_acc) if p is not None],
                },
            ],
            rollback_markers=[
                i for i, m in zip(iteration_indices, metrics) if not m.extraction_accepted
            ],
            rollback_values=[m.extraction_base_accuracy for m in metrics if not m.extraction_accepted],
            filename=f"round_{round_index:06d}_extraction_accuracy.svg",
            summary={
                "iterations": len(metrics),
                "accepted": sum(1 for m in metrics if m.extraction_accepted),
                "rolled_back": sum(1 for m in metrics if not m.extraction_accepted),
                "base_accuracy_min": min(base_acc),
                "base_accuracy_max": max(base_acc),
                "patched_accuracy_values": [p for p in patched_acc if p is not None],
            },
        )

    def plot_analysis_accuracy(
        self,
        tracker: RoundMetricsTracker,
        *,
        round_index: int,
    ) -> PlotResult:
        """Plot analysis prompt accuracy evolution (blind eval rate)."""
        metrics = tracker.iteration_metrics
        if not metrics:
            return PlotResult("analysis_accuracy", "", 0, {"note": "no data"})

        # Filter: only iterations where we have analysis base data
        analysis_iterations = [(i + 1, m) for i, m in enumerate(metrics) if m.analysis_base_accuracy is not None]
        if not analysis_iterations:
            return PlotResult("analysis_accuracy", "", 0, {"note": "no analysis data"})

        iteration_indices = [i for i, _ in analysis_iterations]
        analysis_base = [m.analysis_base_accuracy for _, m in analysis_iterations]
        analysis_patched = [
            m.analysis_patched_accuracy if m.analysis_accepted and m.analysis_patched_accuracy is not None else None
            for _, m in analysis_iterations
        ]

        return self._render_line_plot(
            title=f"Round {round_index}: Analysis Blind Eval Accuracy Evolution",
            x_label="Iteration",
            y_label="Accuracy",
            series=[
                {
                    "name": "Analysis Base Accuracy",
                    "color": "#f39c12",
                    "points": list(zip(iteration_indices, analysis_base)),
                },
                {
                    "name": "Analysis Patched Accuracy",
                    "color": "#e67e22",
                    "points": [(i, p) for i, p in zip(iteration_indices, analysis_patched) if p is not None],
                },
            ],
            rollback_markers=[
                i for i, m in analysis_iterations if not m.analysis_accepted
            ],
            rollback_values=[m.analysis_base_accuracy for _, m in analysis_iterations if not m.analysis_accepted],
            filename=f"round_{round_index:06d}_analysis_accuracy.svg",
            summary={
                "analysis_iterations": len(analysis_iterations),
                "analysis_accepted": sum(1 for _, m in analysis_iterations if m.analysis_accepted),
                "analysis_rolled_back": sum(1 for _, m in analysis_iterations if not m.analysis_accepted),
            },
        )

    def plot_combined_summary(
        self,
        tracker: RoundMetricsTracker,
        *,
        round_index: int,
    ) -> PlotResult:
        """Plot combined extraction + analysis summary."""
        metrics = tracker.iteration_metrics
        if not metrics:
            return PlotResult("combined_summary", "", 0, {"note": "no data"})

        iteration_indices = list(range(1, len(metrics) + 1))
        base_acc = [m.extraction_base_accuracy for m in metrics]
        patched_acc = [
            m.extraction_patched_accuracy if m.extraction_accepted and m.extraction_patched_accuracy is not None else None
            for m in metrics
        ]
        analysis_base = [m.analysis_base_accuracy for m in metrics]

        return self._render_line_plot(
            title=f"Round {round_index}: Combined Accuracy Summary",
            x_label="Iteration",
            y_label="Accuracy",
            series=[
                {"name": "Extraction Base", "color": "#3498db", "points": list(zip(iteration_indices, base_acc))},
                {"name": "Extraction Patched", "color": "#27ae60", "points": [(i, p) for i, p in zip(iteration_indices, patched_acc) if p is not None]},
                {
                    "name": "Analysis Base",
                    "color": "#f39c12",
                    "points": [(i, a) for i, a in zip(iteration_indices, analysis_base) if a is not None],
                },
            ],
            rollback_markers=[i for i, m in zip(iteration_indices, metrics) if not m.extraction_accepted],
            rollback_values=[m.extraction_base_accuracy for m in metrics if not m.extraction_accepted],
            filename=f"round_{round_index:06d}_combined_summary.svg",
            summary={
                "total_iterations": len(metrics),
                "accepted_iterations": sum(1 for m in metrics if m.extraction_accepted),
            },
        )

    def save_metrics_json(
        self,
        tracker: RoundMetricsTracker,
        *,
        round_index: int,
    ) -> str:
        """Save all metrics as structured JSON for external tools."""
        data = {
            "round_index": round_index,
            "global_iteration_counter": tracker.global_iteration_counter,
            "iteration_metrics": [
                {
                    "iteration_index": m.iteration_index,
                    "local_iteration_index": m.local_iteration_index,
                    "extraction": {
                        "base_accuracy": m.extraction_base_accuracy,
                        "base_correct_count": m.extraction_base_correct_count,
                        "base_total_count": m.extraction_base_total_count,
                        "patched_accuracy": m.extraction_patched_accuracy,
                        "patched_correct_count": m.extraction_patched_correct_count,
                        "patched_total_count": m.extraction_patched_total_count,
                        "accepted": m.extraction_accepted,
                        "patch_count": m.extraction_patch_count,
                    },
                    "analysis": {
                        "base_accuracy": m.analysis_base_accuracy,
                        "base_correct_count": m.analysis_base_correct_count,
                        "base_total_count": m.analysis_base_total_count,
                        "patched_accuracy": m.analysis_patched_accuracy,
                        "patched_correct_count": m.analysis_patched_correct_count,
                        "patched_total_count": m.analysis_patched_total_count,
                        "accepted": m.analysis_accepted,
                        "patch_count": m.analysis_patch_count,
                    },
                    "duration_seconds": m.duration_seconds,
                }
                for m in tracker.iteration_metrics
            ],
            "failed_attempts": [
                {
                    "attempt_number": fa.attempt_number,
                    "source": fa.source,
                    "extraction_base_accuracy": fa.extraction_base_accuracy,
                    "analysis_base_accuracy": fa.analysis_base_accuracy,
                    "reason": fa.reason,
                }
                for fa in tracker.failed_attempts
            ],
        }

        filepath = self.output_dir / f"round_{round_index:06d}_metrics.json"
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return str(filepath)

    def _render_line_plot(
        self,
        *,
        title: str,
        x_label: str,
        y_label: str,
        series: list[dict[str, Any]],
        rollback_markers: list[int],
        rollback_values: list[float],
        filename: str,
        summary: dict[str, Any],
    ) -> PlotResult:
        """Render a line plot as a self-contained SVG file."""
        width = 900
        height = 500
        padding_left = 60
        padding_right = 30
        padding_top = 60
        padding_bottom = 80
        plot_w = width - padding_left - padding_right
        plot_h = height - padding_top - padding_bottom

        # Collect all y values to compute scale
        all_y = [v for s in series for _, v in s["points"]] + [v for v in rollback_values]
        if not all_y:
            all_y = [0.0, 1.0]
        y_min = 0.0
        y_max = max(1.0, max(all_y))
        y_range = y_max - y_min or 1.0

        all_x = [i for s in series for i, _ in s["points"]] + rollback_markers
        x_min = min(all_x) if all_x else 1
        x_max = max(all_x) if all_x else max(1, len(series[0]["points"]) if series else 1)
        x_range = x_max - x_min or 1

        def px(x: float) -> float:
            return padding_left + ((x - x_min) / x_range) * plot_w

        def py(y: float) -> float:
            return padding_top + (1.0 - (y - y_min) / y_range) * plot_h

        # Build SVG content
        svg_lines: list[str] = []
        svg_lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" font-family="Arial, Helvetica, sans-serif">')
        svg_lines.append(f'<rect width="{width}" height="{height}" fill="#ffffff"/>')

        # Title
        svg_lines.append(f'<text x="{width/2}" y="30" text-anchor="middle" font-size="18" font-weight="bold">{title}</text>')

        # Axes
        svg_lines.append(f'<line x1="{padding_left}" y1="{padding_top}" x2="{padding_left}" y2="{padding_top + plot_h}" stroke="#333" stroke-width="2"/>')
        svg_lines.append(f'<line x1="{padding_left}" y1="{padding_top + plot_h}" x2="{padding_left + plot_w}" y2="{padding_top + plot_h}" stroke="#333" stroke-width="2"/>')

        # Y-axis grid lines and labels
        for i in range(0, 11):
            y_val = y_min + (i / 10) * y_range
            y_px = py(y_val)
            svg_lines.append(f'<line x1="{padding_left}" y1="{y_px:.1f}" x2="{padding_left + plot_w}" y2="{y_px:.1f}" stroke="#ddd" stroke-width="1"/>')
            svg_lines.append(f'<text x="{padding_left - 8}" y="{y_px + 4:.1f}" text-anchor="end" font-size="11">{y_val:.2f}</text>')

        # X-axis labels
        for i in range(int(x_min), int(x_max) + 1):
            x_px = px(i)
            svg_lines.append(f'<text x="{x_px:.1f}" y="{padding_top + plot_h + 20:.1f}" text-anchor="middle" font-size="11">{i}</text>')

        # Axis labels
        svg_lines.append(f'<text x="{padding_left + plot_w / 2}" y="{padding_top + plot_h + 50:.1f}" text-anchor="middle" font-size="13">{x_label}</text>')
        svg_lines.append(f'<text x="15" y="{padding_top + plot_h / 2}" text-anchor="middle" font-size="13" transform="rotate(-90 15 {padding_top + plot_h / 2})">{y_label}</text>')

        # Draw series lines
        for s in series:
            if not s["points"]:
                continue
            # Sort points by x
            sorted_points = sorted(s["points"], key=lambda p: p[0])
            path_d = " ".join(
                f"{'M' if idx == 0 else 'L'} {px(x):.1f} {py(y):.1f}"
                for idx, (x, y) in enumerate(sorted_points)
            )
            svg_lines.append(f'<path d="{path_d}" fill="none" stroke="{s["color"]}" stroke-width="2.5"/>')
            for x, y in sorted_points:
                svg_lines.append(f'<circle cx="{px(x):.1f}" cy="{py(y):.1f}" r="4" fill="{s["color"]}"/>')

        # Rollback markers (red crosses)
        for x, y in zip(rollback_markers, rollback_values):
            cx = px(x)
            cy = py(y)
            # Draw X mark
            r = 8
            svg_lines.append(f'<line x1="{cx - r}" y1="{cy - r}" x2="{cx + r}" y2="{cy + r}" stroke="#e74c3c" stroke-width="2.5"/>')
            svg_lines.append(f'<line x1="{cx - r}" y1="{cy + r}" x2="{cx + r}" y2="{cy - r}" stroke="#e74c3c" stroke-width="2.5"/>')
            svg_lines.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="none" stroke="#e74c3c" stroke-width="1" opacity="0.5"/>')

        # Legend
        legend_y = padding_top
        legend_x = padding_left + plot_w - 180
        for idx, s in enumerate(series):
            ly = legend_y + idx * 22
            svg_lines.append(f'<circle cx="{legend_x + 5}" cy="{ly}" r="4" fill="{s["color"]}"/>')
            svg_lines.append(f'<text x="{legend_x + 18}" y="{ly + 4:.1f}" font-size="12">{s["name"]}</text>')

        # Rollback legend
        ly = legend_y + len(series) * 22
        svg_lines.append(f'<line x1="{legend_x}" y1="{ly - 4}" x2="{legend_x + 10}" y2="{ly + 4}" stroke="#e74c3c" stroke-width="2.5"/>')
        svg_lines.append(f'<line x1="{legend_x}" y1="{ly + 4}" x2="{legend_x + 10}" y2="{ly - 4}" stroke="#e74c3c" stroke-width="2.5"/>')
        svg_lines.append(f'<text x="{legend_x + 18}" y="{ly + 5:.1f}" font-size="12">Rolled back</text>')

        svg_lines.append("</svg>")

        svg_content = "\n".join(svg_lines)
        filepath = self.output_dir / filename
        filepath.write_text(svg_content)

        return PlotResult(
            plot_type="line_plot",
            file_path=str(filepath),
            data_points=sum(len(s["points"]) for s in series),
            summary=summary,
        )

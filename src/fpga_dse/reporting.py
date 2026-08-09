from __future__ import annotations

import csv
import html
from pathlib import Path
from typing import Any

from fpga_dse.models import AnalysisResult, AnalyzedDesign, Objective
from fpga_dse.workspace import write_json_atomic


def write_reports(result: AnalysisResult, output_directory: str | Path, *, top: int = 20) -> dict[str, Path]:
    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output / "report.json",
        "csv": output / "report.csv",
        "markdown": output / "report.md",
        "html": output / "report.html",
    }
    write_json_atomic(paths["json"], _json_payload(result))
    _write_csv(result, paths["csv"])
    paths["markdown"].write_text(_markdown_report(result, top=top), encoding="utf-8")
    paths["html"].write_text(_html_report(result, top=top), encoding="utf-8")
    return paths


def _json_payload(result: AnalysisResult) -> dict[str, Any]:
    recommended = result.recommended
    return {
        "schema_version": 1,
        "project": result.project,
        "summary": {
            "successful_designs": result.successful_count,
            "feasible_designs": len(result.feasible_designs),
            "pareto_designs": len(result.pareto_designs),
            "recommended_design_id": recommended.record.design_id if recommended else None,
        },
        "objectives": [
            {"metric": objective.metric, "goal": objective.goal, "weight": objective.weight}
            for objective in result.objectives
        ],
        "designs": [design.to_dict() for design in result.designs],
    }


def _write_csv(result: AnalysisResult, path: Path) -> None:
    parameter_names = sorted(
        {name for design in result.designs for name in design.record.parameters}
    )
    metric_names = sorted({name for design in result.designs for name in design.record.metrics})
    fieldnames = [
        "design_id",
        "status",
        "feasible",
        "pareto_optimal",
        "score",
        "duration_seconds",
        *[f"param.{name}" for name in parameter_names],
        *[f"metric.{name}" for name in metric_names],
        "violations",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for design in result.designs:
            row: dict[str, Any] = {
                "design_id": design.record.design_id,
                "status": design.record.status,
                "feasible": design.feasible,
                "pareto_optimal": design.pareto_optimal,
                "score": "" if design.score is None else f"{design.score:.8f}",
                "duration_seconds": design.record.duration_seconds,
                "violations": "; ".join(design.violations),
            }
            row.update({f"param.{key}": value for key, value in design.record.parameters.items()})
            row.update({f"metric.{key}": value for key, value in design.record.metrics.items()})
            writer.writerow(row)


def _markdown_report(result: AnalysisResult, *, top: int) -> str:
    recommended = result.recommended
    lines = [
        f"# FPGA DSE Report: {result.project}",
        "",
        "## Summary",
        "",
        f"- Successful designs: **{result.successful_count}**",
        f"- Feasible designs: **{len(result.feasible_designs)}**",
        f"- Pareto-optimal designs: **{len(result.pareto_designs)}**",
        f"- Recommended design: **{recommended.record.design_id if recommended else 'none'}**",
        "",
        "## Objectives",
        "",
        "| Metric | Goal | Weight |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| `{objective.metric}` | {objective.goal} | {objective.weight:g} |"
        for objective in result.objectives
    )
    lines.extend(["", f"## Top {min(top, len(result.designs))} Designs", ""])
    lines.extend(_markdown_design_table(result.designs[:top], result.objectives))
    lines.extend(["", "## Pareto Frontier", ""])
    lines.extend(_markdown_design_table(result.pareto_designs, result.objectives))
    lines.append("")
    return "\n".join(lines)


def _markdown_design_table(
    designs: tuple[AnalyzedDesign, ...] | list[AnalyzedDesign],
    objectives: tuple[Objective, ...],
) -> list[str]:
    if not designs:
        return ["No designs available."]
    parameter_names = sorted({name for design in designs for name in design.record.parameters})
    headers = ["Design", "Score", "Feasible", "Pareto", *parameter_names, *[item.metric for item in objectives]]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for design in designs:
        values = [
            f"`{design.record.design_id}`",
            "—" if design.score is None else f"{design.score:.4f}",
            "yes" if design.feasible else "no",
            "yes" if design.pareto_optimal else "no",
            *[str(design.record.parameters.get(name, "—")) for name in parameter_names],
            *[str(design.record.metrics.get(objective.metric, "—")) for objective in objectives],
        ]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _html_report(result: AnalysisResult, *, top: int) -> str:
    recommended = result.recommended
    cards = (
        ("Successful", result.successful_count),
        ("Feasible", len(result.feasible_designs)),
        ("Pareto optimal", len(result.pareto_designs)),
        ("Recommended", recommended.record.design_id if recommended else "none"),
    )
    card_html = "".join(
        f'<section class="card"><span>{html.escape(str(label))}</span><strong>{html.escape(str(value))}</strong></section>'
        for label, value in cards
    )
    objective_html = "".join(
        f"<li><code>{html.escape(objective.metric)}</code>: {objective.goal}, weight {objective.weight:g}</li>"
        for objective in result.objectives
    )
    table_html = _html_design_table(result.designs[:top], result.objectives)
    pareto_html = _html_design_table(result.pareto_designs, result.objectives)
    chart = _objective_chart(result)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FPGA DSE Report — {html.escape(result.project)}</title>
<style>
:root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
body {{ margin: 0; background: #0b1020; color: #e8edf8; }}
main {{ width: min(1180px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0 72px; }}
h1 {{ font-size: clamp(2rem, 5vw, 4rem); margin: 0 0 8px; letter-spacing: -0.04em; }}
h2 {{ margin-top: 48px; }}
p, li {{ color: #aeb9cf; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 28px 0; }}
.card {{ border: 1px solid #27314d; border-radius: 14px; background: #11182b; padding: 18px; }}
.card span {{ display: block; color: #8e9bb5; font-size: .8rem; text-transform: uppercase; letter-spacing: .08em; }}
.card strong {{ display: block; margin-top: 8px; font-size: 1.45rem; overflow-wrap: anywhere; }}
.table-wrap {{ overflow-x: auto; border: 1px solid #27314d; border-radius: 14px; }}
table {{ border-collapse: collapse; width: 100%; min-width: 760px; background: #11182b; }}
th, td {{ padding: 11px 13px; text-align: left; border-bottom: 1px solid #27314d; font-size: .9rem; }}
th {{ color: #8e9bb5; background: #151e34; position: sticky; top: 0; }}
tr:last-child td {{ border-bottom: 0; }}
.badge {{ border: 1px solid #394665; border-radius: 999px; padding: 3px 8px; font-size: .75rem; }}
.good {{ border-color: #3f8f70; color: #85e0ba; }}
svg {{ width: 100%; height: auto; background: #11182b; border: 1px solid #27314d; border-radius: 14px; }}
code {{ color: #a7c7ff; }}
</style>
</head>
<body><main>
<p>Reproducible design-space exploration</p>
<h1>{html.escape(result.project)}</h1>
<div class="grid">{card_html}</div>
<h2>Objectives</h2><ul>{objective_html}</ul>
{chart}
<h2>Top designs</h2>{table_html}
<h2>Pareto frontier</h2>{pareto_html}
</main></body></html>
"""


def _html_design_table(
    designs: tuple[AnalyzedDesign, ...] | list[AnalyzedDesign],
    objectives: tuple[Objective, ...],
) -> str:
    if not designs:
        return "<p>No designs available.</p>"
    parameter_names = sorted({name for design in designs for name in design.record.parameters})
    headers = ["Design", "Score", "Feasible", "Pareto", *parameter_names, *[item.metric for item in objectives]]
    heading = "".join(f"<th>{html.escape(name)}</th>" for name in headers)
    rows: list[str] = []
    for design in designs:
        values = [
            design.record.design_id,
            "—" if design.score is None else f"{design.score:.4f}",
            "yes" if design.feasible else "no",
            "yes" if design.pareto_optimal else "no",
            *[str(design.record.parameters.get(name, "—")) for name in parameter_names],
            *[str(design.record.metrics.get(objective.metric, "—")) for objective in objectives],
        ]
        cells = "".join(f"<td>{html.escape(value)}</td>" for value in values)
        rows.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{heading}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _objective_chart(result: AnalysisResult) -> str:
    if len(result.objectives) < 2 or not result.feasible_designs:
        return ""
    x_objective, y_objective = result.objectives[:2]
    designs = result.feasible_designs
    x_values = [float(design.record.metrics[x_objective.metric]) for design in designs]
    y_values = [float(design.record.metrics[y_objective.metric]) for design in designs]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)

    def scale(value: float, low: float, high: float, start: float, stop: float) -> float:
        return (start + stop) / 2 if low == high else start + (value - low) * (stop - start) / (high - low)

    points: list[str] = []
    for design in designs:
        x = scale(float(design.record.metrics[x_objective.metric]), x_min, x_max, 65, 735)
        y = scale(float(design.record.metrics[y_objective.metric]), y_min, y_max, 335, 35)
        radius = 6 if design.pareto_optimal else 3.5
        opacity = 1 if design.pareto_optimal else 0.45
        points.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius}" fill="#8fb7ff" opacity="{opacity}">'
            f"<title>{html.escape(design.record.design_id)}</title></circle>"
        )
    return f"""
<h2>Objective map</h2>
<svg viewBox="0 0 800 390" role="img" aria-label="Scatter plot of the first two objectives">
<line x1="65" y1="335" x2="735" y2="335" stroke="#52617f" />
<line x1="65" y1="35" x2="65" y2="335" stroke="#52617f" />
<text x="400" y="375" fill="#aeb9cf" text-anchor="middle">{html.escape(x_objective.metric)}</text>
<text x="18" y="185" fill="#aeb9cf" text-anchor="middle" transform="rotate(-90 18 185)">{html.escape(y_objective.metric)}</text>
{''.join(points)}
</svg>
"""

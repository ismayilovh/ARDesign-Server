#!/usr/bin/env python3
"""Generate the report table and malformed-input notes from the measurement CSV."""
import argparse
import csv
from pathlib import Path


GROUPS = ["OBJ", "STL", "GLB/glTF", "FBX", "CAD"]


def number(row, field):
    try:
        return float(row[field]) if row[field] else None
    except (KeyError, ValueError):
        return None


def fmt_range(values):
    values = [int(value) for value in values if value is not None]
    return f"{min(values):,}–{max(values):,}" if values else "—"


def mean(values):
    values = [value for value in values if value is not None]
    return sum(values) / len(values) if values else None


def fmt(value, digits=1):
    return f"{value:.{digits}f}" if value is not None else "—"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--output", type=Path, default=Path("measurement-summary.md"))
    args = parser.parse_args()
    with args.csv.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    valid = [row for row in rows if row.get("expected_failure", "false").lower() != "true"]
    groups = GROUPS + (["Other"] if any(row.get("group") not in GROUPS for row in valid) else [])
    lines = ["# Converter measurement summary", "",
             "The table excludes inputs marked as expected failures. Fill deviation columns in the CSV after the Blender/trimesh step, then rerun this command to refresh deviation aggregates.", "",
             "| Format group | Test files | Triangle range | Successful conversions | Mean conversion (s) | Mean Draco reduction (%) | Mean / max deviation (mm) |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for group in groups + ["Total"]:
        subset = valid if group == "Total" else [r for r in valid if r.get("group") == group]
        if not subset:
            continue
        success = [r for r in subset if r.get("result", "").startswith("success")]
        marked = "*" if any(r.get("result") == "success with warnings" for r in success) else ""
        max_dev = [number(r, "deviation_max_mm") for r in subset]
        max_dev = [v for v in max_dev if v is not None]
        lines.append("| {} | {} | {} | {}/{}{} | {} | {} | {}/{} |".format(
            group, len(subset), fmt_range(number(r, "triangles") for r in subset),
            len(success), len(subset), marked,
            fmt(mean(number(r, "conversion_seconds") for r in subset)),
            fmt(mean(number(r, "draco_reduction_percent") for r in subset)),
            fmt(mean(number(r, "deviation_mean_mm") for r in subset)),
            fmt(max(max_dev) if max_dev else None)))
    failures = [r for r in rows if r.get("expected_failure", "false").lower() == "true"]
    lines += ["", "## Malformed-input review", ""]
    if failures:
        for row in failures:
            message = row.get("warnings") or row.get("error") or "No warning or error recorded"
            lines.append(f"- **{row.get('file', '(unnamed)')}**: {message}")
    else:
        lines.append("No inputs were marked as expected failures.")
    lines += ["", "## Unit scale check", ""]
    for unit in ("mm", "in"):
        differences = []
        for row in valid:
            if row.get("unit", "").lower() != unit:
                continue
            dimensions = []
            for axis in "xyz":
                source = number(row, f"source_bounds_m_{axis}")
                output = number(row, f"output_bounds_m_{axis}")
                if source not in (None, 0) and output is not None:
                    dimensions.append(abs(output - source) / abs(source) * 100)
            if dimensions:
                differences.append((max(dimensions), row.get("file", "(unnamed)")))
        if differences:
            value, filename = max(differences)
            lines.append(f"- **{unit} inputs:** maximum bounding-box dimension difference {value:.3f}% ({filename}).")
        else:
            lines.append(f"- **{unit} inputs:** source bounds are not yet filled in the CSV.")
    lines += ["", "*Success with warnings is included as success and marked with an asterisk. Record the warning reason alongside the report.*", ""]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8")
    print(args.output.resolve())


if __name__ == "__main__":
    main()

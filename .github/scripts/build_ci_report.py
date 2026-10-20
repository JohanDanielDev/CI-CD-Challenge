#!/usr/bin/env python3
import argparse
import html
import os
from pathlib import Path
import xml.etree.ElementTree as ET


def read_test_report(path: Path) -> tuple[dict[str, int | str], list[dict[str, str]]]:
    if not path.is_file():
        raise FileNotFoundError(f"JUnit test report not found: {path}")

    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
    cases: list[dict[str, str]] = []
    for suite in suites:
        for key in ("tests", "failures", "errors", "skipped"):
            totals[key] += int(suite.get(key, 0))
        totals["time"] += float(suite.get("time", 0))
        for case in suite.findall("testcase"):
            outcome = "passed"
            details = ""
            for child in case:
                if child.tag in {"failure", "error", "skipped"}:
                    outcome = child.tag
                    details = child.get("message", "") or (child.text or "")
                    break
            cases.append(
                {
                    "name": case.get("name", "unnamed"),
                    "classname": case.get("classname", ""),
                    "time": case.get("time", ""),
                    "outcome": outcome,
                    "details": details.strip(),
                }
            )
    return totals, cases


def read_coverage(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise FileNotFoundError(f"Coverage report not found: {path}")

    root = ET.parse(path).getroot()
    lines_valid = int(root.get("lines-valid", 0))
    lines_covered = int(root.get("lines-covered", 0))
    branches_valid = int(root.get("branches-valid", 0))
    branches_covered = int(root.get("branches-covered", 0))
    return {
        "line": f"{100 * lines_covered / lines_valid:.1f}%" if lines_valid else "N/A",
        "line_detail": f"{lines_covered} / {lines_valid} lines",
        "branch": f"{100 * branches_covered / branches_valid:.1f}%"
        if branches_valid
        else "N/A",
        "branch_detail": f"{branches_covered} / {branches_valid} branches",
    }


def read_sonar(path: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    import json

    summary_path = path / "sonar-summary.json"
    issues_path = path / "sonar-issues.json"
    if not summary_path.is_file() or not issues_path.is_file():
        raise FileNotFoundError(f"SonarQube JSON reports not found in {path}")

    summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    issues_data = json.loads(issues_path.read_text(encoding="utf-8"))
    measures = {
        item["metric"]: item.get("value", "N/A")
        for item in summary_data.get("component", {}).get("measures", [])
    }
    summary = {
        "quality_gate": measures.get("alert_status", "N/A"),
        "bugs": measures.get("bugs", "0"),
        "vulnerabilities": measures.get("vulnerabilities", "0"),
        "code_smells": measures.get("code_smells", "0"),
        "coverage": f"{measures['coverage']}%" if "coverage" in measures else "N/A",
        "lines": measures.get("ncloc", "N/A"),
    }
    issues = []
    for issue in issues_data.get("issues", []):
        issues.append(
            {
                "severity": issue.get("severity", "N/A"),
                "type": issue.get("type", "N/A"),
                "file": issue.get("component", "").split(":")[-1],
                "line": str(issue.get("line", "")),
                "message": issue.get("message", ""),
            }
        )
    return summary, issues


def cell(value: object) -> str:
    return html.escape(str(value), quote=True)


def build_page(
    test_totals: dict[str, int | float],
    test_cases: list[dict[str, str]],
    coverage: dict[str, str],
    sonar: dict[str, str],
    issues: list[dict[str, str]],
) -> str:
    repository = os.environ.get("GITHUB_REPOSITORY", "repository")
    ref = os.environ.get("GITHUB_REF_NAME", "unknown")
    commit = os.environ.get("GITHUB_SHA", "unknown")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"https://github.com/{repository}/actions/runs/{run_id}" if run_id else ""
    suite_rows = "".join(
        "<tr>"
        f"<td>{cell(case['outcome'])}</td><td>{cell(case['classname'])}</td>"
        f"<td>{cell(case['name'])}</td><td>{cell(case['time'])}</td>"
        f"<td><details><summary>Details</summary><pre>{cell(case['details'])}</pre></details></td>"
        "</tr>"
        for case in test_cases
    )
    issue_rows = "".join(
        "<tr>"
        f"<td>{cell(issue['severity'])}</td><td>{cell(issue['type'])}</td>"
        f"<td>{cell(issue['file'])}</td><td>{cell(issue['line'])}</td>"
        f"<td>{cell(issue['message'])}</td></tr>"
        for issue in issues
    )
    run_link = f'<a href="{cell(run_url)}">Actions run {cell(run_id)}</a>' if run_url else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Movie app CI report</title>
  <style>
    :root {{ color-scheme: light dark; font: 16px/1.5 system-ui, sans-serif; }}
    body {{ max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }}
    h1, h2 {{ line-height: 1.2; }}
    .meta, .cards {{ display: flex; flex-wrap: wrap; gap: 1rem; }}
    .card {{ border: 1px solid #8886; border-radius: .7rem; padding: 1rem; min-width: 130px; }}
    .value {{ display: block; font-size: 1.6rem; font-weight: 700; }}
    .muted {{ opacity: .75; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ width: 100%; border-collapse: collapse; margin: 1rem 0 2rem; }}
    th, td {{ padding: .55rem; border-bottom: 1px solid #8886; text-align: left; vertical-align: top; }}
    pre {{ white-space: pre-wrap; }}
  </style>
</head>
<body>
  <h1>Movie app CI report</h1>
  <div class="meta muted">
    <span>Branch: {cell(ref)}</span>
    <span>Commit: <code>{cell(commit[:12])}</code></span>
    <span>{run_link}</span>
  </div>
  <h2>Tests and coverage</h2>
  <section class="cards">
    <div class="card"><span class="value">{test_totals['tests']}</span>Tests</div>
    <div class="card"><span class="value">{test_totals['failures']}</span>Failures</div>
    <div class="card"><span class="value">{test_totals['errors']}</span>Errors</div>
    <div class="card"><span class="value">{test_totals['skipped']}</span>Skipped</div>
    <div class="card"><span class="value">{cell(coverage['line'])}</span>{cell(coverage['line_detail'])}</div>
    <div class="card"><span class="value">{cell(coverage['branch'])}</span>{cell(coverage['branch_detail'])}</div>
  </section>
  <h2>SonarQube summary</h2>
  <section class="cards">
    <div class="card"><span class="value">{cell(sonar['quality_gate'])}</span>Quality gate</div>
    <div class="card"><span class="value">{cell(sonar['bugs'])}</span>Bugs</div>
    <div class="card"><span class="value">{cell(sonar['vulnerabilities'])}</span>Vulnerabilities</div>
    <div class="card"><span class="value">{cell(sonar['code_smells'])}</span>Code smells</div>
    <div class="card"><span class="value">{cell(sonar['coverage'])}</span>Coverage</div>
    <div class="card"><span class="value">{cell(sonar['lines'])}</span>Lines of code</div>
  </section>
  <h2>Test cases</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Result</th><th>Suite</th><th>Test</th><th>Seconds</th><th>Details</th></tr></thead>
    <tbody>{suite_rows or '<tr><td colspan="5">No test cases were reported.</td></tr>'}</tbody>
  </table></div>
  <h2>SonarQube issues ({len(issues)})</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>Severity</th><th>Type</th><th>File</th><th>Line</th><th>Message</th></tr></thead>
    <tbody>{issue_rows or '<tr><td colspan="5">No issues found.</td></tr>'}</tbody>
  </table></div>
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a static HTML CI report site.")
    parser.add_argument("--tests", type=Path, required=True, help="JUnit XML report path")
    parser.add_argument("--coverage", type=Path, required=True, help="Coverage XML report path")
    parser.add_argument("--sonar-dir", type=Path, required=True, help="Directory with Sonar JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="Pages site output directory")
    args = parser.parse_args()

    totals, cases = read_test_report(args.tests)
    coverage = read_coverage(args.coverage)
    sonar, issues = read_sonar(args.sonar_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "index.html").write_text(
        build_page(totals, cases, coverage, sonar, issues), encoding="utf-8"
    )
    (args.output_dir / ".nojekyll").touch()


if __name__ == "__main__":
    main()

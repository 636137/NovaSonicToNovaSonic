"""
Test Reporter

Generates detailed reports from test evaluations.
Supports multiple output formats: JSON, HTML, Markdown.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from voice_tester.evaluator import TestEvaluation


class TestReporter:
    """
    Generates test reports in various formats.
    """
    
    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path("reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_report(
        self,
        evaluation: TestEvaluation,
        format: str = "all",
        include_transcript: bool = True,
        include_recording_links: bool = True,
    ) -> Dict[str, str]:
        """
        Generate test report in specified format(s).
        
        Args:
            evaluation: The TestEvaluation result
            format: "json", "html", "markdown", or "all"
            include_transcript: Include full conversation transcript
            include_recording_links: Include links to recordings
        
        Returns:
            Dict mapping format to file path
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = self.output_dir / f"{timestamp}_{evaluation.scenario_name}"
        report_dir.mkdir(parents=True, exist_ok=True)
        
        result = {}
        
        if format in ("json", "all"):
            path = self._generate_json(evaluation, report_dir, include_transcript)
            result["json"] = str(path)
        
        if format in ("html", "all"):
            path = self._generate_html(evaluation, report_dir, include_transcript)
            result["html"] = str(path)
        
        if format in ("markdown", "all"):
            path = self._generate_markdown(evaluation, report_dir, include_transcript)
            result["markdown"] = str(path)
        
        return result
    
    def _generate_json(
        self,
        evaluation: TestEvaluation,
        report_dir: Path,
        include_transcript: bool,
    ) -> Path:
        """Generate JSON report"""
        path = report_dir / "report.json"
        
        data = {
            "test_id": evaluation.test_id,
            "scenario_name": evaluation.scenario_name,
            "verdict": evaluation.verdict,
            "score": round(evaluation.score, 2),
            "generated_at": datetime.now().isoformat(),
            "steps": {
                "total": evaluation.steps_total,
                "completed": evaluation.steps_completed,
                "failed": evaluation.steps_failed,
            },
            "duration_seconds": round(evaluation.duration_seconds, 2),
            "criteria_results": evaluation.criteria_results,
            "assertion_results": evaluation.assertion_results,
            "step_results": [
                {
                    "step_id": s.step_id,
                    "status": s.status,
                    "expected_patterns": s.expected_patterns,
                    "matched_patterns": s.matched_patterns,
                    "error": s.error,
                }
                for s in evaluation.step_results
            ],
            "errors": evaluation.errors,
            "warnings": evaluation.warnings,
            "recommendations": evaluation.recommendations,
        }
        
        if include_transcript:
            data["transcript"] = evaluation.transcript
        
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        
        return path
    
    def _generate_html(
        self,
        evaluation: TestEvaluation,
        report_dir: Path,
        include_transcript: bool,
    ) -> Path:
        """Generate HTML report"""
        path = report_dir / "report.html"
        
        verdict_color = {
            "PASS": "#28a745",
            "PARTIAL": "#ffc107",
            "FAIL": "#dc3545",
        }.get(evaluation.verdict, "#6c757d")
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Voice Test Report - {evaluation.test_id}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .verdict {{
            display: inline-block;
            padding: 8px 16px;
            border-radius: 4px;
            color: white;
            font-weight: bold;
            font-size: 24px;
            background: {verdict_color};
        }}
        .score {{
            font-size: 48px;
            font-weight: bold;
            color: {verdict_color};
        }}
        .section {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .section h2 {{
            margin-top: 0;
            border-bottom: 2px solid #eee;
            padding-bottom: 10px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 10px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
        }}
        .pass {{ color: #28a745; }}
        .fail {{ color: #dc3545; }}
        .conversation {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 4px;
            max-height: 400px;
            overflow-y: auto;
        }}
        .turn {{
            margin-bottom: 10px;
            padding: 8px;
            border-radius: 4px;
        }}
        .turn.system {{
            background: #e3f2fd;
            margin-right: 20%;
        }}
        .turn.ai {{
            background: #f3e5f5;
            margin-left: 20%;
        }}
        .turn .speaker {{
            font-weight: bold;
            font-size: 12px;
            color: #666;
        }}
        .recommendation {{
            background: #fff3cd;
            padding: 10px;
            border-radius: 4px;
            margin-bottom: 10px;
            border-left: 4px solid #ffc107;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Voice Test Report</h1>
        <div>
            <span class="verdict">{evaluation.verdict}</span>
            <span class="score">{evaluation.score:.0f}%</span>
        </div>
        <p><strong>Test ID:</strong> {evaluation.test_id}</p>
        <p><strong>Scenario:</strong> {evaluation.scenario_name}</p>
        <p><strong>Duration:</strong> {evaluation.duration_seconds:.1f} seconds</p>
        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
    
    <div class="section">
        <h2>Summary</h2>
        <table>
            <tr>
                <th>Metric</th>
                <th>Value</th>
            </tr>
            <tr>
                <td>Total Steps</td>
                <td>{evaluation.steps_total}</td>
            </tr>
            <tr>
                <td>Completed Steps</td>
                <td class="pass">{evaluation.steps_completed}</td>
            </tr>
            <tr>
                <td>Failed Steps</td>
                <td class="fail">{evaluation.steps_failed}</td>
            </tr>
        </table>
    </div>
    
    <div class="section">
        <h2>Criteria Results</h2>
        <table>
            <tr>
                <th>Step</th>
                <th>Expected</th>
                <th>Actual</th>
                <th>Result</th>
            </tr>
            {"".join(f'''
            <tr>
                <td>{c.get('step_id', '')}</td>
                <td>{c.get('expected_status', '')}</td>
                <td>{c.get('actual_status', '')}</td>
                <td class="{'pass' if c.get('passed') else 'fail'}">
                    {'✓' if c.get('passed') else '✗'}
                </td>
            </tr>''' for c in evaluation.criteria_results)}
        </table>
    </div>
    
    <div class="section">
        <h2>Assertions</h2>
        <table>
            <tr>
                <th>Type</th>
                <th>Details</th>
                <th>Result</th>
            </tr>
            {"".join(f'''
            <tr>
                <td>{a.get('type', '')}</td>
                <td><code>{json.dumps(a.get('details', {}))[:100]}</code></td>
                <td class="{'pass' if a.get('passed') else 'fail'}">
                    {'✓ PASS' if a.get('passed') else '✗ FAIL'}
                </td>
            </tr>''' for a in evaluation.assertion_results)}
        </table>
    </div>
    
    {f'''
    <div class="section">
        <h2>Recommendations</h2>
        {"".join(f'<div class="recommendation">{r}</div>' for r in evaluation.recommendations) if evaluation.recommendations else '<p>No recommendations.</p>'}
    </div>
    ''' if evaluation.recommendations else ''}
    
    {f'''
    <div class="section">
        <h2>Conversation Transcript</h2>
        <div class="conversation">
            {"".join(f'''
            <div class="turn {'system' if t.get('speaker', '') in ['system', 'bot', 'connect'] else 'ai'}">
                <div class="speaker">{t.get('speaker', 'Unknown').upper()}</div>
                <div>{t.get('text', '')}</div>
            </div>''' for t in evaluation.transcript)}
        </div>
    </div>
    ''' if include_transcript and evaluation.transcript else ''}
</body>
</html>
"""
        
        with open(path, "w") as f:
            f.write(html)
        
        return path
    
    def _generate_markdown(
        self,
        evaluation: TestEvaluation,
        report_dir: Path,
        include_transcript: bool,
    ) -> Path:
        """Generate Markdown report"""
        path = report_dir / "report.md"
        
        md = f"""# Voice Test Report

## Overview

| Field | Value |
|-------|-------|
| **Test ID** | `{evaluation.test_id}` |
| **Scenario** | {evaluation.scenario_name} |
| **Verdict** | **{evaluation.verdict}** |
| **Score** | {evaluation.score:.0f}% |
| **Duration** | {evaluation.duration_seconds:.1f}s |
| **Generated** | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |

## Summary

- **Total Steps:** {evaluation.steps_total}
- **Completed:** {evaluation.steps_completed} ✓
- **Failed:** {evaluation.steps_failed} ✗

## Criteria Results

| Step | Expected | Actual | Result |
|------|----------|--------|--------|
"""
        for c in evaluation.criteria_results:
            result = "✓" if c.get('passed') else "✗"
            md += f"| {c.get('step_id', '')} | {c.get('expected_status', '')} | {c.get('actual_status', '')} | {result} |\n"
        
        md += """
## Assertions

| Type | Passed |
|------|--------|
"""
        for a in evaluation.assertion_results:
            result = "✓" if a.get('passed') else "✗"
            md += f"| {a.get('type', '')} | {result} |\n"
        
        if evaluation.recommendations:
            md += """
## Recommendations

"""
            for r in evaluation.recommendations:
                md += f"- {r}\n"
        
        if include_transcript and evaluation.transcript:
            md += """
## Conversation Transcript

"""
            for t in evaluation.transcript:
                speaker = t.get('speaker', 'unknown').upper()
                text = t.get('text', '')
                md += f"**[{speaker}]**: {text}\n\n"
        
        with open(path, "w") as f:
            f.write(md)
        
        return path


def generate_report(
    evaluation: TestEvaluation,
    output_dir: Path = None,
    format: str = "all",
) -> Dict[str, str]:
    """Convenience function to generate a report"""
    reporter = TestReporter(output_dir)
    return reporter.generate_report(evaluation, format)

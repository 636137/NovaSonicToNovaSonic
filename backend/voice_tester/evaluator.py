"""
Test Evaluator

Evaluates test results against success criteria defined in scenarios.
Generates pass/fail verdicts and detailed analysis.
"""
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of a single test step"""
    step_id: str
    status: str  # completed, failed, skipped
    expected_patterns: List[str] = field(default_factory=list)
    matched_patterns: List[str] = field(default_factory=list)
    transcript_segment: str = ""
    duration_ms: int = 0
    error: Optional[str] = None


@dataclass
class TestEvaluation:
    """Complete test evaluation result"""
    test_id: str
    scenario_name: str
    verdict: str  # PASS, FAIL, PARTIAL
    score: float  # 0-100
    
    steps_total: int = 0
    steps_completed: int = 0
    steps_failed: int = 0
    
    criteria_results: List[Dict] = field(default_factory=list)
    assertion_results: List[Dict] = field(default_factory=list)
    step_results: List[StepResult] = field(default_factory=list)
    
    duration_seconds: float = 0
    transcript: List[Dict] = field(default_factory=list)
    
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class TestEvaluator:
    """
    Evaluates test execution against scenario success criteria.
    """
    
    def __init__(self, scenario: Dict[str, Any]):
        self.scenario = scenario
        self.success_criteria = scenario.get('success_criteria', {})
        self.assertions = scenario.get('assertions', [])
        self.steps = scenario.get('steps', [])
    
    def evaluate(self, test_result: Dict[str, Any]) -> TestEvaluation:
        """
        Evaluate a test result against the scenario criteria.
        
        Args:
            test_result: The test result from DynamoDB containing:
                - test_id
                - conversation: List of conversation turns
                - status
                - started_at
                - ended_at
                - etc.
        
        Returns:
            TestEvaluation with detailed results
        """
        evaluation = TestEvaluation(
            test_id=test_result.get('test_id', ''),
            scenario_name=self.scenario.get('name', 'Unknown'),
            verdict='UNKNOWN',
            score=0.0,
        )
        
        conversation = test_result.get('conversation', [])
        evaluation.transcript = conversation
        
        # Calculate duration
        started = test_result.get('started_at', '')
        ended = test_result.get('ended_at', '')
        if started and ended:
            try:
                start_dt = datetime.fromisoformat(started.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(ended.replace('Z', '+00:00'))
                evaluation.duration_seconds = (end_dt - start_dt).total_seconds()
            except:
                pass
        
        # Build transcript text
        transcript_text = self._build_transcript_text(conversation)
        
        # Evaluate steps
        evaluation.steps_total = len(self.steps)
        step_results = self._evaluate_steps(conversation)
        evaluation.step_results = step_results
        evaluation.steps_completed = sum(1 for s in step_results if s.status == 'completed')
        evaluation.steps_failed = sum(1 for s in step_results if s.status == 'failed')
        
        # Evaluate success criteria
        criteria_results = self._evaluate_criteria(step_results)
        evaluation.criteria_results = criteria_results
        
        # Evaluate assertions
        assertion_results = self._evaluate_assertions(transcript_text, evaluation)
        evaluation.assertion_results = assertion_results
        
        # Calculate final verdict and score
        evaluation.verdict, evaluation.score = self._calculate_verdict(
            criteria_results, 
            assertion_results,
            evaluation
        )
        
        # Generate recommendations
        evaluation.recommendations = self._generate_recommendations(evaluation)
        
        return evaluation
    
    def _build_transcript_text(self, conversation: List[Dict]) -> str:
        """Build a single text string from conversation for pattern matching"""
        parts = []
        for turn in conversation:
            speaker = turn.get('speaker', 'unknown')
            text = turn.get('text', '')
            parts.append(f"[{speaker}]: {text}")
        return "\n".join(parts)
    
    def _evaluate_steps(self, conversation: List[Dict]) -> List[StepResult]:
        """Evaluate each step against the conversation"""
        results = []
        
        conversation_text = " ".join(t.get('text', '') for t in conversation)
        
        for step in self.steps:
            step_id = step.get('id', '')
            action = step.get('action', '')
            expect = step.get('expect', {})
            expected_patterns = expect.get('patterns', [])
            
            result = StepResult(
                step_id=step_id,
                status='unknown',
                expected_patterns=expected_patterns,
            )
            
            if action == 'listen':
                # Check if expected patterns were heard
                for pattern in expected_patterns:
                    try:
                        if re.search(pattern, conversation_text, re.IGNORECASE):
                            result.matched_patterns.append(pattern)
                    except re.error:
                        # Invalid regex, try literal match
                        if pattern.lower() in conversation_text.lower():
                            result.matched_patterns.append(pattern)
                
                if result.matched_patterns:
                    result.status = 'completed'
                else:
                    result.status = 'failed'
                    
            elif action == 'speak':
                # Check if AI spoke (look for ai_spoke entries after this step would have executed)
                ai_turns = [t for t in conversation if t.get('speaker') in ['ai', 'ai_spoke', 'caller']]
                if ai_turns:
                    result.status = 'completed'
                else:
                    result.status = 'failed'
                    
            elif action == 'hangup':
                # Hangup is considered complete if call ended
                result.status = 'completed'
            
            else:
                result.status = 'completed'  # Default to completed for unknown actions
            
            results.append(result)
        
        return results
    
    def _evaluate_criteria(self, step_results: List[StepResult]) -> List[Dict]:
        """Evaluate success criteria"""
        results = []
        
        required = self.success_criteria.get('required', [])
        
        for criterion in required:
            step_id = criterion.get('step', '')
            expected_status = criterion.get('status', 'completed')
            
            # Find matching step result
            matching = next((s for s in step_results if s.step_id == step_id), None)
            
            if matching:
                passed = matching.status == expected_status
            else:
                passed = False
            
            results.append({
                'type': 'required_step',
                'step_id': step_id,
                'expected_status': expected_status,
                'actual_status': matching.status if matching else 'not_found',
                'passed': passed,
            })
        
        return results
    
    def _evaluate_assertions(self, transcript_text: str, evaluation: TestEvaluation) -> List[Dict]:
        """Evaluate assertions"""
        results = []
        
        for assertion in self.assertions:
            assertion_type = assertion.get('type', '')
            passed = False
            details = {}
            
            if assertion_type == 'transcript_contains':
                patterns = assertion.get('patterns', [])
                all_required = assertion.get('all_required', False)
                
                matched = []
                for pattern in patterns:
                    try:
                        if re.search(pattern, transcript_text, re.IGNORECASE):
                            matched.append(pattern)
                    except:
                        if pattern.lower() in transcript_text.lower():
                            matched.append(pattern)
                
                if all_required:
                    passed = len(matched) == len(patterns)
                else:
                    passed = len(matched) > 0
                
                details = {'patterns': patterns, 'matched': matched}
                
            elif assertion_type == 'transcript_excludes':
                patterns = assertion.get('patterns', [])
                
                found = []
                for pattern in patterns:
                    try:
                        if re.search(pattern, transcript_text, re.IGNORECASE):
                            found.append(pattern)
                    except:
                        if pattern.lower() in transcript_text.lower():
                            found.append(pattern)
                
                passed = len(found) == 0
                details = {'patterns': patterns, 'found': found}
                
            elif assertion_type == 'duration':
                min_seconds = assertion.get('min_seconds', 0)
                max_seconds = assertion.get('max_seconds', float('inf'))
                
                duration = evaluation.duration_seconds
                passed = min_seconds <= duration <= max_seconds
                
                details = {
                    'min_seconds': min_seconds,
                    'max_seconds': max_seconds,
                    'actual_seconds': duration,
                }
                
            elif assertion_type == 'steps_completed':
                min_pct = assertion.get('minimum_percentage', 100)
                
                if evaluation.steps_total > 0:
                    actual_pct = (evaluation.steps_completed / evaluation.steps_total) * 100
                else:
                    actual_pct = 0
                
                passed = actual_pct >= min_pct
                details = {'minimum_percentage': min_pct, 'actual_percentage': actual_pct}
            
            results.append({
                'type': assertion_type,
                'passed': passed,
                'details': details,
            })
        
        return results
    
    def _calculate_verdict(
        self, 
        criteria_results: List[Dict],
        assertion_results: List[Dict],
        evaluation: TestEvaluation
    ) -> Tuple[str, float]:
        """Calculate final verdict and score"""
        
        # Count passed/failed
        criteria_passed = sum(1 for c in criteria_results if c.get('passed', False))
        criteria_total = len(criteria_results)
        
        assertion_passed = sum(1 for a in assertion_results if a.get('passed', False))
        assertion_total = len(assertion_results)
        
        # Calculate scores
        criteria_score = (criteria_passed / criteria_total * 100) if criteria_total > 0 else 100
        assertion_score = (assertion_passed / assertion_total * 100) if assertion_total > 0 else 100
        step_score = (evaluation.steps_completed / evaluation.steps_total * 100) if evaluation.steps_total > 0 else 100
        
        # Weighted average
        overall_score = (criteria_score * 0.4 + assertion_score * 0.3 + step_score * 0.3)
        
        # Determine verdict
        if overall_score >= 90 and criteria_passed == criteria_total:
            verdict = 'PASS'
        elif overall_score >= 50:
            verdict = 'PARTIAL'
        else:
            verdict = 'FAIL'
        
        return verdict, overall_score
    
    def _generate_recommendations(self, evaluation: TestEvaluation) -> List[str]:
        """Generate recommendations based on evaluation"""
        recommendations = []
        
        # Check for failed steps
        failed_steps = [s for s in evaluation.step_results if s.status == 'failed']
        if failed_steps:
            step_ids = [s.step_id for s in failed_steps[:3]]
            recommendations.append(
                f"Review failed steps: {', '.join(step_ids)}. "
                "Check if expected patterns are correct or if the bot flow changed."
            )
        
        # Check for duration issues
        for assertion in evaluation.assertion_results:
            if assertion['type'] == 'duration' and not assertion['passed']:
                details = assertion['details']
                actual = details.get('actual_seconds', 0)
                min_s = details.get('min_seconds', 0)
                max_s = details.get('max_seconds', float('inf'))
                
                if actual < min_s:
                    recommendations.append(
                        f"Call duration ({actual:.1f}s) was shorter than expected ({min_s}s). "
                        "The call may have ended prematurely."
                    )
                elif actual > max_s:
                    recommendations.append(
                        f"Call duration ({actual:.1f}s) exceeded maximum ({max_s}s). "
                        "There may be issues with the conversation flow."
                    )
        
        # Check for excluded patterns that were found
        for assertion in evaluation.assertion_results:
            if assertion['type'] == 'transcript_excludes' and not assertion['passed']:
                found = assertion['details'].get('found', [])
                if found:
                    recommendations.append(
                        f"Detected error indicators: {', '.join(found)}. "
                        "The bot may have encountered errors during the test."
                    )
        
        return recommendations


def evaluate_test(scenario: Dict[str, Any], test_result: Dict[str, Any]) -> TestEvaluation:
    """Convenience function to evaluate a test"""
    evaluator = TestEvaluator(scenario)
    return evaluator.evaluate(test_result)

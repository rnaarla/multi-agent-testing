"""
Behavioral assertion engine for multi-agent test graphs.

Supports:
- Equality and range assertions
- Pattern matching (regex, JSON path)
- Semantic similarity checks
- Negotiation convergence metrics
- Memory precision and recall
- Custom assertion plugins
"""

import re
import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import UTC, datetime


class AssertionType(Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES_REGEX = "matches_regex"
    JSON_PATH = "json_path"
    RANGE = "range"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    SEMANTIC_SIMILARITY = "semantic_similarity"
    CONVERGENCE = "convergence"
    MEMORY_RECALL = "memory_recall"
    SCHEMA_VALID = "schema_valid"
    LATENCY_UNDER = "latency_under"
    COST_UNDER = "cost_under"
    CUSTOM = "custom"


@dataclass
class AssertionResult:
    """Result of evaluating a single assertion."""
    assertion_id: str
    assertion_type: str
    target_node: str
    expected: Any
    actual: Any
    passed: bool
    message: str
    evaluated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Ensure serializable
        if not isinstance(self.expected, (str, int, float, bool, list, dict, type(None))):
            self.expected = str(self.expected)
        if not isinstance(self.actual, (str, int, float, bool, list, dict, type(None))):
            self.actual = str(self.actual)


class AssertionEngine:
    """
    Engine for evaluating behavioral assertions on agent outputs.
    
    Supports built-in assertion types and custom plugins.
    """
    
    def __init__(self):
        self.custom_assertions: Dict[str, Callable] = {}
        self._register_builtin_assertions()
    
    def _register_builtin_assertions(self):
        """Register built-in assertion handlers."""
        self._handlers = {
            AssertionType.EQUALS: self._assert_equals,
            AssertionType.NOT_EQUALS: self._assert_not_equals,
            AssertionType.CONTAINS: self._assert_contains,
            AssertionType.NOT_CONTAINS: self._assert_not_contains,
            AssertionType.MATCHES_REGEX: self._assert_regex,
            AssertionType.JSON_PATH: self._assert_json_path,
            AssertionType.RANGE: self._assert_range,
            AssertionType.GREATER_THAN: self._assert_greater_than,
            AssertionType.LESS_THAN: self._assert_less_than,
            AssertionType.LATENCY_UNDER: self._assert_latency_under,
            AssertionType.COST_UNDER: self._assert_cost_under,
            AssertionType.SCHEMA_VALID: self._assert_schema_valid,
            AssertionType.SEMANTIC_SIMILARITY: self._assert_semantic_similarity,
            AssertionType.CONVERGENCE: self._assert_convergence,
            AssertionType.MEMORY_RECALL: self._assert_memory_recall,
        }
    
    def register_custom(self, name: str, handler: Callable):
        """Register a custom assertion handler."""
        self.custom_assertions[name] = handler
    
    def _get_value(self, path: str, context: Dict[str, Any]) -> Any:
        """Extract value from context using dot notation path."""
        parts = path.split(".")
        value = context
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            elif isinstance(value, list) and part.isdigit():
                value = value[int(part)]
            else:
                return None
        
        return value
    
    def _assert_equals(
        self, 
        expected: Any, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check exact equality."""
        passed = actual == expected
        message = f"Expected {expected}, got {actual}"
        return passed, message
    
    def _assert_not_equals(
        self, 
        expected: Any, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check inequality."""
        passed = actual != expected
        message = f"Expected not equal to {expected}, got {actual}"
        return passed, message
    
    def _assert_contains(
        self, 
        expected: Any, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check if actual contains expected."""
        if isinstance(actual, str):
            passed = str(expected) in actual
        elif isinstance(actual, (list, dict)):
            passed = expected in actual
        else:
            passed = False
        message = f"Expected to contain '{expected}'"
        return passed, message
    
    def _assert_not_contains(
        self, 
        expected: Any, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check if actual does not contain expected."""
        if isinstance(actual, str):
            passed = str(expected) not in actual
        elif isinstance(actual, (list, dict)):
            passed = expected not in actual
        else:
            passed = True
        message = f"Expected not to contain '{expected}'"
        return passed, message
    
    def _assert_regex(
        self, 
        expected: str, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check regex pattern match."""
        if not isinstance(actual, str):
            actual = str(actual)
        pattern = re.compile(expected)
        passed = bool(pattern.search(actual))
        message = f"Expected to match pattern '{expected}'"
        return passed, message
    
    def _assert_json_path(
        self, 
        expected: Any, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check value at JSON path."""
        json_path = config.get("json_path", "")
        
        try:
            if isinstance(actual, str):
                actual = json.loads(actual)
            
            value = self._get_value(json_path, actual)
            passed = value == expected
            message = f"At path '{json_path}': expected {expected}, got {value}"
        except (json.JSONDecodeError, KeyError) as e:
            passed = False
            message = f"JSON path evaluation failed: {e}"
        
        return passed, message
    
    def _assert_range(
        self, 
        expected: Dict, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check if value is within range."""
        try:
            value = float(actual)
            min_val = expected.get("min", float("-inf"))
            max_val = expected.get("max", float("inf"))
            passed = min_val <= value <= max_val
            message = f"Expected {value} in range [{min_val}, {max_val}]"
        except (TypeError, ValueError):
            passed = False
            message = f"Cannot compare non-numeric value: {actual}"
        
        return passed, message
    
    def _assert_greater_than(
        self, 
        expected: Any, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check if actual > expected."""
        try:
            passed = float(actual) > float(expected)
            message = f"Expected {actual} > {expected}"
        except (TypeError, ValueError):
            passed = False
            message = f"Cannot compare values: {actual}, {expected}"
        
        return passed, message
    
    def _assert_less_than(
        self, 
        expected: Any, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check if actual < expected."""
        try:
            passed = float(actual) < float(expected)
            message = f"Expected {actual} < {expected}"
        except (TypeError, ValueError):
            passed = False
            message = f"Cannot compare values: {actual}, {expected}"
        
        return passed, message
    
    def _assert_latency_under(
        self, 
        expected: float, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check if latency is under threshold."""
        # actual should be latency_ms from agent output
        try:
            passed = float(actual) < float(expected)
            message = f"Latency {actual}ms (threshold: {expected}ms)"
        except (TypeError, ValueError):
            passed = False
            message = f"Invalid latency value: {actual}"
        
        return passed, message
    
    def _assert_cost_under(
        self, 
        expected: float, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check if cost is under threshold."""
        try:
            passed = float(actual) < float(expected)
            message = f"Cost ${actual} (threshold: ${expected})"
        except (TypeError, ValueError):
            passed = False
            message = f"Invalid cost value: {actual}"
        
        return passed, message
    
    def _assert_schema_valid(
        self, 
        expected: Dict, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Validate against JSON schema."""
        try:
            import jsonschema
            jsonschema.validate(actual, expected)
            passed = True
            message = "Schema validation passed"
        except ImportError:
            passed = False
            message = "jsonschema package not installed"
        except jsonschema.ValidationError as e:
            passed = False
            message = f"Schema validation failed: {e.message}"
        
        return passed, message
    
    def _assert_semantic_similarity(
        self, 
        expected: str, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check semantic similarity (placeholder for embedding-based comparison)."""
        threshold = config.get("threshold", 0.8)
        
        # Placeholder: simple word overlap for now
        # In production, use embeddings (sentence-transformers, OpenAI embeddings)
        if not isinstance(actual, str):
            actual = str(actual)
        
        expected_words = set(expected.lower().split())
        actual_words = set(actual.lower().split())
        
        if not expected_words:
            similarity = 0.0
        else:
            overlap = len(expected_words & actual_words)
            similarity = overlap / len(expected_words)
        
        passed = similarity >= threshold
        message = f"Semantic similarity: {similarity:.2f} (threshold: {threshold})"
        
        return passed, message
    
    def _assert_convergence(
        self, 
        expected: Dict, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check negotiation convergence between agents."""
        # Expected format: {"rounds": N, "threshold": T}
        max_rounds = expected.get("rounds", 10)
        threshold = expected.get("threshold", 0.1)
        
        # actual should be a list of negotiation values
        if not isinstance(actual, list) or len(actual) < 2:
            return False, "Convergence requires list of negotiation values"
        
        # Check if values converge within max_rounds
        values = [float(v) for v in actual[:max_rounds]]
        
        if len(values) >= 2:
            final_diff = abs(values[-1] - values[-2])
            passed = final_diff <= threshold
            message = f"Convergence diff: {final_diff:.4f} (threshold: {threshold})"
        else:
            passed = False
            message = "Insufficient data for convergence check"
        
        return passed, message
    
    def _assert_memory_recall(
        self, 
        expected: List, 
        actual: Any, 
        config: Dict
    ) -> tuple[bool, str]:
        """Check memory recall precision/recall metrics."""
        threshold = config.get("threshold", 0.8)
        
        if not isinstance(actual, list):
            actual = [actual]
        
        expected_set = set(str(e) for e in expected)
        actual_set = set(str(a) for a in actual)
        
        # Calculate recall
        if not expected_set:
            recall = 1.0
        else:
            recall = len(expected_set & actual_set) / len(expected_set)
        
        passed = recall >= threshold
        message = f"Memory recall: {recall:.2f} (threshold: {threshold})"
        
        return passed, message
    
    def evaluate(
        self,
        assertions: List[Dict[str, Any]],
        context: Dict[str, Any],
        agent_outputs: List[Any]
    ) -> List[AssertionResult]:
        """
        Evaluate all assertions against execution context.
        
        Args:
            assertions: List of assertion definitions
            context: Execution context with node outputs
            agent_outputs: List of AgentOutput objects
            
        Returns:
            List of AssertionResult objects
        """
        results = []
        
        # Build output index for quick lookup
        output_map = {o.node_id: o for o in agent_outputs}
        
        for i, assertion in enumerate(assertions):
            assertion_id = assertion.get("id", f"assertion_{i}")
            assertion_type = assertion.get("type", "equals")
            target_node = assertion.get("target", "")
            field = assertion.get("field", "response")
            expected = assertion.get("expected")
            config = assertion.get("config", {})
            
            # Get actual value
            if target_node in context:
                node_output = context[target_node]
                actual = node_output.get(field) if isinstance(node_output, dict) else node_output
            elif target_node in output_map:
                # Check agent output metadata
                agent_out = output_map[target_node]
                if field == "latency_ms":
                    actual = agent_out.latency_ms
                elif field == "cost_usd":
                    actual = agent_out.cost_usd
                else:
                    actual = agent_out.output_data.get(field)
            else:
                actual = None
            
            # Evaluate assertion
            try:
                atype = AssertionType(assertion_type)
                if atype in self._handlers:
                    passed, message = self._handlers[atype](expected, actual, config)
                elif assertion_type in self.custom_assertions:
                    passed, message = self.custom_assertions[assertion_type](
                        expected, actual, config
                    )
                else:
                    passed = False
                    message = f"Unknown assertion type: {assertion_type}"
            except Exception as e:
                passed = False
                message = f"Assertion error: {str(e)}"
            
            results.append(AssertionResult(
                assertion_id=assertion_id,
                assertion_type=assertion_type,
                target_node=target_node,
                expected=expected,
                actual=actual,
                passed=passed,
                message=message,
                metadata={"field": field, "config": config}
            ))
        
        return results

"""
Contract validation system for agent-to-agent communication.

Supports:
- Input/output schema validation
- Type checking
- Required field enforcement
- Value constraints
- Custom validators
"""

import json
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class ContractType(Enum):
    SCHEMA = "schema"
    REQUIRED_FIELDS = "required_fields"
    TYPE_CHECK = "type_check"
    VALUE_CONSTRAINT = "value_constraint"
    CUSTOM = "custom"


@dataclass
class ContractViolation:
    """Record of a contract violation."""
    contract_id: str
    contract_type: str
    source_node: Optional[str]
    target_node: Optional[str]
    field: str
    expected: Any
    actual: Any
    message: str
    severity: str = "error"  # error, warning, info
    detected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self):
        # Ensure serializable
        if not isinstance(self.expected, (str, int, float, bool, list, dict, type(None))):
            self.expected = str(self.expected)
        if not isinstance(self.actual, (str, int, float, bool, list, dict, type(None))):
            self.actual = str(self.actual)


class ContractValidator:
    """
    Validates contracts between agent nodes.
    
    Contracts define the expected interface between nodes:
    - What data format is expected
    - Required fields
    - Type constraints
    - Value constraints
    """
    
    def __init__(self):
        self.custom_validators: Dict[str, Callable] = {}
    
    def register_custom(self, name: str, validator: Callable):
        """Register a custom contract validator."""
        self.custom_validators[name] = validator
    
    def _validate_schema(
        self,
        contract: Dict[str, Any],
        data: Dict[str, Any]
    ) -> List[ContractViolation]:
        """Validate data against JSON schema."""
        violations = []
        schema = contract.get("schema", {})
        contract_id = contract.get("id", "unknown")
        
        try:
            import jsonschema
            jsonschema.validate(data, schema)
        except ImportError:
            violations.append(ContractViolation(
                contract_id=contract_id,
                contract_type="schema",
                source_node=contract.get("source"),
                target_node=contract.get("target"),
                field="*",
                expected="jsonschema package",
                actual="not installed",
                message="jsonschema package required for schema validation",
                severity="warning"
            ))
        except jsonschema.ValidationError as e:
            violations.append(ContractViolation(
                contract_id=contract_id,
                contract_type="schema",
                source_node=contract.get("source"),
                target_node=contract.get("target"),
                field=".".join(str(p) for p in e.absolute_path),
                expected=str(e.schema),
                actual=str(e.instance),
                message=e.message,
                severity="error"
            ))
        
        return violations
    
    def _validate_required_fields(
        self,
        contract: Dict[str, Any],
        data: Dict[str, Any]
    ) -> List[ContractViolation]:
        """Check for required fields."""
        violations = []
        required = contract.get("required_fields", [])
        contract_id = contract.get("id", "unknown")
        
        if not isinstance(data, dict):
            violations.append(ContractViolation(
                contract_id=contract_id,
                contract_type="required_fields",
                source_node=contract.get("source"),
                target_node=contract.get("target"),
                field="*",
                expected="dict",
                actual=type(data).__name__,
                message="Data must be a dictionary for field validation",
                severity="error"
            ))
            return violations
        
        for field_name in required:
            if field_name not in data:
                violations.append(ContractViolation(
                    contract_id=contract_id,
                    contract_type="required_fields",
                    source_node=contract.get("source"),
                    target_node=contract.get("target"),
                    field=field_name,
                    expected="present",
                    actual="missing",
                    message=f"Required field '{field_name}' is missing",
                    severity="error"
                ))
        
        return violations
    
    def _validate_types(
        self,
        contract: Dict[str, Any],
        data: Dict[str, Any]
    ) -> List[ContractViolation]:
        """Validate field types."""
        violations = []
        type_spec = contract.get("types", {})
        contract_id = contract.get("id", "unknown")
        
        type_mapping = {
            "string": str,
            "str": str,
            "integer": int,
            "int": int,
            "float": float,
            "number": (int, float),
            "boolean": bool,
            "bool": bool,
            "list": list,
            "array": list,
            "dict": dict,
            "object": dict,
            "null": type(None),
            "none": type(None),
        }
        
        if not isinstance(data, dict):
            return violations
        
        for field_name, expected_type in type_spec.items():
            if field_name not in data:
                continue
            
            actual_value = data[field_name]
            expected_python_type = type_mapping.get(expected_type.lower())
            
            if expected_python_type is None:
                continue
            
            if not isinstance(actual_value, expected_python_type):
                violations.append(ContractViolation(
                    contract_id=contract_id,
                    contract_type="type_check",
                    source_node=contract.get("source"),
                    target_node=contract.get("target"),
                    field=field_name,
                    expected=expected_type,
                    actual=type(actual_value).__name__,
                    message=f"Field '{field_name}' expected type {expected_type}, got {type(actual_value).__name__}",
                    severity="error"
                ))
        
        return violations
    
    def _validate_constraints(
        self,
        contract: Dict[str, Any],
        data: Dict[str, Any]
    ) -> List[ContractViolation]:
        """Validate value constraints."""
        violations = []
        constraints = contract.get("constraints", {})
        contract_id = contract.get("id", "unknown")
        
        if not isinstance(data, dict):
            return violations
        
        for field_name, constraint in constraints.items():
            if field_name not in data:
                continue
            
            value = data[field_name]
            
            # Min/max for numeric values
            if isinstance(value, (int, float)):
                if "min" in constraint and value < constraint["min"]:
                    violations.append(ContractViolation(
                        contract_id=contract_id,
                        contract_type="value_constraint",
                        source_node=contract.get("source"),
                        target_node=contract.get("target"),
                        field=field_name,
                        expected=f">= {constraint['min']}",
                        actual=str(value),
                        message=f"Field '{field_name}' value {value} is below minimum {constraint['min']}",
                        severity="error"
                    ))
                
                if "max" in constraint and value > constraint["max"]:
                    violations.append(ContractViolation(
                        contract_id=contract_id,
                        contract_type="value_constraint",
                        source_node=contract.get("source"),
                        target_node=contract.get("target"),
                        field=field_name,
                        expected=f"<= {constraint['max']}",
                        actual=str(value),
                        message=f"Field '{field_name}' value {value} exceeds maximum {constraint['max']}",
                        severity="error"
                    ))
            
            # Length constraints for strings/lists
            if isinstance(value, (str, list)):
                if "min_length" in constraint and len(value) < constraint["min_length"]:
                    violations.append(ContractViolation(
                        contract_id=contract_id,
                        contract_type="value_constraint",
                        source_node=contract.get("source"),
                        target_node=contract.get("target"),
                        field=field_name,
                        expected=f"length >= {constraint['min_length']}",
                        actual=str(len(value)),
                        message=f"Field '{field_name}' length {len(value)} is below minimum {constraint['min_length']}",
                        severity="error"
                    ))
                
                if "max_length" in constraint and len(value) > constraint["max_length"]:
                    violations.append(ContractViolation(
                        contract_id=contract_id,
                        contract_type="value_constraint",
                        source_node=contract.get("source"),
                        target_node=contract.get("target"),
                        field=field_name,
                        expected=f"length <= {constraint['max_length']}",
                        actual=str(len(value)),
                        message=f"Field '{field_name}' length {len(value)} exceeds maximum {constraint['max_length']}",
                        severity="error"
                    ))
            
            # Enum constraint
            if "enum" in constraint and value not in constraint["enum"]:
                violations.append(ContractViolation(
                    contract_id=contract_id,
                    contract_type="value_constraint",
                    source_node=contract.get("source"),
                    target_node=contract.get("target"),
                    field=field_name,
                    expected=f"one of {constraint['enum']}",
                    actual=str(value),
                    message=f"Field '{field_name}' value '{value}' not in allowed values",
                    severity="error"
                ))
            
            # Pattern constraint for strings
            if "pattern" in constraint and isinstance(value, str):
                import re
                if not re.match(constraint["pattern"], value):
                    violations.append(ContractViolation(
                        contract_id=contract_id,
                        contract_type="value_constraint",
                        source_node=contract.get("source"),
                        target_node=contract.get("target"),
                        field=field_name,
                        expected=f"matches pattern {constraint['pattern']}",
                        actual=str(value),
                        message=f"Field '{field_name}' does not match pattern '{constraint['pattern']}'",
                        severity="error"
                    ))
        
        return violations
    
    def validate_input(
        self,
        contract: Dict[str, Any],
        context: Dict[str, Any]
    ) -> List[ContractViolation]:
        """
        Validate input data against contract before node execution.
        
        Args:
            contract: Contract definition
            context: Execution context with predecessor outputs
            
        Returns:
            List of violations (empty if valid)
        """
        violations = []
        
        # Get input data from context based on contract spec
        input_sources = contract.get("input_sources", [])
        data = {}
        for source in input_sources:
            if source in context:
                data.update(context[source] if isinstance(context[source], dict) else {"value": context[source]})
        
        # Run validations
        if contract.get("schema"):
            violations.extend(self._validate_schema(contract, data))
        
        if contract.get("required_fields"):
            violations.extend(self._validate_required_fields(contract, data))
        
        if contract.get("types"):
            violations.extend(self._validate_types(contract, data))
        
        if contract.get("constraints"):
            violations.extend(self._validate_constraints(contract, data))
        
        return violations
    
    def validate_output(
        self,
        contract: Dict[str, Any],
        output_data: Dict[str, Any]
    ) -> List[ContractViolation]:
        """
        Validate output data against contract after node execution.
        
        Args:
            contract: Contract definition
            output_data: Node output to validate
            
        Returns:
            List of violations (empty if valid)
        """
        violations = []
        
        # Run validations
        if contract.get("schema"):
            violations.extend(self._validate_schema(contract, output_data))
        
        if contract.get("required_fields"):
            violations.extend(self._validate_required_fields(contract, output_data))
        
        if contract.get("types"):
            violations.extend(self._validate_types(contract, output_data))
        
        if contract.get("constraints"):
            violations.extend(self._validate_constraints(contract, output_data))
        
        return violations

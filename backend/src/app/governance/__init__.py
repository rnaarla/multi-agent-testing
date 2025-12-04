"""
Governance and Safety Controls.

Provides:
- PII detection and redaction
- Policy-based content filtering
- Safety scoring
- Compliance tracking
"""

import re
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import hashlib


# ============================================================================
# Detection Patterns
# ============================================================================

class PIIType(Enum):
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    API_KEY = "api_key"
    PASSWORD = "password"
    NAME = "name"
    ADDRESS = "address"
    DATE_OF_BIRTH = "date_of_birth"


# Regex patterns for PII detection
PII_PATTERNS = {
    PIIType.EMAIL: r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    PIIType.PHONE: r'\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b',
    PIIType.SSN: r'\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b',
    PIIType.CREDIT_CARD: r'\b(?:\d{4}[-\s]?){3}\d{4}\b',
    PIIType.IP_ADDRESS: r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
    PIIType.API_KEY: r'\b(?:sk-|api[_-]?key[_-]?|secret[_-]?)[a-zA-Z0-9]{20,}\b',
    PIIType.PASSWORD: r'(?i)(?:password|passwd|pwd)\s*[:=]\s*[^\s]+',
}


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PIIDetection:
    """Record of detected PII."""
    pii_type: PIIType
    value: str
    masked_value: str
    position: Tuple[int, int]
    context: str
    confidence: float = 1.0


@dataclass
class PolicyViolation:
    """Record of a policy violation."""
    policy_id: str
    policy_name: str
    violation_type: str
    content: str
    context: str
    severity: str  # low, medium, high, critical
    recommendation: str


@dataclass
class SafetyScore:
    """Safety assessment score."""
    overall_score: float  # 0-1, higher is safer
    pii_score: float
    policy_score: float
    toxicity_score: float
    detections: List[PIIDetection] = field(default_factory=list)
    violations: List[PolicyViolation] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# PII Detection and Redaction
# ============================================================================

class PIIDetector:
    """
    Detects and redacts personally identifiable information.
    """
    
    def __init__(self, patterns: Optional[Dict[PIIType, str]] = None):
        self.patterns = patterns or PII_PATTERNS
        self._compiled = {
            pii_type: re.compile(pattern, re.IGNORECASE)
            for pii_type, pattern in self.patterns.items()
        }
    
    def detect(self, text: str) -> List[PIIDetection]:
        """Detect all PII in text."""
        detections = []
        
        for pii_type, pattern in self._compiled.items():
            for match in pattern.finditer(text):
                value = match.group()
                start, end = match.span()
                
                # Get context (surrounding text)
                context_start = max(0, start - 20)
                context_end = min(len(text), end + 20)
                context = text[context_start:context_end]
                
                detections.append(PIIDetection(
                    pii_type=pii_type,
                    value=value,
                    masked_value=self._mask_value(value, pii_type),
                    position=(start, end),
                    context=context
                ))
        
        return detections
    
    def _mask_value(self, value: str, pii_type: PIIType) -> str:
        """Mask a PII value for safe display."""
        if pii_type == PIIType.EMAIL:
            parts = value.split("@")
            if len(parts) == 2:
                return f"{parts[0][:2]}***@{parts[1]}"
            return "***@***"
        
        elif pii_type == PIIType.PHONE:
            return re.sub(r'\d', '*', value)[:-4] + value[-4:]
        
        elif pii_type == PIIType.SSN:
            return "***-**-" + value[-4:]
        
        elif pii_type == PIIType.CREDIT_CARD:
            return "**** **** **** " + value[-4:]
        
        elif pii_type == PIIType.API_KEY:
            return value[:4] + "*" * (len(value) - 8) + value[-4:]
        
        else:
            return "*" * len(value)
    
    def redact(self, text: str, replacement: str = "[REDACTED]") -> Tuple[str, List[PIIDetection]]:
        """Redact all PII from text."""
        detections = self.detect(text)
        
        # Sort by position (reverse) to avoid offset issues
        detections.sort(key=lambda d: d.position[0], reverse=True)
        
        redacted = text
        for detection in detections:
            start, end = detection.position
            redacted = redacted[:start] + replacement + redacted[end:]
        
        return redacted, detections
    
    def hash_pii(self, text: str) -> str:
        """Create a hash of detected PII for tracking without storing raw values."""
        detections = self.detect(text)
        if not detections:
            return ""
        
        pii_values = sorted([d.value for d in detections])
        combined = "|".join(pii_values)
        return hashlib.sha256(combined.encode()).hexdigest()


# ============================================================================
# Policy Engine
# ============================================================================

@dataclass
class PolicyRule:
    """A single policy rule."""
    id: str
    name: str
    description: str
    pattern: Optional[str] = None
    keywords: Optional[List[str]] = None
    severity: str = "medium"
    enabled: bool = True


class PolicyEngine:
    """
    Rule-based policy enforcement engine.
    """
    
    DEFAULT_RULES = [
        PolicyRule(
            id="harmful_content",
            name="Harmful Content Detection",
            description="Detects potentially harmful or dangerous content",
            keywords=["kill", "attack", "bomb", "weapon", "hack", "exploit"],
            severity="high"
        ),
        PolicyRule(
            id="profanity",
            name="Profanity Filter",
            description="Detects profane language",
            keywords=["damn", "hell"],  # Simplified list
            severity="low"
        ),
        PolicyRule(
            id="prompt_injection",
            name="Prompt Injection Detection",
            description="Detects potential prompt injection attempts",
            pattern=r'(?i)(ignore|disregard|forget)\s+(previous|above|all)\s+(instructions?|rules?|prompts?)',
            severity="critical"
        ),
        PolicyRule(
            id="jailbreak",
            name="Jailbreak Attempt Detection",
            description="Detects jailbreak attempts",
            pattern=r'(?i)(pretend|act|roleplay|imagine)\s+(you\s+are|as|to\s+be)\s+(an?\s+)?(evil|bad|unrestricted|unfiltered)',
            severity="critical"
        ),
        PolicyRule(
            id="code_injection",
            name="Code Injection Detection",
            description="Detects potential code injection in responses",
            pattern=r'<script|javascript:|eval\(|exec\(|os\.system|subprocess\.',
            severity="high"
        ),
    ]
    
    def __init__(self, rules: Optional[List[PolicyRule]] = None):
        self.rules = rules or self.DEFAULT_RULES
        self._compiled_patterns = {}
        
        for rule in self.rules:
            if rule.pattern:
                self._compiled_patterns[rule.id] = re.compile(rule.pattern)
    
    def add_rule(self, rule: PolicyRule):
        """Add a new policy rule."""
        self.rules.append(rule)
        if rule.pattern:
            self._compiled_patterns[rule.id] = re.compile(rule.pattern)
    
    def check(self, text: str) -> List[PolicyViolation]:
        """Check text against all enabled policies."""
        violations = []
        
        for rule in self.rules:
            if not rule.enabled:
                continue
            
            # Check pattern-based rules
            if rule.pattern and rule.id in self._compiled_patterns:
                pattern = self._compiled_patterns[rule.id]
                matches = pattern.findall(text)
                
                for match in matches:
                    match_str = match if isinstance(match, str) else " ".join(match)
                    violations.append(PolicyViolation(
                        policy_id=rule.id,
                        policy_name=rule.name,
                        violation_type="pattern_match",
                        content=match_str,
                        context=text[:100] + "..." if len(text) > 100 else text,
                        severity=rule.severity,
                        recommendation=f"Review content for {rule.description}"
                    ))
            
            # Check keyword-based rules
            if rule.keywords:
                text_lower = text.lower()
                for keyword in rule.keywords:
                    if keyword.lower() in text_lower:
                        violations.append(PolicyViolation(
                            policy_id=rule.id,
                            policy_name=rule.name,
                            violation_type="keyword_match",
                            content=keyword,
                            context=text[:100] + "..." if len(text) > 100 else text,
                            severity=rule.severity,
                            recommendation=f"Content contains flagged keyword: {keyword}"
                        ))
        
        return violations


# ============================================================================
# Safety Scorer
# ============================================================================

class SafetyScorer:
    """
    Comprehensive safety assessment for agent outputs.
    """
    
    def __init__(
        self,
        pii_detector: Optional[PIIDetector] = None,
        policy_engine: Optional[PolicyEngine] = None
    ):
        self.pii_detector = pii_detector or PIIDetector()
        self.policy_engine = policy_engine or PolicyEngine()
    
    def score(self, text: str) -> SafetyScore:
        """Generate comprehensive safety score for text."""
        # Detect PII
        pii_detections = self.pii_detector.detect(text)
        
        # Check policies
        policy_violations = self.policy_engine.check(text)
        
        # Calculate scores
        pii_score = self._calculate_pii_score(pii_detections)
        policy_score = self._calculate_policy_score(policy_violations)
        toxicity_score = self._estimate_toxicity(text)
        
        # Overall score (weighted average)
        overall_score = (
            pii_score * 0.3 +
            policy_score * 0.4 +
            toxicity_score * 0.3
        )
        
        return SafetyScore(
            overall_score=overall_score,
            pii_score=pii_score,
            policy_score=policy_score,
            toxicity_score=toxicity_score,
            detections=pii_detections,
            violations=policy_violations,
            metadata={
                "text_length": len(text),
                "pii_count": len(pii_detections),
                "violation_count": len(policy_violations)
            }
        )
    
    def _calculate_pii_score(self, detections: List[PIIDetection]) -> float:
        """Calculate PII safety score (1 = no PII, 0 = many PII)."""
        if not detections:
            return 1.0
        
        # Weight by PII type severity
        severity_weights = {
            PIIType.SSN: 1.0,
            PIIType.CREDIT_CARD: 1.0,
            PIIType.API_KEY: 0.9,
            PIIType.PASSWORD: 0.9,
            PIIType.PHONE: 0.5,
            PIIType.EMAIL: 0.4,
            PIIType.IP_ADDRESS: 0.3,
            PIIType.NAME: 0.2,
            PIIType.ADDRESS: 0.4,
            PIIType.DATE_OF_BIRTH: 0.3,
        }
        
        total_weight = sum(
            severity_weights.get(d.pii_type, 0.5)
            for d in detections
        )
        
        # Decay function: more PII = lower score
        return max(0, 1 - (total_weight * 0.2))
    
    def _calculate_policy_score(self, violations: List[PolicyViolation]) -> float:
        """Calculate policy compliance score (1 = compliant, 0 = many violations)."""
        if not violations:
            return 1.0
        
        severity_weights = {
            "low": 0.1,
            "medium": 0.3,
            "high": 0.5,
            "critical": 1.0
        }
        
        total_weight = sum(
            severity_weights.get(v.severity, 0.3)
            for v in violations
        )
        
        return max(0, 1 - (total_weight * 0.25))
    
    def _estimate_toxicity(self, text: str) -> float:
        """
        Estimate toxicity score (1 = not toxic, 0 = very toxic).
        
        Note: In production, use a proper toxicity model like Perspective API
        or a fine-tuned classifier.
        """
        # Simple heuristic for demo purposes
        toxic_indicators = [
            r'\b(hate|stupid|idiot|dumb)\b',
            r'[A-Z]{5,}',  # Excessive caps
            r'!{3,}',  # Excessive exclamation
        ]
        
        toxicity_count = 0
        for pattern in toxic_indicators:
            toxicity_count += len(re.findall(pattern, text, re.IGNORECASE))
        
        # Normalize
        return max(0, 1 - (toxicity_count * 0.1))


# ============================================================================
# Governance Middleware
# ============================================================================

class GovernanceMiddleware:
    """
    Middleware for applying governance controls to agent I/O.
    """
    
    def __init__(
        self,
        pii_detector: Optional[PIIDetector] = None,
        policy_engine: Optional[PolicyEngine] = None,
        safety_scorer: Optional[SafetyScorer] = None,
        redact_pii: bool = True,
        block_violations: bool = False,
        min_safety_score: float = 0.5
    ):
        self.pii_detector = pii_detector or PIIDetector()
        self.policy_engine = policy_engine or PolicyEngine()
        self.safety_scorer = safety_scorer or SafetyScorer(
            self.pii_detector, self.policy_engine
        )
        self.redact_pii = redact_pii
        self.block_violations = block_violations
        self.min_safety_score = min_safety_score
    
    def process_input(self, text: str) -> Tuple[str, SafetyScore]:
        """Process input text through governance controls."""
        score = self.safety_scorer.score(text)
        
        # Check for blocking violations
        if self.block_violations:
            critical_violations = [
                v for v in score.violations 
                if v.severity == "critical"
            ]
            if critical_violations:
                raise ValueError(
                    f"Input blocked due to policy violation: {critical_violations[0].policy_name}"
                )
        
        # Redact PII if enabled
        processed_text = text
        if self.redact_pii and score.detections:
            processed_text, _ = self.pii_detector.redact(text)
        
        return processed_text, score
    
    def process_output(self, text: str) -> Tuple[str, SafetyScore]:
        """Process output text through governance controls."""
        score = self.safety_scorer.score(text)
        
        # Check minimum safety score
        if score.overall_score < self.min_safety_score:
            raise ValueError(
                f"Output safety score {score.overall_score:.2f} below minimum {self.min_safety_score}"
            )
        
        # Redact PII if enabled
        processed_text = text
        if self.redact_pii and score.detections:
            processed_text, _ = self.pii_detector.redact(text)
        
        return processed_text, score


# ============================================================================
# Export Functions
# ============================================================================

def create_default_governance() -> GovernanceMiddleware:
    """Create governance middleware with default settings."""
    return GovernanceMiddleware(
        redact_pii=True,
        block_violations=False,
        min_safety_score=0.3
    )


def check_safety(text: str) -> Dict[str, Any]:
    """Quick safety check for text."""
    scorer = SafetyScorer()
    score = scorer.score(text)
    
    return {
        "overall_score": round(score.overall_score, 2),
        "pii_score": round(score.pii_score, 2),
        "policy_score": round(score.policy_score, 2),
        "toxicity_score": round(score.toxicity_score, 2),
        "pii_detected": len(score.detections),
        "violations": len(score.violations),
        "is_safe": score.overall_score >= 0.5
    }

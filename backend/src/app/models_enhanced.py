"""
Enhanced database models with full enterprise features.

Includes:
- Versioned test graphs
- Execution traces and logs
- Audit logging
- User and role management
"""

from sqlalchemy import (
    Table, Column, Integer, String, JSON, Float, MetaData, 
    Text, Boolean, DateTime, ForeignKey, Index, Enum as SQLEnum
)
from sqlalchemy.sql import func
from datetime import UTC, datetime
import enum

metadata = MetaData()


def utcnow():
    """Timezone-aware UTC helper to avoid deprecated datetime.utcnow()."""
    return datetime.now(UTC)


# ============================================================================
# Enums
# ============================================================================

class RunStatus(enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    CANCELLED = "cancelled"
    RETRY = "retry"


class AuditAction(enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    EXECUTE = "execute"
    VIEW = "view"


class UserRole(enum.Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"
    API = "api"


# ============================================================================
# User Management
# ============================================================================

User = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(255), unique=True, nullable=False),
    Column("password_hash", String(255)),
    Column("name", String(255)),
    Column("role", String(50), default="viewer"),
    Column("is_active", Boolean, default=True),
    Column("api_key", String(64), unique=True),
    Column("tenant_id", String(128), default="default"),
    Column("created_at", DateTime, default=utcnow),
    Column("updated_at", DateTime, default=utcnow, onupdate=utcnow),
    Column("last_login", DateTime),
    Index("idx_users_email", "email"),
    Index("idx_users_api_key", "api_key"),
    Index("idx_users_tenant", "tenant_id"),
)


# ============================================================================
# Test Graph Management (Versioned)
# ============================================================================

TestGraph = Table(
    "test_graphs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", Text),
    Column("content", JSON, nullable=False),
    Column("version", Integer, default=1),
    Column("is_active", Boolean, default=True),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("tenant_id", String(128), default="default"),
    Column("created_at", DateTime, default=utcnow),
    Column("updated_at", DateTime, default=utcnow, onupdate=utcnow),
    Column("tags", JSON),  # ["regression", "smoke", "integration"]
    Column("metadata", JSON),  # Additional graph metadata
    Index("idx_graphs_name", "name"),
    Index("idx_graphs_active", "is_active"),
    Index("idx_graphs_tenant", "tenant_id"),
)


TestGraphVersion = Table(
    "test_graph_versions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("graph_id", Integer, ForeignKey("test_graphs.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("content", JSON, nullable=False),
    Column("content_hash", String(64)),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("tenant_id", String(128), default="default"),
    Column("created_at", DateTime, default=utcnow),
    Column("change_description", Text),
    Index("idx_graph_versions_graph", "graph_id"),
    Index("idx_graph_versions_hash", "content_hash"),
    Index("idx_graph_versions_tenant", "tenant_id"),
)


# ============================================================================
# Test Runs and Execution
# ============================================================================

TestRun = Table(
    "test_runs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("graph_id", Integer, ForeignKey("test_graphs.id")),
    Column("graph_version", Integer),
    Column("tenant_id", String(128)),
    Column("status", String(50), default="pending"),
    Column("results", JSON),
    Column("latency_ms", Float),
    Column("cost_usd", Float),
    Column("tokens_in", Integer, default=0),
    Column("tokens_out", Integer, default=0),
    Column("assertions_passed", Integer, default=0),
    Column("assertions_failed", Integer, default=0),
    Column("contract_violations", Integer, default=0),
    Column("execution_mode", String(50), default="normal"),
    Column("seed", Integer),
    Column("provider", String(100)),
    Column("model", String(100)),
    Column("triggered_by", Integer, ForeignKey("users.id")),
    Column("webhook_url", String(500)),
    Column("celery_task_id", String(100)),
    Column("started_at", DateTime),
    Column("completed_at", DateTime),
    Column("created_at", DateTime, default=utcnow),
    Column("error_message", Text),
    Column("metadata", JSON),
    Index("idx_runs_graph", "graph_id"),
    Index("idx_runs_status", "status"),
    Index("idx_runs_created", "created_at"),
)


# ============================================================================
# Execution Traces (for replay and debugging)
# ============================================================================

ExecutionTrace = Table(
    "execution_traces",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("test_runs.id"), nullable=False),
    Column("trace_data", JSON, nullable=False),  # Full trace object
    Column("graph_hash", String(64)),
    Column("created_at", DateTime, default=utcnow),
    Index("idx_traces_run", "run_id"),
)


AgentOutput = Table(
    "agent_outputs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("test_runs.id"), nullable=False),
    Column("node_id", String(255), nullable=False),
    Column("agent_type", String(100)),
    Column("input_data", JSON),
    Column("output_data", JSON),
    Column("latency_ms", Float),
    Column("cost_usd", Float),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("provider", String(100)),
    Column("model", String(100)),
    Column("trace_id", String(64)),
    Column("created_at", DateTime, default=utcnow),
    Index("idx_outputs_run", "run_id"),
    Index("idx_outputs_node", "node_id"),
)


# ============================================================================
# Assertion Results
# ============================================================================

AssertionResult = Table(
    "assertion_results",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("test_runs.id"), nullable=False),
    Column("assertion_id", String(255)),
    Column("assertion_type", String(100)),
    Column("target_node", String(255)),
    Column("expected", JSON),
    Column("actual", JSON),
    Column("passed", Boolean),
    Column("message", Text),
    Column("metadata", JSON),
    Column("created_at", DateTime, default=utcnow),
    Index("idx_assertions_run", "run_id"),
    Index("idx_assertions_passed", "passed"),
)


# ============================================================================
# Contract Violations
# ============================================================================

ContractViolation = Table(
    "contract_violations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("test_runs.id"), nullable=False),
    Column("contract_id", String(255)),
    Column("contract_type", String(100)),
    Column("source_node", String(255)),
    Column("target_node", String(255)),
    Column("field", String(255)),
    Column("expected", JSON),
    Column("actual", JSON),
    Column("message", Text),
    Column("severity", String(50)),
    Column("created_at", DateTime, default=utcnow),
    Index("idx_violations_run", "run_id"),
)


# ============================================================================
# Audit Logging
# ============================================================================

AuditLog = Table(
    "audit_logs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id")),
    Column("action", String(50), nullable=False),
    Column("resource_type", String(100)),  # "graph", "run", "user"
    Column("resource_id", Integer),
    Column("details", JSON),
    Column("ip_address", String(45)),
    Column("user_agent", String(500)),
    Column("correlation_id", String(64)),
    Column("previous_hash", String(128)),
    Column("event_hash", String(128)),
    Column("retention_days", Integer, default=365),
    Column("tenant_id", String(128), default="default"),
    Column("created_at", DateTime, default=utcnow),
    Index("idx_audit_user", "user_id"),
    Index("idx_audit_action", "action"),
    Index("idx_audit_created", "created_at"),
    Index("idx_audit_tenant", "tenant_id"),
)


# ============================================================================
# Webhook Configuration
# ============================================================================

Webhook = Table(
    "webhooks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255)),
    Column("url", String(500), nullable=False),
    Column("secret", String(255)),
    Column("events", JSON),  # ["run_completed", "run_failed"]
    Column("is_active", Boolean, default=True),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("created_at", DateTime, default=utcnow),
    Index("idx_webhooks_active", "is_active"),
)


WebhookDelivery = Table(
    "webhook_deliveries",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("webhook_id", Integer, ForeignKey("webhooks.id")),
    Column("event", String(100)),
    Column("payload", JSON),
    Column("response_status", Integer),
    Column("response_body", Text),
    Column("delivered_at", DateTime),
    Column("success", Boolean),
    Index("idx_deliveries_webhook", "webhook_id"),
)


# ============================================================================
# Provider Configuration
# ============================================================================

ProviderConfig = Table(
    "provider_configs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), unique=True, nullable=False),
    Column("provider_type", String(50), nullable=False),
    Column("config", JSON),  # Encrypted in production
    Column("is_default", Boolean, default=False),
    Column("is_active", Boolean, default=True),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("tenant_id", String(128), default="default"),
    Column("created_at", DateTime, default=utcnow),
    Column("updated_at", DateTime, default=utcnow, onupdate=utcnow),
    Index("idx_providers_type", "provider_type"),
    Index("idx_providers_tenant", "tenant_id"),
)


# ============================================================================
# Metrics Aggregation (TimescaleDB compatible)
# ============================================================================

MetricsDaily = Table(
    "metrics_daily",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("date", DateTime, nullable=False),
    Column("graph_id", Integer, ForeignKey("test_graphs.id")),
    Column("total_runs", Integer, default=0),
    Column("passed_runs", Integer, default=0),
    Column("failed_runs", Integer, default=0),
    Column("error_runs", Integer, default=0),
    Column("avg_latency_ms", Float),
    Column("p50_latency_ms", Float),
    Column("p95_latency_ms", Float),
    Column("p99_latency_ms", Float),
    Column("total_cost_usd", Float),
    Column("total_tokens", Integer),
    Index("idx_metrics_date", "date"),
    Index("idx_metrics_graph", "graph_id"),
)


# ============================================================================
# Safety and Governance
# ============================================================================

SafetyPolicy = Table(
    "safety_policies",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(255), nullable=False),
    Column("description", Text),
    Column("rules", JSON),  # Policy rules configuration
    Column("is_active", Boolean, default=True),
    Column("created_by", Integer, ForeignKey("users.id")),
    Column("tenant_id", String(128), default="default"),
    Column("created_at", DateTime, default=utcnow),
)


SafetyViolation = Table(
    "safety_violations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("run_id", Integer, ForeignKey("test_runs.id")),
    Column("policy_id", Integer, ForeignKey("safety_policies.id")),
    Column("violation_type", String(100)),
    Column("details", JSON),
    Column("severity", String(50)),
    Column("content_hash", String(64)),  # Hash of offending content
    Column("tenant_id", String(128), default="default"),
    Column("created_at", DateTime, default=utcnow),
    Index("idx_safety_run", "run_id"),
    Index("idx_safety_type", "violation_type"),
    Index("idx_safety_tenant", "tenant_id"),
)

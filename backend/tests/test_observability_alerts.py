from app.observability.alerts import (
    RUNBOOK_URL,
    build_incident_payload,
    default_alert_rules,
    serialize_prometheus_rules,
)


def test_prometheus_rule_serialization_structure():
    rules = default_alert_rules()
    payload = serialize_prometheus_rules(rules)

    assert "groups" in payload
    assert payload["groups"][0]["name"] == "multi_agent_testing"
    prom_rule = payload["groups"][0]["rules"][0]
    assert prom_rule["alert"] == rules[0].name
    assert "expr" in prom_rule


def test_incident_payload_links_runbook():
    rule = default_alert_rules()[0]
    payload = build_incident_payload(rule)
    assert payload["title"].startswith("[Alert]")
    assert RUNBOOK_URL in payload["runbook"]


import json

from fastapi.testclient import TestClient

from app.collaboration.slack import SlackNotifier, SlackMessage
from app.main import app


class DummyResponse:
    def __init__(self, status_code=200, text="ok"):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.text)


def test_slack_notifier_sends_payload(monkeypatch):
    captured = {}

    class DummySession:
        def post(self, url, data, timeout):
            captured["url"] = url
            captured["payload"] = json.loads(data)
            captured["timeout"] = timeout
            return DummyResponse()

    notifier = SlackNotifier("https://hooks.slack.com/foo", session=DummySession())
    result = notifier.send(SlackMessage(channel="#ops", text="hello"))
    assert result["status"] == "sent"
    assert captured["payload"]["channel"] == "#ops"
    assert captured["payload"]["text"] == "hello"


def test_slack_notifier_skips_without_webhook():
    notifier = SlackNotifier(webhook_url=None)
    result = notifier.send_message("hello world")
    assert result["status"] == "skipped"


def test_slack_notifier_posts_payload(monkeypatch):
    captured = {}

    class DummySession:
        def post(self, url, data, timeout):
            captured["payload"] = json.loads(data)
            captured["url"] = url
            return DummyResponse()

    notifier = SlackNotifier("https://hooks.slack.test/web", session=DummySession())
    result = notifier.send_message("deploy", metadata={"env": "staging"})

    assert result["status"] == "sent"
    assert captured["payload"]["text"] == "deploy"
    assert captured["payload"]["metadata"]["env"] == "staging"


def test_slack_router_endpoint(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")

    def fake_send(self, message):
        return {"status": "sent", "channel": message.channel}

    monkeypatch.setattr(SlackNotifier, "send", fake_send)

    client = TestClient(app)
    response = client.post(
        "/collab/slack/notify",
        json={"channel": "#data", "text": "Test message"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "sent"

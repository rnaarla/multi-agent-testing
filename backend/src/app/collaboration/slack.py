"""Slack collaboration utilities."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


@dataclass
class SlackMessage:
    channel: str
    text: str
    username: str = "multi-agent-bot"
    metadata: Optional[Dict[str, Any]] = None


class SlackNotifier:
    """Send notifications to Slack webhooks for collaboration workflows."""

    def __init__(self, webhook_url: Optional[str] = None, session: Optional[requests.Session] = None):
        self.webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL")
        self.session = session or requests.Session()

    def send(self, message: SlackMessage) -> Dict[str, str]:
        payload: Dict[str, Any] = {
            "channel": message.channel,
            "text": message.text,
            "username": message.username,
        }
        if message.metadata:
            payload["metadata"] = message.metadata
        response = self.session.post(self.webhook_url, data=json.dumps(payload), timeout=10)
        response.raise_for_status()
        return {"status": "sent", "channel": message.channel}

    def send_message(
        self,
        text: str,
        *,
        channel: str = "#general",
        username: str = "multi-agent-bot",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.webhook_url:
            return {"status": "skipped"}
        message = SlackMessage(channel=channel, text=text, username=username, metadata=metadata)
        return self.send(message)


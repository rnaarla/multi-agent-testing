import os

from fastapi import APIRouter, Body, HTTPException

from app.collaboration.slack import SlackNotifier, SlackMessage


router = APIRouter()


@router.post("/slack/notify")
def slack_notify(
    channel: str = Body(...),
    text: str = Body(...),
    username: str = Body("multi-agent-bot"),
) -> dict:
    webhook = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook:
        raise HTTPException(status_code=500, detail="SLACK_WEBHOOK_URL not configured")

    notifier = SlackNotifier(webhook)
    result = notifier.send(SlackMessage(channel=channel, text=text, username=username))
    return result


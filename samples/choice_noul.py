#!/usr/bin/env python3
"""Call the Kev System One API with Choice, Noul and Score questions about support tickets.

    KEV_API_URL=https://<id>.execute-api.<region>.amazonaws.com/demo KEV_API_KEY=<key> python samples/choice_noul.py

KEV_API_KEY is sent as x-api-key; leave it unset for a local server (docker run -p 8080:8080 ...).
The first request after the Lambda has been idle waits for the model to load and can time out at API Gateway's 29 s
limit; retry it.
"""
import json
import os
import urllib.error
import urllib.request

API_URL = os.environ.get("KEV_API_URL", "http://127.0.0.1:8080").rstrip("/")
API_KEY = os.environ.get("KEV_API_KEY")

QUESTIONS = {
    "team": {
        "type": "choice",
        "instructions": "Which team should handle this?",
        "criteria": {"billing": "Charges and refunds", "shipping": "Deliveries", "returns": "Exchanges"},
    },
    "urgent": {"type": "noul", "instructions": "Does this need a reply today?"},
    "frustration": {
        "type": "score",
        "instructions": "How frustrated is the customer?",
        "criteria": ["calm", "mildly annoyed", "angry"],
    },
}

TICKETS = [
    "I was charged twice for order 1182. Please refund one of the charges.",
    "My parcel has been stuck at the depot for a week and nobody answers. This is the third time I am writing.",
    "The jacket is a size too small. Can I swap it for a large whenever convenient?",
]


def system_one(state: str) -> dict:
    headers = {"content-type": "application/json", **({"x-api-key": API_KEY} if API_KEY else {})}
    body = json.dumps({"state": state, "model": "kev-latest", "questions": QUESTIONS}).encode()
    request = urllib.request.Request(f"{API_URL}/v1/systemone", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode()[:500]}")


def main():
    for ticket in TICKETS:
        result = system_one(ticket)
        answers = result["answers"]
        print(f"\n> {ticket}")
        team = answers["team"]
        print(f"  team:        {team['choice']} (confidence {team['confidence']:.2f}) {team['probabilities']}")
        print(f"  urgent:      p(yes) = {answers['urgent']['noul']:.2f}")
        print(f"  frustration: expected level {answers['frustration']['score']:.2f} of 0..2")
        print(f"  latency:     {result['latency_ms']} ms")


if __name__ == "__main__":
    main()

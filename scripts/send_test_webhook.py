"""Send one signed webhook to a running Gatewise server.

    python scripts/send_test_webhook.py [base_url]

Signs the payload with GITHUB_WEBHOOK_SECRET, so the server performs a genuine
signature check rather than being handed a pre-verified request.
"""

import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "packages")

from dotenv import load_dotenv

load_dotenv()

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8077"
SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "demo-secret")
DELIVERY = os.environ.get("DELIVERY_ID", "live-1")

PAYLOAD = {
    "action": "opened",
    "repository": {"full_name": "walidboulanouar/awesome-jev-use-cases"},
    "pull_request": {
        "number": 172,
        "title": "fix(serve): probe cuda usability and add --device flag",
        "body": (
            "Adds a device probe so serve refuses to start on an unsupported GPU "
            "rather than failing later at inference time."
        ),
        "user": {"login": "lab1207"},
        "base": {"ref": "main"},
        "head": {"ref": "fix/serve-device", "sha": "aa11bb22"},
        "labels": [],
    },
}


def main() -> int:
    body = json.dumps(PAYLOAD).encode("utf-8")
    signature = "sha256=" + hmac.new(
        SECRET.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()

    request = urllib.request.Request(
        f"{BASE_URL}/webhooks/github",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": signature,
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": DELIVERY,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            print(f"status: {response.status}")
            print(json.dumps(json.loads(response.read()), indent=2))
    except urllib.error.HTTPError as exc:
        print(f"status: {exc.code}")
        print(exc.read().decode("utf-8", "replace"))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

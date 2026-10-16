"""End-to-end smoke test through the web chat channel (no WhatsApp/Instagram needed).

Run the server with PUBLISH_DRY_RUN=true, then:
    python scripts/smoke_web_chat.py samples/talk.mp4
"""

import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"


def wait_for(client: httpx.Client, needle: str, seen: set[str], timeout: float = 300) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for msg in client.get(f"{BASE}/api/chat/messages").json():
            if msg["direction"] == "out" and msg["id"] not in seen:
                seen.add(msg["id"])
                print(f"  bot> {msg['text'][:160]!r}" + (f" [video {msg['video_url'][:40]}...]" if msg["video_url"] else ""))
                if needle.lower() in msg["text"].lower():
                    return msg["text"]
        time.sleep(1.5)
    raise SystemExit(f"timed out waiting for {needle!r}")


def say(client: httpx.Client, text: str) -> None:
    print(f"  you> {text}")
    client.post(f"{BASE}/api/chat/messages", json={"text": text}).raise_for_status()


def main(video: str) -> None:
    client = httpx.Client(timeout=60)
    email = f"smoke{int(time.time())}@test.dev"
    client.post(f"{BASE}/api/auth/register", json={"email": email, "password": "password123", "name": "Smoke"}).raise_for_status()
    seen: set[str] = set()
    with open(video, "rb") as fh:
        client.post(f"{BASE}/api/chat/upload", files={"file": ("talk.mp4", fh, "video/mp4")},
                    data={"caption": "tips for creators"}).raise_for_status()
    started = time.time()
    wait_for(client, "Reply:", seen)
    print(f"  (edit took {time.time() - started:.0f}s)")
    say(client, "2")
    wait_for(client, "What should I change", seen)
    say(client, "no hook please and captions at the top")
    wait_for(client, "Reply:", seen)
    say(client, "1")
    wait_for(client, "Pick a caption", seen)
    say(client, "2")
    wait_for(client, "Post now or later", seen)
    say(client, "2")
    wait_for(client, "When should I post", seen)
    say(client, "in 1 minute")
    wait_for(client, "Scheduled for", seen)
    wait_for(client, "Live on Instagram", seen, timeout=180)
    drafts = client.get(f"{BASE}/api/drafts").json()
    detail = client.get(f"{BASE}/api/drafts/{drafts[0]['id']}").json()
    print("gates:", detail["gates"])
    print("audit:", [f"{e['actor']}:{e['action']}" for e in detail["events"]])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples/talk.mp4")

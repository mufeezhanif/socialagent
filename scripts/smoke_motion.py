"""Web-chat smoke test for the opt-in motion graphics path: upload, reply 5, wait for the motion edit."""

import sys
import time

import httpx

from smoke_web_chat import BASE, say, wait_for


def main(video: str) -> None:
    client = httpx.Client(timeout=60)
    client.post(f"{BASE}/api/auth/register",
                json={"email": f"motion{int(time.time())}@test.dev", "password": "password123"}).raise_for_status()
    me = client.get(f"{BASE}/api/me").json()
    print("motion available:", me["features"]["motion"])
    seen: set[str] = set()
    with open(video, "rb") as fh:
        client.post(f"{BASE}/api/chat/upload", files={"file": ("talk.mp4", fh, "video/mp4")}).raise_for_status()
    wait_for(client, "Reply:", seen)
    say(client, "5")
    started = time.time()
    text = wait_for(client, "Reply:", seen, timeout=900)
    print(f"  (motion edit took {time.time() - started:.0f}s)")
    print("motion in summary:", "Motion graphics" in text)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples/talk.mp4")

# SocialAgent: WhatsApp → AI video edit → Instagram

Built for **Agentika 2.0** (NaSCon 2026). Theme: *Human + AI: Better Together*.

Send a raw clip to the WhatsApp bot. The AI editor cuts pauses and filler words, reframes to vertical 9:16, burns in
word-by-word captions, adds a hook and cleans the audio, then sends it back for approval. After you approve, it writes
three caption options with hashtags, and posts to Instagram now or at a time you pick.

**Human-in-the-loop by design:** nothing reaches Instagram until a person has approved the edit (for the current
revision), the caption, and the posting time. The publish service enforces this in code. The AI asks instead of
guessing, never invents facts, and every AI and human action is logged on the dashboard timeline.

## Architecture

```
WhatsApp ⇄ wa-gateway (Node + Baileys, 127.0.0.1:3001) ── POST /internal/wa/events ──► FastAPI
Browser (React SPA) ⇄ FastAPI (public PORT) ── state machine + Claude intents
                                             ── job worker: faster-whisper · Claude director · FFmpeg
                                             ── scheduler → Instagram Graph API (Reels)
Postgres: users, drafts, jobs, messages, audit, encrypted WhatsApp session
```

One container on Alternate Clouds runs both processes under `supervisord`.

| Part | Path |
|---|---|
| API, conversation engine, worker | `backend/app` |
| Video pipeline (probe, transcribe, director, cuts, captions, render) | `backend/app/pipeline` |
| WhatsApp gateway | `wa-gateway/src` |
| Web app (onboarding, drafts, chat, calendar, admin) | `frontend/src` |

## Run locally

```bash
# backend (SQLite by default)
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Windows; use .venv/bin on macOS/Linux
PUBLISH_DRY_RUN=true ADMIN_EMAILS=you@example.com .venv/Scripts/python -m uvicorn app.main:app --port 8000

# frontend (proxies /api to :8000)
cd frontend && npm install && npm run dev

# pipeline only
cd backend && .venv/Scripts/python -m app.pipeline.cli ../samples/talk.mp4 --style hype --out ../samples/out/talk

# full chat flow without WhatsApp
python scripts/smoke_web_chat.py samples/talk.mp4
```

The WhatsApp gateway (`cd wa-gateway && npm install && npm start`) links as a WhatsApp companion device. Run it in
**one** place only (production), or every message is answered twice.

## Deploy (Alternate Clouds)

1. Create a GitHub service from this repo (Dockerfile at the root). Size: 2 vCPU / 4 Gi or more.
2. Set the variables from `.env.example` (generate secrets with `python scripts/gen_secrets.py`).
3. Set `PORT` on the Source tab to match the `PORT` variable (default 8000). Rebuild, then Deploy.
4. Log in with an `ADMIN_EMAILS` account, open `/app/admin` and pair the bot phone (QR or pairing code).

## Credits

- [Baileys](https://github.com/WhiskeySockets/Baileys) (MIT): WhatsApp Web protocol client
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) with OpenAI Whisper models: transcription
- [FFmpeg](https://ffmpeg.org) and libass: rendering and captions
- [OpenCV](https://opencv.org) (Apache-2.0): face detection for smart cropping
- [Anthropic Claude API](https://docs.anthropic.com): edit director, intent parsing, captions
- [Anton font](https://github.com/googlefonts/AntonFont) (SIL OFL 1.1, see `assets/fonts/OFL-Anton.txt`)
- Style presets and storyboard structure inspired by the [brag](https://github.com/latent-spaces/brag) skill (MIT)
- React, Vite, Tailwind CSS, TanStack Query, lucide-react, sonner, qrcode.react, FastAPI, SQLAlchemy

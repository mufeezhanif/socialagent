# Plan v2: WhatsApp → AI video edit → Instagram agent (Agentika 2.0)

## Context

**Team and constraints**
- Team of 2 at the Agentika 2.0 hackathon.
- **Deadline: today, 17 Oct, 12:45 PM PKT.** No code changes after it, and the app must stay live until about 6 PM.
- The app must be hosted on Alternate Clouds.

**The fixed idea:** a user
1. registers on our site,
2. connects Instagram,
3. links WhatsApp,
4. sends videos to our WhatsApp agent.

The agent edits each video, sends it back for approval, drafts a caption and hashtags for approval, then posts now or
schedules to Instagram. Stack: FastAPI + React.

`PLAN.md` at the repo root is v1. The latest answers change it:

| Topic | Answer | What changes |
|---|---|---|
| AI keys | **Anthropic only** | Claude does all reasoning. Speech-to-text runs locally (faster-whisper). No Groq. |
| WhatsApp | **Baileys on a teammate's personal number** (replaces the Meta Cloud API) | No 24 h reply window, no 5-tester limit, no buttons. The team accepts the ban risk. |
| Editing | **"brag" skill + every free editing technique** | An AI director in the brag style, with motion graphics rendered by HyperFrames (Apache-2.0, the engine brag uses), on top of an FFmpeg base edit. |
| Setup | **Only the Meta developer account is ready** | Still to do: IG professional account, Instagram app product, Alternate Clouds credits. |
| Time | **~18 h requested, but it is already 17 Oct** | Realistic budget is about 11–12 h, so the timeline is compressed. |

**Outcome:** by 10:00 AM, a full loop that is deployed and reliable, with rich edits. The theme (Human + AI: Better
Together) is enforced by approval gates in code.

## Key decisions

| Area | Decision |
|---|---|
| WhatsApp | A Node 22 + TypeScript **Baileys gateway** in the same container (internal port 3001). FastAPI owns all logic. The gateway only moves messages and media. |
| Baileys auth | Stored in **Postgres**, encrypted (custom auth-state adapter with `BufferJSON`), so redeploys don't force re-pairing. Pairing uses a QR or pairing code on an **admin-only** page. |
| LLM | Claude `claude-sonnet-5-5` through the `anthropic` SDK (`AsyncAnthropic`, `messages.parse` with Pydantic). Effort `low` for intents and time parsing, `medium` for the director and captions. Check `stop_reason` for refusals. |
| Speech-to-text | **faster-whisper `small` int8** on CPU, with word timestamps and the built-in VAD. The model is baked into the image. It also transcribes voice-note instructions. |
| Edit engine | **Stage A:** FFmpeg base edit (always runs). **Stage B:** brag-style motion layer via HyperFrames (headless Chrome + FFmpeg) if the spike passes, otherwise an FFmpeg/ASS motion pack. Switched by `RENDER_ENGINE` env. |
| Director safety | Claude outputs **JSON storyboards only**. Code fills vetted HTML templates. LLM-written HTML or JS never runs in Chrome. |
| Instagram | Instagram API with Instagram Login. Reels publish (container, poll, publish). Long-lived tokens encrypted with Fernet. |
| Data | External Postgres: the Alternate Clouds `database` kind if it gives Postgres, otherwise Neon. Media on container disk (wiped on redeploy, which is acceptable), moved to a bucket later. |
| Deploy | One Alternate Clouds GitHub service built from the Dockerfile. `supervisord` runs uvicorn (public `PORT`) and the gateway (127.0.0.1:3001). Size 2 vCPU / 4 Gi, or 4 vCPU / 8 Gi if HyperFrames ships. |
| Approvals | 3 gates (edit, caption, publish) enforced in the publish service. The AI escalates when unsure and never invents facts. Everything goes in an audit log. |

## Architecture

```
WhatsApp users ⇄ WhatsApp ⇄ [wa-gateway: Node/Baileys @127.0.0.1:3001]
                                   │ POST /internal/wa/events  (shared secret)
                                   ▼
Browser (React SPA) ⇄ HTTPS ⇄ [FastAPI @PORT] ── conversation engine (state machine + Claude intents)
                                   │           ── job worker: faster-whisper · Claude director · FFmpeg · HyperFrames
                                   │           ── scheduler: due posts → Instagram publish · token refresh
                                   ▼
             Postgres (users, drafts, jobs, messages, audit, baileys_auth)     media: /data/media
External: api.anthropic.com · graph.instagram.com · WhatsApp via Baileys
```

**Channel abstraction:** `WhatsAppChannel` talks to the gateway and `WebChannel` talks to the DB. This keeps the engine
channel-agnostic. The web chat doubles as the local dev harness and as the judge/demo fallback if the WhatsApp session drops.

## WhatsApp gateway rules (personal-number safety)

**Which messages the gateway handles**
- Only `messages.upsert` events of type `notify`.
- Ignore `fromMe`, groups (`@g.us`), `status@broadcast` and newsletters.

**Who gets a reply**
- **Only** messages containing a valid `LINK-XXXXXX` code, and linked users.
- Everything else is silently ignored and its content is not stored. Those are the teammate's private chats.

**Identity**
- Identity is the sender JID of the link-code message. This works with v7 `@lid` JIDs.
- The typed phone number is for display and matching only.

**Ban-risk behaviour**
- Send `composing` presence and wait briefly before replying.
- Never message non-linked numbers first. Keep volume low.

**Approvals without buttons**
- Buttons are unreliable on unofficial clients. Use numbered replies (`1/2/3`), keywords, and a 👍 reaction to approve.
- Polls come in P1 (they need a `getMessage` store).

**Media**
- **In:** `downloadMediaMessage(..., { reuploadRequest: sock.updateMediaMessage })` saves to `/data/media/in/…` and passes the path to FastAPI.
- **Out:** FastAPI passes a file path and the gateway calls `sendMessage(jid, { video, caption, mimetype: 'video/mp4' })`. Previews stay ≤ 15 MB.

**Disconnects**

| Reason | Action |
|---|---|
| `loggedOut` | Stop, and show "re-pair" on the admin page |
| `connectionReplaced` (redeploy overlap) | Back off; don't fight the other session |
| Anything else | Reconnect with exponential backoff |

**One live session at a time.** Every linked device receives every message, so a local and a prod gateway running together
means double replies. Develop locally against the web chat and link WhatsApp to prod only.

**Pairing secrets**
- The pairing QR or code grants full access to the teammate's WhatsApp.
- Show it to `ADMIN_EMAILS` only, never log it, and encrypt the auth blobs with `TOKEN_ENCRYPTION_KEY`.
- After the event: WhatsApp, Linked devices, log out, then delete the auth rows.

**Version:** pin the current `baileys` 7.x at implementation time and follow its v7 migration notes for LID mapping.

## Conversation (no buttons)

```
You: [video] "weekend sale, 20% off everything"
Bot: 🎬 Got it, editing now (~1–2 min).
Bot: [preview]  Edit ready 0:48 → 0:34 · style: Hype
     • cut 14 s of pauses and "umm"s  • vertical 9:16, face-centred
     • word-by-word captions + hook "Weekend sale is ON"  • music bed + punchline card
     Reply 1 ✅ approve · 2 ✏️ change something · 3 🎨 another style · 4 🗑 discard  (or react 👍)
You: 2 → voice note "cut the part where I say sorry"  → revision 1/3 preview
You: 👍
Bot: Captions: 1) … 2) … 3) …   Hashtags (12): …   Reply 1–3, or send your own.
You: 2
Bot: 1 🚀 post now · 2 🗓 schedule · 3 💾 save
You: 2 → "today 8pm" → "Scheduled 17 Oct, 8:00 PM PKT ✅" … later "🎉 Live: <permalink>"
```

The state machine, routing order and edge cases carry over from PLAN.md v1 §5. Drop the Meta-only parts: the 24 h
window, button limits, and errors 131030 and 131047.

## Editing toolkit (all free)

| Tier | Effect | How |
|---|---|---|
| P0 | Cut pauses and filler ("um", "uh", repeats) | faster-whisper words + VAD give keep-segments, then FFmpeg trim/concat |
| P0 | Vertical 9:16 | Blur-pad by default. Face-centred crop when OpenCV finds one steady face |
| P0 | Clean audio | `highpass`, `afftdn` denoise, `acompressor`, `loudnorm` −14 LUFS |
| P0 | Animated captions | ASS, 2–4 words per line, current word highlighted, brand colours, bold OFL font |
| P0 | Hook title (first 2.5 s) | ASS style, or a HyperFrames card |
| P1 | Jump-cut zoom alternation | Alternate 100 % / 110 % crop per segment to hide jump cuts |
| P1 | Colour grade | `eq` plus free `.cube` LUTs via `lut3d`, one per style |
| P1 | Music bed + SFX | License-checked tracks and Kenney CC0 SFX. `sidechaincompress` ducks the music under the voice |
| P1 | **brag-style motion layer** | HyperFrames templates: hook card, kinetic captions, emoji pops, zoom punch-ins on emphasis words, progress bar, punchline/CTA end card, poster frame baked into frame 0 |
| P1 | Styles (brag tones, adapted) | `clean`, `hype`, `cinematic`, `funny`, `deadpan`, `luxury`. Each picks template, LUT and music. Reply "3 🎨" re-renders in another style |
| P1 | Brand kit | Logo watermark, colours, font, CTA end card |
| P2 | Extras | Multi-clip merge with `xfade`, speed ramps, `deshake` stabilisation, bilingual captions (Claude translates) |

**Director.** One structured Claude call takes about 8 frames, the transcript, the brand kit and the user's notes. It
returns a `Storyboard` with these fields:
- keep segments, style, hook,
- highlight words, emoji moments,
- punchline/CTA text, crop hint, cover frame,
- `user_summary`, `question_for_user`.

Code validates and clamps it. Invalid output falls back to a deterministic plan (silence cut + defaults). Every effect is
an independent op, so a failing op is skipped instead of failing the whole edit.

**Dev time.**
- Read the brag and HyperFrames skill files (talking-head captions, overlays on footage).
- Port their storyboard structure, tone presets, mixing guidance and still-frame QA into the director prompt and templates.
- Check the licence of brag's bundled music before shipping it. Kenney SFX are CC0.
- Credit everything in the README.

**HyperFrames spike** (first 90 min, on a teammate's laptop):
- Render one 30 s, 1080×1920 template over a sample clip.
- Ship HyperFrames only if the render takes ≤ ~120 s on 4 vCPU **and** Chromium runs in the container.
- Otherwise ship the FFmpeg/ASS motion pack.

## Captions, schedule, publish

Carries over from PLAN.md v1 §7:
- **Caption pack:** Claude writes 3 options, 8–15 hashtags, and `facts_to_confirm` (claims it wants the user to confirm). Code checks the limits.
- **Scheduling:** Claude parses the time and code validates it. A scheduler loop with a unique publish job per draft, so nothing posts twice.
- **Publishing:** the Instagram container is created at publish time. The permalink is sent on WhatsApp. Baileys has no window limit, so this works at any time.

## Files to create (repo root)

```
Dockerfile, supervisord.conf, .env.example, README.md (credits), PLAN.md (rewrite as v2)
backend/app/   main.py, config.py, db.py, models.py
               auth/, routes/ (drafts, brand, instagram, whatsapp_link, chat, media, admin, health, internal_wa)
               agent/ (engine.py, states.py, intents.py, copy.py)
               channels/ (base.py, whatsapp.py → gateway client, web.py)
               pipeline/ (probe, transcribe, faces, director, ops/*, subtitles, render_ffmpeg, render_hyperframes, cli.py)
               integrations/ (claude.py, instagram_api.py)
               worker/ (queue.py, runner.py, scheduler.py)
backend/tests/ storyboard validation, cut map + subtitle remap, intent routing, gateway-event filtering, caption limits
wa-gateway/    src/index.ts (socket + reconnect), authState.ts (Postgres), filters.ts, server.ts (/send, /status, /pair)
render/templates/  HyperFrames compositions per style (filled by Jinja2)
assets/        fonts/, luts/, music/, sfx/
frontend/      Vite React app: landing, auth, onboarding (IG → WhatsApp link + QR → brand kit), drafts,
               draft detail (before/after, audit), calendar, chat, admin (pairing, gateway status, pause)
```

**Dockerfile**
- Base `python:3.12-slim`. Copy the Node 22 binary from `node:22-bookworm-slim`.
- apt packages: `ffmpeg`, `supervisor`, fonts including `fonts-noto-color-emoji`, and `chromium` behind the build arg `WITH_HYPERFRAMES`.
- `pip` installs: faster-whisper (model pre-downloaded), `opencv-python-headless`, `anthropic`, FastAPI stack.
- Build the gateway TypeScript to JS.

## Timeline (T0 = plan approved; times assume T0 ≈ 1:00 AM. Shift if later. Freeze times are fixed.)

| Block | Claude Code | Teammate A | Teammate B | Milestone |
|---|---|---|---|---|
| T0 → 2:30 | Scaffold everything: Dockerfile + supervisord, gateway with Postgres auth, `/healthz`, admin pairing page | Alternate Clouds: credits, service name, DB, first deploy; pair the bot number | Meta: Instagram product, IG app id/secret, redirect URI, tester; switch IG to Professional; HyperFrames spike | **M0:** live URL, gateway connected |
| 2:30 → 5:30 | Link-code flow, engine with numbered replies, P0 pipeline, Claude caption pack | Test on prod WhatsApp; record sample clips | Auth + onboarding UI | **M1:** clip in → edited preview → approve → captions |
| 5:30 → 8:00 | Instagram OAuth, publish, scheduler; deploy | Drafts list/detail UI | Demo IG account; publish tests | **M2:** full loop on the deployed URL (safety net) |
| 8:00 → 10:00 | P1 in order of value: motion layer (HyperFrames or ASS), music + SFX, styles, brand kit, web chat | QA, bug triage | Rest / rotate | **M3** |
| **10:00** | **Feature freeze, final deploy.** The last emergency redeploy must start by 11:30 | | | |
| 10:15 → 12:15 | Bug fixes only | End-to-end test on prod; record the 2–3 min demo video | LinkedIn post (written by you), screenshots, PDF | **Submit by 12:15** |

**Cut lines**
- M1 not done by 6:00: drop P1 entirely.
- M2 not live by 8:30: no HyperFrames; ship the FFmpeg pack.
- Rest in turns. No risky refactors after 9:00.
- Optional speed-up: a second Claude Code session builds `render/templates/` and `frontend/` in parallel, in separate folders.

## Human checklist (start now)

- [ ] **Alternate Clouds:**
  - log in and confirm credits,
  - pick the service name (it sets the URL `https://<name>-app.alternatefutures.ai`),
  - try `acc services create --kind database`.
- [ ] **Anthropic** API key with credits.
- [ ] **Meta app** (existing dev account):
  - add Instagram, then "API setup with Instagram login",
  - note the Instagram App ID and Secret,
  - add redirect `https://<name>-app.alternatefutures.ai/api/instagram/callback`,
  - add a tester and accept the invite in Instagram,
  - set the privacy and data-deletion URLs.
- [ ] **Instagram** account switched to Professional (Creator), and safe to post demo Reels to.
- [ ] **Teammate's phone** on hand to pair (WhatsApp, then Linked devices). The bot replies only to linked users and link codes.

## Verification

**Local**
- `python -m app.pipeline.cli samples/talk.mp4 --style hype` renders the master and the preview.
- `pytest backend/tests` passes.
- A full conversation runs through the web chat at `/app/chat`.

**Gateway**
- The admin page shows a QR. Pairing sets status to `open`.
- After a container restart it reconnects without re-pairing, because auth is in Postgres.

**Prod end-to-end (after each deploy)**
1. `/healthz` is OK.
2. Send `LINK-…` from a second phone: linked ✅.
3. Send a clip: the preview arrives within about 2 min.
4. Reply `2` plus a voice note: a revision arrives.
5. React 👍, then pick caption `2`.
6. Schedule "in 2 minutes".
7. The Reel appears on Instagram, the permalink arrives on WhatsApp, and the audit log separates AI and human actions.

**Negative checks**
- A message from an unlinked number or a group gets no reply and nothing is stored.
- A duplicate event is processed once.
- A publish without approvals is refused.

## Top risks

- **Teammate's number banned, or the session drops mid-demo.** Keep volume low and inbound-only. Web chat fallback. Re-pair runbook. Record the demo video early.
- **HyperFrames/Chromium too slow or broken in the container.** The spike decides. The FFmpeg pack is the floor.
- **CPU-bound renders.** One render at a time, 720p previews, an instant "editing…" message, and 4 vCPU requested.
- **Disqualification items.** The team writes the LinkedIn post (never use brag's `share-copy.txt` for it). No keys in the repo or the video.

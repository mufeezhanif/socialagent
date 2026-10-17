"""Every message the bot sends lives here, so tone can change without touching logic."""

WELCOME_LINKED = (
    "✅ WhatsApp linked to *{app}*!\n\n"
    "How it works:\n"
    "1. Send me a raw video 🎬\n"
    "2. I edit it and send it back for your OK\n"
    "3. I write captions, you pick one\n"
    "4. I post it to Instagram, now or later\n\n"
    "Type *help* anytime."
)
LINK_INVALID = "That link code is invalid or expired. Open the website and get a fresh one."

RECEIVED = "🎬 Got it! Editing now, usually 1-2 minutes."
RECEIVED_REPLACED = "🎬 New video received. Your previous draft is saved on the dashboard; editing this one now."
STILL_WORKING = "⏳ Still working on your video, hang tight."
TOO_LONG = "That video is {dur}s long. I can edit up to {max}s right now. Please send a shorter clip."
TOO_SHORT = "That clip is very short ({dur}s). Send at least 3 seconds."
TOO_BIG = "I couldn't download that video (it may be too big). Please send it again, or a shorter clip (up to {max}s)."
RETRYING = "🔁 Trying again..."
ONLY_VIDEO = "I edit videos for now. Send me a video 🎬"
NO_DRAFT = "Send me a video to get started 🎬"

EDIT_READY = "✨ *Edit ready* ({din}s → {dout}s) · style: {style}\n{bullets}"
QUESTION = "\n\n❓ {question}"
MOTION_START = "✨ Adding motion graphics: kinetic captions, zoom punches, emoji pops and an end card. Takes 2-4 minutes..."
MOTION_UNAVAILABLE = "Motion graphics aren't set up on this server yet."


def approval_options(motion: bool = False) -> str:
    lines = ["\n\nReply:", "1 ✅ approve", "2 ✏️ change something", "3 🎨 try another style", "4 🗑 discard"]
    if motion:
        lines.append("5 ✨ motion graphics (2-4 min)")
    lines.append("(or react 👍 to approve)")
    return "\n".join(lines)

ASK_CHANGES = (
    "What should I change? Type it or send a voice note.\n"
    'e.g. "cut the first 3 seconds", "no hook", "captions at the top", "make it cinematic"'
)
REVISING = "On it ✂️ (revision {n} of {max})"
REVISION_LIMIT = "That's {max} revisions already. Reply 1 to approve or 4 to discard, or fine-tune on the dashboard: {url}"
NEW_STYLE = "🎨 Trying the *{style}* style..."
DISCARDED = "🗑 Discarded. Send another video whenever you're ready."

ASK_CONTEXT = (
    "Approved ✅\n\nAnything I should mention in the caption, like an offer, link or location?\n"
    "Reply with the details, or *skip*."
)
WRITING_CAPTIONS = "✍️ Writing captions..."
CAPTION_OPTIONS = "Pick a caption:\n\n*1)* {c1}\n\n*2)* {c2}\n\n*3)* {c3}\n\nHashtags: {tags}"
CAPTION_REPLY = "\n\nReply 1, 2 or 3, send your own caption, or ask for a tweak (\"make 2 shorter\")."
FACT_CHECK = "\n\n⚠️ Please double-check: {facts}"
CAPTION_SET = "Caption locked ✅"

ASK_PUBLISH = "Post now or later?\n1 🚀 post now\n2 🗓 schedule\n3 💾 save as draft"
NEED_INSTAGRAM = (
    "Instagram isn't connected yet: {url}\n"
    "Connect it, then reply 1 🚀 to post now or 2 🗓 to schedule. Reply 3 💾 to save it as a draft."
)
ASK_TIME = 'When should I post? e.g. "today 8pm", "tomorrow 9am", "in 2 hours".\nSuggested: {suggestion}'
TIME_UNCLEAR = 'I couldn\'t read that time. Try "today 8pm", "tomorrow 10am" or "in 30 minutes".'
TIME_PAST = "That time has already passed. Pick a time in the future."
SCHEDULED = "🗓 Scheduled for {when} ✅\nReply *cancel* to unschedule or *now* to post right away."
UNSCHEDULED = "Unscheduled. Reply 1 to post now, 2 to pick a new time or 3 to save."
PUBLISHING = "🚀 Posting to Instagram..."
PUBLISHED = "🎉 Live on Instagram: {permalink}"
PUBLISH_FAILED = "⚠️ Instagram didn't accept the post: {error}\nReply *retry* to try again."
SAVED = "💾 Saved as a draft. Find it on your dashboard: {url}"

FAILED = "⚠️ Something went wrong while {stage}. Reply *retry* to try again."
UNCLEAR = "Sorry, I didn't get that."

HELP = (
    "*How to use me*\n"
    "• Send a video and I'll edit it\n"
    "• Reply with the numbers I show you\n"
    "• *status*: what I'm doing with your latest video\n"
    "• *retry*: try again after an error\n"
    "• Dashboard: {url}"
)
STATUS = "Latest draft: {status}{extra}"

STATUS_LABELS = {
    "processing": "editing ⏳",
    "revising": "applying your changes ⏳",
    "awaiting_video_approval": "waiting for your approval of the edit",
    "awaiting_change_notes": "waiting for your change request",
    "awaiting_context": "waiting for caption details",
    "captioning": "writing captions ⏳",
    "awaiting_caption_choice": "waiting for you to pick a caption",
    "awaiting_publish_choice": "waiting for post now / schedule",
    "awaiting_schedule_time": "waiting for a posting time",
    "scheduled": "scheduled",
    "publishing": "posting ⏳",
    "published": "published",
    "saved": "saved as draft",
    "discarded": "discarded",
    "failed": "failed",
}

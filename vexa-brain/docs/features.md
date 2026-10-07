# VXA — Future Features

Ideas parked for the next build pipeline. Each entry says what it is, why it matters, what is
technically possible on Android, and a rough build order. Nothing here is built yet.

---

## 1. VXA Keyboard — the assistant inside every text field

**Status:** idea · next pipeline
**Inspiration:** [Acti — "The Agentic Keyboard"](https://openacti.com/) (iOS, Android, Mac). Users type an
intent in any text field, long-press the Acti Bar (a key in place of the space bar) and the result is
inserted where they type. It connects to 100+ APIs/apps (Gmail, Notion, Calendly, weather…), lets users
build "Skill Keys", and has a community "Skill Hub". No pricing or privacy claims on the landing page.

### Why it fits VXA

- **It is exactly where the pain is.** Today: open ChatGPT → ask for a reply → copy → go back → paste.
  With a keyboard, the reply is written where the cursor already is.
- **No accessibility service, no screen tapping.** A keyboard is an official Android input method
  (`InputMethodService`); banking apps don't block it the way they block accessibility services.
- **Works in every app** (WhatsApp, LinkedIn, Gmail, Instagram, SMS) with one setup step:
  "set VXA as your keyboard".
- **Acti is wide; VXA is deep.** Acti connects to many tools; VXA knows *you* — your people, your tone,
  your Org (tasks, follow-ups), and speaks Telugu / Telugu-English. That is the difference to sell.
- It can replace the floating-bubble plan (step 2) for the "write my reply" use case.

### How it would feel

- Types like a normal keyboard (it must be a good keyboard first, or nobody keeps it).
- A slim **VXA bar** above the keys shows one-tap suggestions for the current app.
- **Long-press shortcuts** on letter keys, configurable in the VXA app:

| Long-press | Action | Result inserted in the text field |
|---|---|---|
| `R` | Reply | A reply to the latest message from this chat, in your tone |
| `W` | Rewrite | Your typed text made clearer / politer / shorter |
| `T` | Telugu | Translate or transliterate (English ⇄ Telugu ⇄ Telugu-English) |
| `O` | Org | "Add to Org" — the typed text becomes a task/reminder/follow-up |
| `E` | Email | Expand a one-liner into a full email (for Gmail's compose box) |
| `M` | Me | Insert facts from memory: portfolio link, resume link, address, availability |

- Every result is a **preview chip first** (tap to insert, long-press to edit) — VXA never sends anything.

### What a keyboard can and cannot see (the important constraint)

| Can see | Cannot see |
|---|---|
| The text in the field being edited (before/after the cursor) | The chat history on screen (other person's messages) |
| Which app is in front (`EditorInfo.packageName`) and field hints | Other apps' content in general |
| The clipboard (when the user copies something) | Anything while typing in password fields (must be skipped anyway) |

So **"reply to the latest message" needs another source for the other person's words**:

1. **Notification access (best):** recent incoming messages per app/chat are already in Vexa's
   notification listener (feature 1 in the roadmap). Keyboard opens in WhatsApp → VXA knows the last
   messages that arrived from WhatsApp → offers replies to the most recent conversation.
2. **Clipboard:** user long-presses the message → Copy → `R` → reply to the copied text.
3. **Default-assistant screen text (step 2 plan):** optional power-user mode for full on-screen context.

### Privacy rules (non-negotiable — keyboards see everything typed)

- Never read, store or send text from password, OTP, PIN, number-only or `NO_PERSONALIZED_LEARNING` fields.
- Never log keystrokes. Text leaves the phone **only** when the user triggers a VXA action, and only the
  minimum needed (field text + selected context).
- Android warns users that a third-party keyboard "may collect all text you type"; the onboarding must
  explain plainly what VXA sends and when.
- Keep "Vexa never handles money / bank / OTP" — skip suggestions entirely in banking apps.

### Technical sketch

**Android (`Vexa_Observe`)**
- New `VxaKeyboardService : InputMethodService` + settings entry + "enable keyboard" onboarding.
- Don't build the typing engine from scratch: start from an open-source keyboard such as
  **FlorisBoard** (Apache-2.0) for layouts, swipe, autocorrect and Indic support, and add the VXA bar,
  long-press actions and preview chips on top. Typing quality is the biggest risk of this feature.
- Context = field text + `EditorInfo` (app, field type) + latest notifications for that app + clipboard.
- Insert results with `currentInputConnection.commitText(...)`.
- Shortcut config screen in the VXA app (which key → which action, on/off per app).

**Server (`vexa-brain`)**
- `POST /api/keyboard/suggest` — `{action, app, fieldText, context, language}` → `{suggestions: [...]}`.
  Reuse the planner's DRAFT behaviour, memory and personality; return 1-3 short options.
- Learn from what the user inserts / edits (same learning service) so drafts need fewer edits over time.
- Latency budget ~1-2 s (keyboard users won't wait) → fastest Groq model, small prompts.

### Build order

1. Notification listener (recent messages per app) — needed for good replies anyway.
2. Minimal IME on FlorisBoard: VXA bar + `R` (reply) + `W` (rewrite), preview chip, insert.
3. `T` Telugu / Telugu-English, `O` Add to Org, `M` memory snippets.
4. Shortcut customisation screen; per-app suggestions in the bar.
5. Later: "Skill keys" users define themselves (Acti-style), shared templates.

### Open questions

- Fork FlorisBoard vs. keep VXA as a lightweight "toolbar" that users switch to from Gboard
  (Android's keyboard switcher) — easier to build, but less sticky.
- Telugu typing quality vs. Gboard — test with real users before committing.
- Play Store review for keyboards that send text to a server: prepare a clear data-safety section.

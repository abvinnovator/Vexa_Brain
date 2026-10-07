# VXA — Privacy & Security

How VXA handles personal data, how to explain it to people, and what still has to be fixed.
Written against the code as it is today (Oct 2026) — gaps are listed honestly, not hidden.

---

## 1. The idea in one line

> **VXA is a memory you own.** It remembers your life so its answers fit you — and you can see,
> edit and delete every single thing it knows.

VXA is not trying to collect data. Its whole value is *context*: connecting "how many calories in a
banana?" to "you started going to the gym last week". That only works if VXA remembers — so the
product has to make remembering **visible, controllable and minimal**.

---

## 2. When someone says "you're just stealing people's data"

Don't answer with "Google and Meta already have your data anyway." It's true, but it sounds like
an excuse — "others do worse" doesn't make us trustworthy. Answer with what VXA does *differently*:

| They say | You say |
|---|---|
| "You're harvesting my data." | "VXA keeps a memory for *you*, not for us. Open Org → tap YOU and you see every fact it knows. Tap ✕ and it's gone — from the memory and the graph." |
| "You'll train your AI on it." | "We don't train any model on your data. VXA keeps notes about you; the AI reads only the few notes a question needs, then forgets them." |
| "You'll sell it / show me ads." | "No ads, no selling, no sharing. Ever. That's in the privacy policy, not just a promise." |
| "Why does it need so much?" | "It doesn't take — you tell it. It learns from what you say to it and what you add to Org. It doesn't read your gallery, contacts or messages on its own." |
| "What about my bank / OTPs?" | "VXA never reads, stores or acts on bank, payment or OTP data. The bubble skips password fields, and banking apps block assistants anyway." |
| "What about my friends' messages on screen?" | "When you tap the bubble, the chat text is used for that one reply and thrown away — never stored, never learned from, never logged." |
| "ChatGPT also has memory." | "Yes — and it's a black box. VXA shows you its whole memory, organised by your life, and you can delete any line." |

The honest framing: **giants have your data for their benefit; VXA holds your context for yours,
and you hold the delete button.**

---

## 3. Principles (the promises — keep every one)

1. **Yours, visible:** everything VXA knows is shown in Org (YOU + each area). No hidden profile.
2. **Deletable:** any fact can be forgotten from the app; a full "delete everything" must exist.
3. **Minimal:** store distilled facts ("you joined Cognizant in June 2026"), not raw chats or screens.
4. **Purpose-limited:** data is used only to help the user. No ads, no selling, no model training.
5. **Least exposure to AI providers:** send a model only the few facts one question needs.
6. **Never:** bank, payment, OTP, passwords, health records you didn't type, contacts/gallery scraping.
7. **No silent actions:** VXA drafts; the user sends. Nothing goes out in the user's name automatically.
8. **Honest wording:** never claim "fully private / on-device" while cloud models are used.

---

## 4. What VXA stores today, and where

| Data | Where it lives | Notes |
|---|---|---|
| Chat history | Phone (Room DB, app-private) | Not sent anywhere except the last 6 messages with each request. Android auto-backup **disabled** (fixed). |
| Org items (tasks, reminders, follow-ups) | Phone + MongoDB | Needed for sync across devices and server reminders. |
| Knowledge / memory (facts about the user) | Server: `knowledge/` files + Neo4j graph; curated view cached in MongoDB | Learned from chat + Org captures. User can forget facts in Org. |
| Bubble screen text | **Nowhere** — used for one request | Not stored, not learned from; LangSmith traces redacted (fixed today). |
| Usage stats (app usage) | Phone | Optional permission. |
| Gmail (if connected) | Read on demand via Gmail credentials on the server | See gap #2. |

### Who else sees data (sub-processors)

| Service | What it receives | Action needed |
|---|---|---|
| Groq / OpenRouter (LLMs) | The prompt for each request: question + relevant facts | Check each provider's data policy. **Some OpenRouter free models log or train on prompts** — disable those in OpenRouter privacy settings or drop them from the fallback list. |
| LangSmith | Full prompts + replies of traced calls (debugging) | Bubble calls are redacted. Turn tracing **off in production** or redact all user content. Delete old traces that contain chats. |
| MongoDB Atlas | Org items, situations, curated facts | Enable IP allow-list (not 0.0.0.0/0), strong password, encryption at rest (Atlas default). |
| Neo4j Aura | Knowledge graph | Same: credentials in env only, restrict access. |
| Render | Runs the server; its logs include the first 60 characters of chat messages | Remove message text from logs. |

---

## 5. Gaps — in priority order

| # | Gap | Risk | Status |
|---|---|---|---|
| 1 | **No authentication on the API.** Anyone with the server URL (it's in the APK) could read all memory (`/api/org/...`), read the Gmail inbox and **send email as the user**. | Critical | **Partly fixed today:** app key (`X-VXA-Key`). Turn it on: set `VXA_APP_KEY` on Render and `vxa.appKey=` (same value) in `ObserveAI/local.properties`, rebuild. A key inside an APK can be extracted, so this is a stopgap → real fix is #3. |
| 2 | Gmail via SMTP/IMAP with an app password stored on the server | High | Move to Gmail API + OAuth per user (planned); never store a reusable password. |
| 3 | Single hard-coded user (`local_user`), no accounts | High (before any second user) | Google Sign-In on the phone → server verifies the ID token on every request; all data keyed by the verified user id. |
| 4 | LangSmith stores full prompts (personal facts, chats) | Medium | Bubble redacted (fixed). Redact or disable for all user content in production; delete existing traces. |
| 5 | Free LLM providers may retain prompts | Medium | Prefer providers that don't train on API data; let privacy-minded users bring their own key. |
| 6 | Chat text in Render logs | Medium | Log ids and lengths, not content. |
| 7 | No "export my data" / "delete everything" | Medium (and a legal requirement) | Add both to Settings; deletion must wipe Mongo, Neo4j, knowledge files and the phone. |
| 8 | `CORS: *` on the server | Low (mobile app), higher with a web client | Restrict to known origins when the portfolio chatbot / web app ships. |
| 9 | Cleartext HTTP allowed to local dev IPs | Low | Remove from release builds. |
| 10 | Memory grows forever | Low now | Merge/expire stale facts (temporal facts after their date). |

---

## 6. Hard lines (non-negotiable, in code and in the policy)

- Never read, store or act on **bank, payment, UPI, card, OTP or password** data.
- Never send a message, email or post **on the user's behalf without them tapping send**.
- Never store or learn from **other people's messages** seen through the bubble.
- Never use user data for **ads, sale, or model training**.
- The user can **see and delete** everything VXA remembers.

---

## 7. India: DPDP Act 2023 checklist

The Digital Personal Data Protection Act applies to VXA (personal data of people in India).

- [ ] **Notice + consent** in plain language (English + Telugu) before collecting anything — what, why, who processes it.
- [ ] **Purpose limitation** — use data only for the stated purpose (personal assistance).
- [ ] **Rights:** access (Org already shows memory), correction, erasure ("delete everything"), and withdrawal of consent.
- [ ] **Grievance contact** listed in the app and policy.
- [ ] **Security safeguards** — gaps #1–#6 above.
- [ ] **Breach handling** — a written plan to notify users and the Data Protection Board.
- [ ] **Children** — VXA is 18+ unless verifiable parental consent is added.
- [ ] **Play Store Data safety form** matches reality (declare: personal info, messages typed to VXA, app activity; "not sold", "not shared for ads", "user can request deletion").

---

## 8. Draft in-app privacy note (show at onboarding)

> **Your memory, your control.**
> VXA remembers what you tell it — your work, plans, people and routines — so its answers fit your life.
> - You can see everything VXA knows in **Org → YOU**, and delete anything with one tap.
> - When you ask something, only the few notes that question needs are sent to the AI model, for that moment.
> - When you tap the bubble, the chat on screen is used for that one reply and never saved.
> - VXA never touches your bank, payments or OTPs, never sends anything without you, and never sells or trains on your data.

(Translate to Telugu before launch.)

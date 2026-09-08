# 🤖 ARIA — Internal Knowledge & Ticketing Assistant

> **MCP-connected chatbot for IT operations teams — RAG answers from Confluence, writes new articles when nothing exists, and turns chat into clean Jira tickets, streamed live**

ARIA sits in front of six internal teams — **Service Desk, Command Center, Network, Linux, Database, and Windows Engineering** — as one chat interface. A LangChain probing layer reads each question first: if it's too vague to search on, ARIA asks one clarifying question instead of guessing. Once the issue is clear, a ChromaDB-backed retrieval loop finds the best matching Confluence article — rewording and re-searching if the first pass isn't confident — and streams a grounded answer token-by-token. If nothing matches, ARIA drafts and publishes a new article, so the knowledge base grows itself. A **"Log as Ticket"** action turns the raw back-and-forth of the chat into a well-formed Jira Service Desk ticket, not a dump of the conversation.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.112+-009688?style=flat&logo=fastapi&logoColor=white)
![LangChain](https://img.shields.io/badge/LangChain-probing_layer-1C3C3C?style=flat)
![ChromaDB](https://img.shields.io/badge/ChromaDB-RAG-6366f1?style=flat)
![MCP](https://img.shields.io/badge/MCP-Server-8b5cf6?style=flat)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🗂️ **Six team spaces** | Service Desk · Command Center · Network · Linux · Database · Windows Engineering, each with its own Confluence space + Jira project |
| 🧭 **LangChain probing layer** | Reads the question before anything else runs; a genuinely vague report ("my thing is broken") gets one clarifying question instead of a guess |
| 🔎 **RAG retrieval (ChromaDB)** | Articles are chunked and embedded, not dumped whole into the prompt; retrieval is confidence-scored and re-tried with a reworded query when the first pass is weak |
| ✍️ **Self-healing KB** | No confident match → ARIA drafts an article, publishes it, and indexes it immediately — the next person with the same question finds it already there |
| 🌊 **Real-time streaming** | Answers stream token-by-token over SSE with a "Musing…" / "Reading…" / "Drafting…" status and a blinking cursor, like a live typed reply |
| 🌡️ **temperature=0.2 everywhere** | Every completion call — decision, synthesis, drafting, ticket writing — is grounded and low-temperature on purpose; prompts explicitly forbid inventing steps not in the source |
| 🛡️ **Guardrails** | Hard-blocks high-sensitivity PHI/PII (SSN, card numbers, MRNs), sexual/nudity content, and security-risk requests (credential theft, bypassing auth) *before* anything reaches an LLM, Confluence, or Jira |
| 🔓 **Soft PII redaction** | Low-sensitivity contact info (email, phone, IP) is masked but still passed through — a ticket needs a reporter's email |
| 🎫 **Log as Ticket** | Converts the chat's raw comments into a clean summary + description + priority and files it in Jira Service Desk |
| 🔌 **MCP server** | Every capability is also exposed as an MCP tool for Claude Desktop / Claude Code |
| 🧪 **Offline-first** | Local JSON knowledge base + ticket store, fully demo-able with no Jira/Confluence/Okta tenant; flip one flag to go live |

---

## 🏗️ Project Structure

```
aria-service-desk-assistant/
├── main.py                 ← FastAPI app: /api/chat, /api/chat/stream (SSE), /api/ticket, /api/teams
├── mcp_server.py            ← Same capabilities exposed over MCP (stdio)
├── config.py                ← Settings: mock mode, temperature, Jira/Confluence/Okta creds
├── models.py                 ← Team enum + Pydantic request/response models
├── prompts.py                ← Prompt templates (decision, synthesis, drafting, ticket writer)
├── probe_agent.py             ← LangChain layer: clarity check + search-intent reword loop
├── vector_store.py              ← ChromaDB chunking/embedding/retrieval
├── knowledge_agent.py            ← Orchestrates probe → retrieve → synthesize/draft, streamed
├── ticket_writer.py                ← Chat transcript → clean ticket summary/description
├── guardrails.py                    ← Hard blocks: PHI/PII, sexual content, security risk
├── phi_filter.py                     ← Soft redaction: email/phone/IP, masked not blocked
├── confluence_client.py               ← Search + publish articles (mock JSON ↔ real Confluence REST)
├── jira_client.py                      ← Create tickets (mock JSON ↔ real Jira REST)
├── okta_client.py                       ← Requester lookup, name/department only (mock ↔ real Okta REST)
├── kb_store.py                           ← Local JSON-backed knowledge base (the mock/offline Confluence)
├── data/
│   ├── mock_kb.json                       ← Seed articles per team (Troubleshooting/How-To/Runbook)
│   ├── chroma/ (runtime)                   ← Local vector index
│   └── mock_tickets.json (runtime)          ← Filed tickets in mock mode
└── static/
    └── index.html                           ← Chat UI: musing status, streaming text, blinking cursor
```

---

## 🔄 Chat Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│ USER picks a team, asks a question                                        │
└────────────────────────────────┬──────────────────────────────────────────┘
                                  ▼
                POST /api/chat/stream  →  guardrails.screen()  → blocked? refuse & stop
                                  │
                                  ▼
               probe_agent.assess()  (LangChain: ChatOpenAI + prompt template)
                                  │
                     clear enough to search?
                ┌─────────────────┴─────────────────┐
               NO                                   YES
                │                                     │
   stream back ONE clarifying              vector_store: chunk + embed (ChromaDB)
   question, wait for the reply                        │
                                            best_articles_context(team, intent)
                                                         │
                                          LLM: found? confidence 0.0–1.0
                                        low confidence → probe_agent.reword()
                                          → re-embed search → retry (max 2 rounds)
                                                ┌────────┴────────┐
                                            confident match     still nothing
                                                │                     │
                                  stream synthesis from        stream a drafted
                                  the one matched article       article, publish +
                                  (source: knowledge_base)       index it immediately
                                                │                (source: drafted_article)
                                                └──────────┬──────────┘
                                                            ▼
                                              ChatResponse events → SSE →
                                              UI renders with blinking cursor
```

## 🎫 Log as Ticket Flow

```
USER clicks "Log as Ticket" on the current conversation
                 │
                 ▼
   POST /api/ticket  →  guardrails.screen(transcript)  → blocked? 400, no ticket filed
                 │
                 ▼
   phi_filter.redact_history()  (soft-mask email/phone/IP)
                 │
                 ▼
   ticket_writer.build_ticket(team, history)
     LLM (temperature=0.2) turns raw comments into:
       { summary, description, priority }
                 │
                 ▼
   okta_client.lookup_user(email)  → requester name/department only
                 │
                 ▼
   jira_client.create_ticket(...)  → files in the team's Jira project
                 │
                 ▼
   TicketResponse: { ticket_key, ticket_url, summary, description }
```

---

## 🚀 Quick Start

```bash
git clone https://github.com/emran-Automation-Techlead/aria-service-desk-assistant.git
cd aria-service-desk-assistant
pip install -r requirements.txt
cp .env.example .env      # keep ARIA_MOCK_MODE=true to run fully offline
python main.py
```

Open **http://localhost:7862**

### Going live against real Jira / Confluence / Okta

Set `ARIA_MOCK_MODE=false` in `.env` and fill in:

```env
JIRA_BASE_URL=https://yourcompany.atlassian.net
JIRA_EMAIL=aria-bot@yourcompany.com
JIRA_API_TOKEN=...

CONFLUENCE_BASE_URL=https://yourcompany.atlassian.net
CONFLUENCE_EMAIL=aria-bot@yourcompany.com
CONFLUENCE_API_TOKEN=...

OKTA_DOMAIN=yourcompany.okta.com
OKTA_API_TOKEN=...
```

No code changes required — `confluence_client.py`, `jira_client.py`, and `okta_client.py` switch from the local JSON stores to live REST calls automatically. The vector index (`vector_store.py`) indexes whatever `confluence_client.search()` returns either way, so RAG retrieval works identically against mock or live content.

### Running the MCP server

```bash
python mcp_server.py
```

Point any MCP host (Claude Desktop, Claude Code) at this command to give it `search_knowledge_base`, `create_confluence_article`, `create_jira_ticket`, and `lookup_okta_user` as tools — each screened by the same guardrails as the chat UI.

---

## 🛡️ Guardrails vs. soft redaction

Two distinct layers, on purpose:

- **`guardrails.py` — hard refusal.** Runs before anything reaches an LLM, Confluence, or Jira. Blocks outright: high-sensitivity PHI/PII (SSNs, card numbers, medical record numbers, via regex), sexual/nudity content (OpenAI Moderation API, scored against thresholds tuned tighter than the API's own `flagged` default — validated so ordinary IT phrasing like "kill the process" scores near zero), and security-risk requests (credential theft, bypassing MFA/auth, malware, exfiltration — a curated keyword heuristic plus the moderation model's illicit-content score, since phrasing like this isn't reliably caught by moderation alone).
- **`phi_filter.py` — soft redaction.** Low-sensitivity, operationally-necessary contact details (email, phone, IP) are masked with `[REDACTED-<TYPE>]` but the message still goes through — a ticket needs a reporter's email, a network issue needs an IP. API responses carry a `redactions` audit list (type + count).

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI + Uvicorn, SSE streaming |
| **AI** | OpenAI (`gpt-4o-mini` by default, `temperature=0.2` everywhere) |
| **Orchestration** | LangChain (`langchain-openai` + `langchain-core`) for the intake-probing/reword loop |
| **RAG** | ChromaDB — chunked, embedded (`text-embedding-3-small`), confidence-scored retrieval |
| **Safety** | OpenAI Moderation API + custom PHI/PII and security-risk pattern checks |
| **Agent protocol** | MCP (`mcp` Python SDK, stdio transport) |
| **Integrations** | Jira Service Desk REST, Confluence Cloud REST, Okta REST — each with an offline JSON-backed mock mode |
| **Config** | Pydantic Settings v2 · python-dotenv |
| **UI** | Single-page vanilla HTML/JS chat widget — SSE consumer, musing status, blinking cursor |

---

## 📄 License

MIT

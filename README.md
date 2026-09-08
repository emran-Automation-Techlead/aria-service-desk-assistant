# 🤖 ARIA — Internal Knowledge & Ticketing Assistant

> **MCP-connected chatbot for IT operations teams — answers from Confluence, writes new articles when nothing exists, and turns chat into clean Jira tickets**

ARIA sits in front of six internal teams — **Service Desk, Command Center, Network, Linux, Database, and Windows Engineering** — as one chat interface. It answers from each team's Confluence space, and when no article covers the question, it drafts one, publishes it, and answers from the draft — so the knowledge base grows itself. A **"Log as Ticket"** action takes the raw back-and-forth of the chat and turns it into a well-formed Jira Service Desk ticket, not a dump of the conversation.

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.112+-009688?style=flat&logo=fastapi&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-Server-8b5cf6?style=flat)
![License](https://img.shields.io/badge/License-MIT-green?style=flat)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🗂️ **Six team spaces** | Service Desk · Command Center · Network · Linux · Database · Windows Engineering, each with its own Confluence space + Jira project |
| 📚 **KB-grounded answers** | Answers are synthesized only from that team's existing articles — no invented steps |
| ✍️ **Self-healing KB** | No matching article → ARIA drafts one, publishes it to Confluence, and answers from it; the next person with the same question finds it already there |
| 🎫 **Log as Ticket** | Converts the chat's raw comments into a clean summary + description + priority and files it in Jira Service Desk |
| 🛡️ **PHI-safe wrapper** | Emails, phone numbers, SSNs, card numbers, MRNs, and IPs are redacted *before* anything reaches the LLM, Confluence, or Jira |
| 🔌 **MCP server** | Every capability (`search_knowledge_base`, `create_confluence_article`, `create_jira_ticket`, `lookup_okta_user`) is also exposed as an MCP tool for Claude Desktop / Claude Code |
| 🧪 **Offline-first** | Ships with a local JSON knowledge base + ticket store — fully demo-able with no Jira/Confluence/Okta tenant; flip one flag to go live |

---

## 🏗️ Project Structure

```
aria-service-desk-assistant/
├── main.py                 ← FastAPI app: /api/chat, /api/ticket, /api/teams
├── mcp_server.py            ← Same capabilities exposed over MCP (stdio)
├── config.py                ← Settings: mock mode + Jira/Confluence/Okta creds
├── models.py                 ← Team enum + Pydantic request/response models
├── prompts.py                ← Prompt templates (answer, draft article, ticket writer)
├── knowledge_agent.py        ← RAG-lite over Confluence: answer or draft+publish
├── ticket_writer.py           ← Chat transcript → clean ticket summary/description
├── phi_filter.py               ← Regex-based PHI/PII redaction, applied before any external call
├── confluence_client.py        ← Search + publish articles (mock JSON ↔ real Confluence REST)
├── jira_client.py               ← Create tickets (mock JSON ↔ real Jira REST)
├── okta_client.py                ← Requester lookup, name/department only (mock ↔ real Okta REST)
├── kb_store.py                    ← Local JSON-backed knowledge base (the mock/offline Confluence)
├── data/
│   ├── mock_kb.json                ← Seed articles per team
│   └── mock_tickets.json (runtime)  ← Filed tickets in mock mode
└── static/
    └── index.html                   ← Chat UI: team picker, chat window, Log as Ticket
```

---

## 🔄 Chat Flow

```
┌────────────────────────────────────────────────────────────────────────┐
│ USER picks a team, asks a question                                      │
└───────────────────────────────┬────────────────────────────────────────┘
                                 ▼
                   POST /api/chat  →  phi_filter.redact()
                                 │
                                 ▼
              knowledge_agent.answer(team, question, history)
                                 │
                confluence_client.search(team) → team's articles
                                 │
                    LLM: does an article answer this?
                     ┌───────────┴───────────┐
                    YES                       NO
                     │                         │
        answer synthesized from            LLM drafts a new article
        the matching article               confluence_client.publish_article()
        (source: knowledge_base)            (source: drafted_article)
                     │                         │
                     └───────────┬─────────────┘
                                 ▼
                     ChatResponse → rendered in UI
```

## 🎫 Log as Ticket Flow

```
USER clicks "Log as Ticket" on the current conversation
                 │
                 ▼
   POST /api/ticket  →  phi_filter.redact_history()
                 │
                 ▼
   ticket_writer.build_ticket(team, history)
     LLM turns raw comments into:
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

No code changes required — `confluence_client.py`, `jira_client.py`, and `okta_client.py` switch from the local JSON stores to live REST calls automatically.

### Running the MCP server

```bash
python mcp_server.py
```

Point any MCP host (Claude Desktop, Claude Code) at this command to give it `search_knowledge_base`, `create_confluence_article`, `create_jira_ticket`, and `lookup_okta_user` as tools.

---

## 🛡️ PHI-safe wrapper

Every message — chat input, chat history, and the ticket transcript — passes through `phi_filter.redact()` before it reaches the LLM, Confluence, or Jira. Emails, US phone numbers, SSNs, card-number-shaped digit runs, MRNs, and IPv4 addresses are replaced with `[REDACTED-<TYPE>]` tokens; the API responses carry a `redactions` audit list (type + count) so the caller knows what was stripped without ever seeing the raw value again. Okta lookups are similarly scoped to non-sensitive fields only (name, department, manager).

---

## 🛠️ Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI + Uvicorn |
| **AI** | OpenAI (`gpt-4o-mini` by default, configurable) |
| **Agent protocol** | MCP (`mcp` Python SDK, stdio transport) |
| **Integrations** | Jira Service Desk REST, Confluence Cloud REST, Okta REST — each with an offline JSON-backed mock mode |
| **Config** | Pydantic Settings v2 · python-dotenv |
| **UI** | Single-page vanilla HTML/JS chat widget served by FastAPI |

---

## 📄 License

MIT

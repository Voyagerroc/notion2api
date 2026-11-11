# Notion2API & Notion AI Terminal Agent

> **Turn Notion AI into an Autonomous CLI Agent & OpenAI-Compatible Local API Bridge.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-orange.svg)](https://platform.openai.com/docs/api-reference)

---

## 🌟 Overview / Genel Bakış

**Notion2API** bridges the Notion AI Web API into two production-grade workflows:
1. **Autonomous Terminal AI Agent (`ask_notion.py` / `notion-ai`)**: A full-featured terminal development companion equipped with a ReAct tool-calling loop, an AST-validated safe code patcher with instant rollback, a background SQLite task queue with worker leasing, and direct Notion workspace publishing.
2. **Local OpenAI-Compatible API Server (`app.server:app`)**: Exposes standard `/v1/chat/completions` endpoints for Cursor, Cline, Cherry Studio, Zotero, or any custom LLM client with streaming (SSE), thinking traces, and live web search visibility.

---

## 🚀 Key Features / Öne Çıkan Özellikler

### 1. 🤖 Autonomous ReAct Agent Loop (`-a` / `--agent`)
- Confined filesystem tools (`read_file`, `read_file_range`, `list_files`, `file_info`).
- Built-in error fingerprinter that catches repetitive tool failures and prevents endless loops.
- Model-agnostic XML/JSON tool call parsing with fallback AST evaluation.

### 2. 🛡️ Safe AST Code Patcher & Rollback (`-e` / `--rollback`)
- Atomic writes via `.tmp` file syncing before swap (`os.replace`).
- Python syntax tree verification (`ast.parse`) prevents broken code from touching disk.
- Automatic SHA-256 validated `.bak` creation with color-coded diff review (`[e/H]` confirmation).
- 1-command rollback: `notion-ai --rollback target.py`.

### 3. ⚡ Persistent Task Queue & Background Worker (`--queue-add` / `--worker`)
- SQLite-backed state machine with atomic task claiming (`BEGIN IMMEDIATE`).
- Worker heartbeats, dead worker recovery, and exponential backoff retry.
- Phased task execution (`execute` → `notion_save`) prevents expensive code re-runs on network timeouts.

### 4. 📝 Direct Notion Workspace Publishing (`-s` / `--save-to-notion`)
- Save terminal reasoning, agent summaries, or code diff reports directly to your private Notion workspace pages.
- Native markdown conversion and headless CLI sync.

### 5. 🌐 Local OpenAI-Compatible Server
- 34+ AI models supported: Claude 3.5 Sonnet, Claude Opus, GPT-4o, Gemini 1.5, DeepSeek, and Auto.
- Multi-account pooling with round-robin rotation and cooldown handling.
- Streaming reasoning (`thinking`) and live web search traces.

---

## 📦 Quick Start / Hızlı Başlangıç

### 1. Clone the Repository / Depoyu Klonlayın
```bash
git clone https://github.com/Voyagerroc/notion2api.git
cd notion2api
```

### 2. Install Dependencies / Bağımlılıkları Yükleyin
```bash
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Setup Credentials / Notion Girişi Yapın
Run the automated login script to capture your active Notion session:
```bash
python login.py
```
*Alternatively, copy `.env.example` to `.env` and fill in `NOTION_ACCOUNTS` manually.*

---

## 💻 CLI Usage Guide / Terminal Kullanım Kılavuzu

You can run `python ask_notion.py` directly, or link it globally as `notion-ai`:

### Basic Prompting & Model Selection
```bash
# Ask using the default smart model
python ask_notion.py "Explain quantum computing in 3 bullets"

# Select specific model (sonnet, opus, gpt, gemini, auto)
python ask_notion.py -m sonnet "Write a Python script for exponential backoff"
```

### Context-Aware Prompting (Reading Files)
```bash
# Feed one or more local files into context
python ask_notion.py -f app/patcher.py "Analyze potential edge cases in this code"
```

### Autonomous Safe Code Patching (`-e` & `--rollback`)
```bash
# Analyze and patch an existing file with interactive diff review
python ask_notion.py -e main.py "Add UTF-8 encoding verification and clean exit handling"

# Rollback changes if anything goes wrong
python ask_notion.py --rollback main.py
```

### Autonomous ReAct Agent Loop (`-a`)
```bash
# Let Notion AI explore files, inspect schemas, and formulate answers
python ask_notion.py -a "List files in the app folder and summarize what each module does"
```

### Background Task Queue (`--queue-add` & `--worker`)
```bash
# Queue long-running tasks
python ask_notion.py --queue-add "Refactor Server" "Refactor app/server.py for better error handling"

# List active and completed tasks
python ask_notion.py --queue-list

# Run worker process (can be scheduled or run in background)
python ask_notion.py --worker
```

### Direct Notion Page Publishing (`-s`)
```bash
# Run analysis and publish report directly to your Notion workspace
python ask_notion.py -s "Architecture Decision Record" "Draft ADR for migration to SQLite queue"
```

---

## 🖥️ Running the OpenAI-Compatible API Server

Start the local server (supports Cherry Studio, Cline, Cursor, Open WebUI):
```bash
python -m uvicorn app.server:app --host 127.0.0.1 --port 8765
```
Or use the provided launcher:
```bash
# Windows
.\Baslat-Notion-AI.bat
```

### Web UI
Open your browser at `http://127.0.0.1:8765` for the built-in dark-mode chat interface with thinking panels and search logs.

---

## 🏗️ Architecture / Mimari Yapı

```
notion2api/
├── app/
│   ├── agent_loop.py      # Autonomous ReAct loop with loop breaking & error fingerprinting
│   ├── patcher.py         # Safe AST-validated atomic patcher with SHA-256 rollback
│   ├── task_queue.py      # SQLite persistent queue with worker leases & heartbeat
│   ├── tools.py           # Confined filesystem tools (read, list, slice)
│   ├── notion_client.py   # Notion AI reverse-engineered client & TLS impersonation
│   ├── conversation.py    # Sliding window conversation manager
│   ├── server.py          # FastAPI OpenAI-compatible API server
│   └── config.py          # Environment & account rotation configuration
├── ask_notion.py          # Unified CLI entrypoint (agent, worker, patcher, chat)
├── login.py               # Chrome-based Notion credential extractor
├── Baslat-Notion-AI.bat   # Windows one-click server & UI starter
└── requirements.txt       # Python dependencies
```

---

## 🤝 Contributing & Community / Katkıda Bulunma

We welcome contributions from developers worldwide! This project is under active self-evolution:

- **Issues & Discussions**: Check the [Issues Tab](https://github.com/Voyagerroc/notion2api/issues) for open roadmaps and RFCs.
- **Pull Requests**:
  1. Fork the repository.
  2. Create your feature branch (`git checkout -b feature/amazing-feature`).
  3. Commit your changes (`git commit -m 'feat: Add amazing feature'`).
  4. Push to the branch (`git push origin feature/amazing-feature`).
  5. Open a Pull Request.

---

## 📄 License

Distributed under the MIT License. See `LICENSE` for more information.

---

<p align="center">
  Crafted with ❤️ by <a href="https://github.com/Voyagerroc">Voyagerroc</a> and the open-source community.
</p>

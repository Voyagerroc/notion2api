# Notion2API & Notion AI Terminal Agent

> **Turn Notion AI into an Autonomous CLI Agent & OpenAI-Compatible Local API Bridge.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![OpenAI Compatible](https://img.shields.io/badge/OpenAI-Compatible-orange.svg)](https://platform.openai.com/docs/api-reference)

---

## 🌟 Overview / Genel Bakış

**Notion2API** bridges the Notion AI Web API into two experimental local workflows:
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
- Python syntax tree verification (`ast.parse`) checks Python syntax before replacement; it does not prove semantic correctness or provide an OS sandbox.
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
- Model aliases are listed by `notion-ai --list-models`; this is a local mapping, not verification of current account access or provider availability.
- Multi-account pooling with round-robin rotation and cooldown handling.
- Streaming reasoning (`thinking`) and live web search traces.

---

## Origin and credits

This project is a derivative of [maverickxone/notion2api](https://github.com/maverickxone/notion2api). It was compared against upstream commit `cc7fcf4` (2026-10-23): 43 of the 55 file paths the two repositories share are byte-identical, and 12 differ. The upstream README declares the MIT License; upstream has no separate LICENSE file. This repository adds the terminal agent, patcher, task queue, packaging, tests and CI, and modifies the core server and client modules. See [NOTICE](NOTICE) for details.

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

python -m pip install -e .
```

### 3. Setup Credentials / Notion Girişi Yapın
Run the automated login script to capture your active Notion session:
```bash
voyager-relay login
```
Use your own eligible Notion account and enter credentials only in the local masked login flow. Never paste tokens into agent chat. This unofficial integration is subject to provider terms, plans and quotas; no free inference or model availability is guaranteed.

---

## 💻 CLI Usage Guide / Terminal Kullanım Kılavuzu

The editable install creates **both** `notion-ai` and `voyager-relay`, plus `notion-ai-server`. While the virtual environment is activated, these commands work from any directory; no copied `.cmd` wrappers or shell aliases are needed. Existing `python ask_notion.py` usage remains supported.

```console
notion-ai --help
voyager-relay --help
notion-ai-server --help
```

These help commands are offline and do not read credentials or create state. To install commands in a persistent user tool environment instead, run `uv tool install --editable .` from the checkout and add the path reported by `uv tool dir --bin` to your PATH. No shell profile is modified by this project.

For a reproducible development environment, install uv 0.12.5 and use `uv sync --locked --extra dev`; run commands with `uv run --locked --extra dev`. `uv.lock` pins the resolved dependency graph with platform/Python markers. A plain pip editable install uses the declared ranges rather than the lock.

### Local state and compatibility

A source/editable checkout keeps its existing `.env`, `accounts.json` and `data/` locations. A wheel installation stores state below `%LOCALAPPDATA%/notion2api` on Windows or `$XDG_DATA_HOME/notion2api` (default `~/.local/share/notion2api`) on Linux. Set `NOTION2API_HOME` before running **any** command to use a different isolated state directory; credentials are not copied automatically. Explicit environment variables take precedence over `.env`.

`whoami` describes saved local configuration; it does not verify the remote session, model access or cost. `logout` removes local login/session files, not remote sessions or all conversation databases. See [SECURITY.md](SECURITY.md).


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
notion-ai-server --host 127.0.0.1 --port 8765
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

## Validation and boundaries

```console
uv run --locked --extra dev ruff check .
uv run --locked --extra dev pytest tests/ -q
uv build --wheel
uv run --locked --extra dev python scripts/check_distribution.py
```

CI runs the offline suite, basic source/test lint, wheel-content checks and actual installed-command smoke checks on Windows/Linux with Python 3.10, 3.11 and 3.13. Synthetic fixtures and mocked upstream calls do not establish live Notion access, production readiness or legal compliance. AST validation is a syntax safeguard, not an OS sandbox or correctness guarantee. Outgoing prompts/files require review. Direct workspace publishing additionally requires the separately configured `ntn` CLI.

## 🤝 Contributing & Community / Katkıda Bulunma

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the locked setup, test isolation and dependency-update procedure.

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

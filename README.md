# BEAIT — FL Studio AI Assistant

A Windows desktop companion application that translates natural-language production instructions (Turkish and English) into structured, verifiable FL Studio workflows using MIDI scripting, mixer routing, automated UI control, and multi-provider LLM planning.

> **Note:** BEAIT is an external assistant and orchestration layer for an existing FL Studio 2025 installation—not a standalone DAW.

---

## Overview

BEAIT bridges natural-language creative direction with live DAW execution through a split-pane desktop workspace (`Tauri 2 + React + TypeScript`) backed by a local `FastAPI` orchestration service (`127.0.0.1:8000`). Requests are converted into typed, bounded `ActionPlan` steps executed via the `flstudio-mcp` SysEx/TCP bridge (`127.0.0.1:9787`) and native Windows GUI automation, followed by state readback verification.

---

## Key Capabilities

- **Natural-Language Production Orchestration:** Parses tempo, key, scale, genre, instrumentation, and song sections (`Intro`, `Build`, `Drop`, `Breakdown`, `Outro`) into multi-track patterns, Piano Roll MIDI notes, mixer routing, and Playlist placement.
- **Multi-Chat Workspaces with Isolated AI Memory:** Supports creating, renaming, switching, and deleting independent chat sessions persisted in SQLite (`chat_sessions`, `chat_messages`, `chat_session_plans`). Each chat maintains its own conversational and musical context, while new chats start with a clean state.
- **Multi-Provider AI Planning & Song Research:** Integrates OpenAI, Google Gemini (with optional Google Search song research grounding), Anthropic Claude, or local OpenAI-compatible endpoints (e.g., Ollama / LM Studio), with deterministic procedural fallback via `CreativeBeatEngine`.
- **Mixing, FX Chains & Limiter Safeguards:** Loads role-appropriate FX chains, balances stereo levels/panning via `MixMasterEngine`, and constrains master ceiling/clipper thresholds to prevent unintended `-INF dB` muting or digital clipping.
- **Readback Verification & Approval Gating:** Checks applied state (tempo, channel rack, mixer parameters, exports) after writes and gates high-risk or destructive operations behind explicit approval prompts.
- **Privacy & Secret Hygiene:** Audio renders and `.flp` files are excluded from LLM prompts by default (`allow_audio_upload=False`); runtime logs and diagnostics automatically mask API keys and user paths.

---

## Architecture

```text
+-------------------------------------------------------------------+
|               Desktop Companion (Tauri 2 / React / Vite)          |
|  Multi-Chat UI | Live Action Feed | Context Inspector | Settings  |
+---------------------------------+---------------------------------+
                                  | HTTP & WebSocket (127.0.0.1:8000)
                                  v
+-------------------------------------------------------------------+
|                   Python FastAPI Backend (Uvicorn)                |
|  TaskExecutionManager | ProducerOrchestrator | VerificationEngine |
|  ModelProviderAdapter | MixMasterEngine      | SQLite Persistence |
+--------------------+------------------------------+---------------+
                     | TCP (127.0.0.1:9787)         | Windows UI / stdio
                     v                              v
          +---------------------+        +-------------------------+
          | flstudio-mcp Daemon |        | FL Studio GUI / HCU     |
          | (MIDI SysEx Bridge) |        | (Live Automation Layer) |
          +----------+----------+        +-------------------------+
                     |
                     v
          +---------------------+
          |   FL Studio 2025    |
          +---------------------+
```

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Desktop UI | Tauri 2, React 18, TypeScript, Tailwind CSS, Zustand |
| Backend API | Python 3.12+ (tested on 3.14), FastAPI, Uvicorn, WebSockets, Pydantic |
| Persistence | SQLite (`backend/data/fl_assistant.db`) |
| FL Studio Bridge | `flstudio-mcp` daemon & controller script (`device_FLStudioMCP.py`) |
| Music & Audio | `mido`, `python-rtmidi`, `pretty_midi`, `music21`, `librosa`, `soundfile`, `numpy` |
| GUI Automation | Python Windows UI automation (`fl_live_gui.py`) + optional Microsoft Hybrid Computer Use |

---

## Prerequisites

- **OS:** Windows 10 or Windows 11 (64-bit)
- **DAW:** FL Studio 2025 (with `FLStudioMCP` controller script configured in Hardware settings)
- **Python:** 3.12 or newer
- **Node.js:** 20 or newer (with `npm` or `pnpm`)
- **Optional (Tauri native packaging):** Rust & Cargo, MSVC C++ Build Tools, WebView2
- **Optional (Virtual MIDI / HCU binaries):** `loopMIDI`, `.NET 8+ SDK`, and `Go 1.22+` (to build `external/Hybrid-Computer-Use`)

---

## Quick Start

### 1. Clone & Fetch External Dependencies

```powershell
git clone https://github.com/EmirhanEtem/BEAIT.git
cd BEAIT
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_external.ps1
```

### 2. Configure Python Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
cd ..
```

### 3. Install Frontend Dependencies

```powershell
npm --prefix apps\desktop install
```

### 4. Configure Environment Variables

```powershell
copy .env.example .env
```

Edit `.env` to set `LLM_PROVIDER` (`openai`, `gemini`, `anthropic`, or `local`) and the corresponding API key or local endpoint. Never commit `.env` to version control.

### 5. Launch the Assistant

Run the unified launcher script (syncs the FL Studio controller script, starts the MCP daemon on port `9787`, runs system diagnostics, launches FastAPI on `127.0.0.1:8000`, and starts the desktop UI on `localhost:5173`):

```powershell
.\scripts\start_assistant.ps1
```

Or run backend diagnostics only:

```powershell
.\scripts\start_assistant.ps1 -CheckOnly
```

---

## Testing & Build Verification

### Backend Unit & Integration Tests

Offline tests skip live FL Studio and built HCU binary requirements via pytest markers (`backend/pytest.ini`):

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend\tests -m "not real_fl and not real_hcu"
```

### Frontend Type-Check & Production Bundle

```powershell
npm --prefix apps\desktop run build
```

---

## Repository Structure

```text
BEAIT/
├── apps/desktop/       # Tauri 2 + React + TypeScript desktop interface
├── backend/            # FastAPI backend, orchestration, music/mix engines, SQLite store, tests
├── configs/            # Pinned external dependencies and genre presets
├── docs/               # Architecture, setup, security, troubleshooting guides (TR)
├── external/           # Uncommitted external tools populated via scripts/fetch_external.ps1
├── scripts/            # Windows bootstrap and unified launcher scripts
├── .env.example        # Environment variable template
├── CHANGELOG.md        # Milestone and phase history (TR)
└── README.md
```

---

## Documentation

Detailed technical documentation is located in [`docs/`](docs/):

- [System Architecture (TR)](docs/architecture.md)
- [Windows Setup Guide (TR)](docs/setup-windows.md)
- [FL Studio Integration (TR)](docs/fl-studio-integration.md)
- [Security & Approval Model (TR)](docs/security.md)
- [User Guide (TR)](docs/user-guide.md)
- [Troubleshooting (TR)](docs/troubleshooting.md)
- [Changelog (TR)](CHANGELOG.md)

---

## License

For private/internal use. Third-party dependency licenses are documented in [`docs/license-inventory.md`](docs/license-inventory.md).

# FL Studio AI Assistant

## Agent-Ready Project Specification & Implementation Brief

**Document type:** Product Requirements + Technical Architecture +
Phased Implementation Plan\
**Target platform:** Windows 10/11\
**Primary application:** FL Studio\
**Product principle:** This product is an AI assistant that operates FL
Studio. It is NOT a replacement DAW, a standalone music-production
application, or a clone of FL Studio.

------------------------------------------------------------------------

# 0. CRITICAL INSTRUCTIONS FOR THE IMPLEMENTING AGENT

You are the senior software architect and implementation agent
responsible for building this product.

Your task is to design, implement, test, and document a Windows desktop
AI assistant that can control an already-installed copy of FL Studio
through a hybrid control architecture.

## 0.1 Mandatory operating rules

1.  **Do not build a DAW.** FL Studio remains the actual music
    production environment. Do not recreate its Piano Roll, Playlist,
    Mixer, Channel Rack, plugin host, or audio engine.
2.  Build a companion desktop application that communicates with the
    user and coordinates actions inside FL Studio.
3.  Use a **hybrid control architecture**:
    -   Use FL Studio's scripting/MCP integration for reliable,
        structured DAW operations whenever supported.
    -   Use GUI automation for operations that are unavailable through
        the API/MCP integration.
    -   Use local Python services for file inspection, sample analysis,
        audio analysis, and other tasks that do not require direct DAW
        interaction.
4.  The user must be able to observe what the assistant is doing. Show
    action descriptions, progress, screenshots/screen previews where
    appropriate, and a synchronized cursor/action indicator in the
    companion interface.
5.  Do not falsely claim that a cursor is moving visibly in the real
    Windows desktop if the selected automation backend performs
    background input. The companion application's cursor visualization
    must accurately represent the actual action target and timing.
6.  Never execute an unverified destructive action silently. Use
    confirmations, checkpoints, backups, and rollback where feasible.
7.  Every action must have a traceable status: planned, running,
    succeeded, failed, skipped, or awaiting approval.
8.  Implement robust error handling. Never report an action as
    successful merely because a command was sent. Verify the resulting
    state.
9.  Do not hard-code one LLM provider. Build a provider abstraction so
    the system can support cloud and local models.
10. Keep secrets out of source code, logs, screenshots, and project
    files.
11. Write tests for core logic and integration boundaries. Document what
    is mocked and what is genuinely connected to FL Studio.
12. Do not silently skip a phase, weaken its acceptance criteria, or
    start the next phase without the user's approval.

## 0.2 Mandatory phase-gate rule --- IMPORTANT

Development MUST be divided into the phases in this document.

At the end of **every phase**, do the following:

1.  Stop implementation.

2.  Run that phase's tests and acceptance checks.

3.  Produce a concise phase-completion report containing:

    -   What was implemented.
    -   Files and major modules created or changed.
    -   Tests executed and their results.
    -   What works in a real FL Studio environment versus what is
        mocked.
    -   Known bugs, limitations, and technical debt.
    -   Screenshots, logs, or a short demo when useful.
    -   Any decisions that require the user's input.

4.  Tell the user explicitly that the phase is complete.

5.  Ask this exact question (or a natural Turkish equivalent):

    **"Phase \[N\] tamamlandı. Test sonuçları ve çıktılar yukarıda.
    Phase \[N+1\]'e geçmemi onaylıyor musun?"**

6.  **Wait for the user's explicit approval.**

7.  Do not begin the next phase until the user approves it.

A vague response, silence, or an unrelated message is not approval. If
the user requests changes, remain in the current phase, implement the
requested changes, rerun the relevant tests, and ask for approval again.

Do not combine multiple phases into one delivery. Do not automatically
continue after reporting completion. The user must control phase
transitions.

------------------------------------------------------------------------

# 1. PRODUCT VISION

Build a polished Windows desktop companion called **FL Studio AI
Assistant** (working name).

The user describes a musical goal in natural language. The assistant
interprets the request, plans the necessary production steps, and
carries them out inside the user's existing FL Studio session.

Example request:

> "FL Studio'da 128 BPM, A minor tonunda melodic techno tarzında bir
> başlangıç oluştur. Kick ve percussion düzenini kur, bas ve ana
> melodiyi yaz. Sonra temel bir arrangement hazırla."

The assistant should be able to: - Inspect the current FL Studio project
and understand its available context. - Read relevant project
information such as tempo, channels, patterns, mixer state, and
transport state where supported. - Plan a sequence of music-production
actions. - Execute supported operations through FL Studio MCP/API. - Use
visible GUI automation for operations that are only available through FL
Studio's interface. - Search and inspect the user's sample folders with
permission. - Create and edit MIDI patterns, melodies, chords,
basslines, and drum patterns. - Configure supported mixer and plugin
parameters. - Arrange patterns and clips in the Playlist where
supported. - Render/export through the GUI when no reliable API is
available. - Analyze rendered audio and report issues or improvement
suggestions. - Show the user a live activity feed and a clear record of
every operation.

The assistant should behave like a production collaborator, not an
uncontrollable macro recorder. It should explain its plan, execute
carefully, verify results, and allow the user to intervene.

## 1.1 Product boundaries

### In scope

-   Windows companion desktop app.
-   Chat-based interaction.
-   FL Studio project context and control.
-   MCP/API integration.
-   GUI automation fallback.
-   Music-generation and arrangement logic.
-   Audio and sample analysis.
-   Action history, verification, checkpoints, and recovery.
-   User preferences and project memory.

### Out of scope for the initial MVP

-   Replacing FL Studio.
-   Building a new DAW or custom audio workstation.
-   Reimplementing VST hosting.
-   Building a commercial sample marketplace.
-   Automatically distributing or publishing tracks.
-   Guaranteeing professional mastering quality.
-   Training a foundation music model from scratch.
-   Unattended destructive project editing.
-   Supporting every DAW. FL Studio is the only target for the first
    release.

------------------------------------------------------------------------

# 2. USER EXPERIENCE

## 2.1 Desktop companion interface

Build a desktop application that can remain open beside FL Studio. It
must not obstruct normal FL Studio usage.

Suggested layout:

### A. Main chat panel

-   Natural-language input.
-   Conversation history.
-   User and assistant messages.
-   Display of the current project name when available.
-   Clear distinction between suggestions, planned actions, and
    completed actions.
-   Ability to stop an active task.

### B. Live activity panel

Show each action as it happens, for example: - Reading FL Studio project
state. - Setting tempo to 128 BPM. - Creating a drum pattern. - Writing
MIDI notes. - Opening a plugin window. - Selecting a preset. - Moving a
Playlist clip. - Rendering the project. - Analyzing the exported audio.

Each action should display: - Action name. - Short explanation. - Target
application/window. - Start time and duration. - Current status. -
Verification result. - Error details, if any.

### C. Screen/activity view

-   Show a screenshot or screen preview when useful.
-   Highlight the target control or area when possible.
-   Show a cursor/action marker synchronized with the automation event.
-   Make it clear whether the action is happening in the real desktop or
    is only being represented in the companion UI.
-   Do not capture or transmit the desktop continuously without the
    user's knowledge.
-   Provide a pause/stop control.

### D. Project context panel

Display known information, with an explicit "unknown" state where
unavailable: - Project title/path. - FL Studio version, if detectable. -
Tempo. - Time signature. - Current pattern/track context. - Channel
list. - Mixer channels. - Current transport state. - Detected key/scale
only when derived from actual project/audio evidence or explicitly
provided by the user.

### E. Settings

-   Model provider and model selection.
-   API key management using secure OS storage where feasible.
-   Local model configuration.
-   FL Studio MCP connection status.
-   GUI automation connection status.
-   Sample-library directories.
-   Permission settings.
-   Logging and privacy settings.
-   Language setting (Turkish initially; architecture ready for
    English).

## 2.2 Interaction principles

-   Before a complex task, show a short action plan.
-   For routine, reversible operations, execute after the user asks.
-   Ask for approval before destructive, irreversible, expensive, or
    privacy-sensitive operations.
-   Always provide a global Stop button.
-   If a task fails, explain the failed step and offer a safe recovery
    path.
-   Do not hide uncertainty. If the assistant cannot verify an
    operation, say so.
-   Never fabricate project state, plugin names, sample availability, or
    successful actions.

------------------------------------------------------------------------

# 3. TECHNICAL ARCHITECTURE

## 3.1 High-level architecture

``` text
┌──────────────────────────────────────────────────────────┐
│                 Windows Desktop Companion                │
│                                                          │
│  Chat | Activity Feed | Screen Preview | Cursor Overlay  │
│  Project Context | Settings | Stop / Approval Controls   │
└──────────────────────────────┬───────────────────────────┘
                               │ WebSocket / HTTP
                               ▼
┌──────────────────────────────────────────────────────────┐
│                    Python Backend                         │
│                                                          │
│  API Layer                                               │
│  ├── Session Manager                                     │
│  ├── Task Manager                                        │
│  ├── Permission Manager                                  │
│  └── WebSocket Event Publisher                           │
│                                                          │
│  Producer Orchestrator                                   │
│  ├── Intent Understanding                                │
│  ├── Context Builder                                     │
│  ├── Task Planner                                        │
│  ├── Action Router                                       │
│  ├── Verification Engine                                 │
│  └── Recovery / Checkpoint Manager                       │
│                                                          │
│  Specialist Modules                                      │
│  ├── Composer                                            │
│  ├── Rhythm Designer                                     │
│  ├── Sound Designer                                      │
│  ├── Arranger                                            │
│  └── Critic / Mixing Assistant                           │
│                                                          │
│  Integrations                                            │
│  ├── FL Studio MCP Adapter                               │
│  ├── GUI Automation Adapter                              │
│  ├── Filesystem / Sample Adapter                         │
│  └── Audio Analysis Adapter                              │
│                                                          │
│  Storage: SQLite | Logs | Project Snapshots              │
└───────────────┬──────────────────────┬───────────────────┘
                │                      │
                ▼                      ▼
       ┌────────────────┐     ┌─────────────────────┐
       │  FL Studio     │     │ Windows GUI         │
       │  MCP / Script  │     │ Automation          │
       │  Integration   │     │                     │
       └───────┬────────┘     └─────────────────────┘
               │
               ▼
       ┌────────────────┐
       │   FL Studio    │
       │  Actual DAW    │
       └────────────────┘
```

## 3.2 Recommended technology stack

### Desktop

-   Tauri 2.
-   React.
-   TypeScript.
-   Tailwind CSS.
-   A lightweight state-management solution such as Zustand.
-   WebSocket client for live backend events.

Reasoning: Tauri provides a relatively lightweight Windows desktop shell
while React/TypeScript makes it practical to build a polished companion
interface.

### Backend

-   Python 3.12.
-   FastAPI.
-   WebSocket event streaming.
-   Pydantic for validated schemas.
-   asyncio for asynchronous orchestration.
-   SQLite for MVP persistence.

### Model provider layer

Create a provider-independent interface. Support: - OpenAI-compatible
provider adapter. - Anthropic adapter. - Local model adapter where
feasible. - Mock provider for deterministic tests.

Do not bind orchestration logic to a single vendor's SDK. Keep
provider-specific code inside `model_providers/`.

The LLM should plan and interpret. It must not be trusted as the sole
source of truth for DAW state or action success.

### FL Studio integration

Primary candidate: - `rosasynthesiz/flstudio-mcp` ---
https://github.com/rosasynthesiz/flstudio-mcp

Use it as an integration dependency or a carefully maintained fork. Pin
a known working commit/version and document local modifications.

The repository currently documents a broad set of project, mixer,
channel, pattern, plugin, MIDI, and analysis tools. However, its
documented limitations matter: - Some plugin parameter writes may be
partial or unsupported. - Loading plugins and audio files may require UI
interaction. - Audio rendering/export may require UI interaction. - MIDI
note writing may require a session-specific apply step. - The
integration has specific Windows/Python/MIDI setup requirements.

Do not assume every MCP tool works in every FL Studio version. Build
capability detection and integration tests.

### GUI automation

Primary candidate: - Microsoft Research Hybrid Computer Use (HCU),
subject to compatibility and licensing review.

Repository/documentation: -
https://github.com/microsoft/hybrid-computer-use

Use its accessibility/UI Automation capabilities where available, and
screenshot/pointer/keyboard actions where necessary.

Important: - GUI automation sends real input to the signed-in desktop. -
A dedicated desktop session or controlled environment is safer for
autonomous execution. - FL Studio custom/plugin interfaces may not
expose complete accessibility information. - Add a fallback strategy for
controls that cannot be located reliably. - Never use blind coordinate
clicks when a semantic UI target can be found. - Before coordinate-based
actions, verify the active window, screen dimensions, scaling, and
target screenshot.

### Music and MIDI libraries

Evaluate and use where appropriate: - `pretty_midi` - `mido` - `music21`

Use these for music-theory operations, MIDI construction, note/event
processing, and validation. They do not replace FL Studio's audio
engine.

### Audio analysis

-   `librosa`
-   `soundfile`
-   `numpy`
-   Optional `ffmpeg` for supported conversion/inspection workflows.

Use audio analysis for: - Duration and silence detection. - RMS and peak
levels. - Clipping detection. - Spectral balance indicators. -
Tempo/onset estimates. - Basic frequency-band analysis. - Comparing a
render against requested high-level properties.

Do not present heuristic measurements as objective professional mixing
judgments.

### Persistence and logs

-   SQLite for users, settings, projects, tasks, actions, approvals, and
    preferences.
-   Structured logs with `structlog` or an equivalent.
-   Store secrets in Windows Credential Manager or a secure OS-backed
    storage mechanism where practical.
-   Never write API keys to normal logs.

------------------------------------------------------------------------

# 4. REPOSITORY STRUCTURE

Use a clean monorepo structure similar to:

``` text
fl-studio-ai-assistant/
│
├── apps/
│   └── desktop/
│       ├── src/
│       │   ├── app/
│       │   ├── components/
│       │   ├── panels/
│       │   ├── chat/
│       │   ├── activity/
│       │   ├── screen/
│       │   ├── cursor/
│       │   ├── project-context/
│       │   └── settings/
│       ├── src-tauri/
│       └── package.json
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── schemas/
│   │   ├── sessions/
│   │   ├── orchestration/
│   │   ├── agents/
│   │   │   ├── composer.py
│   │   │   ├── rhythm.py
│   │   │   ├── sound_designer.py
│   │   │   ├── arranger.py
│   │   │   └── critic.py
│   │   ├── action_router/
│   │   ├── integrations/
│   │   │   ├── fl_studio/
│   │   │   ├── computer_use/
│   │   │   ├── filesystem/
│   │   │   └── audio/
│   │   ├── music_engine/
│   │   ├── verification/
│   │   ├── recovery/
│   │   ├── project_memory/
│   │   ├── model_providers/
│   │   ├── database/
│   │   └── config/
│   └── tests/
│
├── external/
│   └── flstudio-mcp/       # pinned submodule/fork or documented dependency
│
├── docs/
│   ├── architecture.md
│   ├── setup-windows.md
│   ├── fl-studio-integration.md
│   ├── gui-automation.md
│   ├── action-protocol.md
│   ├── security.md
│   └── phase-reports/
│
├── scripts/
├── configs/
├── .env.example
├── .gitignore
└── README.md
```

The exact structure may be adjusted if there is a strong technical
reason. Document any major deviation before proceeding.

------------------------------------------------------------------------

# 5. CORE BACKEND DESIGN

## 5.1 Producer Orchestrator

The Producer Orchestrator is the central coordinator. It receives a user
request and converts it into a controlled, verifiable plan.

Responsibilities: 1. Parse the user's musical intent. 2. Identify
missing information. 3. Read the available FL Studio context. 4. Decide
which specialist logic is needed. 5. Produce a sequence of typed
actions. 6. Send actions to the Action Router. 7. Track progress and
publish events to the desktop UI. 8. Verify each result. 9. Recover
safely from failures. 10. Summarize the result and remaining
limitations.

The orchestrator must not directly execute arbitrary shell commands
generated by an LLM.

## 5.2 Specialist roles

Implement specialist modules as logical roles, not necessarily separate
autonomous LLM agents.

### Composer

-   Melody creation.
-   Chord progressions.
-   Bassline ideas.
-   Key and scale consistency.
-   Musical motif variation.

### Rhythm Designer

-   Kick patterns.
-   Snare/clap placement.
-   Hi-hats.
-   Percussion.
-   Groove and velocity variation.

### Sound Designer

-   Preset selection assistance.
-   Synth parameter suggestions.
-   Sound-layering plans.
-   Plugin configuration through supported controls.

### Arranger

-   Intro/build/drop/breakdown/outro structure.
-   Pattern and clip placement.
-   Section transitions.
-   Energy progression.

### Critic / Mixing Assistant

-   Inspect arrangement and audio.
-   Detect obvious technical issues.
-   Identify clipping, excessive silence, and level imbalance
    indicators.
-   Suggest revisions.
-   Never claim subjective quality is objectively guaranteed.

Start with one model and separate role prompts/functions. Multi-model or
multi-agent execution can be considered later if measurable benefits
justify its complexity.

## 5.3 Action Router

Every planned operation must be represented as a typed action. The
router chooses the correct execution path.

Example routing table:

  -----------------------------------------------------------------------
  Operation               Preferred route         Fallback
  ----------------------- ----------------------- -----------------------
  Read tempo              FL Studio MCP/API       UI inspection

  Change tempo            FL Studio MCP/API       GUI automation

  Read channel list       FL Studio MCP/API       UI inspection

  Create MIDI notes       FL Studio MCP/API       Piano Roll GUI

  Create drum pattern     FL Studio MCP/API       Channel Rack GUI

  Mixer parameter         MCP/API if supported    GUI automation

  Open plugin window      GUI automation          None

  Load plugin             GUI automation          None

  Load audio/sample file  GUI automation          Supported API if
                                                  verified

  Search sample folders   Filesystem adapter      None

  Analyze sample audio    Audio engine            None

  Arrange Playlist clips  MCP/API if supported    GUI automation

  Render/export           GUI automation if       Verified API if
                          required                supported

  Analyze rendered file   Audio analysis          None
  -----------------------------------------------------------------------

Routing must be based on a capability registry, not assumptions. Each
integration should advertise which operations it supports and whether
they are read-only or write-capable.

## 5.4 Action lifecycle

Use a consistent lifecycle:

``` text
PLANNED
  ↓
AWAITING_APPROVAL (only when required)
  ↓
READY
  ↓
RUNNING
  ↓
VERIFYING
  ├── SUCCEEDED
  ├── FAILED
  └── NEEDS_RECOVERY
```

Additional terminal/interruption states: - CANCELLED - SKIPPED -
TIMED_OUT

Each action must include: - `action_id` - `task_id` - `action_type` -
`target` - `parameters` - `execution_route` - `risk_level` -
`requires_approval` - `status` - `created_at` - `started_at` -
`finished_at` - `verification` - `error` - `retry_count`

Do not allow the model to invent arbitrary action types. Validate every
action against a strict schema and allowlist.

## 5.5 Verification

Examples: - After changing BPM, read BPM again and compare. - After
writing MIDI, read the pattern or inspect the resulting note events
where supported. - After changing a mixer value, read it back where
supported. - After a GUI action, take a fresh screenshot or inspect the
UI state. - After rendering, verify that the output file exists, has a
plausible size, and can be decoded. - After moving a clip, inspect the
resulting Playlist state if the integration supports it.

If verification is impossible, status must be `UNVERIFIED`, or the
action must remain failed/uncertain according to the schema. Never
silently convert "command sent" into "success".

## 5.6 Checkpoints and recovery

Before a sequence of significant project edits: - Save a new project
version or create a backup copy when possible. - Record the initial
project state that can be read safely. - Store the planned action
sequence. - Record completed actions. - Provide a stop mechanism. -
Avoid attempting a rollback that could cause more damage than the
original failure.

For MVP, a safe backup copy before major changes is preferable to a
complex undo engine.

------------------------------------------------------------------------

# 6. MUSIC-PRODUCTION LOGIC

## 6.1 User intent schema

The system should be able to represent musical requests with structured
fields such as:

``` json
{
  "genre": "melodic techno",
  "tempo_bpm": 128,
  "key": "A",
  "scale": "minor",
  "time_signature": "4/4",
  "mood": ["dark", "energetic", "atmospheric"],
  "sections": ["intro", "build", "drop"],
  "requested_elements": [
    "kick",
    "percussion",
    "bass",
    "lead_melody"
  ],
  "constraints": {
    "use_existing_project": true,
    "preserve_existing_tracks": true
  }
}
```

This is an example schema, not a requirement to ask users to fill out a
form. Natural-language input remains the primary interface.

## 6.2 Music theory and MIDI engine

Build deterministic utilities for: - Note names and MIDI note numbers. -
Scale construction. - Chord construction and inversion. - Key-aware
melody generation. - Rhythm grids. - Note duration and velocity. -
Quantization. - Pattern length and bar calculations. - MIDI event
validation.

The LLM may propose musical ideas, but deterministic code should
validate note ranges, timing, scale membership when requested, and
malformed MIDI data.

## 6.3 Sample discovery

The sample scanner should: - Search only user-approved directories. -
Support common audio formats. - Extract metadata such as duration,
sample rate, channels, and bit depth where available. - Compute useful
audio features. - Categorize samples heuristically (kick, snare, hat,
percussion, bass, melodic, ambience) with confidence scores. - Allow the
user to audition a sample before loading it. - Never upload local sample
files to a cloud provider without explicit consent.

## 6.4 Arrangement

Represent arrangement as a structured plan before editing: - Section
name. - Start bar. - End bar. - Active patterns/tracks. - Transition
notes. - Energy target. - Required automation or fills.

Do not assume that every genre follows a fixed arrangement. Ask only
when a missing decision materially blocks the task.

## 6.5 Audio analysis

For each render: - Check file integrity. - Measure duration. - Detect
silence and clipping. - Measure peak and RMS. - Estimate tempo only as
an estimate. - Provide spectral observations with caveats. - Compare
actual results to the requested brief.

The Critic role should distinguish measurable findings from subjective
musical suggestions.

------------------------------------------------------------------------

# 7. SECURITY, PRIVACY, AND SAFETY

This application can control another program and access user files.
Treat it as privileged desktop software.

Mandatory requirements: 1. Use an explicit allowlist of supported
actions. 2. Do not execute arbitrary shell commands from model output.
3. Do not browse arbitrary filesystem locations without permission. 4.
Require user approval before deleting, overwriting, moving, or uploading
files. 5. Require approval before exporting to an external location or
transmitting audio externally. 6. Do not upload project files, samples,
or renders to cloud models by default. 7. Clearly show which data is
sent to a selected model provider. 8. Store credentials securely. 9.
Redact secrets from logs. 10. Keep an auditable action history. 11.
Provide an immediate Stop control. 12. Detect unexpected active windows
before GUI automation. 13. Do not continue coordinate-based actions
after the window layout changes without revalidation. 14. Do not
automate license circumvention, unauthorized plugin access, or other
prohibited activity. 15. Document the security assumptions and
limitations of the selected GUI automation framework.

------------------------------------------------------------------------

# 8. PHASED IMPLEMENTATION PLAN

**The following phases are sequential and gated. The agent must stop
after every phase and ask the user for approval before proceeding.**

## PHASE 0 --- Repository and environment assessment

### Goal

Establish the development environment and confirm that the required
integration technologies can run on the target Windows machine.

### Tasks

-   Inspect the existing repository before changing anything.
-   Identify installed Python, Node.js, Rust, and package-manager
    versions.
-   Confirm Windows version and architecture.
-   Confirm whether FL Studio is installed and determine its version if
    possible.
-   Check whether loopMIDI or an equivalent virtual MIDI routing tool is
    installed.
-   Review the FL Studio MCP repository and pin a compatible revision.
-   Review Microsoft HCU requirements, supported Windows version, and
    licensing.
-   Create the initial repository structure.
-   Create `.gitignore` and `.env.example`.
-   Write `docs/setup-windows.md`.
-   Do not begin full product implementation in this phase.

### Deliverables

-   Environment report.
-   Dependency/version report.
-   Initial repository structure.
-   Setup instructions.
-   Compatibility/risk report.

### Acceptance criteria

-   All required tools and versions are documented.
-   The selected FL Studio MCP revision is pinned.
-   The HCU installation path is documented.
-   No secrets are committed.
-   The user can follow the setup document without guessing missing
    steps.

### Phase gate

Stop, report results, and ask for approval to begin Phase 1.

------------------------------------------------------------------------

## PHASE 1 --- Integration proof of concept

### Goal

Prove that the backend can communicate with FL Studio and that GUI
automation can inspect/control a test window safely.

### Tasks

-   Set up the FL Studio MCP integration.
-   Configure the required virtual MIDI ports if the integration
    requires them.
-   Start the MCP daemon/service.
-   Implement a minimal Python MCP client/adapter.
-   Implement connection health checks.
-   Read basic project/transport information where supported.
-   Test one safe operation, such as reading BPM and changing it to a
    test value only after user approval.
-   Restore the original BPM after the test.
-   Install and test HCU independently.
-   Capture a screenshot and inspect a UI Automation tree.
-   Test a harmless action in a controlled window before targeting FL
    Studio.
-   Record exact failures and unsupported operations.

### Deliverables

-   `backend/app/integrations/fl_studio/`
-   `backend/app/integrations/computer_use/`
-   Integration test scripts.
-   `docs/fl-studio-integration.md`
-   `docs/gui-automation.md`
-   Proof-of-concept report.

### Acceptance criteria

-   Backend can detect whether FL Studio integration is connected.
-   At least one read operation succeeds against a real FL Studio
    session.
-   A safe write operation is verified, or a documented blocker explains
    why it cannot be completed.
-   HCU can inspect a controlled window and capture a screenshot.
-   Failures are surfaced clearly and do not crash the backend.

### Phase gate

Stop and ask for explicit approval before Phase 2.

------------------------------------------------------------------------

## PHASE 2 --- Desktop companion foundation

### Goal

Create the first usable desktop companion with a working backend
connection and live action feed.

### Tasks

-   Initialize Tauri 2 + React + TypeScript.
-   Create the desktop window and application navigation.
-   Build the chat panel UI.
-   Build the activity feed.
-   Build connection-status indicators.
-   Build project-context panel with unknown/unavailable states.
-   Build settings screen.
-   Build Stop control.
-   Create FastAPI endpoints for health, session, task submission, and
    settings.
-   Implement WebSocket event streaming.
-   Define shared event schemas.
-   Display backend events in the desktop activity feed.
-   Add a screenshot preview component, but do not implement
    unrestricted continuous capture.
-   Add a cursor/action marker that visualizes known automation targets
    without falsely representing background input as real cursor
    movement.
-   Add basic logging and error notifications.

### Deliverables

-   Running Windows desktop application.
-   Running Python backend.
-   WebSocket event stream.
-   Basic UI and settings.
-   `docs/architecture.md`
-   UI/backend tests.

### Acceptance criteria

-   Desktop app launches.
-   Backend health is visible in the UI.
-   A test task can be submitted from the UI.
-   Backend events appear in the activity feed in real time.
-   Stop cancels a running mock task.
-   UI clearly distinguishes mock actions from real FL Studio actions.
-   No FL Studio production editing is required yet.

### Phase gate

Stop and ask for approval before Phase 3.

------------------------------------------------------------------------

## PHASE 3 --- Action system, permissions, and verification

### Goal

Build the safe execution foundation before allowing complex
music-production tasks.

### Tasks

-   Define typed action schemas.
-   Implement action lifecycle and state transitions.
-   Implement capability registry for integrations.
-   Implement Action Router.
-   Implement risk levels and approval requirements.
-   Implement action history persistence in SQLite.
-   Implement task cancellation.
-   Implement timeouts and bounded retries.
-   Implement verification interface.
-   Implement checkpoints and project backup workflow.
-   Implement recovery states.
-   Add deterministic mock integrations for tests.
-   Add tests for invalid actions, duplicate requests, cancellation,
    timeouts, and failed verification.

### Deliverables

-   Action system.
-   Permission/approval manager.
-   Verification engine.
-   SQLite persistence.
-   Recovery/checkpoint manager.
-   `docs/action-protocol.md`
-   Automated tests.

### Acceptance criteria

-   Invalid action types are rejected.
-   Model output cannot directly execute arbitrary shell commands.
-   Every action receives a unique ID and traceable status.
-   Approval-required actions cannot execute before approval.
-   Cancellation stops pending work and safely interrupts running work
    where possible.
-   Verification failure is visible.
-   Mock integration tests cover success and failure paths.

### Phase gate

Stop and ask for approval before Phase 4.

------------------------------------------------------------------------

## PHASE 4 --- Real FL Studio control MVP

### Goal

Allow the assistant to inspect and control a limited but useful set of
real FL Studio functions.

### Initial supported capabilities

1.  Read project/transport context where supported.
2.  Read and set BPM.
3.  Read channel/pattern context where supported.
4.  Create or edit a simple MIDI pattern.
5.  Create a basic drum pattern.
6.  Read and adjust selected mixer parameters where supported.
7.  Open a plugin window using GUI automation.
8.  Perform a small number of safe GUI operations with verification.

### Tasks

-   Implement capability discovery.
-   Implement real MCP operations behind typed adapters.
-   Implement MIDI generation utilities.
-   Validate generated MIDI before sending it to FL Studio.
-   Implement GUI fallback for explicitly unsupported operations.
-   Implement screenshot-based post-action checks.
-   Implement safe test project workflow.
-   Add a "dry run / show plan" mode.
-   Add user approval for operations that can overwrite existing work.
-   Test with a disposable FL Studio project before using a real
    project.

### Deliverables

-   Working FL Studio adapter.
-   MIDI/music utilities.
-   Capability registry entries.
-   Integration tests.
-   Demo project.
-   Phase report with a capability matrix.

### Acceptance criteria

-   The assistant can read real project context where supported.
-   It can set BPM and verify the resulting BPM.
-   It can create at least one simple MIDI/drum pattern in a test
    project.
-   It can show the action sequence in the desktop app.
-   Unsupported operations are clearly identified and routed to GUI
    automation only when safe.
-   Existing project content is not silently destroyed.

### Phase gate

Stop and ask for approval before Phase 5.

------------------------------------------------------------------------

## PHASE 5 --- GUI automation and visible operation experience

### Goal

Make GUI-only operations reliable, observable, and safe.

### Tasks

-   Implement active-window detection.
-   Implement screenshot capture on demand.
-   Implement UI Automation target discovery.
-   Implement safe click/type/keyboard/scroll/drag wrappers.
-   Implement coordinate fallback only after screenshot and window
    validation.
-   Implement stale-target detection.
-   Implement focus checks.
-   Implement cursor/action visualization in the companion app.
-   Implement action markers and target descriptions.
-   Implement interruption and recovery when the user manually interacts
    with FL Studio.
-   Test opening plugin windows and navigating a limited set of common
    dialogs.
-   Add explicit user confirmation for risky UI operations.

### Deliverables

-   GUI automation adapter.
-   Screen preview and cursor/action visualization.
-   GUI action verification.
-   Manual-intervention detection.
-   Safety documentation.

### Acceptance criteria

-   The automation can identify the intended target or fail safely.
-   It does not blindly click stale coordinates.
-   The user can stop an automation sequence.
-   The companion UI accurately communicates what the automation is
    doing.
-   Manual user interaction does not silently result in a long sequence
    of misdirected actions.

### Phase gate

Stop and ask for approval before Phase 6.

------------------------------------------------------------------------

## PHASE 6 --- Music production engine

### Goal

Generate musically coherent, structured production material and place it
in FL Studio.

### Tasks

-   Implement key/scale utilities.
-   Implement chord progression generation.
-   Implement melody generation.
-   Implement bassline generation.
-   Implement drum pattern generation.
-   Implement velocity and timing variation.
-   Implement deterministic MIDI validation.
-   Implement genre/mood presets as editable configuration, not
    hard-coded universal rules.
-   Implement arrangement planning.
-   Implement Playlist placement using the best supported route.
-   Add sample-folder scanning with explicit directory permission.
-   Add sample metadata extraction and categorization.
-   Add sample audition workflow.
-   Keep all generated content editable in FL Studio.

### Deliverables

-   Music engine modules.
-   Sample scanner.
-   Arrangement planner.
-   MIDI test fixtures.
-   Example FL Studio project.

### Acceptance criteria

-   Given a key, scale, tempo, and genre brief, the engine can produce
    valid MIDI patterns.
-   Generated notes satisfy explicit key/scale constraints where
    requested.
-   Rhythm patterns fit the requested meter and bar length.
-   The user can inspect and edit all generated notes/clips in FL
    Studio.
-   Sample scanning is restricted to approved directories.
-   The engine does not claim that generated music is guaranteed to be
    stylistically perfect.

### Phase gate

Stop and ask for approval before Phase 7.

------------------------------------------------------------------------

## PHASE 7 --- Audio rendering and analysis

### Goal

Complete the loop from project edits to render inspection and actionable
feedback.

### Tasks

-   Implement a GUI-based render/export workflow where necessary.
-   Detect the correct export dialog and verify settings.
-   Require approval before overwriting an existing render.
-   Verify output file existence and integrity.
-   Implement audio analysis using librosa/soundfile/numpy.
-   Detect clipping, silence, peak/RMS levels, and basic spectral
    observations.
-   Provide a structured analysis report.
-   Connect analysis results to the Critic role.
-   Allow the assistant to propose revisions but require approval before
    applying substantial changes.

### Deliverables

-   Render/export workflow.
-   Audio analysis module.
-   Critic feedback format.
-   Example render and analysis report.

### Acceptance criteria

-   A test project can be rendered through the supported workflow.
-   Output file is validated.
-   Analysis results are reproducible.
-   The assistant distinguishes measured facts from subjective
    recommendations.
-   Failed renders are reported honestly.

### Phase gate

Stop and ask for approval before Phase 8.

------------------------------------------------------------------------

## PHASE 8 --- Producer Orchestrator and end-to-end workflow

### Goal

Connect intent understanding, planning, music generation, FL Studio
control, verification, and audio analysis into a cohesive workflow.

### Tasks

-   Implement natural-language intent parsing.
-   Build project context into the model prompt.
-   Implement task planning with typed actions.
-   Implement role-based specialist modules.
-   Implement provider abstraction and configuration.
-   Implement plan preview and approval.
-   Implement bounded execution loops.
-   Implement critic feedback and revision suggestions.
-   Implement project memory and user preference storage.
-   Implement task summaries and session history.
-   Add an end-to-end test using a disposable FL Studio project.

### Deliverables

-   Producer Orchestrator.
-   Model provider adapters.
-   Project memory.
-   End-to-end demo.
-   User guide.

### Acceptance criteria

The following example must work end-to-end, with any unsupported step
reported rather than faked:

> "FL Studio'da 128 BPM, A minor tonunda melodic techno başlangıcı
> oluştur. Kick ve percussion düzenini kur, bassline ve ana melodiyi
> yaz, sonra kısa bir intro ve drop arrangement'ı hazırla."

The assistant must: - Read project context. - Present a plan. - Obtain
any required approvals. - Execute supported operations. - Show actions
live. - Verify each action. - Save safely. - Render only with approval
if required. - Analyze the render if available. - Summarize what was
completed and what remains.

### Phase gate

Stop and ask for approval before Phase 9.

------------------------------------------------------------------------

## PHASE 9 --- Hardening, packaging, and release candidate

### Goal

Prepare a stable Windows MVP for real-world use.

### Tasks

-   Test installation on a clean Windows environment.
-   Create a setup wizard or clear first-run setup.
-   Validate Python/backend packaging strategy.
-   Package the Tauri application.
-   Add diagnostics and integration health checks.
-   Add crash/error reporting that respects privacy.
-   Add log export.
-   Add project backup guidance.
-   Test reconnect behavior.
-   Test interrupted tasks and app restarts.
-   Review licensing of all dependencies.
-   Review security and privacy documentation.
-   Write user documentation and troubleshooting guide.

### Deliverables

-   Windows installer/build.
-   Setup guide.
-   Troubleshooting guide.
-   License inventory.
-   Security/privacy documentation.
-   Release-candidate test report.

### Acceptance criteria

-   A new user can install and configure the application by following
    the documentation.
-   Connection failures are understandable and recoverable.
-   The app does not claim success when FL Studio is unavailable.
-   Stop/cancellation and approval controls work.
-   No secrets are packaged into the installer.
-   All known limitations are documented.

### Phase gate

Stop and ask the user whether to proceed with a post-MVP roadmap. Do not
silently begin additional features.

------------------------------------------------------------------------

# 9. MVP DEFINITION

The first meaningful MVP is not a fully autonomous professional
producer. It is a reliable assistant that can:

1.  Run as a Windows desktop companion.
2.  Connect to a real FL Studio session.
3.  Read a limited set of project information.
4.  Accept natural-language requests.
5.  Create a simple drum pattern and MIDI material.
6.  Use GUI automation for a small number of unsupported operations.
7.  Show the user what it is doing.
8.  Verify important changes.
9.  Stop safely.
10. Preserve the user's existing project through backups/checkpoints.

The MVP should prioritize reliability and transparency over the number
of features.

------------------------------------------------------------------------

# 10. TESTING STRATEGY

## Unit tests

-   Music theory functions.
-   MIDI validation.
-   Action schema validation.
-   State transitions.
-   Risk classification.
-   Router selection.
-   Verification logic.
-   Audio-analysis calculations.

## Integration tests

-   MCP connection and health checks.
-   FL Studio read/write operations.
-   HCU window inspection.
-   GUI action wrappers.
-   SQLite persistence.
-   WebSocket event delivery.

## End-to-end tests

-   Submit a task from desktop UI.
-   Generate a plan.
-   Approve a safe test action.
-   Execute against a disposable project.
-   Verify the resulting state.
-   Stop an active task.
-   Recover from a simulated failure.

## Test safety

-   Use a disposable FL Studio project.
-   Never run destructive tests against the user's main project.
-   Mock external model providers in deterministic tests.
-   Mark every test as mocked, simulated, or real integration.

------------------------------------------------------------------------

# 11. IMPLEMENTATION QUALITY RULES

-   Use type hints in Python.
-   Use Pydantic models for API/action schemas.
-   Keep modules small and responsibilities clear.
-   Avoid giant files and circular imports.
-   Use structured logging.
-   Add docstrings for public interfaces.
-   Use environment variables for non-secret configuration.
-   Use secure storage for credentials.
-   Add `.env.example`, never commit `.env`.
-   Pin important dependency versions.
-   Keep a `CHANGELOG.md` or phase reports.
-   Keep setup instructions current.
-   Add tests with every meaningful feature.
-   Prefer deterministic logic for music theory and action validation.
-   Treat model output as untrusted input.
-   Do not over-engineer multi-agent orchestration before the
    single-orchestrator MVP works.

------------------------------------------------------------------------

# 12. FIRST ACTION FOR THE IMPLEMENTING AGENT

Start with **PHASE 0 ONLY**.

Do not implement Phase 1 or later in the first run.

First inspect the existing workspace/repository and the user's Windows
development environment as far as the available tools permit. Do not
delete, overwrite, or reorganize existing files without approval.

If the environment cannot be inspected directly, ask the user for the
minimum required information and provide exact commands they can run.

At the end of Phase 0: - Run all Phase 0 checks. - Write the Phase 0
report to `docs/phase-reports/phase-0-report.md`. - Summarize the
results to the user. - Ask for explicit approval to begin Phase 1. -
Then STOP.

**The most important instruction in this entire document: never move to
the next phase without the user's explicit approval.**

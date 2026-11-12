# GUI Automation (Microsoft Hybrid Computer Use)

## Selected framework

| Item | Value |
|---|---|
| Project | [microsoft/Hybrid-Computer-Use](https://github.com/microsoft/Hybrid-Computer-Use) (MIT), v1.0.0 |
| Pinned commit | `697d3fbda04cb322915866bab1aad79c726a61e3`, see `configs/external-pins.json` |
| Binaries | `external/Hybrid-Computer-Use/artifacts/windows/computer-use.exe` (Go MCP server) + `computer-use-windows-provider.exe` (.NET 8 UIA provider, self-contained) |

## Build

The upstream `build.ps1` requires PowerShell 7, which is not installed. We run the same two steps directly
(`scripts/fetch_external.ps1` does all of it):

```powershell
dotnet publish computer-use\native\windows\ComputerUse.Windows.Runtime\ComputerUse.Windows.Runtime.csproj -c Release -r win-x64 --self-contained true -o artifacts\windows\provider-publish
# move computer-use-windows-provider.exe next to computer-use.exe
go build -trimpath -ldflags "-s -w -X main.version=1.0.0" -o artifacts\windows\computer-use.exe .\cmd\computer-use
```

Requirements: Go ≥ 1.22 (have 1.25.6), .NET SDK ≥ 8 (have 10.0.201). NuGet restore needs network access.

## Interface

`computer-use.exe mcp` is an MCP server over stdio with exactly two tools:

* **AX** (semantic, Windows UI Automation): modes `apps`, `observe`, `find`, `act`.
  Refs are `wN` for windows and `rN` for elements. Stale refs fail. Each result says whether input was emitted (`input_emitted`).
* **GUI** (visual): `screenshot`, `zoom`, pixel `click`/`type`/`keypress`/`scroll`/`drag`.
  Checks for a stale frame (`gui_frame_stale` means nothing was sent).

Our client: `backend/app/integrations/computer_use/adapter.py` — `GUIAutomationAdapter`
(JSON-RPC over stdio, allowlist = `AX`, `GUI` only, timeout per call).

## Phase 1 results (REAL, not mocked)

| Test | Result |
|---|---|
| MCP handshake, tools = `[AX, GUI]` | ✅ |
| GUI screenshot (full desktop, 1365×768) | ✅ (sandboxed shell) |
| AX `apps` read-only, `input_emitted:false` | ✅ |
| Harmless action: UIA `set_value` on a WinForms TextBox in a test window owned by the script, read back independently from the target process | ✅ `verified: true` |
| Tk `Entry` widget exposed in the UIA tree | ❌ Not exposed. Custom-drawn widgets are invisible to AX |
| AX `activate` (bring window to foreground) from a background process | ❌ `window_activation_failed`. Windows foreground lock. HCU correctly sent **no** input |

## Important findings for FL Studio

1. **FL Studio draws most of its UI itself.** As with Tk, many controls will likely be missing from the UIA
   tree. Expect AX to cover window titles, menus and standard dialogs (Export, Open/Save). Mixer knobs,
   Channel Rack steps and plugin UIs will need the GUI channel (screenshot + validated coordinates).
   This will be measured against the real FL window in Phase 4/5.
2. **Foreground activation can be refused** by Windows when the caller is not the foreground app.
   Prefer UIA patterns that do not need focus (`set_value`, invoke). Keyboard input needs a confirmed
   foreground check first.
3. **Execution context matters.** In the agent's sandboxed shell, AX could only see windows created inside
   the sandbox. Outside the sandbox, the screenshot failed with "invalid handle". HCU's own doctor says:
   *run in an unlocked interactive user session at the target application's integrity level*. The production
   backend must run as a normal process in the user's desktop session, at the same integrity level as FL Studio
   (FL not elevated, or both elevated).

## Safety notes

* HCU sends **real input** to the signed-in desktop. Phase 1 sent input only to a window the test owned.
* Screenshots are written to a temp folder and never uploaded.
* Never click by coordinates without a fresh screenshot and window validation (Phase 5).

## Run

```powershell
cd backend
.venv\Scripts\python scripts\poc_hcu.py          # read-only
.venv\Scripts\python scripts\poc_hcu.py --act    # + harmless action in its own test window
.venv\Scripts\python -m pytest -m real_hcu
```


import { create } from "zustand";

export interface ConnectionState {
  backend_online: boolean;
  fl_mcp_connected: boolean;
  fl_studio_alive: boolean;
  fl_heartbeat_age: number | null;
  hcu_available: boolean;
  hcu_version: string | null;
  error_message: string | null;
}

export interface ProjectContextInfo {
  connected: boolean;
  title: string | null;
  fl_version: string | null;
  tempo: number | null;
  time_signature: string | null;
  playing: boolean | null;
  recording: boolean | null;
  channels: Array<{ i?: number; name?: string; [key: string]: any }>;
  mixer_tracks: Array<{ i?: number; name?: string; [key: string]: any }>;
  patterns: Array<{ [key: string]: any }>;
}

export interface ActionItem {
  action_id: string;
  task_id: string;
  name: string;
  description: string;
  target: string;
  route: "FL_MCP" | "GUI_AUTOMATION" | "LOCAL_SERVICE" | "MOCK";
  status: "PLANNED" | "AWAITING_APPROVAL" | "READY" | "RUNNING" | "VERIFYING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "SKIPPED";
  risk_level: string;
  requires_approval: boolean;
  verified: boolean | null;
  verification_detail: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface TaskResponse {
  task_id: string;
  prompt: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  is_mock: boolean;
  created_at: string;
  completed_at: string | null;
  actions: ActionItem[];
  result_summary: string | null;
  error: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
  task_id?: string | null;
  created_at: string;
}

export interface CursorMarker {
  active: boolean;
  x?: number | null;
  y?: number | null;
  label?: string | null;
  is_real_desktop: boolean;
}

export interface AppSettings {
  llm_provider: string;
  openai_model: string;
  openai_base_url: string;
  anthropic_model: string;
  local_model_url: string;
  local_model_name: string;
  fl_mcp_host: string;
  fl_mcp_port: number;
  hcu_enabled: boolean;
  sample_directories: string[];
  language: string;
  auto_verify: boolean;
  safe_mode: boolean;
}

interface AppStore {
  // Navigation
  activeTab: "main" | "activity" | "screen" | "project" | "settings";
  setActiveTab: (tab: "main" | "activity" | "screen" | "project" | "settings") => void;

  // Connection & Context
  connection: ConnectionState;
  projectContext: ProjectContextInfo;
  cursorMarker: CursorMarker;

  // Chat & Tasks
  messages: ChatMessage[];
  tasks: TaskResponse[];
  activeTask: TaskResponse | null;
  isExecuting: boolean;

  // Settings
  settings: AppSettings;

  // Actions
  initWebSocket: () => void;
  submitTask: (prompt: string, isMock?: boolean) => Promise<void>;
  stopActiveTask: () => Promise<void>;
  refreshHealth: () => Promise<void>;
  refreshContext: () => Promise<void>;
  updateSettings: (newSettings: Partial<AppSettings>) => Promise<void>;
}

const BACKEND_URL = "http://127.0.0.1:8765";
const WS_URL = "ws://127.0.0.1:8765/ws";

export const useStore = create<AppStore>((set, get) => ({
  activeTab: "main",
  setActiveTab: (tab) => set({ activeTab: tab }),

  connection: {
    backend_online: false,
    fl_mcp_connected: false,
    fl_studio_alive: false,
    fl_heartbeat_age: null,
    hcu_available: false,
    hcu_version: null,
    error_message: null,
  },

  projectContext: {
    connected: false,
    title: null,
    fl_version: null,
    tempo: null,
    time_signature: null,
    playing: null,
    recording: null,
    channels: [],
    mixer_tracks: [],
    patterns: [],
  },

  cursorMarker: {
    active: false,
    x: null,
    y: null,
    label: null,
    is_real_desktop: false,
  },

  messages: [],
  tasks: [],
  activeTask: null,
  isExecuting: false,

  settings: {
    llm_provider: "openai",
    openai_model: "gpt-4o",
    openai_base_url: "https://api.openai.com/v1",
    anthropic_model: "claude-sonnet-4-20250514",
    local_model_url: "http://localhost:11434",
    local_model_name: "llama3",
    fl_mcp_host: "127.0.0.1",
    fl_mcp_port: 9787,
    hcu_enabled: true,
    sample_directories: [],
    language: "tr",
    auto_verify: true,
    safe_mode: true,
  },

  initWebSocket: () => {
    let ws: WebSocket | null = null;
    let reconnectTimer: any = null;

    const connect = () => {
      try {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
          set((state) => ({
            connection: { ...state.connection, backend_online: true },
          }));
        };

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data);
            const { type, payload } = data;

            switch (type) {
              case "connection_status":
                set({ connection: payload });
                break;
              case "project_context":
                set({ projectContext: payload });
                break;
              case "chat_message":
                set((state) => {
                  if (state.messages.some((m) => m.id === payload.id)) return state;
                  return { messages: [...state.messages, payload] };
                });
                break;
              case "task_update":
                set((state) => {
                  const existingIndex = state.tasks.findIndex((t) => t.task_id === payload.task_id);
                  let updatedTasks = [...state.tasks];
                  if (existingIndex >= 0) {
                    updatedTasks[existingIndex] = payload;
                  } else {
                    updatedTasks.push(payload);
                  }
                  const isExec = payload.status === "RUNNING" || payload.status === "QUEUED";
                  return {
                    tasks: updatedTasks,
                    activeTask: isExec ? payload : null,
                    isExecuting: isExec,
                  };
                });
                break;
              case "action_update":
                set((state) => {
                  if (!state.activeTask) return state;
                  const updatedActions = state.activeTask.actions.map((act) =>
                    act.action_id === payload.action_id ? payload : act
                  );
                  return {
                    activeTask: { ...state.activeTask, actions: updatedActions },
                  };
                });
                break;
              case "cursor_marker":
                set({ cursorMarker: payload });
                break;
            }
          } catch (e) {
            console.error("WS Parse Error:", e);
          }
        };

        ws.onclose = () => {
          set((state) => ({
            connection: { ...state.connection, backend_online: false },
          }));
          reconnectTimer = setTimeout(connect, 3000);
        };

        ws.onerror = () => {
          ws?.close();
        };
      } catch (err) {
        reconnectTimer = setTimeout(connect, 3000);
      }
    };

    connect();
    get().refreshHealth();
    get().refreshContext();
  },

  submitTask: async (prompt: string, isMock: boolean = true) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, is_mock: isMock }),
      });
      if (res.ok) {
        const task = await res.json();
        set({ activeTask: task, isExecuting: true });
      }
    } catch (e) {
      console.error("Failed to submit task:", e);
    }
  },

  stopActiveTask: async () => {
    try {
      await fetch(`${BACKEND_URL}/api/tasks/stop-active`, { method: "POST" });
      set({ isExecuting: false });
    } catch (e) {
      console.error("Failed to stop active task:", e);
    }
  },

  refreshHealth: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/health/refresh`, { method: "POST" });
      if (res.ok) {
        const health = await res.json();
        set({ connection: health });
      }
    } catch (e) {
      set((state) => ({
        connection: { ...state.connection, backend_online: false },
      }));
    }
  },

  refreshContext: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/context/refresh`, { method: "POST" });
      if (res.ok) {
        const ctx = await res.json();
        set({ projectContext: ctx });
      }
    } catch (e) {
      console.error("Failed to refresh context:", e);
    }
  },

  updateSettings: async (newSettings) => {
    try {
      const updated = { ...get().settings, ...newSettings };
      const res = await fetch(`${BACKEND_URL}/api/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updated),
      });
      if (res.ok) {
        const saved = await res.json();
        set({ settings: saved });
      }
    } catch (e) {
      console.error("Failed to save settings:", e);
    }
  },
}));


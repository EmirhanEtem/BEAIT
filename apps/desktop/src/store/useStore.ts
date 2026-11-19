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
  session_id?: string | null;
  prompt: string;
  status: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  is_mock: boolean;
  created_at: string;
  completed_at: string | null;
  actions: ActionItem[];
  result_summary: string | null;
  error: string | null;
}

export interface ChatSession {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message_preview?: string | null;
}

export interface ChatMessage {
  id: string;
  session_id?: string | null;
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
  gemini_model?: string;
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
  sessions: ChatSession[];
  activeSessionId: string | null;
  isChatSidebarOpen: boolean;
  setChatSidebarOpen: (open: boolean) => void;
  messages: ChatMessage[];
  tasks: TaskResponse[];
  activeTask: TaskResponse | null;
  isExecuting: boolean;

  // Settings
  settings: AppSettings;

  // Actions
  initWebSocket: () => void;
  fetchSessions: () => Promise<void>;
  createNewChat: (title?: string) => Promise<ChatSession | null>;
  selectChat: (sessionId: string) => Promise<void>;
  deleteChat: (sessionId: string) => Promise<void>;
  renameChat: (sessionId: string, title: string) => Promise<void>;
  submitTask: (prompt: string, isMock?: boolean) => Promise<void>;
  stopActiveTask: () => Promise<void>;
  refreshHealth: () => Promise<void>;
  refreshContext: () => Promise<void>;
  fetchSettings: () => Promise<void>;
  updateSettings: (newSettings: Partial<AppSettings>) => Promise<void>;
}

export const BACKEND_URL = "http://127.0.0.1:8000";
export const WS_URL = "ws://127.0.0.1:8000/ws";

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

  sessions: [],
  activeSessionId: null,
  isChatSidebarOpen: true,
  setChatSidebarOpen: (open) => set({ isChatSidebarOpen: open }),
  messages: [],
  tasks: [],
  activeTask: null,
  isExecuting: false,

  settings: {
    llm_provider: "openai",
    openai_model: "gpt-4o",
    openai_base_url: "https://api.openai.com/v1",
    gemini_model: "gemini-3.5-flash-lite",
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
          get().refreshHealth();
          get().refreshContext();
          get().fetchSettings();
          get().fetchSessions();
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
              case "session_updated":
                set((state) => {
                  const idx = state.sessions.findIndex((s) => s.session_id === payload.session_id);
                  const next = [...state.sessions];
                  if (idx >= 0) {
                    next[idx] = payload;
                  } else {
                    next.unshift(payload);
                  }
                  next.sort(
                    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
                  );
                  return { sessions: next };
                });
                break;
              case "chat_message":
                set((state) => {
                  const msgSid = payload.session_id || state.activeSessionId;
                  const targetActive = state.activeSessionId || msgSid || null;
                  const updatedSessions = state.sessions.map((s) =>
                    s.session_id === msgSid
                      ? {
                          ...s,
                          updated_at: payload.created_at || s.updated_at,
                          message_count: s.message_count + 1,
                          last_message_preview: String(payload.text || "")
                            .trim()
                            .replace(/\s+/g, " ")
                            .slice(0, 120),
                        }
                      : s
                  );
                  if (targetActive && msgSid && msgSid !== targetActive) {
                    return { sessions: updatedSessions };
                  }
                  if (state.messages.some((m) => m.id === payload.id)) {
                    return { sessions: updatedSessions };
                  }
                  return {
                    activeSessionId: targetActive,
                    sessions: updatedSessions,
                    messages: [...state.messages, payload],
                  };
                });
                break;
              case "task_update":
                set((state) => {
                  const belongsToActive =
                    !payload.session_id ||
                    !state.activeSessionId ||
                    payload.session_id === state.activeSessionId;
                  if (!belongsToActive) {
                    return state;
                  }
                  const existingIndex = state.tasks.findIndex((t) => t.task_id === payload.task_id);
                  const updatedTasks = [...state.tasks];
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
                  if (state.activeTask.task_id !== payload.task_id) return state;
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
    get().fetchSettings();
    get().fetchSessions();
  },

  fetchSessions: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/chats`);
      if (!res.ok) return;
      const sessions: ChatSession[] = await res.json();
      set({ sessions });
      const currentActive = get().activeSessionId;
      if (currentActive && sessions.some((s) => s.session_id === currentActive)) {
        return;
      }
      if (sessions.length > 0) {
        await get().selectChat(sessions[0].session_id);
      } else {
        await get().createNewChat();
      }
    } catch (e) {
      console.error("Failed to fetch chat sessions:", e);
    }
  },

  createNewChat: async (title?: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/chats`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(title ? { title } : {}),
      });
      if (!res.ok) return null;
      const created: ChatSession = await res.json();
      set((state) => ({
        activeSessionId: created.session_id,
        sessions: [created, ...state.sessions.filter((s) => s.session_id !== created.session_id)],
        messages: [],
        tasks: [],
        activeTask: null,
        isExecuting: false,
      }));
      return created;
    } catch (e) {
      console.error("Failed to create new chat session:", e);
      return null;
    }
  },

  selectChat: async (sessionId: string) => {
    set({
      activeSessionId: sessionId,
      messages: [],
      tasks: [],
      activeTask: null,
      isExecuting: false,
    });
    try {
      const [msgRes, taskRes] = await Promise.all([
        fetch(`${BACKEND_URL}/api/chats/${encodeURIComponent(sessionId)}/messages`),
        fetch(`${BACKEND_URL}/api/tasks?session_id=${encodeURIComponent(sessionId)}`),
      ]);
      if (get().activeSessionId !== sessionId) return;
      const msgs: ChatMessage[] = msgRes.ok ? await msgRes.json() : [];
      const tasks: TaskResponse[] = taskRes.ok ? await taskRes.json() : [];
      const runningTask =
        tasks.find((t) => t.status === "RUNNING" || t.status === "QUEUED") || null;
      set({
        messages: msgs,
        tasks,
        activeTask: runningTask,
        isExecuting: Boolean(runningTask),
      });
    } catch (e) {
      console.error("Failed to select chat session:", e);
    }
  },

  deleteChat: async (sessionId: string) => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/chats/${encodeURIComponent(sessionId)}`, {
        method: "DELETE",
      });
      if (!res.ok) return;
      const data = await res.json();
      const nextSessions: ChatSession[] = data.sessions || [];
      const nextActive: string | null =
        data.active_session_id || (nextSessions[0]?.session_id ?? null);
      set({ sessions: nextSessions });
      if (nextActive) {
        await get().selectChat(nextActive);
      } else {
        await get().createNewChat();
      }
    } catch (e) {
      console.error("Failed to delete chat session:", e);
    }
  },

  renameChat: async (sessionId: string, title: string) => {
    const clean = title.trim();
    if (!clean) return;
    try {
      const res = await fetch(`${BACKEND_URL}/api/chats/${encodeURIComponent(sessionId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: clean }),
      });
      if (!res.ok) return;
      const updated: ChatSession = await res.json();
      set((state) => ({
        sessions: state.sessions.map((s) =>
          s.session_id === updated.session_id ? updated : s
        ),
      }));
    } catch (e) {
      console.error("Failed to rename chat session:", e);
    }
  },

  submitTask: async (prompt: string, isMock: boolean = true) => {
    try {
      let sid = get().activeSessionId;
      if (!sid) {
        const created = await get().createNewChat();
        sid = created?.session_id ?? null;
      }
      const res = await fetch(`${BACKEND_URL}/api/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          is_mock: isMock,
          session_id: sid,
        }),
      });
      if (res.ok) {
        const task = await res.json();
        set((state) => ({
          activeSessionId: task.session_id || state.activeSessionId,
          activeTask: task,
          isExecuting: true,
        }));
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

  fetchSettings: async () => {
    try {
      const res = await fetch(`${BACKEND_URL}/api/settings`);
      if (res.ok) {
        const loaded = await res.json();
        set({ settings: loaded });
      }
    } catch (e) {
      console.error("Failed to fetch settings:", e);
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


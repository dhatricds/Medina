import React, { useEffect, useRef, useState } from "react";
import { useProjectStore } from "../../store/projectStore";
import {
  getChatHistory,
  sendChatMessage,
  confirmChatActions,
  getChatSuggestions,
} from "../../api/client";
import ChatMessage from "./ChatMessage";

interface ChatMsg {
  id?: number;
  role: "user" | "assistant" | "system";
  content: string;
  intent?: string | null;
  actions?: any[] | null;
  created_at?: string;
}

export default function ChatPanel() {
  const projectId = useProjectStore((s) => s.projectId);
  const appState = useProjectStore((s) => s.appState);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [pendingActions, setPendingActions] = useState<any[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Load history when project changes — clear old messages first
  useEffect(() => {
    setMessages([]);
    setPendingActions(null);
    setSuggestions([]);
    if (!projectId) return;
    getChatHistory(projectId).then((data) => {
      setMessages(data.messages || []);
    }).catch(() => {});
  }, [projectId]);

  // Load suggestions when complete
  useEffect(() => {
    if (!projectId || appState !== "complete") return;
    getChatSuggestions(projectId).then((data) => {
      setSuggestions(data.suggestions || []);
    }).catch(() => {});
  }, [projectId, appState]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, loading]);

  const handleSend = async (text?: string) => {
    const msg = (text || input).trim();
    if (!msg || !projectId || loading) return;

    // Add user message locally
    const userMsg: ChatMsg = { role: "user", content: msg };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);
    setPendingActions(null);

    try {
      const resp = await sendChatMessage(projectId, msg);
      const assistantMsg: ChatMsg = {
        role: "assistant",
        content: resp.message?.content || "No response",
        intent: resp.message?.intent,
        actions: resp.message?.actions,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // Handle highlight response — show markers on PDF immediately
      if (resp.highlight) {
        const store = useProjectStore.getState();
        if (resp.highlight.fixture_code) {
          store.highlightFixture(resp.highlight.fixture_code, resp.highlight.plan);
        } else if (resp.highlight.keynote_number) {
          store.highlightKeynote(resp.highlight.keynote_number, resp.highlight.plan);
        }
        // Keep chat open so user can continue conversation
      }

      // If actions need confirmation
      if (resp.needs_confirmation && resp.message?.actions?.length) {
        setPendingActions(resp.message.actions);
      }
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Error: ${err.message || "Unknown error"}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const handleConfirm = async () => {
    if (!pendingActions || !projectId) return;
    setConfirming(true);
    try {
      // Save snapshot of current data so we can show diffs after reprocess
      useProjectStore.getState().savePreReprocessSnapshot();

      await confirmChatActions(projectId, pendingActions);
      setMessages((prev) => [
        ...prev,
        {
          role: "system",
          content: `Confirmed ${pendingActions.length} action(s). Reprocessing with vision verification...`,
        },
      ]);
      setPendingActions(null);
      setSuggestions([]);

      // Activate SSE so frontend updates during reprocessing
      useProjectStore.setState({
        appState: 'processing',
        agents: [
          { id: 1, name: 'Search Agent', description: 'Load, discover, classify pages', status: 'pending', stats: {} },
          { id: 2, name: 'Schedule Agent', description: 'Extract fixture specs from schedule', status: 'pending', stats: {} },
          { id: 3, name: 'Count Agent', description: 'Count fixtures on plans', status: 'pending', stats: {} },
          { id: 4, name: 'Keynote Agent', description: 'Extract and count keynotes', status: 'pending', stats: {} },
          { id: 5, name: 'QA Agent', description: 'Validate and generate output', status: 'pending', stats: {} },
        ],
        sseActive: true,
        error: null,
        chatOpen: false,
      });
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Confirmation failed: ${err.message}` },
      ]);
    } finally {
      setConfirming(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col max-h-[50vh] min-h-[200px] bg-white border border-gray-200 rounded-lg mx-4 my-2 shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-200 bg-gray-50">
        <span className="text-sm font-medium text-gray-700">Chat</span>
        <button
          onClick={() => useProjectStore.getState().setChatOpen(false)}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none"
        >
          &times;
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-1">
        {messages.length === 0 && !loading && (
          <div className="text-center text-gray-400 text-sm mt-8">
            <p className="font-medium mb-1">Ask me anything about this project</p>
            <p className="text-xs">
              Correct counts, add fixtures, ask questions, or adjust parameters
            </p>
          </div>
        )}

        {messages.map((msg, i) => (
          <ChatMessage
            key={i}
            role={msg.role}
            content={msg.content}
            intent={msg.intent}
            actions={msg.actions}
            timestamp={msg.created_at}
          />
        ))}

        {loading && (
          <div className="flex justify-start mb-3">
            <div className="bg-gray-100 rounded-lg px-3 py-2 text-sm text-gray-500">
              <span className="inline-block animate-pulse">Thinking...</span>
            </div>
          </div>
        )}

        {/* Pending action confirmation */}
        {pendingActions && (
          <div className="bg-orange-50 border border-orange-200 rounded-lg p-3 mt-2">
            <p className="text-sm font-medium text-orange-800 mb-2">
              {pendingActions.length} action(s) ready to apply
            </p>
            <div className="flex gap-2">
              <button
                onClick={handleConfirm}
                disabled={confirming}
                className="px-3 py-1 bg-orange-600 text-white text-xs rounded hover:bg-orange-700 disabled:opacity-50"
              >
                {confirming ? "Applying..." : "Confirm & Reprocess"}
              </button>
              <button
                onClick={() => setPendingActions(null)}
                className="px-3 py-1 bg-gray-200 text-gray-700 text-xs rounded hover:bg-gray-300"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Suggestion chips */}
      {suggestions.length > 0 && messages.length === 0 && (
        <div className="px-3 py-2 border-t border-gray-100 flex flex-wrap gap-1">
          {suggestions.map((s, i) => (
            <button
              key={i}
              onClick={() => handleSend(s)}
              className="text-[11px] px-2 py-1 bg-blue-50 text-blue-700 rounded-full hover:bg-blue-100 truncate max-w-[200px]"
              title={s}
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-gray-200 p-2 shrink-0">
        <div className="flex gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a message... (Enter to send)"
            rows={2}
            className="flex-1 resize-none border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400"
          />
          <button
            onClick={() => handleSend()}
            disabled={!input.trim() || loading}
            className="px-3 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed self-end"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

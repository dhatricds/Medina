import React from "react";

interface ChatMsgProps {
  role: "user" | "assistant" | "system";
  content: string;
  intent?: string | null;
  actions?: any[] | null;
  timestamp?: string;
}

export default function ChatMessage({ role, content, intent, actions, timestamp }: ChatMsgProps) {
  const isUser = role === "user";
  const isSystem = role === "system";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} mb-3`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
          isUser
            ? "bg-blue-600 text-white"
            : isSystem
            ? "bg-yellow-50 text-yellow-800 border border-yellow-200"
            : "bg-gray-100 text-gray-800"
        }`}
      >
        {/* Intent badge */}
        {intent && !isUser && !isSystem && (
          <span
            className={`inline-block text-[10px] font-medium uppercase px-1.5 py-0.5 rounded mb-1 mr-1 ${
              intent === "correction"
                ? "bg-orange-100 text-orange-700"
                : intent === "question"
                ? "bg-blue-100 text-blue-700"
                : intent === "param_change"
                ? "bg-purple-100 text-purple-700"
                : "bg-gray-200 text-gray-600"
            }`}
          >
            {intent}
          </span>
        )}

        {/* Message content */}
        <div className="whitespace-pre-wrap break-words">{content}</div>

        {/* Action preview cards */}
        {actions && actions.length > 0 && (
          <div className="mt-2 space-y-1">
            {actions.map((a: any, i: number) => (
              <div
                key={i}
                className="bg-white border border-gray-200 rounded px-2 py-1 text-xs"
              >
                <span className="font-medium text-gray-700">
                  {a.action}
                </span>{" "}
                <span className="text-gray-500">{a.fixture_code}</span>
                {a.confidence != null && (
                  <span
                    className={`ml-1 ${
                      a.confidence >= 0.9
                        ? "text-green-600"
                        : a.confidence >= 0.7
                        ? "text-yellow-600"
                        : "text-red-600"
                    }`}
                  >
                    {Math.round(a.confidence * 100)}%
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Timestamp */}
        {timestamp && (
          <div className="text-[10px] opacity-50 mt-1">
            {new Date(timestamp).toLocaleTimeString()}
          </div>
        )}
      </div>
    </div>
  );
}

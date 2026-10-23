"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, api } from "@/lib/api/client";
import { queryKeys, setMessages } from "@/lib/api/queries";
import type { CoworkAgent } from "@/lib/api/types";
import { streamChat } from "@/lib/sse/chat-stream";

export interface ChatState {
  sending: boolean;
  /** The reply being streamed: its message id and the text so far. */
  streaming: { messageId: string; text: string } | null;
  error: ApiError | null;
}

/**
 * Sends one message and folds the reply stream into the messages cache. Leaving the page
 * aborts only this connection: the server finishes the reply, and the stored message is
 * picked up by `useCoworkMessages` (it polls while a reply is pending).
 */
export function useCoworkChat(runId: string, ideaId: string) {
  const client = useQueryClient();
  const [state, setState] = useState<ChatState>({ sending: false, streaming: null, error: null });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const send = useCallback(
    async (agent: CoworkAgent, content: string) => {
      controller.current?.abort();
      const abort = new AbortController();
      controller.current = abort;
      setState({ sending: true, streaming: null, error: null });
      let completed = false;
      try {
        await streamChat({
          url: api.coworkUrl(runId, ideaId),
          body: { agent, content },
          signal: abort.signal,
          onEvent: (e) => {
            switch (e.event) {
              case "started":
                setMessages(client, runId, ideaId, (items) => [
                  ...items,
                  e.data.user_message,
                  e.data.assistant_message,
                ]);
                setState((s) => ({
                  ...s,
                  streaming: { messageId: e.data.assistant_message.id, text: "" },
                }));
                break;
              case "delta":
                setState((s) =>
                  s.streaming
                    ? { ...s, streaming: { ...s.streaming, text: s.streaming.text + e.data.text } }
                    : s,
                );
                break;
              case "reset":
                setState((s) =>
                  s.streaming ? { ...s, streaming: { ...s.streaming, text: "" } } : s,
                );
                break;
              case "completed":
                completed = true;
                setMessages(client, runId, ideaId, (items) =>
                  items.map((m) => (m.id === e.data.id ? e.data : m)),
                );
                break;
              case "error":
                completed = true;
                setState((s) => ({
                  ...s,
                  error: new ApiError(e.data.message, 200, e.data.code),
                }));
                break;
            }
          },
        });
      } catch (error) {
        if (abort.signal.aborted) return;
        setState((s) => ({
          ...s,
          error: error instanceof ApiError ? error : new ApiError(String(error), 0),
        }));
      } finally {
        if (!abort.signal.aborted) {
          setState((s) => ({ ...s, sending: false, streaming: null }));
          // The stored messages are the truth: after a dropped stream (`completed` never
          // arrived) the pending reply is re-read and then polled until it is stored.
          if (!completed) {
            void client.invalidateQueries({ queryKey: queryKeys.messages(runId, ideaId) });
          }
        }
      }
    },
    [client, runId, ideaId],
  );

  return { ...state, send };
}

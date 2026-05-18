import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Bot, User, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { sendChat } from "@/lib/api";
import type { ChatMessage } from "@/types";
import { cn } from "@/lib/utils";

const SESSION_ID = crypto.randomUUID();
const USER_ID = "demo-user";

const DEMO_PROMPTS = [
  "今対応中の重大インシデントはある？",
  "fake-api-server のエラー率は今どのくらい？",
  "過去のDBカテゴリの解決済みチケットを見せて",
  "DynamoDB ProvisionedThroughputExceeded の一般的な原因は？",
];

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-1.5 px-1 py-0.5 text-muted-foreground">
      <span className="dot" />
      <span className="dot" />
      <span className="dot" />
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div
      className={cn(
        "message-enter flex gap-3",
        isUser ? "flex-row-reverse" : "flex-row"
      )}
    >
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-full",
          isUser ? "bg-primary text-primary-foreground" : "bg-muted"
        )}
      >
        {isUser ? <User className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
      </div>
      <div
        className={cn(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
          isUser
            ? "rounded-tr-sm bg-primary text-primary-foreground"
            : "rounded-tl-sm bg-muted text-foreground"
        )}
      >
        {msg.isLoading ? (
          <ThinkingIndicator />
        ) : (
          <p className="whitespace-pre-wrap">{msg.content}</p>
        )}
      </div>
    </div>
  );
}

export default function ChatTab() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "こんにちは。Agora ITサービスデスクです。インシデントの状況確認、エラーの調査、過去事例の照会など、IT運用に関するご質問をどうぞ。",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleSend = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isLoading) return;

      setInput("");
      setError(null);

      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content: trimmed,
        timestamp: new Date(),
      };
      const loadingMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "assistant",
        content: "",
        timestamp: new Date(),
        isLoading: true,
      };

      setMessages((prev) => [...prev, userMsg, loadingMsg]);
      setIsLoading(true);

      try {
        const response = await sendChat(trimmed, USER_ID, SESSION_ID);
        setMessages((prev) =>
          prev.map((m) =>
            m.id === loadingMsg.id
              ? { ...m, content: response, isLoading: false }
              : m
          )
        );
      } catch (err) {
        setMessages((prev) => prev.filter((m) => m.id !== loadingMsg.id));
        setError(
          err instanceof Error
            ? err.message
            : "エージェントへの接続に失敗しました。proxy.py が起動しているか確認してください。"
        );
      } finally {
        setIsLoading(false);
        inputRef.current?.focus();
      }
    },
    [isLoading]
  );

  return (
    <div className="flex h-full flex-col">
      {/* Message list */}
      <ScrollArea className="flex-1 px-4">
        <div className="space-y-4 py-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {/* Error banner */}
      {error && (
        <div className="mx-4 mb-2 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Demo prompts */}
      {messages.length === 1 && (
        <div className="px-4 pb-2">
          <p className="mb-2 text-xs text-muted-foreground">デモシナリオ</p>
          <div className="flex flex-wrap gap-2">
            {DEMO_PROMPTS.map((p) => (
              <button
                key={p}
                onClick={() => void handleSend(p)}
                className="rounded-full border bg-background px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="border-t px-4 py-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void handleSend(input);
          }}
        >
          <Input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="質問や問い合わせを入力..."
            disabled={isLoading}
            className="flex-1"
          />
          <Button type="submit" size="icon" disabled={isLoading || !input.trim()}>
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}

import { useState } from "react";
import { ChevronDown, ChevronRight, Copy, Check } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { AGENTS, MCPS, type AgentDef, type McpDef, type ToolDef } from "@/data/catalog";

// ---------------------------------------------------------------------------
// Copy button
// ---------------------------------------------------------------------------
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="flex items-center gap-1 rounded px-2 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
      title="System Prompt をコピー"
    >
      {copied ? <Check className="h-3 w-3 text-green-600" /> : <Copy className="h-3 w-3" />}
      {copied ? "コピー完了" : "コピー"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tool list
// ---------------------------------------------------------------------------
function ToolList({ tools }: { tools: ToolDef[] }) {
  if (tools.length === 0) {
    return (
      <p className="text-xs italic text-muted-foreground">
        ツールなし（JSON のみを出力する分類エージェント）
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {tools.map((t) => (
        <li key={t.name} className="flex flex-col gap-0.5">
          <code className="text-xs font-mono font-semibold text-foreground">{t.name}</code>
          <span className="text-xs text-muted-foreground">{t.description}</span>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Agent card
// ---------------------------------------------------------------------------
function AgentCard({ agent }: { agent: AgentDef }) {
  const [promptOpen, setPromptOpen] = useState(false);

  const protocolVariant =
    agent.protocol === "AG-UI"
      ? "open"        // blue
      : "investigating"; // purple

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <CardTitle className="text-sm font-semibold">{agent.name}</CardTitle>
          <Badge variant={protocolVariant}>{agent.protocol}</Badge>
          <Badge variant="outline" className="font-mono text-xs">
            {agent.model}
          </Badge>
        </div>
        <CardDescription className="text-xs leading-relaxed mt-1">
          {agent.description}
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-4 pt-0">
        {/* Tools */}
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            ツール
          </p>
          <ToolList tools={agent.tools} />
        </div>

        {/* System Prompt — collapsible */}
        <div>
          <div className="flex items-center justify-between">
            <button
              onClick={() => setPromptOpen((v) => !v)}
              className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground transition-colors"
            >
              {promptOpen ? (
                <ChevronDown className="h-3 w-3" />
              ) : (
                <ChevronRight className="h-3 w-3" />
              )}
              System Prompt
            </button>
            {promptOpen && <CopyButton text={agent.systemPrompt} />}
          </div>

          {promptOpen && (
            <div className="mt-2 rounded-md border bg-muted/40 px-3 py-2 overflow-auto max-h-96">
              <div
                className={`
                  prose prose-sm max-w-none
                  prose-p:my-1 prose-p:leading-relaxed
                  prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1
                  prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5
                  prose-strong:font-semibold
                  prose-code:text-xs prose-code:rounded prose-code:px-0.5 prose-code:bg-muted
                  prose-pre:text-xs prose-pre:my-1 prose-pre:bg-muted
                  prose-table:text-xs
                  prose-td:px-2 prose-th:px-2
                `}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {agent.systemPrompt}
                </ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// MCP card
// ---------------------------------------------------------------------------
function McpCard({ mcp }: { mcp: McpDef }) {
  const capabilityVariant =
    mcp.capability === "community-knowledge"
      ? "low"            // green
      : mcp.capability === "aws-observability"
      ? "medium"         // yellow
      : "high";          // orange (aws-infrastructure)

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center gap-1.5">
          <CardTitle className="text-sm font-semibold">{mcp.name}</CardTitle>
          <Badge variant={capabilityVariant}>{mcp.capability}</Badge>
        </div>
        <CardDescription className="text-xs font-mono text-muted-foreground/70">
          {mcp.runtimeName}
        </CardDescription>
        <CardDescription className="text-xs leading-relaxed mt-0.5">
          {mcp.description}
        </CardDescription>
      </CardHeader>

      <CardContent className="pt-0">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          ツール
        </p>
        <ToolList tools={mcp.tools} />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Section header
// ---------------------------------------------------------------------------
function SectionHeader({ title, count }: { title: string; count: number }) {
  return (
    <div className="flex items-baseline gap-2">
      <h2 className="text-sm font-semibold">{title}</h2>
      <span className="text-xs text-muted-foreground">{count} 件</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main tab component
// ---------------------------------------------------------------------------
export default function SystemTab() {
  return (
    <div className="flex h-full flex-col gap-6 p-4 overflow-auto">
      {/* Banner */}
      <div className="rounded-lg border border-border/60 bg-muted/40 px-3 py-2 text-xs text-muted-foreground leading-relaxed">
        <span className="font-medium text-foreground">AIの判断基準はすべてテキストで定義されています。</span>
        {" "}System Prompt を編集するだけで、コードを変更せずにエージェントの分類基準・検索戦略・解決フォーマットを改善できます。
        各プロンプトの▶をクリックして内容を確認し、必要に応じてコピーして編集してください。
      </div>

      {/* Agents section */}
      <div className="flex flex-col gap-3">
        <SectionHeader title="AIエージェント" count={AGENTS.length} />
        <div className="grid gap-4 lg:grid-cols-2">
          {AGENTS.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      </div>

      {/* MCP servers section */}
      <div className="flex flex-col gap-3">
        <SectionHeader title="MCPサーバー" count={MCPS.length} />
        <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
          {MCPS.map((mcp) => (
            <McpCard key={mcp.id} mcp={mcp} />
          ))}
        </div>
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, AlertCircle, BookOpen } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { ja } from "date-fns/locale";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listTickets } from "@/lib/api";
import type { Ticket, Category } from "@/types";

function categoryVariant(c: Category): BadgeProps["variant"] {
  const map: Record<Category, BadgeProps["variant"]> = {
    database: "critical",
    network: "high",
    memory: "medium",
    deploy: "high",
    other: "secondary",
  };
  return map[c];
}

function KnowledgeCard({ ticket }: { ticket: Ticket }) {
  const ago = formatDistanceToNow(new Date(ticket.resolved_at ?? ticket.updated_at), {
    addSuffix: true,
    locale: ja,
  });

  return (
    <Card className="transition-shadow hover:shadow-md">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-medium leading-snug">
            {ticket.title}
          </CardTitle>
          <Badge variant={categoryVariant(ticket.category as Category)}>
            {ticket.category}
          </Badge>
        </div>
        <CardDescription className="text-xs">
          #{ticket.ticket_id.slice(0, 8)} · {ago}に解決
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        {ticket.lesson_learned && (
          <p className="text-sm font-medium leading-snug text-foreground">
            {ticket.lesson_learned}
          </p>
        )}
        {ticket.resolution ? (
          <div className={`prose prose-sm max-w-none
            prose-p:my-1 prose-p:leading-relaxed
            prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1 first:prose-headings:mt-0
            prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5
            prose-strong:font-semibold
            prose-code:text-xs prose-code:rounded prose-code:px-0.5
            prose-pre:text-xs prose-pre:my-1
            ${ticket.lesson_learned ? "text-muted-foreground" : ""}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {ticket.resolution}
            </ReactMarkdown>
          </div>
        ) : !ticket.lesson_learned ? (
          <p className="text-xs italic text-muted-foreground">解決策が記録されていません</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function KnowledgeSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex justify-between gap-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-5 w-16" />
        </div>
        <Skeleton className="mt-1 h-3 w-1/2" />
      </CardHeader>
      <CardContent className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
        <Skeleton className="mt-2 h-20 w-full" />
      </CardContent>
    </Card>
  );
}

export default function KnowledgeTab() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTickets({
        status: "resolved",
        category: categoryFilter !== "all" ? categoryFilter : undefined,
        limit: 50,
      });
      setTickets(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ナレッジの読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  }, [categoryFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const categories: Category[] = ["database", "network", "memory", "deploy", "other"];

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      {/* Description */}
      <div className="rounded-lg border border-border/60 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        解決済みインシデントから蓄積された知見ベース。各カードの<span className="font-medium text-foreground">解決策</span>が次の対応に活きます。
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <Select value={categoryFilter} onValueChange={setCategoryFilter}>
          <SelectTrigger className="w-40">
            <SelectValue placeholder="カテゴリ" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">すべてのカテゴリ</SelectItem>
            {categories.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          {!loading && !error && (
            <span>{tickets.length} 件の解決済み事例</span>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <KnowledgeSkeleton key={i} />
            ))}
          </div>
        ) : tickets.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground">
            <BookOpen className="h-8 w-8 opacity-30" />
            <p className="text-sm">解決済みチケットがありません</p>
            <p className="text-xs">Chat タブでインシデントを報告すると、解決後にここに蓄積されます。</p>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {tickets.map((t) => (
              <KnowledgeCard key={t.ticket_id} ticket={t} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

import { useState, useEffect, useCallback } from "react";
import { RefreshCw, AlertCircle, BookOpen } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { ja } from "date-fns/locale";
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
          <Badge variant={categoryVariant(ticket.category)}>
            {ticket.category}
          </Badge>
        </div>
        <CardDescription className="text-xs">
          #{ticket.ticket_id.slice(0, 8)} · {ago}に解決
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-2">
        <p className="line-clamp-2 text-sm text-muted-foreground">
          {ticket.description}
        </p>
        {ticket.resolution && (
          <div className="rounded-md border border-green-200 bg-green-50 p-3">
            <p className="mb-1 text-xs font-semibold text-green-700">解決策</p>
            <p className="text-sm text-green-800">{ticket.resolution}</p>
          </div>
        )}
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
        <Skeleton className="mt-1 h-3 w-4/5" />
        <Skeleton className="mt-2 h-12 w-full" />
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
      // Knowledge = resolved tickets
      const data = await listTickets({
        status: "resolved",
        category: categoryFilter !== "all" ? categoryFilter : undefined,
        limit: 50,
      });
      setTickets(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load knowledge");
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
            <SelectValue placeholder="Category" />
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
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
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
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {tickets.map((t) => (
              <KnowledgeCard key={t.ticket_id} ticket={t} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

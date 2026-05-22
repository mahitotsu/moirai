import { useState, useEffect, useCallback } from "react";
import { RefreshCw, AlertCircle, Inbox } from "lucide-react";
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
import { cn } from "@/lib/utils";
import { listTickets } from "@/lib/api";
import type { Ticket, Severity, Status, Category } from "@/types";

const SEVERITY_ORDER: Record<Severity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function severityVariant(s: Severity): BadgeProps["variant"] {
  return s as BadgeProps["variant"];
}

function statusVariant(s: Status): BadgeProps["variant"] {
  return s as BadgeProps["variant"];
}

type TimelineVariant = "open" | "investigating" | "resolved";

function TimelineStep({
  label,
  time,
  content,
  variant,
  isLast,
}: {
  label: string;
  time?: string;
  content?: string;
  variant: TimelineVariant;
  isLast: boolean;
}) {
  const dotColor: Record<TimelineVariant, string> = {
    open: "bg-slate-400",
    investigating: "bg-amber-500",
    resolved: "bg-green-500",
  };

  return (
    <div className="flex gap-2.5">
      <div className="flex flex-col items-center">
        <div className={cn("mt-1 h-2 w-2 shrink-0 rounded-full", dotColor[variant])} />
        {!isLast && <div className="mt-1 w-px flex-1 bg-border" />}
      </div>
      <div className={cn("min-w-0 flex-1", !isLast && "pb-3")}>
        <div className="flex items-baseline gap-1.5">
          <span className="text-xs font-semibold">{label}</span>
          {time && (
            <span className="text-[10px] text-muted-foreground">{time}</span>
          )}
        </div>
        {content && (
          <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
            {content}
          </p>
        )}
      </div>
    </div>
  );
}

function TicketCard({ ticket }: { ticket: Ticket }) {
  const createdAgo = formatDistanceToNow(new Date(ticket.created_at), {
    addSuffix: true,
    locale: ja,
  });
  const updatedAgo = formatDistanceToNow(new Date(ticket.updated_at), {
    addSuffix: true,
    locale: ja,
  });
  const resolvedAgo = ticket.resolved_at
    ? formatDistanceToNow(new Date(ticket.resolved_at), {
        addSuffix: true,
        locale: ja,
      })
    : null;

  const isInvestigating = ["investigating", "resolved", "closed"].includes(
    ticket.status
  );
  const isResolved = ["resolved", "closed"].includes(ticket.status);

  return (
    <Card className="transition-shadow hover:shadow-md">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-medium leading-snug">
            {ticket.title}
          </CardTitle>
          <div className="flex shrink-0 gap-1.5">
            <Badge variant={severityVariant(ticket.severity)}>
              {ticket.severity}
            </Badge>
            <Badge variant={statusVariant(ticket.status)}>
              {ticket.status}
            </Badge>
          </div>
        </div>
        <CardDescription className="text-xs">
          #{ticket.ticket_id.slice(0, 8)} · {ticket.category}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <TimelineStep
          label="起票"
          time={createdAgo}
          content={ticket.description}
          variant="open"
          isLast={!isInvestigating}
        />
        {isInvestigating && (
          <TimelineStep
            label="調査中"
            time={!isResolved ? updatedAgo : undefined}
            variant="investigating"
            isLast={!isResolved}
          />
        )}
        {isResolved && (
          <TimelineStep
            label="解決"
            time={resolvedAgo ?? updatedAgo}
            content={ticket.resolution}
            variant="resolved"
            isLast
          />
        )}
      </CardContent>
    </Card>
  );
}

function TicketSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex justify-between gap-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-5 w-16" />
        </div>
        <Skeleton className="mt-1 h-3 w-1/2" />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex gap-2.5">
          <Skeleton className="mt-1 h-2 w-2 shrink-0 rounded-full" />
          <div className="flex-1 space-y-1">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function TicketsTab() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [categoryFilter, setCategoryFilter] = useState<string>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTickets({
        status: statusFilter !== "all" ? statusFilter : undefined,
        category: categoryFilter !== "all" ? categoryFilter : undefined,
        limit: 50,
      });
      const sorted = [...data].sort(
        (a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity]
      );
      setTickets(sorted);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tickets");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, categoryFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const categories: Category[] = ["database", "network", "memory", "deploy", "other"];
  const statuses: Status[] = ["open", "investigating", "resolved", "closed"];

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-36">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">すべてのステータス</SelectItem>
            {statuses.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={categoryFilter} onValueChange={setCategoryFilter}>
          <SelectTrigger className="w-36">
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
          {!loading && !error && <span>{tickets.length} 件</span>}
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
          <span className="ml-1 text-xs opacity-70">
            (VITE_TICKET_SERVICE_URL を .env.local に設定してください)
          </span>
        </div>
      )}

      {/* List */}
      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <TicketSkeleton key={i} />
            ))}
          </div>
        ) : tickets.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground">
            <Inbox className="h-8 w-8 opacity-30" />
            <p className="text-sm">チケットが見つかりません</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {tickets.map((t) => (
              <TicketCard key={t.ticket_id} ticket={t} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

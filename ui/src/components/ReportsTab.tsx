import { useState, useEffect, useCallback } from "react";
import { RefreshCw, AlertCircle, BarChart2, ChevronDown, ChevronUp } from "lucide-react";
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
import { listReports } from "@/lib/api";
import type { Report, ReportType } from "@/types";

const REPORT_TYPE_LABELS: Record<ReportType, string> = {
  "incident-summary": "インシデント集計",
  cost: "コスト分析",
  operational: "運用状況",
  custom: "カスタム",
};

function typeVariant(t: ReportType): BadgeProps["variant"] {
  const map: Record<ReportType, BadgeProps["variant"]> = {
    "incident-summary": "critical",
    cost: "high",
    operational: "medium",
    custom: "secondary",
  };
  return map[t];
}

function ReportCard({ report }: { report: Report }) {
  const [expanded, setExpanded] = useState(false);
  const ago = formatDistanceToNow(new Date(report.created_at), {
    addSuffix: true,
    locale: ja,
  });

  return (
    <Card className="transition-shadow hover:shadow-md">
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm font-medium leading-snug">
            {report.title}
          </CardTitle>
          <Badge variant={typeVariant(report.type as ReportType)}>
            {REPORT_TYPE_LABELS[report.type as ReportType] ?? report.type}
          </Badge>
        </div>
        <CardDescription className="text-xs">
          #{report.report_id.slice(0, 8)} · {ago}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-muted-foreground leading-relaxed">{report.summary}</p>

        <Button
          variant="ghost"
          size="sm"
          className="h-7 px-2 text-xs"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? (
            <>
              <ChevronUp className="mr-1 h-3 w-3" />
              詳細を閉じる
            </>
          ) : (
            <>
              <ChevronDown className="mr-1 h-3 w-3" />
              詳細を表示
            </>
          )}
        </Button>

        {expanded && (
          <div className="prose prose-sm max-w-none border-t pt-3
            prose-p:my-1 prose-p:leading-relaxed
            prose-headings:text-sm prose-headings:font-semibold prose-headings:mt-3 prose-headings:mb-1 first:prose-headings:mt-0
            prose-ul:my-1 prose-ol:my-1 prose-li:my-0.5
            prose-strong:font-semibold
            prose-code:text-xs prose-code:rounded prose-code:px-0.5
            prose-pre:text-xs prose-pre:my-1">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {report.details}
            </ReactMarkdown>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ReportSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex justify-between gap-2">
          <Skeleton className="h-4 w-3/4" />
          <Skeleton className="h-5 w-20" />
        </div>
        <Skeleton className="mt-1 h-3 w-1/3" />
      </CardHeader>
      <CardContent className="space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
      </CardContent>
    </Card>
  );
}

const REPORT_TYPES: ReportType[] = ["incident-summary", "cost", "operational", "custom"];

export default function ReportsTab() {
  const [reports, setReports] = useState<Report[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listReports({
        type: typeFilter !== "all" ? typeFilter : undefined,
        limit: 50,
      });
      setReports(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load reports");
    } finally {
      setLoading(false);
    }
  }, [typeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="flex h-full flex-col gap-4 p-4">
      {/* Description */}
      <div className="rounded-lg border border-border/60 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        Analysis Agent が生成したレポートを表示します。Chat タブで「コスト分析して」などと依頼すると新しいレポートが追加されます。
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-2">
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-44">
            <SelectValue placeholder="Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">すべての種類</SelectItem>
            {REPORT_TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {REPORT_TYPE_LABELS[t]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          {!loading && !error && (
            <span>{reports.length} 件のレポート</span>
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
              <ReportSkeleton key={i} />
            ))}
          </div>
        ) : reports.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-muted-foreground">
            <BarChart2 className="h-8 w-8 opacity-30" />
            <p className="text-sm">レポートがありません</p>
            <p className="text-xs">Chat タブで Analysis Agent にレポート生成を依頼してください。</p>
          </div>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {reports.map((r) => (
              <ReportCard key={r.report_id} report={r} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

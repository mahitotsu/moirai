export type Category = "database" | "network" | "memory" | "deploy" | "other";
export type Severity = "low" | "medium" | "high" | "critical";
export type Status = "open" | "investigating" | "resolved" | "closed";

export interface Ticket {
  ticket_id: string;
  title: string;
  description: string;
  category: Category;
  severity: Severity;
  status: Status;
  resolution?: string;
  lesson_learned?: string;
  created_at: string;
  updated_at: string;
  resolved_at?: string;
}

export type ReportType = "incident-summary" | "cost" | "operational" | "custom";

export interface Report {
  report_id: string;
  title: string;
  type: ReportType;
  summary: string;
  details: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  isLoading?: boolean;
}

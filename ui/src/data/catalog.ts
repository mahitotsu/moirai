// System catalog — static metadata for agents and MCP servers.
// System prompts here are fallback values used when Bedrock Prompt Management is unavailable.
// At runtime, SystemTab fetches live prompts from /api/prompts (Bedrock Prompt Management).
// When you edit a system prompt file, update the fallback constants below too.

export type ToolDef = {
  name: string;
  description: string;
};

export type AgentDef = {
  id: string;
  name: string;
  /** AgentCore Runtime protocol */
  protocol: "AG-UI" | "A2A";
  model: string;
  /** Why this model was chosen for this agent */
  modelNote: string;
  description: string;
  tools: ToolDef[];
};

export type McpDef = {
  id: string;
  name: string;
  runtimeName: string;
  capability: string;
  description: string;
  tools: ToolDef[];
};

// ---------------------------------------------------------------------------
// Agent catalog
// ---------------------------------------------------------------------------

export const AGENTS: AgentDef[] = [
  {
    id: "gateway",
    name: "Gateway Agent",
    protocol: "AG-UI",
    model: "claude-sonnet-4-6",
    modelNote: "Sonnet — Guardrails との統合・複数サブエージェントのオーケストレーションに高い推論力が必要",
    description:
      "ユーザー向けオーケストレーター。Chat UI からの横断クエリ受付と、ticket-dispatcher からの自動診断依頼をどちらも処理する。Bedrock Guardrails で禁止操作をブロック。",
    tools: [
      {
        name: "run_triage",
        description:
          "Triage Agent に A2A で委譲。インシデントの重大度・カテゴリ・検索キーワードを JSON で返す。",
      },
      {
        name: "run_diagnosis",
        description:
          "Diagnosis Agent に A2A で委譲。コミュニティ知識と過去チケットを並列検索して診断結果を返す。",
      },
      {
        name: "run_resolution",
        description:
          "Resolution Agent に A2A で委譲。解決計画を生成し、既存チケットを更新（または新規作成）する。",
      },
    ],
  },
  {
    id: "triage",
    name: "Triage Agent",
    protocol: "A2A",
    model: "claude-haiku-4-5",
    modelNote: "Haiku — ツールなし・構造化出力のみの分類タスクは高速・低コストな Haiku で十分",
    description:
      "インシデントを受け取り severity / category / 検索キーワードを分類して JSON で返す。ツール呼び出しなしで構造化出力を返す高速分類エージェント。",
    tools: [],
  },
  {
    id: "diagnosis",
    name: "Diagnosis Agent",
    protocol: "A2A",
    model: "claude-sonnet-4-6",
    modelNote: "Sonnet — 複数 MCP を並列呼び出しして証拠を統合する深い推論が必要",
    description:
      "CloudWatch アラーム確認・コミュニティ知識検索・過去チケット照合を行い、根本原因と推奨アクションを JSON で返す。",
    tools: [
      {
        name: "check_cloudwatch_alarms",
        description:
          "CloudWatch で現在 ALARM 状態のメトリクスアラームを取得する。インフラ異常の ground truth として最初に呼び出す。",
      },
      {
        name: "search_community_knowledge",
        description:
          "Stack Overflow / GitHub Issues / AWS Docs を並列検索し、エラーメッセージや技術用語に関する解決策を集約する。",
      },
      {
        name: "search_past_tickets",
        description:
          "DynamoDB の agora-tickets テーブルから過去の resolved チケットを検索し、類似インシデントの解決策を参照する。",
      },
    ],
  },
  {
    id: "resolution",
    name: "Resolution Agent",
    protocol: "A2A",
    model: "claude-sonnet-4-6",
    modelNote: "Sonnet — 具体的な手順・lesson_learned を structured_output で確実に埋めるには高い指示追従性が必要",
    description:
      "診断結果を元に具体的な解決手順を生成し、AgentCore Gateway 経由で Ticket Service に記録する。lesson_learned も書き込む。",
    tools: [
      {
        name: "create_ticket (Gateway)",
        description:
          "AgentCore Gateway 経由で Ticket Service の POST /tickets を呼び出し、新規インシデントチケットを起票する。",
      },
      {
        name: "update_ticket (Gateway)",
        description:
          "AgentCore Gateway 経由で Ticket Service の PATCH /tickets/{id} を呼び出し、status / resolution / category / lesson_learned を更新する。",
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// MCP server catalog
// ---------------------------------------------------------------------------

export const MCPS: McpDef[] = [
  {
    id: "stackoverflow",
    name: "Stack Overflow MCP",
    runtimeName: "agora_stackoverflow",
    capability: "community-knowledge",
    description:
      "Stack Exchange API を呼び出し、技術的な問題に対する Q&A と採択回答を取得する。自作 FastMCP。",
    tools: [
      {
        name: "search_stackoverflow",
        description:
          "クエリと任意のタグで Stack Overflow を検索し、スコア・回答数・本文プレビューを返す。",
      },
    ],
  },
  {
    id: "github-issues",
    name: "GitHub Issues MCP",
    runtimeName: "agora_github_issues",
    capability: "community-knowledge",
    description:
      "GitHub Search API でバグレポートや議論を検索する。公開リポジトリへの認証不要アクセス。自作 FastMCP。",
    tools: [
      {
        name: "search_github_issues",
        description:
          "クエリと任意のリポジトリ指定で GitHub Issues / PRs を検索し、状態・ラベル・コメント数を返す。",
      },
    ],
  },
  {
    id: "aws-docs",
    name: "AWS Docs MCP",
    runtimeName: "agora_aws_docs",
    capability: "community-knowledge",
    description:
      "AWS 公式ドキュメントを検索・参照する。awslabs/mcp の aws-documentation-mcp-server を流用。",
    tools: [
      {
        name: "search_documentation",
        description: "AWS ドキュメントをキーワード検索してページの抜粋を返す。",
      },
      {
        name: "read_documentation",
        description: "指定した AWS ドキュメント URL のページ本文を取得する。",
      },
    ],
  },
  {
    id: "cloudwatch",
    name: "CloudWatch MCP",
    runtimeName: "agora_cloudwatch",
    capability: "aws-observability",
    description:
      "CloudWatch メトリクス・アラーム・Logs Insights を参照する。awslabs/mcp の cloudwatch-mcp-server を流用。",
    tools: [
      {
        name: "get_metric_data",
        description: "指定した名前空間・メトリクス名・期間でメトリクスデータを取得する。",
      },
      {
        name: "describe_alarms",
        description: "CloudWatch アラームの状態・閾値・理由を取得する。",
      },
      {
        name: "start_query / get_query_results",
        description: "CloudWatch Logs Insights クエリを実行してログを分析する。",
      },
    ],
  },
  {
    id: "infrastructure-inspector",
    name: "Infrastructure Inspector MCP",
    runtimeName: "agora_infrastructure_inspector",
    capability: "aws-infrastructure",
    description:
      "Lambda 関数・FIS 実験・CloudFormation スタックの状態を調査する。診断フロー強化のために自作した FastMCP。",
    tools: [
      {
        name: "inspect_lambda",
        description:
          "Lambda 関数の設定（タイムアウト・メモリ・環境変数キー）とイベントソースマッピングを取得する。",
      },
      {
        name: "list_active_fis_experiments",
        description:
          "現在実行中の FIS 実験を一覧し、注入中の障害タイプと対象リソースを返す。",
      },
      {
        name: "describe_cfn_stack",
        description:
          "CloudFormation スタックのステータスと全リソース一覧を取得する。FaultInjectionStack や AgoraStack の構成確認に使用。",
      },
    ],
  },
];

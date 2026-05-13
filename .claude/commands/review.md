# /review

マイルストーン完了時・疑いが生じたときに実施する深いレビュー。
機械的に直せる問題は即修正、構造・設計に関わる問題は優先順位付きのプランを提示してから承認を得て修正する。

## チェック項目と対応方針

### 1. 実施確認 — BACKLOG.md との整合性

BACKLOG.md で `[x]` になっているタスクを対象に、実装が実際に存在するか確認する。

```bash
# 完了済みタスクに対応するファイル・ディレクトリが存在するか
find services/ mcp-servers/ agents/ infrastructure/ ui/ -type f | sort
```

- ファイルが存在しない → **即修正**（作成または BACKLOG.md の完了マークを戻す）
- ファイルが存在しても中身がスタブのみ → 問題としてリストアップ

### 2. CLAUDE.md 規約への準拠確認

以下を機械的にチェックし、違反があれば**即修正**する。

```bash
# from __future__ import annotations の漏れ
grep -rL "from __future__ import annotations" services/ mcp-servers/ agents/ --include="*.py"

# os.environ 直読み（pydantic-settings を使うべき）
grep -rn "os\.environ\[" services/ mcp-servers/ agents/ --include="*.py"

# クレデンシャルのハードコード疑い
grep -rn "aws_access_key\|aws_secret\|AKIA" services/ mcp-servers/ agents/ --include="*.py"

# エンドポイントのハードコード疑い（localhost 以外の URL リテラル）
grep -rn "https\?://[^\"']*\.(amazonaws\.com\|execute-api)" services/ agents/ --include="*.py"
```

### 3. 凝集性の確認

以下の観点でファイルを読んで判断する。**機械的チェック不可のため、問題発見時はプランを提示して承認後に修正**。

- **エージェントの System Prompt**: `agents/{name}/system_prompt.md` として独立しているか（`agent.py` 内にハードコードされていないか）
- **設定の分離**: 各サービス・エージェントが `settings.py` / `pydantic-settings` で設定を管理しているか
- **DynamoDB クライアントの注入**: `repository.py` がコンストラクタで受け取る構造になっているか（グローバル変数で直接 `boto3.client()` していないか）
- **コンポーネント間の直接依存**: サービス間で import し合っていないか（疎結合の確認）

### 4. ベストプラクティス・ドキュメント整合性

以下を確認し、**軽微な修正は即実施、設計変更を伴う場合はプランを提示**。

- **pyproject.toml の構造**: 各コンポーネントの `pyproject.toml` がルートの uv workspace メンバーとして定義されているか
- **Dockerfile**: `--platform linux/arm64` なし（make build 側で指定）、uv マルチステージビルドになっているか
- **CONCEPT.md との整合**: 実装がCONCEPTの設計原則（責務分割・capability ベース発見・業務データとエージェント文脈の分離等）に従っているか
- **CLAUDE.md との整合**: CLAUDE.md に記載のディレクトリ構成・規約と実態が一致しているか

## 結果の報告形式

レビュー完了後、以下の形式で報告する。

```
## レビュー結果

### 即修正済み
- [修正内容] — [ファイル名]
...

### 要対応（プラン提示）
優先度High:
1. [問題の説明] — [影響範囲]

優先度Medium:
2. ...

### 問題なし
- [チェック項目]
...
```

プラン提示後、ユーザーの承認を得てから構造修正に着手する。

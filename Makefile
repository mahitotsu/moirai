
# make test                       — 全テスト
# make test-service s=ticket-service — サービス単体テスト
# make lint                       — ruff + mypy
# make build img=ticket-service   — ARM64 Dockerビルド (ローカル確認用)
# make cdk-diff                   — CDK差分確認
# make cdk-deploy                 — CDKデプロイ (承認必要、イメージビルド&プッシュを含む)
# make gen-specs                  — OpenAPI spec JSONを再生成
# make register-catalog           — AgentCore Registry catalog 登録 (Registry/Record は CDK 未対応)
#
# デモ制御 (V2):
# make demo-start                 — EventBridge Scheduler 有効化 (トラフィック開始)
# make demo-inject                — FIS 実験開始 (障害注入) ※ task #15 で実装予定
# make demo-stop                  — Scheduler 無効化 + 実行中 FIS 実験を強制終了

.PHONY: test test-service lint build cdk-diff cdk-synth cdk-deploy gen-specs register-catalog \
        demo-start demo-inject demo-stop

test:
	@failed=0; \
	for svcdir in services/*/; do \
	  [ -d "$$svcdir" ] || continue; \
	  find "$$svcdir" -name "test_*.py" | grep -q . || continue; \
	  pkg=$$(basename "$$svcdir"); \
	  uv run --package "$$pkg" pytest "$$svcdir" -v --tb=short 2>/dev/null || failed=1; \
	done; \
	uv run pytest mcp-servers/ agents/ -v --tb=short 2>/dev/null || failed=1; \
	[ "$$failed" -eq 0 ] && touch .test-passed || echo "Tests FAILED"

test-service:
	uv run --package $(s) pytest services/$(s)/ -v --tb=short && touch .test-passed

lint:
	uv run ruff check services/ mcp-servers/ agents/ infrastructure/ --exclude infrastructure/cdk.out
	@found=0; \
	for svcdir in services/*/ mcp-servers/*/ agents/*/; do \
	  [ -d "$$svcdir" ] || continue; \
	  find "$$svcdir" -name "*.py" | grep -q . || continue; \
	  found=1; uv run mypy "$$svcdir" --no-error-summary; \
	done; \
	[ "$$found" -eq 1 ] || echo "mypy: no Python files yet — skipped"

build:
	@if [ -f services/$(img)/pyproject.toml ]; then \
	  uv export --package $(img) --no-dev --no-hashes -o services/$(img)/requirements.txt; \
	  docker build --platform linux/arm64 --provenance=false -t agora-$(img):latest -f services/$(img)/Dockerfile services/$(img); \
	elif [ -f agents/$(img)/pyproject.toml ]; then \
	  uv export --package $(img) --no-dev --no-hashes -o agents/$(img)/requirements.txt; \
	  docker build --platform linux/arm64 --provenance=false -t agora-$(img):latest -f agents/$(img)/Dockerfile agents/; \
	else \
	  uv export --package $(img) --no-dev --no-hashes -o mcp-servers/$(img)/requirements.txt; \
	  docker build --platform linux/arm64 --provenance=false -t agora-$(img):latest -f mcp-servers/$(img)/Dockerfile mcp-servers/$(img); \
	fi

cdk-diff:
	cd infrastructure && AWS_DEFAULT_REGION=$(_REGION) cdk diff

cdk-synth:
	cd infrastructure && AWS_DEFAULT_REGION=$(_REGION) cdk synth

cdk-deploy:
	cd infrastructure && AWS_DEFAULT_REGION=$(_REGION) cdk deploy --all --require-approval never

gen-specs:
	uv run python - << 'EOF'
	import sys, json
	sys.path.insert(0, 'services/ticket-service')
	from app.main import app as t; json.dump(t.openapi(), open('infrastructure/specs/ticket-service.json','w'), indent=2)
	sys.modules.pop('app.main', None); sys.modules.pop('app.settings', None); sys.modules.pop('app.models', None); sys.modules.pop('app.repository', None); sys.modules.pop('app', None)
	sys.path.pop(0); sys.path.insert(0, 'services/asset-service')
	from app.main import app as a; json.dump(a.openapi(), open('infrastructure/specs/asset-service.json','w'), indent=2)
	print("Specs generated in infrastructure/specs/")
	EOF

register-catalog:
	uv run --package agora-infrastructure python infrastructure/scripts/register_catalog.py

# ─── V2 デモ制御 ─────────────────────────────────────────────────────────────

_REGION        := us-east-1
_SCHEDULE_NAME := agora-fake-api-server-schedule
_MONITORING_STACK := AgoraMonitoringStack

demo-start:
	@echo "==> Enabling EventBridge Scheduler (traffic starts, baseline metrics build up)..."
	@TARGET=$$(aws scheduler get-schedule --name $(_SCHEDULE_NAME) --region $(_REGION) --query 'Target' --output json); \
	aws scheduler update-schedule \
	  --name $(_SCHEDULE_NAME) \
	  --schedule-expression "rate(1 minute)" \
	  --flexible-time-window '{"Mode":"OFF"}' \
	  --target "$$TARGET" \
	  --state ENABLED \
	  --region $(_REGION) > /dev/null
	@echo "==> Done. Wait 2–3 minutes for baseline metrics, then run 'make demo-inject'."

demo-inject:
	@echo "==> Starting FIS experiment (DynamoDB GetItem throttle injection)..."
	@TMPL_ID=$$(aws cloudformation describe-stacks \
	  --stack-name $(_MONITORING_STACK) \
	  --region $(_REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='FisTemplateId'].OutputValue" \
	  --output text); \
	if [ -z "$$TMPL_ID" ] || [ "$$TMPL_ID" = "None" ]; then \
	  echo "ERROR: FIS template not found. Run 'make cdk-deploy' first."; exit 1; \
	fi; \
	EXP_ID=$$(aws fis start-experiment \
	  --experiment-template-id "$$TMPL_ID" \
	  --region $(_REGION) \
	  --query 'experiment.id' --output text); \
	echo "==> Experiment started: $$EXP_ID"
	@echo "==> Throttle active ~5 min. Watch alarm 'agora-fake-api-error-rate' in CloudWatch."

demo-stop:
	@echo "==> Disabling EventBridge Scheduler..."
	@TARGET=$$(aws scheduler get-schedule --name $(_SCHEDULE_NAME) --region $(_REGION) --query 'Target' --output json); \
	aws scheduler update-schedule \
	  --name $(_SCHEDULE_NAME) \
	  --schedule-expression "rate(1 minute)" \
	  --flexible-time-window '{"Mode":"OFF"}' \
	  --target "$$TARGET" \
	  --state DISABLED \
	  --region $(_REGION) > /dev/null
	@echo "==> Stopping any running FIS experiments..."
	@for exp_id in $$(aws fis list-experiments --region $(_REGION) \
	    --query "experiments[?state.status=='running'].id" --output text 2>/dev/null); do \
	  echo "    Stopping FIS experiment: $$exp_id"; \
	  aws fis stop-experiment --id "$$exp_id" --region $(_REGION) > /dev/null; \
	done
	@echo "==> Done. All traffic stopped."

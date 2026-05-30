
# ─── 変数定義 ──────────────────────────────────────────────────────────────────
_REGION           := us-east-1
_SCHEDULE_NAME    := agora-fake-api-server-schedule
_MONITORING_STACK := FaultInjectionStack

# ─── コマンド一覧 ──────────────────────────────────────────────────────────────
# make test                       — 全テスト
# make test-service s=ticket-service — サービス単体テスト
# make lint                       — ruff + mypy
# make build img=ticket-service   — ARM64 Dockerビルド (ローカル確認用)
# make cdk-diff                   — CDK差分確認
# make cdk-deploy                 — CDKデプロイ (承認必要、イメージビルド&プッシュを含む)
# make gen-specs                  — OpenAPI spec JSONを再生成
#
# デモ制御 (V2):
# make demo-seed                  — 過去チケット50件を投入 (類似検索・横断クエリ用)
# make demo-start                 — EventBridge Scheduler 有効化 (トラフィック開始)
# make demo-inject                — FIS 実験開始 (障害注入)
# make demo-stop                  — Scheduler 無効化 + 実行中 FIS 実験を強制終了
#
# Observability セットアップ (V3, アカウントごとに1回・冪等):
.PHONY: test test-service lint build cdk-diff cdk-synth cdk-deploy gen-specs \
        demo-seed demo-start demo-inject demo-stop qemu-setup

test:
	@failed=0; \
	for svcdir in services/*/ mcp-servers/*/ agents/*/; do \
	  [ -d "$$svcdir" ] || continue; \
	  find "$$svcdir" -name "test_*.py" | grep -q . || continue; \
	  pkg=$$(basename "$$svcdir"); \
	  uv run --package "$$pkg" pytest "$$svcdir" -v --tb=short 2>/dev/null || failed=1; \
	done; \
	uv run --package agora-infrastructure pytest infrastructure/tests/ -v --tb=short 2>/dev/null || failed=1; \
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

build: qemu-setup
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

qemu-setup:
	@if grep -q enabled /proc/sys/fs/binfmt_misc/qemu-aarch64 2>/dev/null; then \
	  echo "==> QEMU arm64 already registered."; \
	else \
	  echo "==> Registering QEMU binfmt handlers for arm64..."; \
	  docker run --rm --privileged multiarch/qemu-user-static --reset -p yes; \
	fi

cdk-diff:
	cd infrastructure && AWS_DEFAULT_REGION=$(_REGION) cdk diff

cdk-synth:
	cd infrastructure && AWS_DEFAULT_REGION=$(_REGION) cdk synth

cdk-deploy: qemu-setup
	cd infrastructure && AWS_DEFAULT_REGION=$(_REGION) cdk deploy --all --require-approval never

gen-specs:
	TABLE_NAME=dummy uv run python -c "\
	import sys, json; \
	sys.path.insert(0, 'services/ticket-service'); \
	from app.main import app as t; \
	json.dump(t.openapi(), open('infrastructure/specs/ticket-service.json','w'), indent=2); \
	print('Specs generated in infrastructure/specs/')"

# ─── V2 デモ制御 ─────────────────────────────────────────────────────────────

demo-seed:
	@echo "==> Seeding demo data (50 historical tickets) ..."
	@uv run python scripts/seed_demo_data.py
	@echo "==> Seed complete. Knowledge table and S3 Vectors will be updated in ~30 seconds via DynamoDB Streams."

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
	@echo "==> Starting FIS experiment (EC2 DescribeInstances throttle injection)..."
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


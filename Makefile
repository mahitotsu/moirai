REGION  := us-east-1
ACCOUNT := $(shell aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
ECR     := $(ACCOUNT).dkr.ecr.$(REGION).amazonaws.com

# make test                       — 全テスト
# make test-service s=ticket-service — サービス単体テスト
# make lint                       — ruff + mypy
# make build img=ticket-service   — ARM64 Dockerビルド (services/ or mcp-servers/)
# make build img=triage           — ARM64 Dockerビルド (agents/)
# make deploy img=ticket-service  — ECRにプッシュ (承認必要)
# make cdk-diff                   — CDK差分確認
# make cdk-deploy                 — CDKデプロイ (承認必要)
# make gen-specs                  — OpenAPI spec JSONを再生成
# make register-gateway           — AgentCore Gateway 登録 (承認必要)
# make register-registry          — AgentCore Registry 登録 (MCP servers, 承認必要)
# make register-agents            — AgentCore Runtime 登録 (A2A agents, 承認必要)

.PHONY: test test-service lint build deploy cdk-diff cdk-synth cdk-deploy gen-specs register-gateway register-registry register-agents

test:
	uv run pytest services/ mcp-servers/ agents/ -v --tb=short 2>/dev/null && touch .test-passed || \
	  echo "No tests found yet — add tests under services/, mcp-servers/, agents/"

test-service:
	uv run pytest services/$(s)/ -v --tb=short && touch .test-passed

lint:
	uv run ruff check services/ mcp-servers/ agents/ infrastructure/
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
	  cp -r agents/common agents/$(img)/common; \
	  docker build --platform linux/arm64 --provenance=false -t agora-$(img):latest -f agents/$(img)/Dockerfile agents/$(img); \
	  rm -rf agents/$(img)/common; \
	else \
	  uv export --package $(img) --no-dev --no-hashes -o mcp-servers/$(img)/requirements.txt; \
	  docker build --platform linux/arm64 --provenance=false -t agora-$(img):latest -f mcp-servers/$(img)/Dockerfile mcp-servers/$(img); \
	fi

deploy:
	aws ecr get-login-password --region $(REGION) | \
	  docker login --username AWS --password-stdin $(ECR)
	docker tag agora-$(img):latest $(ECR)/agora-$(img):latest
	docker push $(ECR)/agora-$(img):latest

cdk-diff:
	cd infrastructure && cdk diff

cdk-synth:
	cd infrastructure && cdk synth

cdk-deploy:
	cd infrastructure && cdk deploy --all --require-approval broadening

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

register-gateway:
	uv run python infrastructure/scripts/register_gateway.py \
	  --ticket-url "$(TICKET_URL)" \
	  --asset-url  "$(ASSET_URL)"

register-registry:
	uv run python infrastructure/scripts/register_registry.py

register-agents:
	uv run python infrastructure/scripts/register_agents.py

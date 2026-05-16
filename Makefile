
# make test                       — 全テスト
# make test-service s=ticket-service — サービス単体テスト
# make lint                       — ruff + mypy
# make build img=ticket-service   — ARM64 Dockerビルド (ローカル確認用)
# make cdk-diff                   — CDK差分確認
# make cdk-deploy                 — CDKデプロイ (承認必要、イメージビルド&プッシュを含む)
# make gen-specs                  — OpenAPI spec JSONを再生成
# make register-catalog           — AgentCore Registry catalog 登録 (Registry/Record は CDK 未対応)

.PHONY: test test-service lint build cdk-diff cdk-synth cdk-deploy gen-specs register-catalog

test:
	@failed=0; \
	for svcdir in services/*/; do \
	  [ -d "$$svcdir" ] || continue; \
	  find "$$svcdir" -name "test_*.py" | grep -q . || continue; \
	  uv run pytest "$$svcdir" -v --tb=short 2>/dev/null || failed=1; \
	done; \
	uv run pytest mcp-servers/ agents/ -v --tb=short 2>/dev/null || failed=1; \
	[ "$$failed" -eq 0 ] && touch .test-passed || echo "Tests FAILED"

test-service:
	uv run pytest services/$(s)/ -v --tb=short && touch .test-passed

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

register-catalog:
	uv run --package agora-infrastructure python infrastructure/scripts/register_catalog.py

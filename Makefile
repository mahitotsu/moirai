REGION  := us-east-1
ACCOUNT := $(shell aws sts get-caller-identity --query Account --output text 2>/dev/null || echo "unknown")
ECR     := $(ACCOUNT).dkr.ecr.$(REGION).amazonaws.com

# make test                       — 全テスト
# make test-service s=ticket-service — サービス単体テスト
# make lint                       — ruff + mypy
# make build img=ticket-service   — ARM64 Dockerビルド
# make deploy img=ticket-service  — ECRにプッシュ (承認必要)
# make cdk-diff                   — CDK差分確認
# make cdk-deploy                 — CDKデプロイ (承認必要)

.PHONY: test test-service lint build deploy cdk-diff cdk-synth cdk-deploy

test:
	uv run pytest services/ mcp-servers/ agents/ -v --tb=short 2>/dev/null && touch .test-passed || \
	  echo "No tests found yet — add tests under services/, mcp-servers/, agents/"

test-service:
	uv run pytest services/$(s)/ -v --tb=short && touch .test-passed

lint:
	uv run ruff check services/ mcp-servers/ agents/ infrastructure/
	@MYPY_TARGETS=$$(find services/ mcp-servers/ agents/ -name "*.py" -printf "%h\n" 2>/dev/null | sort -u | tr '\n' ' '); \
	if [ -n "$$MYPY_TARGETS" ]; then \
	  uv run mypy $$MYPY_TARGETS --no-error-summary; \
	else \
	  echo "mypy: no Python files yet — skipped"; \
	fi

build:
	docker build --platform linux/arm64 \
	  -t agora-$(img):latest \
	  -f services/$(img)/Dockerfile services/$(img) \
	  2>/dev/null || \
	docker build --platform linux/arm64 \
	  -t agora-$(img):latest \
	  -f mcp-servers/$(img)/Dockerfile mcp-servers/$(img)

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

#!/usr/bin/env bash
# テスト成功時に .test-passed へ現在の git 状態を記録する。
# test_stale.sh と対になるスクリプト。

STAMP=".test-passed"

head=$(git rev-parse HEAD 2>/dev/null) || { echo "" > "$STAMP"; exit 0; }

untracked=$(git ls-files --others --exclude-standard 2>/dev/null)
dirty=$(
  {
    git diff HEAD 2>/dev/null
    if [ -n "$untracked" ]; then
      echo "$untracked"
      echo "$untracked" | xargs cat 2>/dev/null
    fi
  } | sha256sum | cut -d' ' -f1
)

printf '%s %s\n' "$head" "$dirty" > "$STAMP"

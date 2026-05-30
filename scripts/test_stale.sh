#!/usr/bin/env bash
# テストの実行要否を判定する (git ベース)。
#
# Exit 0 (stale) : .test-passed が存在しない、または git の状態が変化した → テスト必要
# Exit 1 (fresh) : git の状態が前回テスト時と一致している → スキップ可能
#
# 判定対象:
#   - git HEAD コミットハッシュ (新しいコミットを検知)
#   - git diff HEAD (追跡済みファイルの staged/unstaged 変更を検知)
#   - 未追跡ファイルのパスと内容 (新規ファイル追加を検知)
#
# 利点: 拡張子フィルタ不要 — .md / Dockerfile / .json など全ファイルタイプの変更を検知する

STAMP=".test-passed"

[ ! -f "$STAMP" ] && exit 0

read -r stored_head stored_dirty < "$STAMP" || exit 0

current_head=$(git rev-parse HEAD 2>/dev/null) || exit 0  # git 使用不可なら stale

# git diff HEAD  : 追跡済みファイルへの全変更 (staged + unstaged)
# git ls-files --others : 未追跡ファイル一覧 + xargs cat でその内容も含める
untracked_files=$(git ls-files --others --exclude-standard 2>/dev/null)
current_dirty=$(
  {
    git diff HEAD 2>/dev/null
    if [ -n "$untracked_files" ]; then
      echo "$untracked_files"
      echo "$untracked_files" | xargs cat 2>/dev/null
    fi
  } | sha256sum | cut -d' ' -f1
)

[ "$stored_head" = "$current_head" ] && [ "$stored_dirty" = "$current_dirty" ] && exit 1
exit 0  # stale

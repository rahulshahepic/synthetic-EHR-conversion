#!/usr/bin/env bash
# Merge one built demo into gh-pages, retrying if another workflow pushes first.
set -euo pipefail

archive="$RUNNER_TEMP/pages-archive"
git worktree add --detach "$archive" HEAD

for try in {1..10}; do
  remote_ref="$(git ls-remote --heads origin gh-pages)"
  if [[ -n "$remote_ref" ]]; then
    git fetch origin gh-pages
    git -C "$archive" checkout -B gh-pages FETCH_HEAD
  else
    git -C "$archive" checkout --detach HEAD
    git -C "$archive" branch -D gh-pages 2>/dev/null || true
    git -C "$archive" checkout --orphan gh-pages
    git -C "$archive" rm -rf --ignore-unmatch .
  fi
  git -C "$archive" clean -fdx

  python tools/publish_site.py site "$archive" \
    "$GITHUB_RUN_ID" "$GITHUB_RUN_ATTEMPT" "$GITHUB_REF_NAME" "$GITHUB_SHA"
  git -C "$archive" add -A
  if git -C "$archive" diff --cached --quiet; then
    exit 0
  fi
  git -C "$archive" -c user.name='github-actions[bot]' \
    -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
    commit -m "Archive demo $GITHUB_RUN_ID attempt $GITHUB_RUN_ATTEMPT"
  if git -C "$archive" push origin HEAD:gh-pages; then
    exit 0
  fi
  echo "Concurrent Pages archive update; retrying ($try/10)" >&2
  sleep "$try"
done

echo 'Could not update gh-pages after 10 attempts' >&2
exit 1

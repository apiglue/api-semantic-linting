#!/usr/bin/env bash
# Download a review artifact from the most recent finished run of this workflow on this
# pull request's branch, so a push that changes no spec can reuse that review.
#
# Usage: previous-review.sh ARTIFACT_NAME DEST_DIR
# Prints the reused run's id and exits 0; exits 1 when no earlier review is available.
set -euo pipefail

artifact="$1"
dest="$2"

workflow="$(basename "${GITHUB_WORKFLOW_REF%@*}")"
tmp="$(mktemp -d)"

# Cancelled runs were superseded before finishing; anything else completed its review.
run_ids="$(gh run list --repo "$GITHUB_REPOSITORY" --workflow "$workflow" \
  --branch "$GITHUB_HEAD_REF" --event pull_request --limit 20 \
  --json databaseId,status,conclusion \
  --jq ".[] | select(.status == \"completed\" and .conclusion != \"cancelled\" and .databaseId != ${GITHUB_RUN_ID}) | .databaseId")"

for run_id in $run_ids; do
  if gh run download "$run_id" --repo "$GITHUB_REPOSITORY" --name "$artifact" --dir "$tmp/$run_id" > /dev/null 2>&1; then
    mkdir -p "$dest"
    cp -R "$tmp/$run_id/." "$dest/"
    echo "$run_id"
    exit 0
  fi
done

exit 1

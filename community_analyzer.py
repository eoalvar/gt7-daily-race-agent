name: GT7 Community Analyzer

on:
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: gt7-community-data-writer
  cancel-in-progress: false

jobs:
  analyze-community:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Run community analyzer
        run: python community_analyzer.py

      - name: Show generated files
        run: |
          echo "Community intelligence files:"
          find data/community_intelligence -maxdepth 2 -type f -print || true

      - name: Commit community intelligence
        shell: bash
        run: |
          set -euo pipefail

          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add data/community_intelligence/

          if git diff --cached --quiet; then
            echo "No community intelligence changes to commit."
            exit 0
          fi

          git commit -m "Update GT7 community intelligence"

          echo "Synchronizing with latest origin/main before push..."

          git fetch origin main
          git rebase origin/main

          echo "Pushing generated community intelligence..."

          if git push origin HEAD:main; then
            echo "Push successful."
            exit 0
          fi

          echo "Remote changed during first push attempt."
          echo "Fetching latest main and retrying once..."

          git fetch origin main
          git rebase origin/main
          git push origin HEAD:main

          echo "Push successful after retry."
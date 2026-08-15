name: GT7 Backfill History

on:
  workflow_dispatch:

permissions:
  contents: write

jobs:
  backfill:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4

      - name: Run archived race debug
        run: python src/debug_archived_race.py

      - name: Commit historical data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add data/

          if git diff --cached --quiet; then
            echo "No historical changes to commit."
          else
            git commit -m "Update GT7 historical Daily Race C data"
            git push
          fi
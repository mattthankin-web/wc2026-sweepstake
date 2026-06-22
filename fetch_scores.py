name: Generate Commentary

on:
  schedule:
    # 04:00 UTC = 2:00pm AEST
    - cron: '0 4 * * *'
  workflow_dispatch:  # allows manual trigger from GitHub UI

jobs:
  commentary:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install requests

      - name: Fetch latest scores first
        env:
          FOOTBALL_API_KEY: ${{ secrets.FOOTBALL_API_KEY }}
        run: python scripts/fetch_scores.py

      - name: Generate commentary
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          FOOTBALL_API_KEY: ${{ secrets.FOOTBALL_API_KEY }}
        run: python scripts/generate_commentary.py

      - name: Commit and push
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/data.json
          git diff --staged --quiet || git commit -m "chore: daily commentary $(date -u '+%Y-%m-%d')"
          git push

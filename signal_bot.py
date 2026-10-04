name: AlphaQuant V5.1 Signal Bot

on:
  schedule:
    - cron: "7,22,37,52 * * * *"
  workflow_dispatch:

permissions:
  contents: read

concurrency:
  group: alphaquant-signal-bot
  cancel-in-progress: false

jobs:
  scan:
    name: SMC Scalp Scan
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      # 1. CHECKOUT
      - name: Checkout repository
        uses: actions/checkout@v4

      # 2. PYTHON (cache pip dihapus: butuh requirements.txt)
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      # 3. DEPENDENCIES
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests

      # 4. VERIFY FILE
      - name: Verify bot files
        run: |
          echo "UTC:"; date -u
          echo "Python:"; python --version
          echo "Files:"; ls -la
          if [ ! -f "signal_bot.py" ]; then
            echo "ERROR: signal_bot.py not found!"
            exit 1
          fi
          echo "signal_bot.py: OK"

      # 5. RESTORE SIGNAL HISTORY
      - name: Restore signals history
        uses: actions/cache/restore@v4
        with:
          path: signals_history.json
          key: signals-history-${{ github.ref_name }}-${{ github.run_id }}
          restore-keys: |
            signals-history-${{ github.ref_name }}-

      # 6. RUN BOT
      - name: Run AlphaQuant Signal Bot
        env:
          TELEGRAM_TOKEN: ${{ secrets.TELEGRAM_TOKEN }}
          CHAT_ID: ${{ secrets.CHAT_ID }}

          SMC_MIN_RISK_PCT: ${{ vars.SMC_MIN_RISK_PCT }}
          SMC_MIN_RISK_PCT_BTC: ${{ vars.SMC_MIN_RISK_PCT_BTC }}
          SMC_MAX_OPEN: ${{ vars.SMC_MAX_OPEN }}
          TOP_PAIRS: ${{ vars.TOP_PAIRS }}
          MIN_VOLUME_USDT: ${{ vars.MIN_VOLUME_USDT }}
          RISK_PER_TRADE: ${{ vars.RISK_PER_TRADE }}
          ACCOUNT_EQUITY: ${{ vars.ACCOUNT_EQUITY }}
          FEE_PER_SIDE: ${{ vars.FEE_PER_SIDE }}
          REPORT_EVERY_HOURS: ${{ vars.REPORT_EVERY_HOURS }}

          RUN_FOREVER: "0"

        run: |
          set -e

          echo "Workflow: ${{ github.workflow }}"
          echo "Repository: ${{ github.repository }}"
          echo "Branch: ${{ github.ref_name }}"
          echo "Run ID: ${{ github.run_id }}"
          date -u

          # Hapus variabel opsional yang kosong supaya default di Python berlaku
          for var in \
            SMC_MIN_RISK_PCT \
            SMC_MIN_RISK_PCT_BTC \
            SMC_MAX_OPEN \
            TOP_PAIRS \
            MIN_VOLUME_USDT \
            RISK_PER_TRADE \
            ACCOUNT_EQUITY \
            FEE_PER_SIDE \
            REPORT_EVERY_HOURS
          do
            if [ -z "${!var}" ]; then
              unset "$var"
            fi
          done

          # Validasi Telegram
          if [ -z "$TELEGRAM_TOKEN" ]; then
            echo "ERROR: TELEGRAM_TOKEN is missing!"
            exit 1
          fi
          if [ -z "$CHAT_ID" ]; then
            echo "ERROR: CHAT_ID is missing!"
            exit 1
          fi
          echo "TELEGRAM_TOKEN: OK"
          echo "CHAT_ID: OK"

          # Status variabel opsional
          for var in \
            SMC_MIN_RISK_PCT \
            SMC_MIN_RISK_PCT_BTC \
            SMC_MAX_OPEN \
            TOP_PAIRS \
            MIN_VOLUME_USDT \
            RISK_PER_TRADE \
            ACCOUNT_EQUITY \
            FEE_PER_SIDE \
            REPORT_EVERY_HOURS
          do
            if [ -n "${!var:-}" ]; then
              echo "$var: SET"
            else
              echo "$var: DEFAULT"
            fi
          done

          echo "Starting signal scanner..."
          python -u signal_bot.py
          echo "AlphaQuant scan completed"

      # 7. CHECK HISTORY
      - name: Check signals history
        if: always()
        run: |
          if [ -f "signals_history.json" ]; then
            echo "signals_history.json: EXISTS"
            ls -lh signals_history.json
          else
            echo "signals_history.json: NOT FOUND"
          fi

      # 8. SAVE HISTORY
      - name: Save signals history
        if: always()
        uses: actions/cache/save@v4
        with:
          path: signals_history.json
          key: signals-history-${{ github.ref_name
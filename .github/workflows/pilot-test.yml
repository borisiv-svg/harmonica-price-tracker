name: 🧪 Crawl4AI Pilot Test

on:
  workflow_dispatch:

jobs:
  pilot-test:
    runs-on: ubuntu-latest
    
    steps:
      - name: 📥 Checkout code
        uses: actions/checkout@v4
      
      - name: 🐍 Setup Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: 📚 Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install crawl4ai
          
          # Поправка за Ubuntu 24.04
          sudo apt-get update
          sudo apt-get install -y libasound2t64 libatk1.0-0 libcups2 libdbus-1-3 \
            libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 \
            libxcomposite1 libxdamage1 libxfixes3 libxkbcommon0 libxrandr2 xvfb
          
          # Инициализация на Crawl4AI
          crawl4ai-setup || true
      
      - name: 🧪 Run Pilot Test
        run: |
          echo "Starting Crawl4AI pilot test..."
          python experimental/crawl4ai_pilot.py
      
      - name: 📋 Upload results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: pilot-results-${{ github.run_number }}
          path: |
            experimental/pilot_results.json
            *.log
          retention-days: 30

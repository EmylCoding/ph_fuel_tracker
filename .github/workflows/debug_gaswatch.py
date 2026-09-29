name: Debug GasWatch Scraping

on:
  workflow_dispatch:

jobs:
  debug:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install requests beautifulsoup4
      
      - name: Debug GasWatch HTML
        run: |
          python << 'EOF'
          import requests
          from bs4 import BeautifulSoup
          
          url = "https://gaswatchph.com/"
          headers = {
              "User-Agent": (
                  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
              )
          }
          
          response = requests.get(url, headers=headers, timeout=20)
          soup = BeautifulSoup(response.text, "html.parser")
          text = " ".join(soup.stripped_strings)
          
          print("=== First 3000 characters ===")
          print(text[:3000])
          print("\n=== Looking for price patterns ===")
          
          if "95.95" in text:
              idx = text.find("95.95")
              print(f"\nFound '95.95' - Context:")
              print(text[max(0, idx-200):idx+200])
          
          if "89.55" in text:
              idx = text.find("89.55")
              print(f"\nFound '89.55' - Context:")
              print(text[max(0, idx-200):idx+200])
          
          if "95" in text and "diesel" in text.lower():
              print("\nSearching for diesel mentions...")
              for i, line in enumerate(text.split("\n")):
                  if "diesel" in line.lower() and any(c.isdigit() for c in line):
                      print(f"Line {i}: {line[:150]}")
          EOF

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

# Print the first 2000 characters to see the structure
print("=== GasWatch Page Text (First 2000 chars) ===")
print(text[:2000])
print("\n")

# Look for where the prices appear
if "95.95" in text:
    idx = text.find("95.95")
    print(f"Found '95.95' at position {idx}")
    print(f"Context: {text[max(0, idx-150):idx+150]}")
    print("\n")

if "89.55" in text:
    idx = text.find("89.55")
    print(f"Found '89.55' at position {idx}")
    print(f"Context: {text[max(0, idx-150):idx+150]}")

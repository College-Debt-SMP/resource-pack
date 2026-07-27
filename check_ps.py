import urllib.request
import json

url = "https://api.github.com/repos/ComunidadAylas/PackSquash/releases"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
response = urllib.request.urlopen(req)
data = json.loads(response.read().decode('utf-8'))

for release in data:
    if "0.4" in release['tag_name']:
        print(f"--- Release {release['tag_name']} ---")
        if "maximum_width_and_height" in release['body'] or "maximum" in release['body']:
            print("MENTIONED IN BODY")
        print(release['body'][:1000])

import os
import httpx
import json
from dotenv import load_dotenv

load_dotenv('nexora/.env')
client = httpx.Client(
    base_url=os.environ['NEBIUS_BASE_URL'],
    headers={'Authorization': f"Bearer {os.environ.get('NEBIUS_API_KEY', '')}"}
)
response = client.get('/models')
print(json.dumps(response.json(), indent=2))

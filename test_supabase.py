import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
bucket = os.getenv("SUPABASE_BUCKET")

client = create_client(url, key)

with open("hello.txt", "rb") as f:
    client.storage.from_(bucket).upload(
        path="hello.txt",
        file=f
    )

print("Upload successful!")
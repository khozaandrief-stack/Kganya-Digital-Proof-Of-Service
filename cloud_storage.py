import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET")

client = create_client(SUPABASE_URL, SUPABASE_KEY)


def upload_backup():
    backup_file = "backups/database_backup.db"

    if not os.path.exists(backup_file):
        print("Backup file not found.")
        return False

    with open(backup_file, "rb") as f:
        client.storage.from_(SUPABASE_BUCKET).upload(
            path="database_backup.db",
            file=f
        )

    print("Cloud backup uploaded successfully.")
    return True


def download_backup():
    data = client.storage.from_(SUPABASE_BUCKET).download(
        "database_backup.db"
    )

    os.makedirs("backups", exist_ok=True)

    with open("backups/database_backup.db", "wb") as f:
        f.write(data)

    print("Backup downloaded successfully.")
    return True
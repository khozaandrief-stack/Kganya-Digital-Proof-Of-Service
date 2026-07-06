
import os
import sqlite3
import shutil
import logging
from datetime import datetime
from cloud_storage import upload_backup, download_backup

DB_NAME = "database.db"
BACKUP_FOLDER = "backups"
BACKUP_FILE = os.path.join(BACKUP_FOLDER, "database_backup.db")
LOG_FILE = os.path.join(BACKUP_FOLDER, "backup.log")

os.makedirs(BACKUP_FOLDER, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def backup_database():
    try:
        if not os.path.exists(DB_NAME):
            logging.error("Database file not found.")
            return False

        source = sqlite3.connect(DB_NAME)
        destination = sqlite3.connect(BACKUP_FILE)

        source.backup(destination)

        destination.close()
        source.close()

        size = round(os.path.getsize(BACKUP_FILE) / (1024 * 1024), 2)

        logging.info(f"Backup completed successfully ({size} MB)")
        print(f"✓ Backup completed successfully ({size} MB)")

        return True

    except Exception as e:
        logging.exception("Backup failed")
        print(f"Backup failed: {e}")
        return False

def restore_database():
    try:
        if os.path.exists(DB_NAME):
            print("✓ Database already exists.")
            return True

        if not os.path.exists(BACKUP_FILE):
            logging.error("No backup database found.")
            print("No backup available.")
            return False

        source = sqlite3.connect(BACKUP_FILE)
        destination = sqlite3.connect(DB_NAME)

        source.backup(destination)

        destination.close()
        source.close()

        logging.info("Database restored successfully.")
        print("✓ Database restored successfully.")

        return True

    except Exception as e:
        logging.exception("Restore failed")
        print(f"Restore failed: {e}")
        return False

from threading import Thread

from threading import Thread

def perform_backup():
    def worker():
        try:
            backup_database()
            upload_backup()
            print("Backup completed.")
        except Exception as e:
            print(f"Backup failed: {e}")

    Thread(target=worker, daemon=True).start()




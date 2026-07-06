from backup_manager import backup_database, restore_database
import os

backup_database()

if os.path.exists("database.db"):
    os.rename("database.db", "database_temp.db")

restore_database()

if os.path.exists("database_temp.db"):
    os.remove("database_temp.db")
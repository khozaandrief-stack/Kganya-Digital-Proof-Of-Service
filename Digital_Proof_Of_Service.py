"""
Digital Proof Of Service System — Complete Database Version
Saves ALL POS data to SQLite database for full read-only viewing.
Includes OTP verification for user creation and secretary/vice-secretary phone numbers.
"""

# =========================================
# IMPORTS
# =========================================
import uuid
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
import os
import sqlite3
import re
import html as html_module
import json
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps
from flask_mail import Mail, Message

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    session,
    abort,
    flash,
    jsonify,
    send_file,
    render_template_string
)
from werkzeug.security import generate_password_hash, check_password_hash

from flask import url_for
#from flask import current_app

import secrets
import string

import tempfile

import base64
import hashlib




# =========================================
# FLASK APPLICATION SETUP
# =========================================
load_dotenv()

key = os.getenv("SECRET_KEY")
if not key:
    raise ValueError("SECRET_KEY is not set in .env file")

app = Flask(__name__)
app.secret_key = key

app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

DB_NAME = "database.db"
POS_FOLDER = "Kganya_Digital_POS"

UPLOAD_FOLDER = "Kganya_Uploads"
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'doc', 'docx', 'xls', 'xlsx'}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB

os.makedirs(os.path.join(UPLOAD_FOLDER, "proof_of_banking"), exist_ok=True)
os.makedirs(os.path.join(UPLOAD_FOLDER, "receipts"), exist_ok=True)

# Email configuration for OTP
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
OTP_EXPIRY_MINUTES = 10



app.config.update(
    MAIL_SERVER=SMTP_SERVER,
    MAIL_PORT=SMTP_PORT,
    MAIL_USE_TLS=(SMTP_PORT == 587),
    MAIL_USE_SSL=(SMTP_PORT == 465),
    MAIL_USERNAME=SMTP_USERNAME,
    MAIL_PASSWORD=SMTP_PASSWORD,
    MAIL_DEFAULT_SENDER=SMTP_USERNAME,
)

app.config["MAIL_MAX_EMAILS"] = None
app.config["MAIL_SUPPRESS_SEND"] = False
app.config["MAIL_ASCII_ATTACHMENTS"] = False
app.config["MAIL_TIMEOUT"] = 30








print(f"SMTP_SERVER={app.config['MAIL_SERVER']}")
print(f"SMTP_PORT={app.config['MAIL_PORT']}")
print(f"MAIL_USE_SSL={app.config['MAIL_USE_SSL']}")
print(f"MAIL_USE_TLS={app.config['MAIL_USE_TLS']}")


def verify_smtp():
    try:
        msg = Message(
            subject="SMTP Startup Test",
            recipients=[SMTP_USERNAME],
            body="SMTP connection successful."
        )

        mail.send(msg)

        print("SMTP OK")

    except Exception as e:
        print(f"SMTP FAILED: {e}")
        

mail = Mail(app)

print("\n========== EMAIL CONFIG ==========")
print("SMTP_SERVER =", app.config["MAIL_SERVER"])
print("MAIL_PORT   =", app.config["MAIL_PORT"])
print("MAIL_USE_TLS=", app.config["MAIL_USE_TLS"])
print("MAIL_USE_SSL=", app.config["MAIL_USE_SSL"])
print("==================================\n")

#with app.app_context():
#    verify_smtp()



# =========================================
# DATABASE SETUP & MIGRATION
# =========================================



#========================================================
# DATABASE CORE (STABLE .get() COMPATIBILITY LAYER)
#========================================================

#import sqlite3
#import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")


class RowDict:
    """
    Stable SQLite row wrapper that supports:
    - row["key"]
    - row.get("key")
    - safe fallback defaults
    """

    def __init__(self, row, keys):
        self._row = row
        self._keys = keys

    def get(self, key, default=None):
        try:
            idx = self._keys.index(key)
            return self._row[idx]
        except Exception:
            return default

    def __getitem__(self, key):
        idx = self._keys.index(key)
        return self._row[idx]

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._keys)


def dict_row_factory(cursor, row):
    """
    Converts SQLite row -> RowDict with safe key mapping
    """
    keys = [col[0] for col in cursor.description] if cursor.description else []
    return RowDict(row, keys)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = dict_row_factory
    return conn


print("DB PATH:", DB_PATH)



def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            price REAL NOT NULL DEFAULT 0.00,
            deduction REAL NOT NULL DEFAULT 0.00
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'admin',
            email TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            secretary_phone TEXT,
            vice_secretary_phone TEXT,
            secretary_email TEXT,
            vice_secretary_email TEXT,
            church_code TEXT,
            church_file_number TEXT UNIQUE,
            church_branch_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            secretary_phone TEXT,
            vice_secretary_phone TEXT,
            secretary_email TEXT,
            vice_secretary_email TEXT,
            church_code TEXT,
            church_file_number TEXT UNIQUE,
            church_branch_name TEXT,
            requested_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otp_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identifier TEXT NOT NULL,
            channel TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            purpose TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            verified INTEGER DEFAULT 0,
            attempts INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_otp_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            created_at TEXT NOT NULL,
            verified INTEGER DEFAULT 0,
            role TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pos_number TEXT NOT NULL,
            bank_sheet TEXT,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            month_name TEXT NOT NULL,
            church_name TEXT,
            church_code TEXT,
            church_file TEXT,
            depositor_name TEXT,
            depositor_id TEXT,
            depositor_phone TEXT,
            witness1 TEXT,
            witness2 TEXT,
            witness3 TEXT,
            total_banking REAL DEFAULT 0.00,
            total_parish REAL DEFAULT 0.00,
            total_stickers INTEGER DEFAULT 0,
            grand_total_cash REAL DEFAULT 0.00,
            expected_total REAL DEFAULT 0.00,
            total_outstanding REAL DEFAULT 0.00,
            final_status TEXT,
            count200 INTEGER DEFAULT 0,
            count100 INTEGER DEFAULT 0,
            count50 INTEGER DEFAULT 0,
            count20 INTEGER DEFAULT 0,
            count10 INTEGER DEFAULT 0,
            count_coins INTEGER DEFAULT 0,
            bank_count200 INTEGER DEFAULT 0,
            bank_count100 INTEGER DEFAULT 0,
            bank_count50 INTEGER DEFAULT 0,
            bank_count20 INTEGER DEFAULT 0,
            bank_count10 INTEGER DEFAULT 0,
            bank_count_coins INTEGER DEFAULT 0,
            minister_count200 INTEGER DEFAULT 0,
            minister_count100 INTEGER DEFAULT 0,
            minister_count50 INTEGER DEFAULT 0,
            minister_count20 INTEGER DEFAULT 0,
            minister_count10 INTEGER DEFAULT 0,
            minister_count_coins INTEGER DEFAULT 0,
            minister_total REAL DEFAULT 0.00,
            banking_amount_words TEXT,
            banking_remarks TEXT,
            minister_remarks TEXT,
            final_conclusion TEXT,
            file_path TEXT,
            html_file_path TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pos_record_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            product_type TEXT,
            sticker_from INTEGER,
            sticker_to INTEGER,
            sticker_count INTEGER DEFAULT 0,
            price_per_sticker REAL DEFAULT 0.00,
            deduction_per_sticker REAL DEFAULT 0.00,
            banking_amount REAL DEFAULT 0.00,
            parish_amount REAL DEFAULT 0.00,
            FOREIGN KEY (pos_record_id) REFERENCES pos_records(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_cancelled_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pos_record_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            product_type TEXT,
            sticker_from INTEGER,
            sticker_to INTEGER,
            sticker_count INTEGER DEFAULT 0,
            is_manual INTEGER DEFAULT 0,
            FOREIGN KEY (pos_record_id) REFERENCES pos_records(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_cash_rows (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pos_record_id INTEGER NOT NULL,
            r200 INTEGER DEFAULT 0,
            r100 INTEGER DEFAULT 0,
            r50 INTEGER DEFAULT 0,
            r20 INTEGER DEFAULT 0,
            r10 INTEGER DEFAULT 0,
            coins INTEGER DEFAULT 0,
            FOREIGN KEY (pos_record_id) REFERENCES pos_records(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pos_record_id INTEGER NOT NULL,
            upload_type TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            mime_type TEXT,
            uploaded_by TEXT NOT NULL,
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            replaced_at TIMESTAMP,
            is_replaced INTEGER DEFAULT 0,
            replaced_by_upload_id INTEGER,
            FOREIGN KEY (pos_record_id) REFERENCES pos_records(id),
            FOREIGN KEY (replaced_by_upload_id) REFERENCES pos_uploads(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products_master (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            price REAL NOT NULL DEFAULT 0,
            deduction REAL NOT NULL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receipt_booklets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            booklet_number TEXT NOT NULL,
            receipt_type TEXT NOT NULL,
            receipt_from INTEGER NOT NULL,
            receipt_to INTEGER NOT NULL,
            total_receipts INTEGER NOT NULL,
            price_at_allocation REAL NOT NULL,
            deduction_at_allocation REAL NOT NULL,
            next_expected_receipt INTEGER NOT NULL,
            is_active INTEGER DEFAULT 1,
            is_completed INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            allocated_by TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            UNIQUE(user_id, product_name, booklet_number)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS booklet_used_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booklet_id INTEGER NOT NULL,
            receipt_from INTEGER NOT NULL,
            receipt_to INTEGER NOT NULL,
            pos_record_id INTEGER,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booklet_id) REFERENCES receipt_booklets(id),
            FOREIGN KEY (pos_record_id) REFERENCES pos_records(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS booklet_cancelled_receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booklet_id INTEGER NOT NULL,
            receipt_from INTEGER NOT NULL,
            receipt_to INTEGER NOT NULL,
            cancellation_type TEXT DEFAULT 'auto',
            pos_record_id INTEGER,
            cancelled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booklet_id) REFERENCES receipt_booklets(id),
            FOREIGN KEY (pos_record_id) REFERENCES pos_records(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS deleted_booklets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_booklet_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            church_branch_name TEXT,
            product_name TEXT NOT NULL,
            booklet_number TEXT NOT NULL,
            receipt_type TEXT NOT NULL,
            receipt_from INTEGER NOT NULL,
            receipt_to INTEGER NOT NULL,
            total_receipts INTEGER NOT NULL,
            price_at_allocation REAL NOT NULL,
            deduction_at_allocation REAL NOT NULL,
            next_expected_receipt INTEGER NOT NULL,
            is_active INTEGER,
            is_completed INTEGER,
            created_at TIMESTAMP,
            allocated_by TEXT,
            deleted_by TEXT NOT NULL,
            deleted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            deletion_reason TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            action_category TEXT,
            description TEXT,
            username TEXT,
            user_role TEXT,
            ip_address TEXT,
            user_agent TEXT,
            session_id TEXT,
            table_affected TEXT,
            record_id INTEGER,
            old_values TEXT,
            new_values TEXT,
            amount REAL,
            pos_record_id INTEGER,
            is_superadmin_action INTEGER DEFAULT 0,
            login_success INTEGER,
            username_entered TEXT,
            password_entered_hash TEXT,
            failure_reason TEXT,
            location TEXT,
            device_info TEXT,
            previous_record_hash TEXT,
            record_hash TEXT,
            tamper_alert INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vice_secretary_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            secretary_email TEXT,
            vice_secretary_email TEXT NOT NULL,
            action TEXT NOT NULL,
            description TEXT,
            timestamp TEXT NOT NULL,
            sent INTEGER DEFAULT 0,
            sent_at TEXT,
            error_message TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skipped_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            church_branch_name TEXT,
            expected_sunday TEXT NOT NULL,
            reason TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            reviewed_by TEXT,
            reviewed_at TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_skipped_user ON skipped_submissions(username)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_skipped_status ON skipped_submissions(status)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_skipped_sunday ON skipped_submissions(expected_sunday)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            registrations_open INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT
        )
    """)

    cursor.execute("SELECT COUNT(*) FROM system_settings")
    row = cursor.fetchone()

    if row and list(row)[0] == 0:
        cursor.execute("INSERT INTO system_settings (registrations_open, updated_by) VALUES (0, 'system')")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admin_email_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            otp_code TEXT NOT NULL,
            temp_password TEXT NOT NULL,
            reset_token TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            verified INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pos_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pos_record_id INTEGER NOT NULL,
            expense_type TEXT NOT NULL,
            description TEXT,
            amount REAL NOT NULL DEFAULT 0.00,
            receipt_upload_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pos_record_id) REFERENCES pos_records(id),
            FOREIGN KEY (receipt_upload_id) REFERENCES pos_uploads(id)
        )
    """)

    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                email TEXT NOT NULL,
                token TEXT NOT NULL UNIQUE,
                expires_at TIMESTAMP NOT NULL,
                used INTEGER DEFAULT 0,
                user_type TEXT DEFAULT 'user',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    except:
        pass

    try:
        cursor.execute("ALTER TABLE password_reset_tokens ADD COLUMN user_type TEXT DEFAULT 'user'")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE pos_records ADD COLUMN total_expenses REAL DEFAULT 0.00")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE pos_records ADD COLUMN net_parish_balance REAL DEFAULT 0.00")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN secretary_email TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN vice_secretary_email TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE pending_users ADD COLUMN secretary_email TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE pending_users ADD COLUMN vice_secretary_email TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE pos_records ADD COLUMN banking_date TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE audit_log ADD COLUMN tamper_alert INTEGER DEFAULT 0")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE skipped_submissions ADD COLUMN reason TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE skipped_submissions ADD COLUMN explanation TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE skipped_submissions ADD COLUMN submitted_at TIMESTAMP")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE skipped_submissions ADD COLUMN reviewed_by TEXT")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE skipped_submissions ADD COLUMN reviewed_at TIMESTAMP")
    except:
        pass

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    except:
        pass
    # ── Add completed_at to receipt_booklets if missing ──
    try:
        cursor.execute("ALTER TABLE receipt_booklets ADD COLUMN completed_at TIMESTAMP")
    except:
        pass
    
    # ── Add pos_record_id to booklet_used_receipts if missing ──
    try:
        cursor.execute("ALTER TABLE booklet_used_receipts ADD COLUMN pos_record_id INTEGER REFERENCES pos_records(id)")
    except:
        pass
    
    # ── Add pos_record_id to booklet_cancelled_receipts if missing ──
    try:
        cursor.execute("ALTER TABLE booklet_cancelled_receipts ADD COLUMN pos_record_id INTEGER REFERENCES pos_records(id)")
    except:
        pass
    
    # ── Add cancellation_type to booklet_cancelled_receipts if missing ──
    try:
        cursor.execute("ALTER TABLE booklet_cancelled_receipts ADD COLUMN cancellation_type TEXT DEFAULT 'auto'")
    except:
        pass
    # ── Add max_receipt_issued to receipt_booklets if missing ──
    try:
        cursor.execute("ALTER TABLE receipt_booklets ADD COLUMN max_receipt_issued INTEGER DEFAULT 0")
    except:
        pass

    conn.commit()
    conn.close() 
    
 
#========================================================
# Safe Email Sending
#=======================================================


# =========================================
# STABLE EMAIL CORE (THREAD SAFE FIX)
# =========================================

from flask import current_app
from flask_mail import Message
import time
from threading import Thread

def _send_mail_job(app_config, msg, retries):
    """
    Stable SMTP sender (no Flask context dependency)
    """

    for attempt in range(1, retries + 1):
        try:
            with app.app_context():
                mail.send(msg)

            print("✓ Email sent successfully")
            return True

        except Exception as e:
            print(f"Email attempt {attempt}/{retries} failed: {e}")

            if attempt < retries:
                time.sleep(2)

    return False


def safe_send_mail(msg, retries=3, async_mode=True):
    """
    Single stable entry point for ALL email sending
    """

    try:
        if async_mode:
            thread = Thread(
                target=_send_mail_job,
                args=(app.config, msg, retries)
            )
            thread.daemon = True
            thread.start()

            print("✓ Email queued (async mode)")
            return True

        print("Sending email (sync mode)...")

        return _send_mail_job(app.config, msg, retries)

    except Exception as e:
        print(f"safe_send_mail error: {e}")
        return False


# =========================================
# AUDIT TRAIL HELPERS
# =========================================

def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    if request.headers.get('X-Real-Ip'):
        return request.headers.get('X-Real-Ip')
    return request.remote_addr or 'unknown'


def get_location_from_ip(ip_address):
    if not ip_address or ip_address in ('127.0.0.1', 'localhost', 'unknown', '::1'):
        return 'Local'
    return 'Unknown'


def get_device_info():
    ua = request.user_agent
    if not ua:
        return None

    return {
        'platform': ua.platform,
        'os': ua.os,
        'browser': ua.browser,
        'device_type': 'Mobile' if ua.platform in ('iphone', 'android') else 'Desktop',
        'raw_user_agent': str(ua.string)[:500]
    }


def compute_record_hash(record_data):
    data_str = json.dumps(record_data, sort_keys=True, default=str)
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest()


def get_last_audit_hash():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT record_hash FROM audit_log ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()

    conn.close()

    return row["record_hash"] if row else "0"


def log_audit_event(action, description, **kwargs):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        username = kwargs.get('username') or session.get('username')
        user_role = kwargs.get('user_role') or session.get('role')
        ip_address = get_client_ip()
        device_info = get_device_info()
        device_info_json = json.dumps(device_info) if device_info else None
        location = get_location_from_ip(ip_address)
        session_id = session.get('_id', 'unknown')

        old_values = kwargs.get('old_values')
        new_values = kwargs.get('new_values')

        record_data = {
            'timestamp': now,
            'action': action,
            'username': username,
            'ip': ip_address,
            'description': description
        }

        previous_hash = get_last_audit_hash()
        record_hash = compute_record_hash({**record_data, 'previous_hash': previous_hash})

        cursor.execute("""
            INSERT INTO audit_log (
                timestamp, action, action_category, description,
                username, user_role, ip_address, user_agent,
                session_id, table_affected, record_id,
                old_values, new_values, amount, pos_record_id,
                is_superadmin_action, login_success,
                username_entered, password_entered_hash, failure_reason,
                location, device_info,
                previous_record_hash, record_hash, tamper_alert
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now,
            action,
            kwargs.get('action_category'),
            description,
            username,
            user_role,
            ip_address,
            request.user_agent.string[:500] if request.user_agent else None,
            session_id,
            kwargs.get('table_affected'),
            kwargs.get('record_id'),
            json.dumps(old_values) if old_values else None,
            json.dumps(new_values) if new_values else None,
            kwargs.get('amount'),
            kwargs.get('pos_record_id'),
            1 if user_role == 'superadmin' else 0,
            kwargs.get('login_success'),
            kwargs.get('username_entered'),
            kwargs.get('password_entered_hash'),
            kwargs.get('failure_reason'),
            location,
            device_info_json,
            previous_hash,
            record_hash,
            0
        ))

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"Audit log error (non-critical): {e}")    
 
def log_login_attempt(username, password, success, failure_reason=None):
    password_hash = hashlib.sha256(password.encode()).hexdigest()[:32] if password else None

    log_audit_event(
        action='LOGIN_SUCCESS' if success else 'LOGIN_FAILED',
        description=f"Login {'successful' if success else 'failed'} for '{username}'",
        action_category='authentication',
        username_entered=username,
        password_entered_hash=password_hash,
        login_success=1 if success else 0,
        failure_reason=failure_reason,
        username=username if success else None,
        user_role=session.get('role') if success else None
    )


def log_data_change(action, table, record_id, description, old_values=None, new_values=None):
    log_audit_event(
        action=action,
        description=description,
        action_category='data_change',
        table_affected=table,
        record_id=record_id,
        old_values=old_values,
        new_values=new_values
    )


def log_pos_action(action, pos_record_id, description, amount=None):
    log_audit_event(
        action=action,
        description=description,
        action_category='pos',
        pos_record_id=pos_record_id,
        amount=amount
    )


def log_booklet_action(action, description, old_values=None, new_values=None):
    log_audit_event(
        action=action,
        description=description,
        action_category='booklet',
        old_values=old_values,
        new_values=new_values
    )


# =========================================
# VICE-SECRETARY NOTIFICATION HELPERS
# =========================================

def send_vice_secretary_notification(username, action, description):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT secretary_email, vice_secretary_email, church_branch_name 
            FROM users WHERE username = ?
        """, (username,))
        user = cursor.fetchone()

        if not user or not user.get('vice_secretary_email'):
            conn.close()
            return False

        secretary_email = user.get('secretary_email', '')
        vice_email = user.get('vice_secretary_email')
        branch_name = user.get('church_branch_name', 'Unknown Branch')

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cursor.execute("""
            INSERT INTO vice_secretary_notifications 
            (username, secretary_email, vice_secretary_email, action, description, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (username, secretary_email, vice_email, action, description, now))

        notification_id = cursor.lastrowid
        conn.commit()
        conn.close()

        if SMTP_USERNAME and SMTP_PASSWORD:
            try:
                subject = f"KGANYA - Activity Notification: {action}"
                body_html = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                    <h2 style="color: #1e3a5f;">KGANYA Digital Proof Of Service</h2>
                    <p>Dear Vice-Secretary,</p>
                    <p>This is an automated notification regarding activity on the KGANYA system.</p>

                    <div style="background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                        <p><strong>Branch:</strong> {html_module.escape(branch_name)}</p>
                        <p><strong>Secretary:</strong> {html_module.escape(username)}</p>
                        <p><strong>Action:</strong> {html_module.escape(action)}</p>
                        <p><strong>Details:</strong> {html_module.escape(description)}</p>
                        <p><strong>Time:</strong> {now}</p>
                    </div>

                    <p>If you did not expect this activity, please contact your administrator immediately.</p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">
                        Kganya Financial Service Providers | Lighting The Way Through Service
                    </p>
                </body>
                </html>
                """

                msg = Message(
                    subject=subject,
                    sender=SMTP_USERNAME,
                    recipients=[vice_email],
                    html=body_html
                )

                if not safe_send_mail(msg):
                    return False

                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE vice_secretary_notifications 
                    SET sent = 1, sent_at = ?
                    WHERE id = ?
                """, (now, notification_id))

                conn.commit()
                conn.close()

            except Exception as e:
                print(f"Failed to send vice-secretary notification: {e}")

                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE vice_secretary_notifications 
                    SET error_message = ?
                    WHERE id = ?
                """, (str(e)[:500], notification_id))

                conn.commit()
                conn.close()

                return False

        else:
            print("SMTP not configured, vice-secretary notification queued but not sent")
            return False

    except Exception as e:
        print(f"Vice-secretary notification error (non-critical): {e}")
        return False


def notify_vice_secretary_on_login(username):
    return send_vice_secretary_notification(
        username,
        "SECRETARY_LOGIN",
        f"Secretary '{username}' has logged into the KGANYA system."
    )


def notify_vice_secretary_on_pos(username, pos_number, pos_id):
    return send_vice_secretary_notification(
        username,
        "POS_SUBMITTED",
        f"Secretary '{username}' submitted POS #{pos_number} (ID: {pos_id})."
    )    

#---------------------------------------------------------------------------------------------------------------
def migrate_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row["name"] for row in cursor.fetchall()]

    cursor.execute("PRAGMA table_info(pending_users)")
    pending_columns = [row["name"] for row in cursor.fetchall()]

    cursor.execute("PRAGMA table_info(admins)")
    admin_columns = [row["name"] for row in cursor.fetchall()]

    cursor.execute("PRAGMA table_info(pos_records)")
    columns = [row["name"] for row in cursor.fetchall()]
    
    # Add created_at to users if not exists
    cursor.execute("PRAGMA table_info(users)")
    user_columns = [row["name"] for row in cursor.fetchall()]
    if "created_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at TIMESTAMP")
        cursor.execute("UPDATE users SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")

    if "secretary_email" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN secretary_email TEXT")
    if "vice_secretary_email" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN vice_secretary_email TEXT")
    if "church_code" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN church_code TEXT")
    if "church_file_number" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN church_file_number TEXT")
    if "church_branch_name" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN church_branch_name TEXT")

    if "secretary_email" not in pending_columns:
        cursor.execute("ALTER TABLE pending_users ADD COLUMN secretary_email TEXT")
    if "vice_secretary_email" not in pending_columns:
        cursor.execute("ALTER TABLE pending_users ADD COLUMN vice_secretary_email TEXT")
    if "church_code" not in pending_columns:
        cursor.execute("ALTER TABLE pending_users ADD COLUMN church_code TEXT")
    if "church_file_number" not in pending_columns:
        cursor.execute("ALTER TABLE pending_users ADD COLUMN church_file_number TEXT")
    if "church_branch_name" not in pending_columns:
        cursor.execute("ALTER TABLE pending_users ADD COLUMN church_branch_name TEXT")

    if "email" not in admin_columns:
        cursor.execute("ALTER TABLE admins ADD COLUMN email TEXT")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_otp_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            created_at TEXT NOT NULL,
            verified INTEGER DEFAULT 0,
            role TEXT
        )
    """)

    new_columns = [
        ("year", "INTEGER"),
        ("month", "INTEGER"),
        ("month_name", "TEXT"),
        ("html_file_path", "TEXT"),
        ("church_name", "TEXT"),
        ("church_code", "TEXT"),
        ("church_file", "TEXT"),
        ("depositor_name", "TEXT"),
        ("depositor_id", "TEXT"),
        ("depositor_phone", "TEXT"),
        ("witness1", "TEXT"),
        ("witness2", "TEXT"),
        ("witness3", "TEXT"),
        ("expected_total", "REAL DEFAULT 0.00"),
        ("total_outstanding", "REAL DEFAULT 0.00"),
        ("count200", "INTEGER DEFAULT 0"),
        ("count100", "INTEGER DEFAULT 0"),
        ("count50", "INTEGER DEFAULT 0"),
        ("count20", "INTEGER DEFAULT 0"),
        ("count10", "INTEGER DEFAULT 0"),
        ("count_coins", "INTEGER DEFAULT 0"),
        ("bank_count200", "INTEGER DEFAULT 0"),
        ("bank_count100", "INTEGER DEFAULT 0"),
        ("bank_count50", "INTEGER DEFAULT 0"),
        ("bank_count20", "INTEGER DEFAULT 0"),
        ("bank_count10", "INTEGER DEFAULT 0"),
        ("bank_count_coins", "INTEGER DEFAULT 0"),
        ("minister_count200", "INTEGER DEFAULT 0"),
        ("minister_count100", "INTEGER DEFAULT 0"),
        ("minister_count50", "INTEGER DEFAULT 0"),
        ("minister_count20", "INTEGER DEFAULT 0"),
        ("minister_count10", "INTEGER DEFAULT 0"),
        ("minister_count_coins", "INTEGER DEFAULT 0"),
        ("minister_total", "REAL DEFAULT 0.00"),
        ("banking_amount_words", "TEXT"),
        ("banking_remarks", "TEXT"),
        ("minister_remarks", "TEXT"),
        ("final_conclusion", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in columns:
            cursor.execute(f"ALTER TABLE pos_records ADD COLUMN {col_name} {col_type}")

    if "year" in columns:
        cursor.execute("SELECT id, created_at FROM pos_records WHERE year IS NULL")
        records = cursor.fetchall()
        for rec in records:
            try:
                dt = datetime.strptime(rec["created_at"], "%Y-%m-%d %H:%M:%S")
                cursor.execute("""
                    UPDATE pos_records SET year=?, month=?, month_name=? WHERE id=?
                """, (dt.year, dt.month, dt.strftime("%B"), rec["id"]))
            except:
                pass

    conn.commit()
    conn.close()
    
    
def seed_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Seed legacy products table
    cursor.execute("SELECT COUNT(*) FROM products")
    row = cursor.fetchone()

    if row and list(row)[0] == 0:
        cursor.executemany("""
            INSERT INTO products (name, price, deduction)
            VALUES (?, ?, ?)
        """, [
            ("KGANYA", 139.00, 1.00),
            ("KGANYA KOLOI", 320.00, 0.00),
            ("SEDI LA KGANYA", 105.00, 0.00),
            ("AMENDMENT", 0.00, 0.00),
            ("NEW BOOKS", 90.00, 0.00),
            ("LEETO", 5.00, 0.00)
        ])

    # Seed products_master table (for booklet system)
    cursor.execute("SELECT COUNT(*) FROM products_master")
    row = cursor.fetchone()

    if row and list(row)[0] == 0:
        cursor.executemany("""
            INSERT INTO products_master (name, price, deduction, is_active)
            VALUES (?, ?, ?, 1)
        """, [
            ("KGANYA", 139.00, 1.00),
            ("KGANYA KOLOI", 320.00, 0.00),
            ("SEDI LA KGANYA", 105.00, 0.00),
            ("AMENDMENT", 0.00, 0.00),
            ("NEW BOOKS", 90.00, 0.00),
            ("LEETO", 5.00, 0.00)
        ])

    superadmin_email = os.getenv("SUPERADMIN_EMAIL", "superadmin@kganya.local")

    cursor.execute("SELECT COUNT(*) FROM admins WHERE username = ?", ("superadmin",))
    row = cursor.fetchone()

    if row and list(row)[0] == 0:
        cursor.execute("""
            INSERT INTO admins (username, password, role, email, force_password_change)
            VALUES (?, ?, ?, ?, ?)
        """, ("superadmin", generate_password_hash("Kganya@Actuary2030!"), "superadmin", superadmin_email, 1))
    else:
        cursor.execute("UPDATE admins SET email = ? WHERE username = ?", (superadmin_email, "superadmin"))

    conn.commit()
    conn.close()
    
def migrate_password_reset_table():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            token TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()



init_db()

# Call this after init_db()
#migrate_password_reset_table()


migrate_db()
seed_data()
os.makedirs(POS_FOLDER, exist_ok=True)

# =========================================
# HELPER FUNCTIONS: DATABASE QUERIES
# =========================================



def store_reset_token(username, email):
    """Store a password reset token with 24-hour expiry."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Only invalidate tokens for this specific email, not all tokens for the user
    cursor.execute("UPDATE password_reset_tokens SET used = 1 WHERE username = ? AND email = ?", (username, email))
    
    token = generate_reset_token()
    now = datetime.now()
    expires = now + timedelta(hours=24)
    
    cursor.execute("""
        INSERT INTO password_reset_tokens (username, token, email, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, (username, token, email, now.strftime("%Y-%m-%d %H:%M:%S"), expires.strftime("%Y-%m-%d %H:%M:%S")))
    
    conn.commit()
    conn.close()
    return token


def validate_reset_token(token):
    """Check if a reset token is valid and not expired."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now_str = datetime.now().isoformat()
    
    cursor.execute("""
        SELECT * FROM password_reset_tokens 
        WHERE token = ? AND used = 0 AND expires_at > ?
    """, (token, now_str))
    
    result = cursor.fetchone()
    conn.close()
    return result



def mark_token_used(token):
    """Mark a token as used after password reset."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,))
    conn.commit()
    conn.close()





def get_admin(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admins WHERE username = ?", (username,))
    admin = cursor.fetchone()
    conn.close()
    return admin

def get_user(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user

def get_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Try products_master first (booklet system), fallback to legacy products
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='products_master'")
    has_master = cursor.fetchone()
    
    if has_master:
        cursor.execute("SELECT id, name, price, deduction FROM products_master WHERE is_active = 1 ORDER BY name")
    else:
        cursor.execute("SELECT * FROM products ORDER BY name")
    
    products = cursor.fetchall()
    conn.close()
    return products

def get_price_by_name(name):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # First try products_master (booklet system)
    cursor.execute("SELECT price, deduction FROM products_master WHERE name = ? AND is_active = 1", (name,))
    product = cursor.fetchone()
    
    # Fallback to legacy products table
    if not product:
        cursor.execute("SELECT price, deduction FROM products WHERE name = ?", (name,))
        product = cursor.fetchone()
    
    conn.close()
    if product:
        return {"price": float(product["price"]), "deduction": float(product["deduction"])}
    return {"price": 0.00, "deduction": 0.00}

def create_user(username, password, secretary_phone, vice_secretary_phone, secretary_email, vice_secretary_email, church_code, church_file_number, church_branch_name):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed = generate_password_hash(password)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO users (username, password, secretary_phone, vice_secretary_phone, secretary_email, vice_secretary_email, church_code, church_file_number, church_branch_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, hashed, secretary_phone, vice_secretary_phone, secretary_email, vice_secretary_email, church_code, church_file_number, church_branch_name, now))
    conn.commit()
    conn.close()

def create_admin(username, password, role="admin", email=None):
    """Create admin. Password is hashed here — always pass plain text."""
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed = generate_password_hash(password)
    cursor.execute("INSERT INTO admins (username, password, role, email) VALUES (?, ?, ?, ?)", 
                   (username, hashed, role, email))
    conn.commit()
    conn.close()
    
    

# ==========================================
# HELPER FUNCTIONS: VALIDATION
# ==========================================

def sanitize_string(value, max_length=255):
    if value is None:
        return ""
    value = str(value).strip()
    value = re.sub(r"[<>&]", "", value)
    return value[:max_length]

def validate_username(username):
    if not username:
        return False, "Username is required."
    if len(username) < 3:
        return False, "Username must be at least 3 characters."
    if len(username) > 50:
        return False, "Username must be at most 50 characters."
    if not re.match(r"^[a-zA-Z0-9_ ]+$", username):  # Added space after _
        return False, "Username can only contain letters, numbers, underscores, and spaces."
    return True, "Valid"

def validate_password(password):
    if not password:
        return False, "Password is required."
    if len(password) < 6:
        return False, "Password must be at least 6 characters."
    return True, "Valid"

def validate_phone(phone):
    if not phone:
        return False, "Phone number is required."
    cleaned = re.sub(r"[\s\-]", "", phone)
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]
    if cleaned.startswith("0"):
        cleaned = "27" + cleaned[1:]
    if not re.match(r"^27[6-8][0-9]{8}$", cleaned):
        return False, "Invalid phone number format. Use format like 0821234567."
    return True, cleaned

def validate_email(email):
    if not email:
        return False, "Email is required."
    email = email.strip().lower()
    pattern = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    if not re.match(pattern, email):
        return False, "Invalid email format."
    return True, email

def validate_church_code(church_code):
    if not church_code:
        return False, "Church code is required."
    cleaned = church_code.strip()
    if not cleaned.isdigit():
        return False, "Church code must be a number."
    return True, cleaned

def validate_church_file_number(church_file_number):
    if not church_file_number:
        return False, "Church file number is required."
    cleaned = church_file_number.strip().upper()
    if len(cleaned) < 2:
        return False, "Church file number must be at least 2 characters."
    if not re.match(r"^[A-Z0-9 ]+$", cleaned):  # Added space before $
        return False, "Church file number can only contain letters, numbers, and spaces."
    return True, cleaned

def validate_church_branch_name(church_branch_name):
    if not church_branch_name:
        return False, "Church branch name is required."
    cleaned = church_branch_name.strip()
    if len(cleaned) < 2:
        return False, "Church branch name must be at least 2 characters."
    return True, cleaned

def email_exists(email):
    """Check if an email already exists in users or pending_users table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE secretary_email = ? OR vice_secretary_email = ?", (email, email))
    if cursor.fetchone():
        conn.close()
        return True
    cursor.execute("SELECT 1 FROM pending_users WHERE secretary_email = ? OR vice_secretary_email = ?", (email, email))
    if cursor.fetchone():
        conn.close()
        return True
    conn.close()
    return False
#---------------------------------------------------------------------------------------------------------------------------

def church_file_number_exists(church_file_number):
    """Check if a church file number already exists in users or pending_users table."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM users WHERE church_file_number = ?", (church_file_number,))
    if cursor.fetchone():
        conn.close()
        return True
    cursor.execute("SELECT 1 FROM pending_users WHERE church_file_number = ?", (church_file_number,))
    if cursor.fetchone():
        conn.close()
        return True
    conn.close()
    return False



# =========================================
# HELPER FUNCTIONS: DATA RETENTION
# =========================================

def cleanup_old_pos_records():
    """
    Automatically delete POS records older than 20 years.
    Keeps users, products, admins, and pending_users intact.
    Returns count of deleted records.
    """
    cutoff_year = datetime.now().year - 20
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find old POS record IDs first (needed for cascading deletes in related tables)
    cursor.execute("SELECT id FROM pos_records WHERE year < ?", (cutoff_year,))
    old_ids = [row["id"] for row in cursor.fetchall()]
    
    if not old_ids:
        conn.close()
        return 0
    
    deleted_count = len(old_ids)
    placeholders = ",".join("?" * len(old_ids))
    
    # Delete related records first (foreign key constraints)
    cursor.execute(f"DELETE FROM pos_items WHERE pos_record_id IN ({placeholders})", old_ids)
    cursor.execute(f"DELETE FROM pos_cash_rows WHERE pos_record_id IN ({placeholders})", old_ids)
    cursor.execute(f"DELETE FROM pos_cancelled_receipts WHERE pos_record_id IN ({placeholders})", old_ids)
    
    # Delete the POS records themselves
    cursor.execute(f"DELETE FROM pos_records WHERE id IN ({placeholders})", old_ids)
    
    conn.commit()
    conn.close()
    
    # Also clean up orphaned HTML/TXT files on disk
    for pos_id in old_ids:
        # We don't have file paths in memory, so we'll scan the folder for old files
        pass  # File cleanup handled separately below
    
    return deleted_count

def cleanup_old_pos_files_on_disk():
    """
    Remove POS HTML/TXT files older than 20 years from disk.
    """
    cutoff_time = datetime.now() - timedelta(days=20 * 365)
    deleted_files = 0
    
    if not os.path.exists(POS_FOLDER):
        return 0
    
    for root, dirs, files in os.walk(POS_FOLDER):
        for filename in files:
            if filename.endswith(('.html', '.txt')):
                filepath = os.path.join(root, filename)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if mtime < cutoff_time:
                        os.remove(filepath)
                        deleted_files += 1
                except (OSError, PermissionError):
                    pass
    
    return deleted_files

# =========================================
# HELPER FUNCTIONS: OTP
# =========================================





import secrets
import string
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

# ============== TOKEN GENERATION ==============

def generate_reset_token():
    """Generate a secure random token."""
    return secrets.token_urlsafe(32)

def create_password_reset_token(username, email=None, expiry_hours=24):
    """
    FIXED VERSION:
    Stores admin reset tokens in the SAME table used by the reset system.
    This removes the admin_password_tokens inconsistency bug.
    """

    conn = get_db_connection()
    cursor = conn.cursor()

    # Generate token
    token = generate_reset_token()

    now = datetime.now()
    expires = now + timedelta(hours=expiry_hours)

    # 1. Invalidate old admin tokens ONLY (safe cleanup)
    cursor.execute("""
        UPDATE password_reset_tokens
        SET used = 1
        WHERE username = ? AND user_type = 'admin' AND used = 0
    """, (username,))

    # 2. Insert into CORRECT table (the one your system already validates)
    cursor.execute("""
        INSERT INTO password_reset_tokens (
            username,
            token,
            email,
            created_at,
            expires_at,
            used,
            user_type
        )
        VALUES (?, ?, ?, ?, ?, 0, 'admin')
    """, (
        username,
        token,
        email,
        now.strftime("%Y-%m-%d %H:%M:%S"),
        expires.strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()

    return token
# ============== EMAIL SENDING ==============

def send_password_reset_email(email, username, token, request=None):
    """Send password reset link to user. Works in both dev and production."""
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("❌ SMTP not configured. Cannot send reset email.")
        return False
    
    # Build URL dynamically based on request or config
    if request:
        # Production: use the actual host from the request
        base_url = request.url_root.rstrip('/')
    else:
        # Fallback for background tasks or testing
        base_url = app.config.get('BASE_URL', 'http://127.0.0.1:5000')
    
    reset_url = f"{base_url}/reset-password/{token}"
    
    try:
        subject = "KGANYA - Set Your Password"
        
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #1e3a5f;">KGANYA Digital Proof Of Service</h2>
            <p>Hello {html_module.escape(username)},</p>
            <p>An admin has created an account for you. Please set your password by clicking the link below:</p>
            <p style="text-align: center; margin: 30px 0;">
                <a href="{reset_url}" style="background: #1e3a5f; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; font-weight: bold;">Set Your Password</a>
            </p>
            <p><strong>This link will expire in 24 hours.</strong></p>
            <p>If you did not request this account, please ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Kganya Financial Service Providers | Lighting The Way Through Service</p>
        </body>
        </html>
        """
        
        msg = Message(
            subject=subject,
            sender=SMTP_USERNAME,
            recipients=[email],
            html=body_html
        )
        
        #mail.send(msg)
        #print(f"✅ Password reset email sent to {email}")
        #return True
        if not safe_send_mail(msg):
            return False
        
    except Exception as e:
        print(f"❌ Failed to send reset email: {e}")
        return False

# ============== TOKEN VALIDATION ==============




    
# =========================================---------------------------------------------------------------------------
# FORGOT PASSWORD HELPERS
# =========================================

def store_user_reset_token(username, email, user_type='user'):
    """Store a password reset token with 24-hour expiry. Used by forgot-password flow."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Invalidate any existing unused tokens for this username+email
    cursor.execute(
        "UPDATE password_reset_tokens SET used = 1 WHERE username = ? AND email = ? AND used = 0",
        (username, email)
    )
    
    token = generate_reset_token()
    now = datetime.now()
    expires = now + timedelta(hours=24)
    
    cursor.execute("""
        INSERT INTO password_reset_tokens (username, token, email, created_at, expires_at, user_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (username, token, email, now.strftime("%Y-%m-%d %H:%M:%S"), 
          expires.strftime("%Y-%m-%d %H:%M:%S"), user_type))
    
    conn.commit()
    conn.close()
    return token


def send_forgot_password_email(email, username, token, is_admin=False):
    """
    Send password reset link to user or admin who forgot their password.
    Returns True if email was sent successfully, otherwise False.
    """

    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("SMTP not configured. Cannot send forgot-password email.")
        return False

    base_url = app.config.get("BASE_URL", "http://127.0.0.1:5000")

    if is_admin:
        reset_url = f"{base_url}/admin-reset-password/{token}"
        account_type = "Admin"
    else:
        reset_url = f"{base_url}/reset-password/{token}"
        account_type = "User"

    try:
        subject = "KGANYA - Password Reset Request"

        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #1e3a5f;">KGANYA Digital Proof Of Service</h2>

            <p>Hello {html_module.escape(username)},</p>

            <p>
                We received a request to reset your password for your
                <strong>{account_type}</strong> account.
            </p>

            <p style="text-align:center; margin:30px 0;">
                <a href="{reset_url}"
                   style="background:#1e3a5f;
                          color:white;
                          padding:12px 30px;
                          text-decoration:none;
                          border-radius:5px;
                          font-weight:bold;">
                    Reset My Password
                </a>
            </p>

            <p><strong>This link will expire in 24 hours.</strong></p>

            <p>
                If you did not request this password reset,
                please ignore this email.
                Your account remains secure.
            </p>

            <hr>

            <p style="color:#666; font-size:12px;">
                Kganya Financial Service Providers |
                Lighting The Way Through Service
            </p>
        </body>
        </html>
        """

        msg = Message(
            subject=subject,
            sender=SMTP_USERNAME,
            recipients=[email],
            html=body_html
        )

        print(f"Sending forgot-password email to {email}...")

        # Use synchronous mode for password resets
        success = safe_send_mail(
            msg,
            retries=3,
            async_mode=False
        )

        if success:
            print(f"✓ Forgot-password email sent to {email}")
            return True

        print(f"✗ Failed to send forgot-password email to {email}")
        return False

    except Exception as e:
        print(f"Failed to send forgot-password email: {e}")
        return False


def get_user_by_username(username):
    """Get user by username (church name)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user


def get_admin_by_email(email):
    """Get admin by email address."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admins WHERE email = ?", (email,))
    admin = cursor.fetchone()
    conn.close()
    return admin

# =========================================---------------------------------------------------------------------------

from flask_mail import Message

def send_email(to, subject, body):
    """Send email using Flask-Mail."""
    try:
        msg = Message(
            subject=subject,
            recipients=[to],
            body=body,
            sender=app.config.get('MAIL_DEFAULT_SENDER') or app.config.get('MAIL_USERNAME')
        )
        #mail.send(msg)
        #return True
        if not safe_send_mail(msg):
            return False
        
    except Exception as e:
        print(f"Email error: {e}")
        return False   
    

def notify_admins_skip_submitted(username, skip_ids):
    """Send email to admins and superadmins from the admins table."""
    try:
        conn = get_db_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get submitter's church info from users table
        cursor.execute("""
            SELECT church_branch_name, secretary_email, vice_secretary_email
            FROM users 
            WHERE username = ?
        """, (username,))
        user_info = cursor.fetchone()
        
        church_name = user_info["church_branch_name"] or "Unknown Church" if user_info else "Unknown Church"
        user_email = (user_info["secretary_email"] or user_info["vice_secretary_email"] or "") if user_info else ""
        
        # Get ALL admin and superadmin emails from ADMINS table
        cursor.execute("""
            SELECT username, role, email
            FROM admins 
            WHERE role IN ('admin', 'superadmin')
            AND email IS NOT NULL
            AND email != ''
        """)
        admins = cursor.fetchall()
        conn.close()
        
        if not admins:
            print(f"[SKIP NOTIFY] No admins/superadmins with emails found.")
            return
        
        subject = f"KGANYA: Skip Reason Submitted - {username} ({church_name})"
        
        body = f"""KGANYA Digital Proof Of Service - Skip Notification

User: {username}
Church: {church_name}
User Contact: {user_email or 'Not set'}
Number of skips: {len(skip_ids)}

Action Required: Review and approve/reject in admin panel.
Review at: http://127.0.0.1:5000/admin/skipped-submissions

---
Do not reply to this email.
"""
        
        for admin in admins:
            try:
                send_email(admin["email"], subject, body)
                print(f"[SKIP NOTIFY] Sent to {admin['role']} {admin['username']} at {admin['email']}")
            except Exception as e:
                print(f"[SKIP NOTIFY] Failed to {admin['email']}: {e}")
                
    except Exception as e:
        print(f"[SKIP NOTIFY] Error: {e}")
#-----------------------------------------------8----------------------------------------------------------------------------
# ============== ROUTE ==============

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Allow user to set permanent password using reset token."""

    token_record = validate_reset_token(token)

    if not token_record:
        return render_template(
            "reset_password.html",
            error="Invalid or expired reset link."
        )

    username = token_record["username"]

    if request.method == "POST":

        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()

        if not new_password:
            return render_template(
                "reset_password.html",
                token=token,
                username=username,
                error="Password is required."
            )

        if len(new_password) < 6:
            return render_template(
                "reset_password.html",
                token=token,
                username=username,
                error="Password must be at least 6 characters."
            )

        if new_password != confirm_password:
            return render_template(
                "reset_password.html",
                token=token,
                username=username,
                error="Passwords do not match."
            )

        try:
            # Hash password
            hashed_pw = generate_password_hash(new_password)

            conn = get_db_connection()
            cursor = conn.cursor()

            # Update USER password
            cursor.execute("""
                UPDATE users
                SET password = ?
                WHERE username = ?
            """, (hashed_pw, username))

            conn.commit()
            conn.close()

            # Mark token as used
            mark_token_used(token)

            # Audit log
            log_data_change(
                "USER_PASSWORD_RESET",
                "users",
                None,
                f"User '{username}' set permanent password via reset token",
                new_values={
                    "username": username,
                    "action": "password_reset"
                }
            )

            return render_template(
                "reset_password.html",
                success="Password set successfully! You can now log in."
            )

        except Exception as e:
            return render_template(
                "reset_password.html",
                token=token,
                username=username,
                error=f"Error updating password: {str(e)}"
            )

    return render_template(
        "reset_password.html",
        token=token,
        username=username
    )





def generate_otp():
    return str(random.randint(100000, 999999))

def store_otp(identifier, otp_code, purpose, channel="email"):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    
    # Delete old unverified OTPs for this identifier and purpose
    cursor.execute("""
        DELETE FROM otp_verifications 
        WHERE (phone_number = ? OR email = ?) 
        AND purpose = ? AND verified = 0
    """, (identifier, identifier, purpose))
    
    # Insert new OTP - include phone_number to satisfy NOT NULL constraint
    if channel == "email":
        cursor.execute("""
            INSERT INTO otp_verifications (phone_number, email, otp_code, purpose, created_at, verified, attempts)
            VALUES (?, ?, ?, ?, ?, 0, 0)
        """, ("", identifier, otp_code, purpose, now.strftime("%Y-%m-%d %H:%M:%S")))
    else:
        cursor.execute("""
            INSERT INTO otp_verifications (phone_number, email, otp_code, purpose, created_at, verified, attempts)
            VALUES (?, ?, ?, ?, ?, 0, 0)
        """, (identifier, "", otp_code, purpose, now.strftime("%Y-%m-%d %H:%M:%S")))
    
    conn.commit()
    conn.close()
    
    
def verify_otp_code(identifier, otp_code, purpose):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        SELECT * FROM otp_verifications 
        WHERE (phone_number = ? OR email = ?) 
        AND otp_code = ? AND purpose = ? 
        AND verified = 0 
        AND created_at > datetime(?, '-10 minutes')
        ORDER BY created_at DESC LIMIT 1
    """, (identifier, identifier, otp_code, purpose, now_str))
    otp_record = cursor.fetchone()
    if not otp_record:
        conn.close()
        return False, "Invalid or expired OTP code."
    cursor.execute("UPDATE otp_verifications SET verified = 1 WHERE id = ?", (otp_record["id"],))
    conn.commit()
    conn.close()
    return True, "OTP verified successfully."


def send_otp_email(recipient, otp_code, purpose):
    
    
    
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("❌ ERROR: SMTP credentials not configured in .env")
        return False
    
    try:
        subject = "KGANYA - Your Verification Code"
        if purpose == "login":
            subject = "KGANYA - Login Verification Code"
        elif purpose == "user_creation":
            subject = "KGANYA - User Creation Verification Code"
        
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #1e3a5f;">KGANYA Digital Proof Of Service</h2>
            <p>Your verification code is:</p>
            <h1 style="color: #1e3a5f; font-size: 36px; letter-spacing: 8px;">{otp_code}</h1>
            <p>This code will expire in {OTP_EXPIRY_MINUTES} minutes.</p>
            <p>If you did not request this code, please ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Kganya Financial Service Providers | Lighting The Way Through Service</p>
        </body>
        </html>
        """
        
        from flask_mail import Message
        msg = Message(
            subject=subject,
            sender=SMTP_USERNAME,
            recipients=[recipient],
            html=body_html
        )
        
        
        #mail.send(msg)
        if not safe_send_mail(msg):
            return False
        #print(f"✅ SUCCESS: OTP email sent to {recipient}")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Email send failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False   
    
# =========================================
# LOGIN OTP HELPERS
# =========================================

def store_login_otp(username, otp_code, role):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM login_otp_sessions WHERE username = ? AND verified = 0", (username,))
    cursor.execute("""
        INSERT INTO login_otp_sessions (username, otp_code, created_at, role)
        VALUES (?, ?, ?, ?)
    """, (username, otp_code, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), role))
    conn.commit()
    conn.close()
    return True

def verify_login_otp(username, otp_code):
    conn = get_db_connection()
    cursor = conn.cursor()
    expiry_time = (datetime.now() - timedelta(minutes=OTP_EXPIRY_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        SELECT * FROM login_otp_sessions 
        WHERE username = ? AND otp_code = ? 
        AND created_at > ? AND verified = 0
        ORDER BY created_at DESC LIMIT 1
    """, (username, otp_code, expiry_time))
    otp_record = cursor.fetchone()
    if not otp_record:
        conn.close()
        return False, None, "Invalid or expired login OTP."
    cursor.execute("UPDATE login_otp_sessions SET verified = 1 WHERE id = ?", (otp_record["id"],))
    conn.commit()
    role = otp_record["role"]
    conn.close()
    return True, role, "Login OTP verified."

def get_user_email_for_login(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT secretary_email, vice_secretary_email FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    if user:
        conn.close()
        return user["secretary_email"] or user["vice_secretary_email"]
    cursor.execute("SELECT secretary_email, vice_secretary_email FROM pending_users WHERE username = ?", (username,))
    pending = cursor.fetchone()
    if pending:
        conn.close()
        return pending["secretary_email"] or pending["vice_secretary_email"]
    cursor.execute("SELECT email FROM admins WHERE username = ?", (username,))
    admin = cursor.fetchone()
    if admin:
        conn.close()
        return admin["email"]
    conn.close()
    return None

def mask_email(email):
    if not email or '@' not in email:
        return email
    parts = email.split('@')
    name = parts[0]
    domain = parts[1]
    if len(name) <= 2:
        masked_name = name[0] + '***'
    else:
        masked_name = name[0] + '***' + name[-1]
    return f"{masked_name}@{domain}"

# =========================================
# HELPER FUNCTIONS: POS DATA ORGANIZATION
# =========================================

def get_user_pos_by_year_month(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM pos_records 
        WHERE created_by = ? 
        ORDER BY year DESC, month DESC, created_at DESC
    """, (username,))
    records = cursor.fetchall()
    conn.close()
    organized = {}
    for record in records:
        year = record["year"]
        month = record["month"]
        month_name = record["month_name"]
        if year not in organized:
            organized[year] = {}
        if month not in organized[year]:
            organized[year][month] = {"name": month_name, "records": []}
        organized[year][month]["records"].append(dict(record))
    return organized

def get_all_pos_by_user():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all pos records
    cursor.execute("""
        SELECT * FROM pos_records 
        ORDER BY created_by, year DESC, month DESC, created_at DESC
    """)
    records = cursor.fetchall()
    
    # Get all pos_items with KGANYA sticker counts per record
    cursor.execute("""
        SELECT pos_record_id, product_name, sticker_count 
        FROM pos_items 
        WHERE product_name = 'KGANYA'
    """)
    kganya_items = cursor.fetchall()
    
    # Build a map of record_id -> kganya_stickers
    kganya_by_record = {}
    for item in kganya_items:
        rid = item["pos_record_id"]
        if rid not in kganya_by_record:
            kganya_by_record[rid] = 0
        kganya_by_record[rid] += item["sticker_count"] or 0
    
    conn.close()
    
    organized = {}
    for record in records:
        username = record["created_by"]
        year = record["year"]
        month = record["month"]
        month_name = record["month_name"]
        
        rec_dict = dict(record)
        # Pre-calculate KGANYA stickers and attach
        rec_dict["kganya_stickers"] = kganya_by_record.get(record["id"], 0)
        
        if username not in organized:
            organized[username] = {}
        if year not in organized[username]:
            organized[username][year] = {}
        if month not in organized[username][year]:
            organized[username][year][month] = {"name": month_name, "records": []}
        organized[username][year][month]["records"].append(rec_dict)
    
    return organized



# =========================================
# HELPER FUNCTIONS: HTML GENERATION
# =========================================

def number_to_words(n):
    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
    
    def convert_less_than_thousand(num):
        if num == 0:
            return ""
        if num < 20:
            return ones[num]
        if num < 100:
            return tens[num // 10] + ("" if num % 10 == 0 else " " + ones[num % 10])
        remainder = num % 100
        if remainder == 0:
            return ones[num // 100] + " Hundred"
        else:
            return ones[num // 100] + " Hundred And " + convert_less_than_thousand(remainder)
    
    if n == 0:
        return "Zero Rands Only"
    
    parts = []
    
    if n >= 1000000:
        millions = n // 1000000
        parts.append(convert_less_than_thousand(millions) + " Million")
        n %= 1000000
    
    if n >= 1000:
        thousands = n // 1000
        parts.append(convert_less_than_thousand(thousands) + " Thousand")
        n %= 1000
    
    if n > 0:
        parts.append(convert_less_than_thousand(n))
    
    result = " ".join(parts) + " Rands Only"
    return result


def generate_pos_html(record, pos_items, cash_rows=None, church_info=None, depositor=None, witnesses=None):
    if cash_rows is None:
        cash_rows = []
    if church_info is None:
        church_info = {}
    if depositor is None:
        depositor = {}
    if witnesses is None:
        witnesses = {}
    items_html = ""
    total_stickers = 0
    total_banking = 0.0
    total_parish = 0.0
    for item in pos_items:
        total_stickers += item.get("sticker_count", 0)
        total_banking += item.get("banking_amount", 0.0)
        total_parish += item.get("parish_amount", 0.0)
        items_html += f"""
        <tr>
            <td>{html_module.escape(str(item.get("product_name", "")))}</td>
            <td>{html_module.escape(str(item.get("product_type", "")))}</td>
            <td>{item.get("sticker_from", 0)}</td>
            <td>{item.get("sticker_to", 0)}</td>
            <td>{item.get("sticker_count", 0)}</td>
            <td>R {item.get("banking_amount", 0.0):.2f}</td>
            <td>R {item.get("parish_amount", 0.0):.2f}</td>
        </tr>
        """
    cash_html = ""
    count200 = count100 = count50 = count20 = count10 = count_coins = 0
    for row in cash_rows:
        if isinstance(row, dict):
            r200 = int(row.get("r200", 0))
            r100 = int(row.get("r100", 0))
            r50 = int(row.get("r50", 0))
            r20 = int(row.get("r20", 0))
            r10 = int(row.get("r10", 0))
            coins = int(row.get("coins", 0))
        else:
            r200 = r100 = r50 = r20 = r10 = coins = 0
        count200 += r200
        count100 += r100
        count50 += r50
        count20 += r20
        count10 += r10
        count_coins += coins
        cash_html += f"""
        <tr>
            <td>{r200}</td>
            <td>{r100}</td>
            <td>{r50}</td>
            <td>{r20}</td>
            <td>{r10}</td>
            <td>{coins}</td>
        </tr>
        """
    total200 = count200 * 200
    total100 = count100 * 100
    total50 = count50 * 50
    total20 = count20 * 20
    total10 = count10 * 10
    total_coins = count_coins
    grand_total = total200 + total100 + total50 + total20 + total10 + total_coins
    expected = total_banking + total_parish
    diff = expected - grand_total
    if abs(diff) < 0.01:
        final_status = "BALANCED"
        final_conclusion = "PULA!! &nbsp;&nbsp;&nbsp;&nbsp; PULA!! &nbsp;&nbsp;&nbsp;&nbsp; PULA!!"
        conclusion_color = "lightgoldenrodyellow"
    elif diff > 0:
        final_status = "DISCREPANCY"
        final_conclusion = f"Total Loss = R {diff:.2f}"
        conclusion_color = "red"
    else:
        final_status = "DISCREPANCY"
        final_conclusion = f"Total Excess = R {abs(diff):.2f}"
        conclusion_color = "red"
    banking_words = number_to_words(int(total_banking))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>POS #{html_module.escape(str(record.get("pos_number", "")))} — KGANYA</title>
    <style>
        body {{ font-family: "Century Gothic", sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: auto; background: white; padding: 25px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1, h2, h3 {{ text-align: center; color: #1e3a5f; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        table, th, td {{ border: 1px solid #ddd; }}
        th {{ background: #1e3a5f; color: white; padding: 10px; }}
        td {{ padding: 8px; text-align: center; }}
        .section-title {{ background: #1e3a5f; color: white; padding: 10px; margin-top: 25px; border-radius: 5px; font-weight: bold; }}
        .status-balanced {{ color: green; font-weight: bold; }}
        .status-discrepancy {{ color: red; font-weight: bold; }}
        .final-remarks {{ font-size: 28px; font-weight: bold; text-align: center; padding: 20px; }}
        .footer {{ text-align: center; margin-top: 30px; padding: 20px; color: #666; border-top: 1px solid #ddd; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>KGANYA</h1>
        <h2>LIGHTING THE WAY THROUGH SERVICE</h2>
        <h3>Digital Proof Of Service</h3>
        <div class="section-title">Church Information</div>
        <table>
            <tr><th>Church Name</th><th>Church Code</th><th>Church File Number</th></tr>
            <tr>
                <td>{html_module.escape(str(church_info.get("name", record.get("created_by", "").replace("_", " "))))}</td>
                <td>{html_module.escape(str(church_info.get("code", record.get("church_code", "—"))))}</td>
                <td>{html_module.escape(str(church_info.get("file", record.get("church_file", "—"))))}</td>
            </tr>
        </table>
        <table>
            <tr><th>Date</th><th>POS Number</th><th>Bank Sheet</th></tr>
            <tr>
                <td>{record.get("created_at", "")}</td>
                <td>{html_module.escape(str(record.get("pos_number", "")))}</td>
                <td>{html_module.escape(str(record.get("bank_sheet", "—")))}</td>
            </tr>
        </table>
        <div class="section-title">Proof Of Service</div>
        <table>
            <thead>
                <tr><th>Product</th><th>Type</th><th>From</th><th>To</th><th>Stickers</th><th>Banking</th><th>Parish</th></tr>
            </thead>
            <tbody>{items_html}</tbody>
        </table>
        <table>
            <tr><th>Total Banking</th><th>Total Parish</th><th>Total Stickers</th></tr>
            <tr><td>R {total_banking:.2f}</td><td>R {total_parish:.2f}</td><td>{total_stickers}</td></tr>
        </table>
        <table>
            <tr><th>Amount in Words</th></tr>
            <tr><td style="font-style: italic; text-align: left; padding: 10px;">{banking_words}</td></tr>
        </table>
        <div class="section-title">Depositor's Details</div>
        <table>
            <tr><th>Name & Surname</th><th>ID Number</th><th>Cellphone</th></tr>
            <tr>
                <td>{html_module.escape(str(depositor.get("name", record.get("depositor_name", "—"))))}</td>
                <td>{html_module.escape(str(depositor.get("id", record.get("depositor_id", "—"))))}</td>
                <td>{html_module.escape(str(depositor.get("phone", record.get("depositor_phone", "—"))))}</td>
            </tr>
        </table>
        <div class="section-title">Witnesses Details</div>
        <table>
            <tr><th>Witness 1</th><th>Witness 2</th><th>Witness 3</th></tr>
            <tr>
                <td>{html_module.escape(str(witnesses.get("witness1", record.get("witness1", "—"))))}</td>
                <td>{html_module.escape(str(witnesses.get("witness2", record.get("witness2", "—"))))}</td>
                <td>{html_module.escape(str(witnesses.get("witness3", record.get("witness3", "—"))))}</td>
            </tr>
        </table>
        <div class="section-title">Cash Calculation</div>
        <table>
            <tr><th>R200</th><th>R100</th><th>R50</th><th>R20</th><th>R10</th><th>Coins</th></tr>
            {cash_html if cash_html else "<tr><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td><td>0</td></tr>"}
        </table>
        <table>
            <tr><th>Type</th><th>Count</th><th>Total</th></tr>
            <tr><td>R200</td><td>{count200}</td><td>R {total200:.2f}</td></tr>
            <tr><td>R100</td><td>{count100}</td><td>R {total100:.2f}</td></tr>
            <tr><td>R50</td><td>{count50}</td><td>R {total50:.2f}</td></tr>
            <tr><td>R20</td><td>{count20}</td><td>R {total20:.2f}</td></tr>
            <tr><td>R10</td><td>{count10}</td><td>R {total10:.2f}</td></tr>
            <tr><td>Coins</td><td>{count_coins}</td><td>R {total_coins:.2f}</td></tr>
            <tr style="font-weight:bold; font-size:18px;"><td colspan="2">Grand Total Cash</td><td>R {grand_total:.2f}</td></tr>
        </table>
        <div class="section-title">Conclusion</div>
        <table>
            <tr><th>Final Status</th><th>Expected Total</th><th>Grand Total Cash</th></tr>
            <tr>
                <td class="{"status-balanced" if final_status == "BALANCED" else "status-discrepancy"}">{final_status}</td>
                <td>R {expected:.2f}</td>
                <td>R {grand_total:.2f}</td>
            </tr>
        </table>
        <div class="final-remarks" style="color: {conclusion_color};">{final_conclusion}</div>
        <div class="footer">
            <h3>Kganya Financial Service Providers | Lighting The Way Through Service</h3>
            <p>Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
    </div>
</body>
</html>"""
    return html





def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_unique_filename(original_filename):
    ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    return f"{uuid.uuid4().hex}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"

def get_pos_uploads(pos_record_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM pos_uploads 
        WHERE pos_record_id = ? AND is_replaced = 0
        ORDER BY upload_type, uploaded_at DESC
    """, (pos_record_id,))
    uploads = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return uploads

def get_upload_history(pos_record_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pu.*, 
               replace_pu.original_filename as replaced_by_filename,
               replace_pu.uploaded_at as replaced_at_time
        FROM pos_uploads pu
        LEFT JOIN pos_uploads replace_pu ON pu.replaced_by_upload_id = replace_pu.id
        WHERE pu.pos_record_id = ?
        ORDER BY pu.uploaded_at DESC
    """, (pos_record_id,))
    history = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return history

# =========================================
# AUTH DECORATORS
# =========================================

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") not in ["admin", "superadmin"]:
            flash("Admin access required.", "error")
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "superadmin":
            flash("Superadmin access required.", "error")
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please log in first.", "error")
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated

#===================================================================================================
# ADEDD FUNCTIONS
#===================================================================================================



# =========================================
# SUPERADMIN DECORATOR
# =========================================


# =========================================
# Activate anothe booklet when a booklet 
# is completed in a submission
# =========================================
def ensure_two_active_booklets(conn, user_id, product):
    """
    Ensure a product has 2 consecutive active booklets.
    If a booklet was just completed, activate the next inactive one.
    """
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, booklet_number, receipt_from, receipt_to, is_active
        FROM receipt_booklets
        WHERE user_id = ? AND product_name = ? AND is_completed = 0
        ORDER BY CAST(booklet_number AS INTEGER) ASC
    """, (user_id, product))
    product_booklets = cursor.fetchall()

    for i, pb in enumerate(product_booklets):
        if i < 2:
            if pb["is_active"] == 0:
                cursor.execute("""
                    UPDATE receipt_booklets 
                    SET is_active = 1, next_expected_receipt = ?
                    WHERE id = ?
                """, (pb["receipt_from"], pb["id"]))
        else:
            if pb["is_active"] == 1:
                cursor.execute("""
                    UPDATE receipt_booklets 
                    SET is_active = 0
                    WHERE id = ?
                """, (pb["id"],))

# =========================================
# GET USER'S ACTIVE BOOKLETS
# =========================================
def get_user_active_booklets(user_id):
    """Get ALL active booklets for a user, with dynamically calculated next_expected."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM receipt_booklets
        WHERE user_id = ? AND is_active = 1 AND is_completed = 0
        ORDER BY product_name, CAST(booklet_number AS INTEGER) ASC
    """, (user_id,))
    
    all_booklets = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # Calculate next_expected for EACH booklet (no filtering!)
    result = []
    for b in all_booklets:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT MAX(receipt_to) as max_sold FROM booklet_used_receipts WHERE booklet_id = ?", (b["id"],))
        max_sold_row = cursor.fetchone()
        max_sold = max_sold_row["max_sold"] if max_sold_row and max_sold_row["max_sold"] is not None else b["receipt_from"] - 1
        
        cursor.execute("SELECT MAX(receipt_to) as max_cancelled FROM booklet_cancelled_receipts WHERE booklet_id = ?", (b["id"],))
        max_cancelled_row = cursor.fetchone()
        max_cancelled = max_cancelled_row["max_cancelled"] if max_cancelled_row and max_cancelled_row["max_cancelled"] is not None else b["receipt_from"] - 1
        
        b["next_expected_receipt"] = max(max_sold, max_cancelled) + 1
        
        conn.close()
        result.append(b)
    
    return result

# =========================================
# GET BOOKLET BY PRODUCT FOR USER
# =========================================


# =========================================
# CHECK IF RECEIPT RANGE IS AVAILABLE
# =========================================

# =========================================
# RECORD USED RECEIPTS
# =========================================


# =========================================
# RECORD CANCELLED RECEIPTS
# =========================================


# =========================================
# UPDATE BOOKLET PROGRESS
# =========================================


# =========================================
# CHECK FOR DUPLICATE BOOKLET GLOBALLY
# =========================================
def is_booklet_duplicate(product_name, receipt_type, receipt_from, receipt_to, exclude_user_id=None):
    """Check if any user already has this exact booklet range and type."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT 1 FROM receipt_booklets
        WHERE product_name = ? AND receipt_type = ? 
        AND receipt_from = ? AND receipt_to = ?
    """
    params = [product_name, receipt_type, receipt_from, receipt_to]
    
    if exclude_user_id:
        query += " AND user_id != ?"
        params.append(exclude_user_id)
    
    cursor.execute(query, params)
    result = cursor.fetchone()
    conn.close()
    return result is not None

# =========================================
# MANAGE PRODUCTS (Admin/Superadmin)
# =========================================



@app.route("/admin/products")
@admin_required
def manage_products():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Try products_master first, fallback to legacy products
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='products_master'")
    has_master = cursor.fetchone()
    
    if has_master:
        cursor.execute("SELECT * FROM products_master ORDER BY name")
    else:
        cursor.execute("SELECT * FROM products ORDER BY name")
    
    products = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template("admin_products.html", products=products)

# =========================================
# ALLOCATE BOOKLETS (Admin/Superadmin)
# =========================================
@app.route("/admin/booklets")
@admin_required
def manage_booklets():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all booklets with user info and current pricing
    cursor.execute("""
        SELECT rb.*, u.username, u.church_branch_name, 
               COALESCE(pm.price, 0) as current_price, 
               COALESCE(pm.deduction, 0) as current_deduction
        FROM receipt_booklets rb
        JOIN users u ON rb.user_id = u.id
        LEFT JOIN products_master pm ON rb.product_name = pm.name
        ORDER BY rb.created_at DESC
    """)
    booklets_raw = [dict(row) for row in cursor.fetchall()]
    
    booklets = []
    for b in booklets_raw:
        booklet = dict(b)
        
        # Recalculate next_expected dynamically from used and cancelled receipts
        cursor.execute("SELECT MAX(receipt_to) as max_sold FROM booklet_used_receipts WHERE booklet_id = ?", (booklet["id"],))
        max_sold_row = cursor.fetchone()
        max_sold = max_sold_row["max_sold"] if max_sold_row and max_sold_row["max_sold"] else booklet["receipt_from"] - 1
        
        cursor.execute("SELECT MAX(receipt_to) as max_cancelled FROM booklet_cancelled_receipts WHERE booklet_id = ?", (booklet["id"],))
        max_cancelled_row = cursor.fetchone()
        max_cancelled = max_cancelled_row["max_cancelled"] if max_cancelled_row and max_cancelled_row["max_cancelled"] else booklet["receipt_from"] - 1
        
        # Override the stored next_expected with the calculated one
        booklet["next_expected_receipt"] = max(max_sold, max_cancelled) + 1
        
        # Check usage flags
        cursor.execute("SELECT COUNT(*) as used_count FROM booklet_used_receipts WHERE booklet_id = ?", (booklet["id"],))
        used = cursor.fetchone()
        booklet["has_used_receipts"] = (used["used_count"] if used else 0) > 0
        
        cursor.execute("SELECT COUNT(*) as cancelled_count FROM booklet_cancelled_receipts WHERE booklet_id = ?", (booklet["id"],))
        cancelled = cursor.fetchone()
        booklet["has_cancelled_receipts"] = (cancelled["cancelled_count"] if cancelled else 0) > 0
        
        booklets.append(booklet)
    
    # Get all users for allocation form
    cursor.execute("SELECT id, username, church_branch_name FROM users ORDER BY username")
    users = [dict(row) for row in cursor.fetchall()]
    
    # Get products
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='products_master'")
    has_master = cursor.fetchone()
    
    if has_master:
        cursor.execute("SELECT * FROM products_master WHERE is_active = 1 ORDER BY name")
    else:
        cursor.execute("SELECT * FROM products ORDER BY name")
    products = [dict(row) for row in cursor.fetchall()]
    
    # Calculate statistics for charts
    # Total receipts per product (sum of total_receipts from all booklets)
    cursor.execute("""
        SELECT product_name, SUM(total_receipts) as total_count
        FROM receipt_booklets
        GROUP BY product_name
        ORDER BY total_count DESC
    """)
    total_stats_raw = {row["product_name"]: row["total_count"] for row in cursor.fetchall()}
    
    # Sold receipts per product
    cursor.execute("""
        SELECT rb.product_name, SUM(bur.receipt_to - bur.receipt_from + 1) as sold_count
        FROM booklet_used_receipts bur
        JOIN receipt_booklets rb ON bur.booklet_id = rb.id
        GROUP BY rb.product_name
    """)
    sold_stats_raw = {row["product_name"]: row["sold_count"] or 0 for row in cursor.fetchall()}
    
    # Cancelled receipts per product
    cursor.execute("""
        SELECT rb.product_name, SUM(bcr.receipt_to - bcr.receipt_from + 1) as cancelled_count
        FROM booklet_cancelled_receipts bcr
        JOIN receipt_booklets rb ON bcr.booklet_id = rb.id
        GROUP BY rb.product_name
    """)
    cancelled_stats_raw = {row["product_name"]: row["cancelled_count"] or 0 for row in cursor.fetchall()}
    
    # Build complete stats including products with zero values
    all_products = set(total_stats_raw.keys()) | set(sold_stats_raw.keys()) | set(cancelled_stats_raw.keys())
    
    total_stats = []
    sold_stats = []
    cancelled_stats = []
    remaining_stats = []
    
    for product in sorted(all_products):
        total = total_stats_raw.get(product, 0)
        sold = sold_stats_raw.get(product, 0)
        cancelled = cancelled_stats_raw.get(product, 0)
        remaining = total - sold - cancelled
        
        total_stats.append({"product": product, "count": total})
        sold_stats.append({"product": product, "count": sold})
        cancelled_stats.append({"product": product, "count": cancelled})
        remaining_stats.append({"product": product, "count": max(0, remaining)})
    
    # Sort by count descending
    total_stats.sort(key=lambda x: x["count"], reverse=True)
    sold_stats.sort(key=lambda x: x["count"], reverse=True)
    cancelled_stats.sort(key=lambda x: x["count"], reverse=True)
    remaining_stats.sort(key=lambda x: x["count"], reverse=True)
    
    stats = {
        "total": total_stats,
        "sold": sold_stats,
        "cancelled": cancelled_stats,
        "remaining": remaining_stats
    }
    
    import json
    stats_json = json.dumps(stats)
    
    conn.close()
    return render_template("admin_booklets.html", booklets=booklets, users=users, products=products, stats_json=stats_json)

@app.route("/user/booklets")
@login_required
def user_booklets():
    """User view of their own booklets - read only."""
    if session.get("role") != "user":
        return redirect("/admin/booklets")

    username = session["username"]

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get user ID
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        flash("User not found.", "error")
        return redirect("/user")

    user_id = user_row["id"]

    # Get user's booklets
    cursor.execute("""
        SELECT rb.*, u.username, u.church_branch_name
        FROM receipt_booklets rb
        JOIN users u ON rb.user_id = u.id
        WHERE rb.user_id = ?
        ORDER BY rb.product_name, CAST(rb.booklet_number AS INTEGER) ASC
    """, (user_id,))
    booklets_raw = cursor.fetchall()

    booklets = []
    for b in booklets_raw:
        booklet = dict(b)
        booklet_id = booklet["id"]

        # ═══════════════════════════════════════════════════════════════
        # NEW: Calculate sold_count and cancelled_count for THIS booklet
        # ═══════════════════════════════════════════════════════════════
        cursor.execute(
            "SELECT COALESCE(SUM(receipt_to - receipt_from + 1), 0) as sold_count "
            "FROM booklet_used_receipts WHERE booklet_id = ?",
            (booklet_id,)
        )
        sold_count_row = cursor.fetchone()
        booklet["sold_count"] = sold_count_row["sold_count"] if sold_count_row else 0

        cursor.execute(
            "SELECT COALESCE(SUM(receipt_to - receipt_from + 1), 0) as cancelled_count "
            "FROM booklet_cancelled_receipts WHERE booklet_id = ?",
            (booklet_id,)
        )
        cancelled_count_row = cursor.fetchone()
        booklet["cancelled_count"] = cancelled_count_row["cancelled_count"] if cancelled_count_row else 0
        # ═══════════════════════════════════════════════════════════════

        # ── MATHEMATICAL RULE: max_receipt_issued = MAX(max_sold, max_cancelled) ──
        cursor.execute(
            "SELECT MAX(receipt_to) as max_sold FROM booklet_used_receipts WHERE booklet_id = ?",
            (booklet_id,)
        )
        max_sold_row = cursor.fetchone()
        max_sold = max_sold_row["max_sold"] if max_sold_row and max_sold_row["max_sold"] is not None else None

        cursor.execute(
            "SELECT MAX(receipt_to) as max_cancelled FROM booklet_cancelled_receipts WHERE booklet_id = ?",
            (booklet_id,)
        )
        max_cancelled_row = cursor.fetchone()
        max_cancelled = max_cancelled_row["max_cancelled"] if max_cancelled_row and max_cancelled_row["max_cancelled"] is not None else None

        # THE KEY FORMULA
        if max_sold is None and max_cancelled is None:
            max_receipt_issued = None
            next_expected = booklet["receipt_from"]
        else:
            max_receipt_issued = max(max_sold or 0, max_cancelled or 0)
            next_expected = max_receipt_issued + 1
            if next_expected > booklet["receipt_to"]:
                next_expected = booklet["receipt_to"]

        booklet["max_receipt_issued"] = max_receipt_issued

        # ── Persist max_receipt_issued to database ──
        cursor.execute(
            "UPDATE receipt_booklets SET max_receipt_issued = ? WHERE id = ?",
            (max_receipt_issued if max_receipt_issued is not None else 0, booklet_id)
        )

        # ── Auto-complete and auto-activate next booklet ──
        if max_receipt_issued is not None and max_receipt_issued >= booklet["receipt_to"]:
            cursor.execute("""
                UPDATE receipt_booklets 
                SET is_completed = 1, is_active = 0, completed_at = CURRENT_TIMESTAMP 
                WHERE id = ?
            """, (booklet_id,))
            booklet["is_completed"] = 1
            booklet["is_active"] = 0
            booklet["display_next_expected"] = None
        else:
            booklet["display_next_expected"] = next_expected
            cursor.execute("""
                UPDATE receipt_booklets 
                SET next_expected_receipt = ?
                WHERE id = ?
            """, (next_expected, booklet_id))
        booklets.append(booklet)

    # ── AFTER processing all booklets, ensure 2 consecutive active per product ──
    cursor.execute("""
        SELECT DISTINCT product_name 
        FROM receipt_booklets 
        WHERE user_id = ?
        ORDER BY product_name
    """, (user_id,))
    products = [row["product_name"] for row in cursor.fetchall()]

    for product in products:
        cursor.execute("""
            SELECT id, booklet_number, receipt_from, receipt_to, is_active
            FROM receipt_booklets
            WHERE user_id = ? AND product_name = ? AND is_completed = 0
            ORDER BY CAST(booklet_number AS INTEGER) ASC
        """, (user_id, product))
        product_booklets = cursor.fetchall()

        for i, pb in enumerate(product_booklets):
            if i < 2:
                if pb["is_active"] == 0:
                    cursor.execute("""
                        UPDATE receipt_booklets 
                        SET is_active = 1, next_expected_receipt = ?
                        WHERE id = ?
                    """, (pb["receipt_from"], pb["id"]))
            else:
                if pb["is_active"] == 1:
                    cursor.execute("""
                        UPDATE receipt_booklets 
                        SET is_active = 0
                        WHERE id = ?
                    """, (pb["id"],))

    conn.commit()

    # ── Statistics for charts (unchanged) ──
    cursor.execute("""
        SELECT product_name, SUM(total_receipts) as total_count
        FROM receipt_booklets
        WHERE user_id = ?
        GROUP BY product_name
        ORDER BY total_count DESC
    """, (user_id,))
    total_stats_raw = {row["product_name"]: row["total_count"] for row in cursor.fetchall()}

    cursor.execute("""
        SELECT rb.product_name, SUM(bur.receipt_to - bur.receipt_from + 1) as sold_count
        FROM booklet_used_receipts bur
        JOIN receipt_booklets rb ON bur.booklet_id = rb.id
        WHERE rb.user_id = ?
        GROUP BY rb.product_name
    """, (user_id,))
    sold_stats_raw = {row["product_name"]: row["sold_count"] or 0 for row in cursor.fetchall()}

    cursor.execute("""
        SELECT rb.product_name, SUM(bcr.receipt_to - bcr.receipt_from + 1) as cancelled_count
        FROM booklet_cancelled_receipts bcr
        JOIN receipt_booklets rb ON bcr.booklet_id = rb.id
        WHERE rb.user_id = ?
        GROUP BY rb.product_name
    """, (user_id,))
    cancelled_stats_raw = {row["product_name"]: row["cancelled_count"] or 0 for row in cursor.fetchall()}

    all_products = set(total_stats_raw.keys()) | set(sold_stats_raw.keys()) | set(cancelled_stats_raw.keys())

    total_stats = []
    sold_stats = []
    cancelled_stats = []
    remaining_stats = []

    for product in sorted(all_products):
        total = total_stats_raw.get(product, 0)
        sold = sold_stats_raw.get(product, 0)
        cancelled = cancelled_stats_raw.get(product, 0)
        remaining = total - sold - cancelled

        total_stats.append({"product": product, "count": total})
        sold_stats.append({"product": product, "count": sold})
        cancelled_stats.append({"product": product, "count": cancelled})
        remaining_stats.append({"product": product, "count": max(0, remaining)})

    total_stats.sort(key=lambda x: x["count"], reverse=True)
    sold_stats.sort(key=lambda x: x["count"], reverse=True)
    cancelled_stats.sort(key=lambda x: x["count"], reverse=True)
    remaining_stats.sort(key=lambda x: x["count"], reverse=True)

    stats = {
        "total": total_stats,
        "sold": sold_stats,
        "cancelled": cancelled_stats,
        "remaining": remaining_stats
    }

    import json
    stats_json = json.dumps(stats)

    conn.close()
    return render_template("user_booklets.html", booklets=booklets, stats_json=stats_json, username=username)



@app.route("/admin/booklets/delete/<int:booklet_id>", methods=["POST"])
@admin_required
def delete_booklet(booklet_id):
    """Delete a booklet and log it to deleted_booklets. Only allowed if no receipts have been used or cancelled."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if booklet exists
    cursor.execute("""
        SELECT rb.*, u.username, u.church_branch_name 
        FROM receipt_booklets rb
        JOIN users u ON rb.user_id = u.id
        WHERE rb.id = ?
    """, (booklet_id,))
    booklet = cursor.fetchone()
    
    if not booklet:
        conn.close()
        flash("Booklet not found.", "error")
        return redirect("/admin/booklets")
    
    # Check if booklet has any used receipts
    cursor.execute("SELECT COUNT(*) as count FROM booklet_used_receipts WHERE booklet_id = ?", (booklet_id,))
    used_count = cursor.fetchone()["count"]
    
    # Check if booklet has any cancelled receipts
    cursor.execute("SELECT COUNT(*) as count FROM booklet_cancelled_receipts WHERE booklet_id = ?", (booklet_id,))
    cancelled_count = cursor.fetchone()["count"]
    
    # If booklet has usage, prevent deletion with a strong warning
    if used_count > 0 or cancelled_count > 0:
        conn.close()
        flash(f"Cannot delete Booklet #{booklet['booklet_number']} for {booklet['product_name']} — it has {used_count} sold and {cancelled_count} cancelled receipts. Deletion would destroy financial records.", "error")
        return redirect("/admin/booklets")
    
    # Log deletion to deleted_booklets before actually deleting
    deleted_by = session.get("username", "unknown")
    cursor.execute("""
        INSERT INTO deleted_booklets (
            original_booklet_id, user_id, username, church_branch_name,
            product_name, booklet_number, receipt_type,
            receipt_from, receipt_to, total_receipts,
            price_at_allocation, deduction_at_allocation,
            next_expected_receipt, is_active, is_completed,
            created_at, allocated_by, deleted_by, deletion_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        booklet["id"], booklet["user_id"], booklet["username"], booklet["church_branch_name"],
        booklet["product_name"], booklet["booklet_number"], booklet["receipt_type"],
        booklet["receipt_from"], booklet["receipt_to"], booklet["total_receipts"],
        booklet["price_at_allocation"], booklet["deduction_at_allocation"],
        booklet["next_expected_receipt"], booklet["is_active"], booklet["is_completed"],
        booklet["created_at"], booklet["allocated_by"], deleted_by,
        "Deleted by admin/superadmin before any usage"
    ))
    
    # Safe to delete - no usage yet
    product_name = booklet["product_name"]
    booklet_number = booklet["booklet_number"]
    
    cursor.execute("DELETE FROM receipt_booklets WHERE id = ?", (booklet_id,))
    conn.commit()
    
    # AUDIT: Log booklet deletion
    log_booklet_action(
        "DELETE_BOOKLET",
        f"Deleted booklet '{booklet_number}' for {product_name} (user: {booklet['username']})",
        old_values=dict(booklet)
    )
    
    conn.close()
    
    flash(f"Booklet '{booklet_number}' for {product_name} has been deleted successfully. Deletion logged.", "success")
    return redirect("/admin/booklets")
    
    flash(f"Booklet '{booklet_number}' for {product_name} has been deleted successfully.", "success")
    return redirect("/admin/booklets")


#------------------------------------------9---------------------------------------------------------
#---------------------------------------------------------------------------------------------------

@app.route("/admin/deleted-booklets")
@admin_required
def view_deleted_booklets():
    """View all deleted booklets with full audit trail."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM deleted_booklets
        ORDER BY deleted_at DESC
    """)
    deleted_booklets = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template("admin_deleted_booklets.html", deleted_booklets=deleted_booklets)

@app.route("/admin/booklets/allocate", methods=["POST"])
@admin_required
def allocate_booklet():
    user_id = int(request.form.get("user_id", 0))
    product_name = request.form.get("product_name", "").strip().upper()
    booklet_number = request.form.get("booklet_number", "").strip()
    receipt_type = request.form.get("receipt_type", "").strip().upper()
    receipt_from = int(request.form.get("receipt_from", 0))
    receipt_to = int(request.form.get("receipt_to", 0))
    
    # Validation
    if not all([user_id, product_name, booklet_number, receipt_type]):
        flash("All fields are required.", "error")
        return redirect("/admin/booklets")
    
    if receipt_to < receipt_from:
        flash("Receipt 'To' must be greater than or equal to 'From'.", "error")
        return redirect("/admin/booklets")
    
    # Check for duplicate booklet globally
    if is_booklet_duplicate(product_name, receipt_type, receipt_from, receipt_to):
        flash("This booklet (same product, type, and range) is already allocated to another user. Please verify.", "error")
        return redirect("/admin/booklets")
    
    # Check if user already has this booklet number for this product
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 1 FROM receipt_booklets 
        WHERE user_id = ? AND product_name = ? AND booklet_number = ?
    """, (user_id, product_name, booklet_number))
    if cursor.fetchone():
        conn.close()
        flash(f"User already has booklet number '{booklet_number}' for {product_name}.", "error")
        return redirect("/admin/booklets")
    
    # Get current price from products_master
    cursor.execute("SELECT price, deduction FROM products_master WHERE name = ?", (product_name,))
    product = cursor.fetchone()
    if not product:
        conn.close()
        flash("Product not found.", "error")
        return redirect("/admin/booklets")
    
    total_receipts = receipt_to - receipt_from + 1
    
    # Check if user already has an active booklet for this product
    cursor.execute("""
        SELECT id FROM receipt_booklets 
        WHERE user_id = ? AND product_name = ? AND is_active = 1 AND is_completed = 0
    """, (user_id, product_name))
    has_active = cursor.fetchone()
    
    is_active = 0 if has_active else 1  # Only activate if no active booklet exists
    
    cursor.execute("""
        INSERT INTO receipt_booklets (
            user_id, product_name, booklet_number, receipt_type,
            receipt_from, receipt_to, total_receipts,
            price_at_allocation, deduction_at_allocation,
            next_expected_receipt, is_active, allocated_by
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id, product_name, booklet_number, receipt_type,
        receipt_from, receipt_to, total_receipts,
        product["price"], product["deduction"],
        receipt_from, is_active, session["username"]
    ))
    
    conn.commit()
    
    # AUDIT: Log booklet allocation
    log_booklet_action(
        "ALLOCATE_BOOKLET",
        f"Allocated booklet '{booklet_number}' for {product_name} to user ID {user_id}",
        new_values={
            "user_id": user_id,
            "product_name": product_name,
            "booklet_number": booklet_number,
            "receipt_type": receipt_type,
            "receipt_from": receipt_from,
            "receipt_to": receipt_to,
            "allocated_by": session["username"]
        }
    )
    
    conn.close()
    
    flash(f"Booklet '{booklet_number}' for {product_name} allocated successfully.", "success")
    return redirect("/admin/booklets")

# =========================================
# VIEW USER BOOKLET PROGRESS (Admin/Superadmin)
# =========================================
@app.route("/admin/booklet-progress/<int:user_id>")
@admin_required
def view_booklet_progress(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get user info
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = dict(cursor.fetchone())
    
    # Get all booklets for user
    cursor.execute("""
        SELECT * FROM receipt_booklets
        WHERE user_id = ?
        ORDER BY product_name, booklet_number
    """, (user_id,))
    booklets = [dict(row) for row in cursor.fetchall()]
    
    # Get used and cancelled receipts per booklet
    for booklet in booklets:
        # Recalculate next_expected dynamically from used and cancelled receipts
        cursor.execute("SELECT MAX(receipt_to) as max_sold FROM booklet_used_receipts WHERE booklet_id = ?", (booklet["id"],))
        max_sold_row = cursor.fetchone()
        max_sold = max_sold_row["max_sold"] if max_sold_row and max_sold_row["max_sold"] else booklet["receipt_from"] - 1
        
        cursor.execute("SELECT MAX(receipt_to) as max_cancelled FROM booklet_cancelled_receipts WHERE booklet_id = ?", (booklet["id"],))
        max_cancelled_row = cursor.fetchone()
        max_cancelled = max_cancelled_row["max_cancelled"] if max_cancelled_row and max_cancelled_row["max_cancelled"] else booklet["receipt_from"] - 1
        
        # Override the stored next_expected with the calculated one
        booklet["next_expected_receipt"] = max(max_sold, max_cancelled) + 1
        
        cursor.execute("""
            SELECT * FROM booklet_used_receipts
            WHERE booklet_id = ? ORDER BY receipt_from
        """, (booklet["id"],))
        booklet["used_receipts"] = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute("""
            SELECT * FROM booklet_cancelled_receipts
            WHERE booklet_id = ? ORDER BY receipt_from
        """, (booklet["id"],))
        booklet["cancelled_receipts"] = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    return render_template("admin_booklet_progress.html", user=user, booklets=booklets)

#===================================================================================================
# ADEDD FUNCTIONS CLOSE
#===================================================================================================


# =========================================
# TEMPLATE CONTEXT PROCESSOR
# =========================================

@app.context_processor
def inject_globals():
    return {
        'app_name': 'KGANYA',
        'app_tagline': 'Lighting The Way Through Service',
        'current_year': datetime.now().year
    }

# =========================================
# ROUTES: AUTHENTICATION
# =========================================



@app.route("/register", methods=["GET", "POST"])
def register():
    # ─── CHECK REGISTRATION LOCK ───
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT registrations_open FROM system_settings WHERE id = 1")
    settings_row = cursor.fetchone()
    registrations_open = settings_row["registrations_open"] if settings_row else 0
    conn.close()

    if request.method == "POST":
        # Server-side block — reject even if frontend is bypassed
        if not registrations_open:
            return render_template("register.html", 
                                   error="Registrations are currently closed.", 
                                   registrations_open=False)

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        secretary_phone = request.form.get("secretary_phone", "").strip()
        vice_secretary_phone = request.form.get("vice_secretary_phone", "").strip()
        secretary_email = request.form.get("secretary_email", "").strip()
        vice_secretary_email = request.form.get("vice_secretary_email", "").strip()
        church_code = request.form.get("church_code", "").strip()
        church_file_number = request.form.get("church_file_number", "").strip()
        church_branch_name = request.form.get("church_branch_name", "").strip()
        otp_code = request.form.get("otp_code", "").strip()

        valid, msg = validate_username(username)
        if not valid:
            return render_template("register.html", error=msg, registrations_open=bool(registrations_open))

        valid, msg = validate_password(password)
        if not valid:
            return render_template("register.html", error=msg, registrations_open=bool(registrations_open))

        valid_sec, cleaned_sec = validate_phone(secretary_phone)
        if not valid_sec:
            return render_template("register.html", error=f"Secretary phone: {cleaned_sec}", registrations_open=bool(registrations_open))

        valid_vice, cleaned_vice = validate_phone(vice_secretary_phone)
        if not valid_vice:
            return render_template("register.html", error=f"Vice-Secretary phone: {cleaned_vice}", registrations_open=bool(registrations_open))

        valid_sec_email, cleaned_sec_email = validate_email(secretary_email)
        if not valid_sec_email:
            return render_template("register.html", error=f"Secretary email: {cleaned_sec_email}", registrations_open=bool(registrations_open))

        valid_vice_email, cleaned_vice_email = validate_email(vice_secretary_email)
        if not valid_vice_email:
            return render_template("register.html", error=f"Vice-Secretary email: {cleaned_vice_email}", registrations_open=bool(registrations_open))

        if email_exists(cleaned_sec_email):
            return render_template("register.html", error=f"Secretary email '{cleaned_sec_email}' already exists. Please use a different email.", registrations_open=bool(registrations_open))
        if email_exists(cleaned_vice_email):
            return render_template("register.html", error=f"Vice-Secretary email '{cleaned_vice_email}' already exists. Please use a different email.", registrations_open=bool(registrations_open))

        valid_church_code, cleaned_church_code = validate_church_code(church_code)
        if not valid_church_code:
            return render_template("register.html", error=cleaned_church_code, registrations_open=bool(registrations_open))

        valid_file_num, cleaned_file_num = validate_church_file_number(church_file_number)
        if not valid_file_num:
            return render_template("register.html", error=cleaned_file_num, registrations_open=bool(registrations_open))

        if church_file_number_exists(cleaned_file_num):
            return render_template("register.html", error=f"Church file number '{cleaned_file_num}' already exists. Please use a different file number.", registrations_open=bool(registrations_open))

        valid_branch, cleaned_branch = validate_church_branch_name(church_branch_name)
        if not valid_branch:
            return render_template("register.html", error=cleaned_branch, registrations_open=bool(registrations_open))

        if not otp_code:
            return render_template("register.html", error="OTP code is required.", registrations_open=bool(registrations_open))

        otp_verified = False
        for email in [cleaned_sec_email, cleaned_vice_email]:
            success, msg = verify_otp_code(email, otp_code, "registration")
            if success:
                otp_verified = True
                break

        if not otp_verified:
            return render_template("register.html", error="Invalid or expired OTP code.", registrations_open=bool(registrations_open))

        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            hashed = generate_password_hash(password)
            cursor.execute("""
                INSERT INTO pending_users (username, password, secretary_phone, vice_secretary_phone, secretary_email, vice_secretary_email, church_code, church_file_number, church_branch_name, requested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (username, hashed, cleaned_sec, cleaned_vice, cleaned_sec_email, cleaned_vice_email, cleaned_church_code, cleaned_file_num, cleaned_branch, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()
            
            log_audit_event(
                "REGISTER_REQUEST",
                f"User '{username}' submitted registration request",
                action_category="authentication",
                username=username
            )
            
            flash("Registration request submitted. Await admin approval.", "success")
            return redirect("/login")
        except sqlite3.IntegrityError as e:
            error_msg = str(e).lower()
            if "church_file_number" in error_msg:
                return render_template("register.html", error="Church file number already exists.", registrations_open=bool(registrations_open))
            return render_template("register.html", error="Username already exists or is awaiting approval.", registrations_open=bool(registrations_open))

    return render_template("register.html", registrations_open=bool(registrations_open))


@app.route("/superadmin/toggle-registration", methods=["POST"])
@superadmin_required
def toggle_registration():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT registrations_open FROM system_settings WHERE id = 1")
    row = cursor.fetchone()
    current = row["registrations_open"] if row else 0
    new_state = 0 if current else 1
    cursor.execute("""
        UPDATE system_settings SET registrations_open = ?, updated_at = CURRENT_TIMESTAMP, updated_by = ?
        WHERE id = 1
    """, (new_state, session.get("username")))
    conn.commit()
    conn.close()
    status = "OPENED" if new_state else "CLOSED"
    flash(f"Registrations {status} successfully.", "success")
    return redirect("/superadmin")

# Add this right before your send_otp route
print("=" * 50)
print("Loading send_otp route...")
print("=" * 50)



 

@app.route('/api/send-otp', methods=['POST'])
def send_otp():

    if request.is_json:
        data = request.get_json(silent=True) or {}
    else:
        data = request.form.to_dict()
    
    recipient = (data.get('recipient') or '').strip()
    purpose = data.get('purpose', 'user_creation')
    method = data.get('method', '').lower()
    
    print("OTP request data:", data)
    
    if not recipient:
        return jsonify({
            'success': False,
            'message': 'Recipient is required'
        }), 400
    
    #
    # CASE 1:
    # Recipient is already an email address
    # (new user creation / new admin creation)
    #
    if method == "email" or "@" in recipient:
    
        email = recipient
    
        print(f"OTP direct email mode -> {email}")
    
    #
    # CASE 2:
    # Recipient is a username
    # (existing users)
    #
    else:
    
        username = recipient
    
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
    
        cursor.execute("""
            SELECT secretary_email
            FROM users
            WHERE username = ?
        """, (username,))
    
        row = cursor.fetchone()
        conn.close()
    
        if not row or not row[0]:
            return jsonify({
                'success': False,
                'message': 'Secretary email not found'
            }), 400
    
        email = row[0]
    
        print(f"OTP username lookup mode -> {username} -> {email}")

    otp_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])

    store_otp(email, otp_code, purpose)

    session['otp_code'] = otp_code
    session['otp_email'] = email
    session['otp_expiry'] = (datetime.now() + timedelta(minutes=10)).isoformat()
    print(f"Sending OTP {otp_code} to {email} for {purpose}")
    success = send_otp_email(email, otp_code, purpose)

    if success:
        print(f"SUCCESS: OTP email sent to {email}")
        return jsonify({'success': True, 'otp_sent': True, 'otp_expiry_seconds': 600})

    print(f"ERROR: Failed to send OTP email to {email}")
    return jsonify({'success': False, 'message': 'Failed to send OTP email'}), 500  

@app.route("/admin/clear-all-pos", methods=["POST"])
@superadmin_required
def clear_all_pos():
    """Clear all POS files - superadmin only."""
    if session.get("role") != "superadmin":
        return jsonify({"success": False, "message": "Only superadmin can clear all POS files."}), 403
        
    if session.get("role") != "superadmin":
        log_audit_event(
            "CLEAR_ALL_POS_DENIED",
            f"Admin '{session.get('username')}' attempted to clear all POS without superadmin rights",
            action_category="security"
        )
        return jsonify({"success": False, "message": "Only superadmin can clear all POS files."}), 403
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get count before deletion from pos_records
        cursor.execute("SELECT COUNT(*) as count FROM pos_records")
        result = cursor.fetchone()
        count = result["count"] if result else 0
        
        # Delete all related records first (foreign key constraints)
        cursor.execute("DELETE FROM pos_items")
        cursor.execute("DELETE FROM pos_cash_rows")
        cursor.execute("DELETE FROM pos_cancelled_receipts")
        
        # Delete all POS records
        cursor.execute("DELETE FROM pos_records")
        
        conn.commit()
        conn.close()
        
        # Clean up HTML/TXT files on disk
        deleted_files = 0
        if os.path.exists(POS_FOLDER):
            for root, dirs, files in os.walk(POS_FOLDER):
                for filename in files:
                    if filename.endswith(('.html', '.txt')):
                        filepath = os.path.join(root, filename)
                        try:
                            os.remove(filepath)
                            deleted_files += 1
                        except (OSError, PermissionError):
                            pass
                        
        # AUDIT: Log superadmin clearing all POS
        log_audit_event(
            "CLEAR_ALL_POS",
            f"Superadmin cleared all {count} POS records and {deleted_files} files",
            action_category="data_deletion"
        )
        
        return jsonify({
            "success": True, 
            "message": f"All {count} POS records and {deleted_files} files have been permanently deleted. The database is now clean."
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": f"Error clearing POS files: {str(e)}"}), 500

    
@app.route("/login", methods=["GET", "POST"])
def login():
    otp_mode = request.args.get("otp") == "1"
    if request.method == "POST":
        login_step = request.form.get("login_step", "1")
        
        if login_step == "1":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            
            if not username or not password:
                return render_template("login.html", error="Username and password are required.")
            
            session.clear()
            
            admin = get_admin(username)
            if admin and check_password_hash(admin["password"], password):
                # Check if admin has pending temporary password reset
                conn = get_db_connection()
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT *
                    FROM password_reset_tokens
                    WHERE username = ?
                      AND user_type = 'admin'
                      AND used = 0
                      AND expires_at > ?
                """,
                (
                    username,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ))
                
                pending_reset = cursor.fetchone()
                
                conn.close()
                
                if pending_reset:
                    flash("You must change your temporary password before continuing.", "warning")
                    return redirect(f"/admin/reset-password/{pending_reset['token']}")
                
                # Existing force password change check
                if admin["force_password_change"] == 1:
                    session["force_change_user"] = username
                    return redirect(url_for("force_password_change"))
                
                email = admin["email"]
                if not email:
                    log_login_attempt(username, password, False, "Admin account has no email configured")
                    return render_template("login.html", error="Admin account has no email configured.")
                
                otp_code = generate_otp()
                store_login_otp(username, otp_code, admin["role"])
                send_otp_email(email, otp_code, "login")
                
                session["pending_login_user"] = username
                session["pending_login_role"] = admin["role"]
                
                return render_template("login.html", 
                                       step=2, 
                                       username=username, 
                                       email_masked=mask_email(email))
            
            user = get_user(username)
            if user and check_password_hash(user["password"], password):
                email = user.get("secretary_email") or user.get("vice_secretary_email")
                if not email:
                    log_login_attempt(username, password, False, "No email address on file")
                    return render_template("login.html", 
                                           error="No email address on file for this account. Please contact admin.")
                
                otp_code = generate_otp()
                store_login_otp(username, otp_code, "user")
                send_otp_email(email, otp_code, "login")
                
                session["pending_login_user"] = username
                session["pending_login_role"] = "user"
                
                return render_template("login.html", 
                                       step=2, 
                                       username=username, 
                                       email_masked=mask_email(email))
            
            # AUDIT: Log failed login
            log_login_attempt(username, password, False, "Invalid username or password")
            return render_template("login.html", error="Invalid username or password")
        
        else:
            username = request.form.get("username", "").strip()
            otp_code = request.form.get("otp_code", "").strip()
            
            pending_user = session.get("pending_login_user")
            if not pending_user or pending_user != username:
                return render_template("login.html", error="Session expired. Please start login again.")
            
            if not otp_code or len(otp_code) != 6:
                return render_template("login.html", 
                                       step=2, 
                                       username=username,
                                       error="Please enter a valid 6-digit OTP code.")
            
            success, role, msg = verify_login_otp(username, otp_code)
            
            if not success:
                log_login_attempt(username, "", False, f"Invalid OTP: {msg}")
                return render_template("login.html", 
                                       step=2, 
                                       username=username,
                                       error=msg)
            
            session.permanent = True
            session["username"] = username
            session["role"] = role
            
            session.pop("pending_login_user", None)
            session.pop("pending_login_role", None)
            
            # AUDIT: Log successful login
            log_login_attempt(username, "", True)
            
            # VICE-SECRETARY NOTIFICATION: Notify when secretary logs in
            if role == "user":
                notify_vice_secretary_on_login(username)
            
            flash(f"Welcome, {username}!", "success")
            
            if role == "superadmin":
                return redirect("/superadmin")
            elif role == "admin":
                return redirect("/admin")
            else:
                return redirect("/user")
    
    return render_template("login.html", step=1)
    

@app.route("/logout")
def logout():
    username = session.get("username", "unknown")
    role = session.get("role", "unknown")
    
    # AUDIT: Log logout
    log_audit_event(
        "LOGOUT",
        f"User '{username}' ({role}) logged out",
        action_category="authentication"
    )
    
    flash("You have been logged out.", "info")
    session.clear()
    response = redirect("/login")
    response.set_cookie("session", "", expires=0)
    return response


@app.route('/force-password-change', methods=['GET', 'POST'])
def force_password_change():
    # Check if user is allowed to be here (either force_change_user or logged in superadmin)
    username = session.get("force_change_user")
    
    if not username:
        # Fallback: check if logged-in user has force_password_change flag
        if session.get("username") and session.get("role") == "superadmin":
            username = session["username"]
            # Check if flag is still set
            admin = get_admin(username)
            if not admin or admin.get("force_password_change") != 1:
                return redirect(url_for("dashboard"))
        else:
            return redirect(url_for("login"))
    
    if request.method == 'POST':
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if not new_password or not confirm_password:
            return render_template('force_password_change.html', error='Both password fields are required.')
        
        if new_password != confirm_password:
            return render_template('force_password_change.html', error='Passwords do not match.')
        
        if len(new_password) < 8:
            return render_template('force_password_change.html', error='Password must be at least 8 characters.')
        
        # Update password and clear force_change flag
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE admins SET password = ?, force_password_change = 0 WHERE username = ?
        """, (generate_password_hash(new_password), username))
        conn.commit()
        conn.close()
        
        # Clear the force_change session
        session.pop("force_change_user", None)
        
        # AUDIT: Log password change
        log_audit_event(
            "FORCE_PASSWORD_CHANGE",
            f"User '{username}' changed password via force-password-change",
            action_category="authentication",
            username=username
        )
        
        flash("Password changed successfully. Please log in with your new password.", "success")
        return redirect(url_for("login"))
    
    return render_template('force_password_change.html')

# =========================================
# ROUTES: HOME / DASHBOARD
# =========================================

@app.route("/")
def home():
    if "username" in session:
        if session.get("role") in ["admin", "superadmin"]:
            return redirect("/admin")
        elif session.get("role") == "user":
            return redirect("/user")
    return redirect("/login")

@app.route("/user")
@login_required
def user_dashboard():
    if session.get("role") != "user":
        return redirect("/login")
    return render_template("user.html")

@app.route("/admin")
@admin_required
def admin():
    """Admin main page with products and skip notification badge."""
    products = get_products() or []
    
    # Get pending skips count for navbar badge
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) as count FROM skipped_submissions WHERE status = 'pending'")
        result = cursor.fetchone()
        pending_skips_count = result['count'] if result else 0
    except Exception as e:
        print(f"Skip count error in admin route: {e}")
        pending_skips_count = 0
    conn.close()
    
    return render_template("admin.html", 
                           products=products, 
                           role=session.get("role"),
                           pending_skips_count=pending_skips_count)

# =========================================
# ROUTES: PRODUCT MANAGEMENT
# =========================================

@app.route("/edit-product/<int:product_id>", methods=["GET"])
@admin_required
def edit_product(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    conn.close()
    if not product:
        flash("Product not found.", "error")
        return redirect("/admin")
    return render_template("edit_product.html", product=product)





@app.route("/delete-product/<int:product_id>", methods=["POST"])
@admin_required
def delete_product(product_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    old_product = dict(cursor.fetchone()) if cursor.fetchone() else None
    
    cursor.execute("SELECT name FROM products WHERE id = ?", (product_id,))
    product = cursor.fetchone()
    if not product:
        conn.close()
        flash("Product not found.", "error")
        return redirect("/admin")
    
    name = product["name"]
    cursor.execute("DELETE FROM products WHERE id = ?", (product_id,))
    
    # Also deactivate in products_master if it exists
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='products_master'")
    if cursor.fetchone():
        cursor.execute("""
            UPDATE products_master SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE name = ?
        """, (name,))
    
    conn.commit()
    conn.close()
    
    # AUDIT: Log product deletion
    log_data_change("DELETE_PRODUCT", "products", product_id,
                    f"Deleted product '{name}'",
                    old_values=old_product)
    
    flash(f"Product '{name}' deleted successfully.", "success")
    return redirect("/admin")


@app.route("/add-product", methods=["POST"])
@admin_required
def add_product():
    name = sanitize_string(request.form.get("name"), 50).upper()
    try:
        price = float(request.form.get("price", 0))
        deduction = float(request.form.get("deduction", 0))
    except (ValueError, TypeError):
        flash("Invalid price or deduction value.", "error")
        return redirect("/admin")
    if price < 0 or deduction < 0:
        flash("Price and deduction cannot be negative.", "error")
        return redirect("/admin")
    if not name:
        flash("Product name is required.", "error")
        return redirect("/admin")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Add to legacy products table
        cursor.execute("INSERT INTO products (name, price, deduction) VALUES (?, ?, ?)", 
                       (name, price, deduction))
        
        # Also add to products_master if it exists
        cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='products_master'")
        if cursor.fetchone():
            cursor.execute("""
                INSERT OR REPLACE INTO products_master (name, price, deduction, is_active, updated_at)
                VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
            """, (name, price, deduction))
        
        conn.commit()
        
        new_id = cursor.lastrowid

        # AUDIT: Log product creation
        log_data_change("CREATE_PRODUCT", "products", new_id,
                        f"Created product '{name}' with price R{price}, deduction R{deduction}",
                        new_values={"name": name, "price": price, "deduction": deduction})
        
        flash(f"Product '{name}' added successfully.", "success")
    except sqlite3.IntegrityError:
        flash("A product with that name already exists.", "error")
    finally:
        conn.close()
    
    return redirect("/admin")

@app.route("/update-product/<int:product_id>", methods=["POST"])
@admin_required
def update_product(product_id):
    name = sanitize_string(request.form.get("name"), 50)
    try:
        price = float(request.form.get("price", 0))
        deduction = float(request.form.get("deduction", 0))
    except (ValueError, TypeError):
        flash("Invalid price or deduction value.", "error")
        return redirect(f"/edit-product/{product_id}")
    if price < 0 or deduction < 0:
        flash("Price and deduction cannot be negative.", "error")
        return redirect(f"/edit-product/{product_id}")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch old values for audit
    cursor.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    old_row = cursor.fetchone()
    old_product = dict(old_row) if old_row else None
    
    # Update legacy products table
    cursor.execute("UPDATE products SET name = ?, price = ?, deduction = ? WHERE id = ?", 
                   (name, price, deduction, product_id))
    
    # Also update products_master if it exists
    cursor.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='products_master'")
    if cursor.fetchone():
        cursor.execute("""
            INSERT OR REPLACE INTO products_master (name, price, deduction, is_active, updated_at)
            VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
        """, (name, price, deduction))
    
    conn.commit()
    conn.close()
    
    # AUDIT: Log product update
    log_data_change("UPDATE_PRODUCT", "products", product_id,
                    f"Updated product '{name}'",
                    old_values=old_product,
                    new_values={"name": name, "price": price, "deduction": deduction})
    
    flash("Product updated successfully.", "success")
    return redirect("/admin")

# ============================================================================================
# ROUTES: USER MANAGEMENT
# ================================================================================================

@app.route("/superadmin")
@superadmin_required
def superadmin_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT registrations_open FROM system_settings WHERE id = 1")
    row = cursor.fetchone()
    registrations_open = row["registrations_open"] if row else 0
    conn.close()
    return render_template("superadmin.html", registrations_open=bool(registrations_open))


@app.route("/admin/pending-users")
@admin_required
def pending_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_users ORDER BY requested_at DESC")
    users = cursor.fetchall()
    conn.close()
    return render_template("pending_users.html", users=users)


@app.route("/admin/approve-user/<int:user_id>")
@admin_required
def approve_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, password, secretary_phone, vice_secretary_phone, secretary_email, vice_secretary_email, church_code, church_file_number, church_branch_name, requested_at FROM pending_users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if user:
        # Use requested_at as created_at, or current time if missing
        created_at = user.get("requested_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute(
            "INSERT INTO users (username, password, secretary_phone, vice_secretary_phone, secretary_email, vice_secretary_email, church_code, church_file_number, church_branch_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user["username"], user["password"], user["secretary_phone"], user["vice_secretary_phone"], user["secretary_email"], user["vice_secretary_email"], user["church_code"], user["church_file_number"], user["church_branch_name"], created_at)
        )
        new_user_id = cursor.lastrowid
        cursor.execute("DELETE FROM pending_users WHERE id = ?", (user_id,))
        conn.commit()
        
        # AUDIT: Log user approval
        log_data_change("APPROVE_USER", "users", new_user_id,
                        f"Admin approved user '{user['username']}'",
                        new_values={"username": user["username"], "church_branch_name": user["church_branch_name"]})
        
        flash(f"User '{user['username']}' approved successfully.", "success")
    else:
        flash("User not found.", "error")
    conn.close()
    return redirect("/admin/pending-users")

@app.route("/admin/create-user", methods=["GET", "POST"])
@admin_required
def create_user_admin():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        secretary_phone = request.form.get("secretary_phone", "").strip()
        vice_secretary_phone = request.form.get("vice_secretary_phone", "").strip()
        secretary_email = request.form.get("secretary_email", "").strip()
        vice_secretary_email = request.form.get("vice_secretary_email", "").strip()
        church_code = request.form.get("church_code", "").strip()
        church_file_number = request.form.get("church_file_number", "").strip()
        church_branch_name = request.form.get("church_branch_name", "").strip()
        otp_code = request.form.get("otp_code", "").strip()

        valid, msg = validate_username(username)
        if not valid:
            return render_template("create_user.html", error=msg)

        valid_sec, cleaned_sec = validate_phone(secretary_phone)
        if not valid_sec:
            return render_template("create_user.html", error=f"Secretary phone: {cleaned_sec}")

        valid_vice, cleaned_vice = validate_phone(vice_secretary_phone)
        if not valid_vice:
            return render_template("create_user.html", error=f"Vice-Secretary phone: {cleaned_vice}")

        valid_sec_email, cleaned_sec_email = validate_email(secretary_email)
        if not valid_sec_email:
            return render_template("create_user.html", error=f"Secretary email: {cleaned_sec_email}")

        valid_vice_email, cleaned_vice_email = validate_email(vice_secretary_email)
        if not valid_vice_email:
            return render_template("create_user.html", error=f"Vice-Secretary email: {cleaned_vice_email}")

        # Check for duplicate emails
        if email_exists(cleaned_sec_email):
            return render_template("create_user.html", error=f"Secretary email '{cleaned_sec_email}' already exists. Please use a different email.")
        if email_exists(cleaned_vice_email):
            return render_template("create_user.html", error=f"Vice-Secretary email '{cleaned_vice_email}' already exists. Please use a different email.")

        valid_church_code, cleaned_church_code = validate_church_code(church_code)
        if not valid_church_code:
            return render_template("create_user.html", error=cleaned_church_code)

        valid_file_num, cleaned_file_num = validate_church_file_number(church_file_number)
        if not valid_file_num:
            return render_template("create_user.html", error=cleaned_file_num)

        # Check for duplicate church file number
        if church_file_number_exists(cleaned_file_num):
            return render_template("create_user.html", error=f"Church file number '{cleaned_file_num}' already exists. Please use a different file number.")

        valid_branch, cleaned_branch = validate_church_branch_name(church_branch_name)
        if not valid_branch:
            return render_template("create_user.html", error=cleaned_branch)

        if not otp_code:
            return render_template("create_user.html", error="OTP code is required.")

        otp_verified = False
        for email in [cleaned_sec_email, cleaned_vice_email]:
            success, msg = verify_otp_code(email, otp_code, "user_creation")
            if success:
                otp_verified = True
                break

        if not otp_verified:
            return render_template("create_user.html", error="Invalid or expired OTP code.")

        if get_user(username) or get_admin(username):
            return render_template("create_user.html", error="Username already exists.")

        # Generate temporary password and create user
        temp_password = generate_temp_password()
        create_user(username, temp_password, cleaned_sec, cleaned_vice, cleaned_sec_email, cleaned_vice_email, cleaned_church_code, cleaned_file_num, cleaned_branch)
        
        # AUDIT: Log user creation by admin
        log_data_change("CREATE_USER", "users", None,
                        f"Admin created user '{username}' for branch '{cleaned_branch}'",
                        new_values={"username": username, "church_branch_name": cleaned_branch, 
                                   "secretary_email": cleaned_sec_email, "vice_secretary_email": cleaned_vice_email})
        
        # Generate reset token and send email to secretary
        token = store_reset_token(username, cleaned_sec_email)
        email_sent = send_password_reset_email(cleaned_sec_email, username, token)
        
        # Also send to vice-secretary
        token2 = store_reset_token(username, cleaned_vice_email)
        send_password_reset_email(cleaned_vice_email, username, token2)
        
        if email_sent:
            return render_template("create_user.html", 
                success=f"User '{username}' created successfully. A password reset link has been sent to {cleaned_sec_email} and {cleaned_vice_email}. The link expires in 24 hours.")
        else:
            return render_template("create_user.html", 
                success=f"User '{username}' created successfully. However, the email could not be sent. Please contact the user with the temporary password.",
                temp_password=temp_password)

    return render_template("create_user.html")









#---------------------------------------------------------------------------------------------------------------------
# =========================================
# ROUTE: FORGOT PASSWORD (Users & Admins)
# =========================================

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Handle forgot password requests for both users and admins."""
    if request.method == "GET":
        return render_template("forgot_password.html")
    
    # POST
    identifier = request.form.get("identifier", "").strip()
    
    if not identifier:
        flash("Please enter your username or email address.", "error")
        return redirect("/forgot-password")
    
    # Try to identify if this is a user (by username/church name) or admin (by email)
    
    # CASE 1: Check if it's a user's church name (username)
    # CASE 1: Check if it's a user's church name (username)
    # Also handle "superadmin" special case — look in admins table
    if identifier.lower() == "superadmin":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admins WHERE username = 'superadmin'")
        superadmin = cursor.fetchone()
        conn.close()
        
        if superadmin and superadmin.get("email"):
            email = superadmin["email"]
            username = "superadmin"
            
            token = store_user_reset_token(username, email, user_type='admin')
            sent = send_forgot_password_email(email, username, token, is_admin=True)
            
            if sent:
                masked = mask_email(email)
                flash(f"Password reset link sent to {masked}. Please check your inbox and spam folder. Link expires in 24 hours.", "success")
                return redirect("/login")
            else:
                flash("Failed to send reset email. Please check SMTP configuration or contact support.", "error")
                return redirect("/forgot-password")
        else:
            flash("Superadmin account has no email configured. Please check your .env file or contact system support.", "error")
            return redirect("/forgot-password")
    
    # Normal user lookup by church name
    user = get_user_by_username(identifier)
    if user:
        # Found a user — get their secretary email
        email = user.get("secretary_email") or user.get("vice_secretary_email")
        username = user["username"]
        
        if not email:
            flash(f"No email address on file for '{username}'. Please contact your administrator.", "error")
            return redirect("/forgot-password")
        
        # Generate token and send
        token = store_user_reset_token(username, email, user_type='user')
        sent = send_forgot_password_email(email, username, token, is_admin=False)
        
        if sent:
            masked = mask_email(email)
            flash(f"Password reset link sent to {masked}. Please check your inbox and spam folder. Link expires in 24 hours.", "success")
            return redirect("/login")
        else:
            flash("Failed to send reset email. Please try again later or contact support.", "error")
            return redirect("/forgot-password")
    
    # CASE 2: Check if it's an admin/superadmin email
    # First validate it looks like an email
    valid_email, cleaned_email = validate_email(identifier)
    if valid_email:
        admin = get_admin_by_email(cleaned_email)
        if admin:
            username = admin["username"]
            email = admin["email"]
            
            # Generate token and send
            token = store_user_reset_token(username, email, user_type='admin')
            sent = send_forgot_password_email(email, username, token, is_admin=True)
            
            if sent:
                masked = mask_email(email)
                flash(f"Password reset link sent to {masked}. Please check your inbox and spam folder. Link expires in 24 hours.", "success")
                return redirect("/login")
            else:
                flash("Failed to send reset email. Please try again later or contact support.", "error")
                return redirect("/forgot-password")
    
    # CASE 3: User entered something that doesn't match anything
    # For security, we don't reveal whether the username/email exists
    flash("If an account exists with that information, a password reset link has been sent to the registered email.", "info")
    return redirect("/login")


@app.route("/admin-reset-password/<token>", methods=["GET", "POST"])
def admin_reset_password(token):
    """Allow admin/superadmin to reset password using forgot-password token."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        SELECT * FROM password_reset_tokens 
        WHERE token = ? AND used = 0 AND expires_at > ? AND user_type = 'admin'
    """, (token, now_str))
    
    token_record = cursor.fetchone()
    
    if not token_record:
        conn.close()
        return render_template("admin_reset_password.html", 
                               error="Invalid or expired reset link. Please request a new one.")
    
    username = token_record["username"]
    
    if request.method == "POST":
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        if not new_password:
            conn.close()
            return render_template("admin_reset_password.html",
                                   token=token,
                                   error="Password is required.")
        
        if len(new_password) < 6:
            conn.close()
            return render_template("admin_reset_password.html",
                                   token=token,
                                   error="Password must be at least 6 characters.")
        
        if new_password != confirm_password:
            conn.close()
            return render_template("admin_reset_password.html",
                                   token=token,
                                   error="Passwords do not match.")
        
        # Update admin password
        hashed_pw = generate_password_hash(new_password)
        cursor.execute("UPDATE admins SET password = ? WHERE username = ?", (hashed_pw, username))
        
        # Mark token as used
        cursor.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (token,))
        
        conn.commit()
        conn.close()
        
        # Audit log
        log_data_change(
            "ADMIN_FORGOT_PASSWORD_RESET",
            "admins",
            None,
            f"Admin '{username}' reset password via forgot-password link",
            new_values={"username": username, "action": "forgot_password_reset"}
        )
        
        flash("Password reset successfully! You can now log in with your new password.", "success")
        return redirect("/login")
    
    conn.close()
    return render_template("admin_reset_password.html", token=token, username=username)

#---------------------------------------------------------------------------------------------------------------------

@app.route("/resend-reset-link", methods=["POST"])
@admin_required
def resend_reset_link():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    
    if not username or not email:
        flash("Username and email required.", "error")
        return redirect("/manage-users")
    
    # Verify user exists
    user = get_user(username)
    if not user:
        flash("User not found.", "error")
        return redirect("/manage-users")
    
    # Invalidate old tokens
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE password_reset_tokens SET used = 1 WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    
    # Create new token and send
    token = store_reset_token(username, email)
    sent = send_password_reset_email(email, username, token)
    
    # AUDIT: Log reset link resend
    log_audit_event(
        "RESEND_RESET_LINK",
        f"Admin resent password reset link to {email} for user '{username}'",
        action_category="user_management"
    )
    
    if sent:
        flash(f"New reset link sent to {email} for user '{username}'. Expires in 24 hours.", "success")
    else:
        flash(f"Failed to send email to {email}. Please check SMTP configuration.", "error")
    
    return redirect("/manage-users")

@app.route("/manage-admins")
@superadmin_required
def manage_admins():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM admins WHERE role != 'superadmin' ORDER BY username")
    admins = cursor.fetchall()
    conn.close()
    return render_template("manage_admins.html", admins=admins)

@app.route("/manage-users")
@admin_required
def manage_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users ORDER BY username")
    users = cursor.fetchall()
    conn.close()
    return render_template("manage_users.html", users=users)

@app.route("/delete-admin/<username>", methods=["GET"])
@superadmin_required
def delete_admin(username):
    """Delete an admin account. Superadmin cannot be deleted."""
    if username == session.get("username"):
        flash("You cannot delete your own account.", "error")
        return redirect("/manage-admins")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify target exists and is not superadmin
    cursor.execute("SELECT role FROM admins WHERE username = ?", (username,))
    target = cursor.fetchone()
    
    if not target:
        conn.close()
        flash("Admin not found.", "error")
        return redirect("/manage-admins")
    
    target_role = target["role"] if "role" in target.keys() else target[0]
    
    if target_role == 'superadmin':
        conn.close()
        flash("Cannot delete superadmin accounts.", "error")
        return redirect("/manage-admins")
    
    # Delete related tokens first (foreign key constraint safety)
    cursor.execute("""
        DELETE FROM password_reset_tokens
        WHERE username = ? AND user_type = 'admin'
    """, (username,))
    
    # Delete admin
    cursor.execute("DELETE FROM admins WHERE username = ?", (username,))
    
    conn.commit()
    conn.close()
    
    # Audit log
    log_data_change("DELETE_ADMIN", "admins", None,
                    f"Superadmin deleted admin '{username}'",
                    old_values={"username": username, "role": target_role})
    
    flash(f"Admin '{username}' deleted successfully.", "success")
    return redirect("/manage-admins")





# =========================================
# ROUTE: ADMIN/SUPERADMIN UPDATE USER EMAIL
# =========================================

@app.route("/admin/update-user-email/<int:user_id>", methods=["POST"])
@admin_required
def update_user_email(user_id):
    new_email = request.form.get("new_email", "").strip()
    
    valid, cleaned_email = validate_email(new_email)
    if not valid:
        flash(f"Invalid email: {cleaned_email}", "error")
        return redirect("/manage-users")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch old email BEFORE updating
    cursor.execute("SELECT secretary_email FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    old_email = row["secretary_email"] if row else None
    
    cursor.execute("SELECT id FROM users WHERE (secretary_email = ? OR vice_secretary_email = ?) AND id != ?", 
                   (cleaned_email, cleaned_email, user_id))
    if cursor.fetchone():
        conn.close()
        flash("This email is already in use by another user.", "error")
        return redirect("/manage-users")
    
    cursor.execute("UPDATE users SET secretary_email = ? WHERE id = ?", (cleaned_email, user_id))
    conn.commit()
    conn.close()
    
    # AUDIT: Log email update
    log_data_change("UPDATE_USER_EMAIL", "users", user_id,
                    f"Admin updated user email from '{old_email}' to '{cleaned_email}'",
                    old_values={"secretary_email": old_email},
                    new_values={"secretary_email": cleaned_email})
    
    flash("User email updated successfully.", "success")
    return redirect("/manage-users")


# =========================================
# ROUTES: POS (PROOF OF SERVICE)
# =========================================





@app.route("/api/product-prices")
@login_required
def product_prices():
    products = get_products()
    data = {}
    for p in products:
        data[p["name"]] = {
            "price": float(p["price"]),
            "deduction": float(p["deduction"]),
            "full_price": float(p["price"]) + float(p["deduction"])
        }
    return jsonify(data)










# =========================================----------------------------
# ROUTES: POS FILES VIEWING
# =========================================------------------------------

@app.route("/my-pos-files")
@login_required
def my_pos_files():
    if session.get("role") != "user":
        return redirect("/login")
    organized_pos = get_user_pos_by_year_month(session["username"])
    return render_template("pos_files_organized.html",
                           organized_pos=organized_pos,
                           is_admin=False,
                           username=session["username"])

@app.route("/all-pos-files")
@admin_required
def all_pos_files():
    organized_by_user = get_all_pos_by_user()
    return render_template("pos_files_admin.html",
                           organized_by_user=organized_by_user,
                           username=session["username"])







@app.route("/view-pos/<int:pos_id>")
@login_required
def view_pos(pos_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pos_records WHERE id = ?", (pos_id,))
    record = cursor.fetchone()
    if not record:
        conn.close()
        abort(404)
    if session.get("role") == "user" and record["created_by"] != session["username"]:
        conn.close()
        abort(403)

    cursor.execute("SELECT * FROM pos_items WHERE pos_record_id = ?", (pos_id,))
    items = cursor.fetchall()

    cursor.execute("SELECT * FROM pos_cash_rows WHERE pos_record_id = ?", (pos_id,))
    cash_rows = cursor.fetchall()

    cursor.execute("SELECT * FROM pos_cancelled_receipts WHERE pos_record_id = ?", (pos_id,))
    cancelled_receipts = cursor.fetchall()

    # Get expenses for this POS
    cursor.execute("SELECT * FROM pos_expenses WHERE pos_record_id = ?", (pos_id,))
    pos_expenses = cursor.fetchall()

    # Get products for product info table
    products = get_products()

    # Build product type map from items (submitted types take priority)
    product_type_map = {}
    for item in items:
        product_type_map[item["product_name"]] = item["product_type"] or ""

    # Get creator's booklet types as fallback
    cursor.execute("SELECT id FROM users WHERE username = ?", (record["created_by"],))
    user_row = cursor.fetchone()
    creator_user_id = user_row["id"] if user_row else None
    
    # Build product type map from items (submitted types take priority)
    product_type_map = {}
    for item in items:
        pt = item["product_type"]
        # Only store if it's actually a non-empty value
        if pt and str(pt).strip():
            product_type_map[item["product_name"]] = pt
    
    # Get creator's booklet types as fallback
    cursor.execute("SELECT id FROM users WHERE username = ?", (record["created_by"],))
    user_row = cursor.fetchone()
    creator_user_id = user_row["id"] if user_row else None
    
    booklet_map = {}
    if creator_user_id:
        cursor.execute("""
            SELECT product_name, receipt_type, booklet_number
            FROM receipt_booklets 
            WHERE user_id = ? AND is_active = 1
            ORDER BY product_name, CAST(booklet_number AS INTEGER) ASC
        """, (creator_user_id,))
        for row in cursor.fetchall():
            if row["product_name"] not in booklet_map:
                booklet_map[row["product_name"]] = row["receipt_type"]
    
    # MERGE: items take priority, booklet_map as fallback for products with no items OR empty types
    for product in products:
        name = product["name"]
        if name not in product_type_map or not product_type_map.get(name):
            product_type_map[name] = booklet_map.get(name, "")

    # Aggregate cash rows into totals for display
    cash_totals = {
        "r200": 0, "r100": 0, "r50": 0, "r20": 0, "r10": 0, "coins": 0
    }
    for row in cash_rows:
        cash_totals["r200"] += (row["r200"] or 0)
        cash_totals["r100"] += (row["r100"] or 0)
        cash_totals["r50"] += (row["r50"] or 0)
        cash_totals["r20"] += (row["r20"] or 0)
        cash_totals["r10"] += (row["r10"] or 0)
        cash_totals["coins"] += (row["coins"] or 0)

    # Get uploads for this POS
    current_uploads = get_pos_uploads(pos_id)
    banking_upload = next((u for u in current_uploads if u["upload_type"] == "proof_of_banking"), None)
    receipts_upload = next((u for u in current_uploads if u["upload_type"] == "receipts"), None)

    conn.close()

    return render_template("view_pos.html", 
                           record=record, 
                           items=items,
                           cash_rows=cash_rows,
                           cash_totals=cash_totals,
                           cancelled_receipts=cancelled_receipts,
                           pos_expenses=pos_expenses,
                           products=products,
                           product_type_map=product_type_map,
                           booklet_map=booklet_map,
                           banking_upload=banking_upload,
                           receipts_upload=receipts_upload)



@app.route("/view-pos-html/<int:pos_id>")
@login_required
def view_pos_html(pos_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pos_records WHERE id = ?", (pos_id,))
    record = cursor.fetchone()
    conn.close()
    if not record:
        abort(404)
    if session.get("role") == "user" and record["created_by"] != session["username"]:
        abort(403)
    html_path = record.get("html_file_path")
    if not html_path or not os.path.exists(html_path):
        flash("HTML file not found.", "error")
        return redirect("/my-pos-files")
    return send_file(html_path)




@app.route("/download-pos/<int:pos_id>")
@login_required
def download_pos(pos_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pos_records WHERE id = ?", (pos_id,))
    record = cursor.fetchone()
    conn.close()
    
    if not record:
        abort(404)
    if session.get("role") == "user" and record["created_by"] != session["username"]:
        abort(403)
    
    file_path = record.get("html_file_path") or record.get("file_path")
    if not file_path or not os.path.exists(file_path):
        flash("File not found on server.", "error")
        return redirect("/my-pos-files")
    
    # Read the original plain HTML content
    with open(file_path, 'r', encoding='utf-8') as f:
        original_html = f.read()
    
    # Build self-contained styled version
    styled_html = build_styled_download_html(original_html)
    
    # Write to temporary file for download
    temp_dir = tempfile.gettempdir()
    download_filename = os.path.basename(file_path)
    temp_path = os.path.join(temp_dir, download_filename)
    
    with open(temp_path, 'w', encoding='utf-8') as f:
        f.write(styled_html)
        
    # AUDIT: Log POS download
    log_pos_action("DOWNLOAD_POS", pos_id,
                   f"User '{session.get('username')}' downloaded POS #{record.get('pos_number')}",
                   amount=record.get('total_banking'))
    
    return send_file(temp_path, as_attachment=True, download_name=download_filename)


def build_styled_download_html(html_content):
    """
    Wraps a plain POS HTML file with full KGANYA styling.
    Embeds the background image as base64 so it works offline.
    """
    
    # Read the background image and convert to base64
    static_folder = app.static_folder or os.path.join(os.path.dirname(__file__), 'static')
    image_path = os.path.join(static_folder, 'Picture1.jpg')
    
    image_base64 = ""
    if os.path.exists(image_path):
        with open(image_path, 'rb') as img_file:
            image_base64 = base64.b64encode(img_file.read()).decode('utf-8')
    
    bg_image_css = f'url("data:image/jpeg;base64,{image_base64}")' if image_base64 else 'none'
    
    # Extract body content from the original HTML
    body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if body_match:
        body_content = body_match.group(1).strip()
    else:
        # Fallback: strip html/head/body tags
        body_content = re.sub(r'<!DOCTYPE.*?>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
        body_content = re.sub(r'<html[^>]*>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
        body_content = re.sub(r'</html>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
        body_content = re.sub(r'<head>.*?</head>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
        body_content = re.sub(r'<body[^>]*>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
        body_content = re.sub(r'</body>', '', body_content, flags=re.DOTALL | re.IGNORECASE)
        body_content = body_content.strip()
    
    # Build self-contained HTML with full styling
    styled_html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>KGANYA Digital Proof Of Service</title>
    <style>
    html {{
        min-height: 100%;
    }}
    body {{
        font-family: "Century Gothic", sans-serif;
        margin: 0;
        padding: 20px;
        background-image:
            linear-gradient(
                rgba(255,255,255,0.35),
                rgba(255,255,255,0.35)
            ),
            {bg_image_css};
        background-size: 100% auto;
        background-position: center top;
        background-repeat: repeat-y;
        background-attachment: scroll;
        min-height: 100vh;
    }}
    .container {{
        max-width: 1300px;
        margin: auto;
        background: rgba(255,255,255,0.18);
        backdrop-filter: blur(14px);
        -webkit-backdrop-filter: blur(14px);
        padding: 25px;
        border-radius: 18px;
        border: 1px solid rgba(255,255,255,0.35);
        box-shadow:
            0 8px 30px rgba(0,0,0,0.25),
            inset 0 1px 0 rgba(255,255,255,0.25);
    }}
    h1, h2, h3 {{
        text-align: center;
        color: lightgoldenrodyellow;
        font-weight: bold;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        margin-top: 20px;
    }}
    table, th, td {{
        border: 1px solid rgba(255,255,255,0.3);
    }}
    th {{
        background: rgba(0,0,0,0.45);
        padding: 10px;
        font-weight: bold;
        color: lightgoldenrodyellow;
    }}
    td {{
        padding: 8px;
        text-align: center;
        background: rgba(255,255,255,0.15);
        color: black;
    }}
    .section-title {{
        background: rgba(0,0,0,0.45);
        color: white;
        padding: 10px;
        margin-top: 30px;
        border-radius: 5px;
        font-weight: bold;
    }}
    .summary {{
        margin-top: 20px;
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 20px;
    }}
    .card {{
        background: rgba(255,255,255,0.2);
        backdrop-filter: blur(6px);
        padding: 15px;
        border-radius: 8px;
        border: 1px solid rgba(255,255,255,0.3);
    }}
    button {{
        background-color: #1e3a5f;
        color: white;
        border: none;
        padding: 10px 20px;
        margin-top: 20px;
        border-radius: 5px;
        cursor: pointer;
    }}
    button:hover {{
        background-color: #162b46;
    }}
    .delete-btn {{
        background-color: #dc3545;
        margin-top: 0;
    }}
    .delete-btn:hover {{
        background-color: #c82333;
    }}
    .status-balanced {{
        color: green;
        font-weight: bold;
    }}
    .status-discrepancy {{
        color: red;
        font-weight: bold;
    }}
    .final-remarks {{
        font-size: 42px;
        font-weight: bold;
        text-align: center;
        padding: 20px;
        letter-spacing: 8px;
    }}
    .footer {{
        text-align: center;
        margin-top: 30px;
        padding: 20px;
        color: lightgoldenrodyellow;
        border-top: 1px solid rgba(255,255,255,0.3);
    }}
    input {{
        width: 90%;
        padding: 5px;
    }}
    select {{
        width: 90%;
        padding: 5px;
    }}
    @media (max-width: 768px) {{
        .summary {{
            grid-template-columns: 1fr;
        }}
    }}
    </style>
</head>
<body>
    <div class="container">
        {body_content}
    </div>
</body>
</html>'''
    
    return styled_html



@app.route("/view-pos-file/<path:filename>")
@login_required
def view_pos_file(filename):
    safe_filename = os.path.basename(filename)
    full_path = os.path.join(POS_FOLDER, safe_filename)
    real_path = os.path.realpath(full_path)
    real_base = os.path.realpath(POS_FOLDER)
    if not real_path.startswith(real_base):
        abort(403)
    if not os.path.exists(real_path):
        abort(404)
    if real_path.endswith('.html'):
        return send_file(real_path)
    with open(real_path, "r", encoding="utf-8") as f:
        content = f.read()
    return f"<pre style='white-space:pre-wrap;word-wrap:break-word;'>{html_module.escape(content)}</pre>"

# =========================================
# API ROUTES
# =========================================

@app.route("/api/my-pos-summary")
@login_required
def api_my_pos_summary():
    if session.get("role") != "user":
        return jsonify({"error": "Unauthorized"}), 403
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT year, month, month_name, COUNT(*) as count,
               SUM(total_banking) as total_banking,
               SUM(total_stickers) as total_stickers
        FROM pos_records
        WHERE created_by = ?
        GROUP BY year, month
        ORDER BY year DESC, month DESC
    """, (session["username"],))
    summary = [{
        "year": row["year"],
        "month": row["month"],
        "month_name": row["month_name"],
        "count": row["count"],
        "total_banking": float(row["total_banking"] or 0),
        "total_stickers": row["total_stickers"] or 0
    } for row in cursor.fetchall()]
    conn.close()
    return jsonify(summary)



# =========================================
# AUDIT TRAIL ROUTES (Superadmin only)
# =========================================

@app.route("/superadmin/audit-log")
@superadmin_required
def audit_log():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    action_filter = request.args.get('action', '')
    category_filter = request.args.get('category', '')
    username_filter = request.args.get('username', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    
    query = "SELECT * FROM audit_log WHERE 1=1"
    params = []
    
    if action_filter:
        query += " AND action = ?"
        params.append(action_filter)
    if category_filter:
        query += " AND action_category = ?"
        params.append(category_filter)
    if username_filter:
        query += " AND (username LIKE ? OR username_entered LIKE ?)"
        params.append(f"%{username_filter}%")
        params.append(f"%{username_filter}%")
    if date_from:
        query += " AND date(timestamp) >= ?"
        params.append(date_from)
    if date_to:
        query += " AND date(timestamp) <= ?"
        params.append(date_to)
    
    query += " ORDER BY id DESC LIMIT 1000"
    
    cursor.execute(query, params)
    logs = [dict(row) for row in cursor.fetchall()]
    
    for log in logs:
        if log.get('device_info'):
            try:
                log['device_info'] = json.loads(log['device_info'])
            except:
                log['device_info'] = None
    
    cursor.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")
    actions = [row['action'] for row in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT action_category FROM audit_log WHERE action_category IS NOT NULL ORDER BY action_category")
    categories = [row['action_category'] for row in cursor.fetchall()]
    
    cursor.execute("SELECT COUNT(*) as count FROM audit_log")
    total_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM audit_log WHERE date(timestamp) = date('now')")
    today_count = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM audit_log WHERE action = 'LOGIN_FAILED'")
    failed_count = cursor.fetchone()['count']
    
    conn.close()
    
    return render_template("audit_log.html",
                           logs=logs,
                           actions=actions,
                           categories=categories,
                           total_count=total_count,
                           today_count=today_count,
                           failed_count=failed_count,
                           filters={
                               'action': action_filter,
                               'category': category_filter,
                               'username': username_filter,
                               'date_from': date_from,
                               'date_to': date_to
                           })

@app.route("/superadmin/audit-log/<int:log_id>")
@superadmin_required
def audit_detail(log_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM audit_log WHERE id = ?", (log_id,))
    log = cursor.fetchone()
    
    if not log:
        conn.close()
        abort(404)
    
    log = dict(log)
    
    for field in ['device_info', 'old_values', 'new_values']:
        if log.get(field):
            try:
                log[field] = json.loads(log[field])
            except:
                pass
    
    cursor.execute("SELECT record_hash FROM audit_log WHERE id < ? ORDER BY id DESC LIMIT 1", (log_id,))
    prev = cursor.fetchone()
    expected_prev_hash = prev['record_hash'] if prev else "0"
    log['tamper_alert'] = (log.get('previous_record_hash') != expected_prev_hash)
    
    user = None
    if log.get('username'):
        cursor.execute("SELECT * FROM users WHERE username = ?", (log['username'],))
        user = cursor.fetchone()
    
    conn.close()
    return render_template("audit_detail.html", log=log, user=user)

@app.route("/superadmin/audit-login-attempts")
@superadmin_required
def audit_login_attempts():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    show_failed_only = request.args.get('failed_only', '0') == '1'
    
    query = "SELECT * FROM audit_log WHERE action_category = 'authentication'"
    if show_failed_only:
        query += " AND login_success = 0"
    query += " ORDER BY id DESC LIMIT 500"
    
    cursor.execute(query)
    attempts = [dict(row) for row in cursor.fetchall()]
    
    for attempt in attempts:
        if attempt.get('device_info'):
            try:
                attempt['device_info'] = json.loads(attempt['device_info'])
            except:
                pass
    
    cursor.execute("SELECT COUNT(*) as count FROM audit_log WHERE action_category = 'authentication'")
    total_attempts = cursor.fetchone()['count']
    
    cursor.execute("SELECT COUNT(*) as count FROM audit_log WHERE action_category = 'authentication' AND login_success = 0")
    failed_attempts = cursor.fetchone()['count']
    
    cursor.execute("""
        SELECT username_entered, COUNT(*) as count 
        FROM audit_log 
        WHERE action_category = 'authentication' AND login_success = 0 AND username_entered IS NOT NULL
        GROUP BY username_entered 
        ORDER BY count DESC 
        LIMIT 10
    """)
    top_failed_usernames = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template("audit_login_attempts.html",
                           attempts=attempts,
                           total_attempts=total_attempts,
                           failed_attempts=failed_attempts,
                           top_failed_usernames=top_failed_usernames,
                           show_failed_only=show_failed_only)

@app.route("/superadmin/audit-statistics")
@superadmin_required
def audit_statistics():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date(timestamp) as date, COUNT(*) as count
        FROM audit_log
        WHERE date(timestamp) >= date('now', '-30 days')
        GROUP BY date(timestamp)
        ORDER BY date(timestamp)
    """)
    daily_activity = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT action_category, COUNT(*) as count
        FROM audit_log
        WHERE action_category IS NOT NULL
        GROUP BY action_category
        ORDER BY count DESC
    """)
    category_breakdown = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT date(timestamp) as date, COUNT(*) as count
        FROM audit_log
        WHERE action = 'LOGIN_FAILED' AND date(timestamp) >= date('now', '-30 days')
        GROUP BY date(timestamp)
        ORDER BY date(timestamp)
    """)
    failed_login_trends = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT username, COUNT(*) as count
        FROM audit_log
        WHERE username IS NOT NULL
        GROUP BY username
        ORDER BY count DESC
        LIMIT 10
    """)
    active_users = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT location, COUNT(*) as count
        FROM audit_log
        WHERE location IS NOT NULL AND location != 'Unknown'
        GROUP BY location
        ORDER BY count DESC
        LIMIT 10
    """)
    location_distribution = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template("audit_statistics.html",
                           daily_activity=daily_activity,
                           category_breakdown=category_breakdown,
                           failed_login_trends=failed_login_trends,
                           active_users=active_users,
                           location_distribution=location_distribution)

@app.route("/superadmin/audit-user-activity/<username>")
@superadmin_required
def audit_user_activity(username):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    
    cursor.execute("""
        SELECT * FROM audit_log 
        WHERE username = ? OR username_entered = ?
        ORDER BY id DESC
        LIMIT 500
    """, (username, username))
    logs = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("""
        SELECT action, COUNT(*) as count
        FROM audit_log
        WHERE username = ? OR username_entered = ?
        GROUP BY action
        ORDER BY count DESC
    """, (username, username))
    action_summary = [dict(row) for row in cursor.fetchall()]
    
    conn.close()
    
    return render_template("audit_user_activity.html",
                           username=username,
                           user=user,
                           logs=logs,
                           action_summary=action_summary)

@app.route("/api/audit/verify-integrity", methods=["POST"])
@superadmin_required
def verify_audit_integrity():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, previous_record_hash, record_hash, timestamp, action FROM audit_log ORDER BY id")
    records = cursor.fetchall()
    conn.close()
    
    violations = []
    prev_hash = "0"
    
    for rec in records:
        if rec['previous_record_hash'] != prev_hash:
            violations.append({
                'id': rec['id'],
                'action': rec['action'],
                'expected_prev': prev_hash,
                'actual_prev': rec['previous_record_hash']
            })
        prev_hash = rec['record_hash']
    
    return jsonify({
        'integrity_passed': len(violations) == 0,
        'total_records': len(records),
        'violations_found': len(violations),
        'violations': violations
    })

@app.route("/api/audit/export")
@superadmin_required
def export_audit_csv():
    import csv
    import io
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audit_log ORDER BY id")
    records = cursor.fetchall()
    conn.close()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    if records:
        headers = list(records[0].keys())
        writer.writerow(headers)
        for rec in records:
            writer.writerow([rec.get(h, '') for h in headers])
    
    output.seek(0)
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'audit_log_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    )

# =========================================
# ERROR HANDLERS
# =========================================

@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="Access denied."), 403

@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500, message="Internal server error."), 500





@app.route("/upload-pos-files/<int:pos_id>", methods=["GET", "POST"])
@login_required
def upload_pos_files(pos_id):
    if session.get("role") not in ["user"]:
        flash("Only users can upload files.", "error")
        return redirect("/")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM pos_records WHERE id = ?", (pos_id,))
    pos_record = cursor.fetchone()
    conn.close()

    if not pos_record:
        flash("POS record not found.", "error")
        return redirect("/my-pos-files")

    if pos_record["created_by"] != session["username"]:
        flash("You can only upload files for your own POS records.", "error")
        return redirect("/my-pos-files")

    if request.method == "POST":
        upload_type = request.form.get("upload_type", "").strip()

        if upload_type not in ["proof_of_banking", "receipts"]:
            flash("Invalid upload type.", "error")
            return redirect(f"/upload-pos-files/{pos_id}")

        if "file" not in request.files:
            flash("No file selected.", "error")
            return redirect(f"/upload-pos-files/{pos_id}")

        file = request.files["file"]

        if file.filename == "":
            flash("No file selected.", "error")
            return redirect(f"/upload-pos-files/{pos_id}")

        if not allowed_file(file.filename):
            flash(f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}", "error")
            return redirect(f"/upload-pos-files/{pos_id}")

        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)

        if file_size > MAX_UPLOAD_SIZE:
            flash(f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024*1024)}MB.", "error")
            return redirect(f"/upload-pos-files/{pos_id}")

        original_filename = secure_filename(file.filename)
        stored_filename = generate_unique_filename(original_filename)

        user_folder = os.path.join(UPLOAD_FOLDER, upload_type, session["username"])
        os.makedirs(user_folder, exist_ok=True)

        file_path = os.path.join(user_folder, stored_filename)
        file.save(file_path)

        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id FROM pos_uploads 
            WHERE pos_record_id = ? AND upload_type = ? AND is_replaced = 0
        """, (pos_id, upload_type))
        existing = cursor.fetchone()
        existing_id = existing["id"] if existing else None

        cursor.execute("""
            INSERT INTO pos_uploads (
                pos_record_id, upload_type, original_filename, stored_filename,
                file_path, file_size, mime_type, uploaded_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pos_id, upload_type, original_filename, stored_filename,
            file_path, file_size, file.content_type or "application/octet-stream",
            session["username"]
        ))

        new_upload_id = cursor.lastrowid

        if existing_id:
            cursor.execute("""
                UPDATE pos_uploads 
                SET is_replaced = 1, replaced_at = CURRENT_TIMESTAMP, replaced_by_upload_id = ?
                WHERE id = ?
            """, (new_upload_id, existing_id))

        conn.commit()
        
        # AUDIT: Log file upload
        log_pos_action("UPLOAD_FILE", pos_id,
                       f"User '{session['username']}' uploaded {upload_type} file '{original_filename}'")
        
        conn.close()

        flash(f"{upload_type.replace('_', ' ').title()} uploaded successfully.", "success")
        return redirect(f"/view-pos/{pos_id}")

    current_uploads = get_pos_uploads(pos_id)
    proof_of_banking = next((u for u in current_uploads if u["upload_type"] == "proof_of_banking"), None)
    receipts = next((u for u in current_uploads if u["upload_type"] == "receipts"), None)

    return render_template("upload_pos_files.html",
                           pos_id=pos_id,
                           pos_number=pos_record["pos_number"],
                           proof_of_banking=proof_of_banking,
                           receipts=receipts)

@app.route("/uploads/<path:filename>")
@login_required
def serve_upload(filename):
    safe_filename = secure_filename(os.path.basename(filename))

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pos_uploads WHERE stored_filename = ? AND is_replaced = 0", (safe_filename,))
    upload = cursor.fetchone()

    if not upload:
        conn.close()
        abort(404)

    if session.get("role") == "user":
        cursor.execute("SELECT created_by FROM pos_records WHERE id = ?", (upload["pos_record_id"],))
        pos = cursor.fetchone()
        conn.close()
        if not pos or pos["created_by"] != session["username"]:
            abort(403)
    else:
        conn.close()

    file_path = upload["file_path"]
    if not os.path.exists(file_path):
        abort(404)

    return send_file(file_path, 
                     download_name=upload["original_filename"],
                     mimetype=upload["mime_type"] or "application/octet-stream")

@app.route("/upload-history/<int:pos_id>")
@login_required
def upload_history(pos_id):
    if session.get("role") not in ["user", "admin", "superadmin"]:
        abort(403)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pos_records WHERE id = ?", (pos_id,))
    pos_record = cursor.fetchone()
    conn.close()

    if not pos_record:
        abort(404)

    if session.get("role") == "user" and pos_record["created_by"] != session["username"]:
        abort(403)

    history = get_upload_history(pos_id)

    return render_template("upload_history.html",
                           pos_record=pos_record,
                           history=history,
                           is_admin=session.get("role") in ["admin", "superadmin"])

@app.route("/admin/uploads")
@admin_required
def admin_view_uploads():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pu.*, pr.pos_number, pr.created_by, pr.church_name, pr.created_at as pos_created_at
        FROM pos_uploads pu
        JOIN pos_records pr ON pu.pos_record_id = pr.id
        WHERE pu.is_replaced = 0
        ORDER BY pu.uploaded_at DESC
    """)
    uploads = [dict(row) for row in cursor.fetchall()]

    user_uploads = {}
    for upload in uploads:
        username = upload["created_by"]
        if username not in user_uploads:
            user_uploads[username] = []
        user_uploads[username].append(upload)

    conn.close()
    return render_template("admin_uploads.html", uploads=uploads, user_uploads=user_uploads)

@app.route("/admin/pos-uploads/<int:pos_id>")
@admin_required
def admin_pos_uploads(pos_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pos_records WHERE id = ?", (pos_id,))
    pos_record = cursor.fetchone()
    conn.close()

    if not pos_record:
        abort(404)

    current_uploads = get_pos_uploads(pos_id)
    history = get_upload_history(pos_id)

    return render_template("admin_pos_uploads.html",
                           pos_record=pos_record,
                           current_uploads=current_uploads,
                           history=history)




#=============================================================================
# LAST ADDED ROUTES, CAN BE REMOVED OR REFINED OR REMOVED IF MODEL SUGGESTS SO
#==============================================================================

from datetime import timedelta

@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    """Comprehensive admin dashboard showing POS submissions, uploads, and tracking."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # =========================================
    # GET ALL POS RECORDS WITH UPLOAD STATUS
    # =========================================
    cursor.execute("""
        SELECT 
            pr.*,
            u.church_branch_name,
            CASE WHEN pb.id IS NOT NULL THEN 1 ELSE 0 END as has_banking,
            CASE WHEN prc.id IS NOT NULL THEN 1 ELSE 0 END as has_receipts,
            pb.original_filename as proof_of_banking_filename,
            pb.stored_filename as proof_of_banking_file,
            prc.original_filename as receipts_filename,
            prc.stored_filename as receipts_file
        FROM pos_records pr
        LEFT JOIN users u ON pr.created_by = u.username
        LEFT JOIN pos_uploads pb ON pr.id = pb.pos_record_id AND pb.upload_type = 'proof_of_banking' AND pb.is_replaced = 0
        LEFT JOIN pos_uploads prc ON pr.id = prc.pos_record_id AND prc.upload_type = 'receipts' AND prc.is_replaced = 0
        ORDER BY pr.created_at DESC
    """)
    all_pos = [dict(row) for row in cursor.fetchall()]
    
    # =========================================
    # GROUP SUBMISSIONS BY YEAR-MONTH-WEEK
    # =========================================
    def parse_datetime(dt_str):
        """Safely parse datetime string from SQLite."""
        if not dt_str:
            return None
        formats = ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']
        for fmt in formats:
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue
        return None
    
    grouped_submissions = {}
    for pos in all_pos:
        dt = parse_datetime(pos.get('created_at'))
        if not dt:
            continue
        
        year = str(dt.year)
        month_name = dt.strftime('%B')
        week = (dt.day - 1) // 7 + 1
        
        pos['year'] = year
        pos['month_name'] = month_name
        pos['user_name'] = pos.get('created_by', 'Unknown')
        pos['church_branch_name'] = pos.get('church_branch_name') or pos.get('church_name') or '—'
        
        if year not in grouped_submissions:
            grouped_submissions[year] = {}
        if month_name not in grouped_submissions[year]:
            grouped_submissions[year][month_name] = {}
        if week not in grouped_submissions[year][month_name]:
            grouped_submissions[year][month_name][week] = []
        grouped_submissions[year][month_name][week].append(pos)
    
    # =========================================
    # CATEGORIZE RECORDS
    # =========================================
    outstanding_submissions = []
    successful_submissions = []
    outstanding_uploads = []
    successful_uploads = []
    
    today = datetime.now()
    
    for pos in all_pos:
        has_banking = pos.get('has_banking', 0) == 1
        has_receipts = pos.get('has_receipts', 0) == 1
        
        dt = parse_datetime(pos.get('created_at')) or today
        days_since = (today - dt).days
        pos['days_since_creation'] = days_since
        
        # Calculate due date (next Sunday)
        days_until_sunday = (6 - dt.weekday()) % 7
        if days_until_sunday == 0:
            days_until_sunday = 7
        due_date = dt + timedelta(days=days_until_sunday)
        pos['due_date'] = due_date.strftime('%Y-%m-%d')
        pos['days_overdue'] = max(0, (today - due_date).days)
        pos['days_until_due'] = max(0, days_until_sunday - (today - dt).days)
        
        # Categorize
        successful_submissions.append(pos)
        
        if not has_banking and not has_receipts:
            outstanding_submissions.append(pos)
        
        if not has_banking or not has_receipts:
            outstanding_uploads.append(pos)
        
        if has_banking and has_receipts:
            successful_uploads.append(pos)
    
    # =========================================
    # GET USERS AND YEARS FOR FILTERS
    # =========================================
    cursor.execute("SELECT username, church_branch_name FROM users ORDER BY username")
    all_users = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT DISTINCT year FROM pos_records ORDER BY year DESC")
    all_years = [str(row['year']) for row in cursor.fetchall()]
    
    # Count pending skips for navbar badge
    cursor.execute("SELECT COUNT(*) as count FROM skipped_submissions WHERE status = 'pending'")
    result = cursor.fetchone()
    pending_skips_count = result['count'] if result else 0
    
    conn.close()
    
    return render_template("admin_dashboard.html",
                           pending_skips_count=pending_skips_count,
                           grouped_submissions=grouped_submissions,
                           outstanding_submissions=outstanding_submissions,
                           successful_submissions=successful_submissions,
                           outstanding_uploads=outstanding_uploads,
                           successful_uploads=successful_uploads,
                           outstanding_submissions_count=len(outstanding_submissions),
                           successful_submissions_count=len(successful_submissions),
                           outstanding_uploads_count=len(outstanding_uploads),
                           successful_uploads_count=len(successful_uploads),
                           all_users=all_users,
                           all_years=all_years)




# =========================================
# SKIPPED SUBMISSIONS - PYTHON ROUTES
# Add all of this to your app.py
# =========================================



# =========================================
# HELPER FUNCTIONS
# =========================================

def get_last_sunday():
    """Get the most recent Sunday's date."""
    today = datetime.now().date()
    days_since_sunday = (today.weekday() + 1) % 7
    last_sunday = today - timedelta(days=days_since_sunday)
    return last_sunday

def get_expected_sundays(username):
    """Get all Sundays where user was expected to submit but didn't."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get user's creation date from users table
    cursor.execute("SELECT created_at FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    
    if not result or not result['created_at']:
        conn.close()
        return []
    
    try:
        first_date = datetime.strptime(result['created_at'], '%Y-%m-%d %H:%M:%S').date()
    except (ValueError, TypeError):
        try:
            first_date = datetime.strptime(result['created_at'], '%Y-%m-%d %H:%M').date()
        except (ValueError, TypeError):
            try:
                first_date = datetime.strptime(result['created_at'], '%Y-%m-%d').date()
            except (ValueError, TypeError):
                conn.close()
                return []
    
    last_sunday = get_last_sunday()
    sundays = []
    current = first_date
    
    # Move to first Sunday on or after creation date
    while current.weekday() != 6:
        current += timedelta(days=1)
    
    while current <= last_sunday:
        sundays.append(current)
        current += timedelta(days=7)
    
    missed = []
    for sunday in sundays:
        sunday_str = sunday.strftime('%Y-%m-%d')
        grace_end = sunday + timedelta(days=3)
        cursor.execute("""
            SELECT COUNT(*) as count FROM pos_records 
            WHERE created_by = ? AND date(created_at) BETWEEN ? AND ?
        """, (username, sunday_str, grace_end.strftime('%Y-%m-%d')))
        has_submission = cursor.fetchone()['count'] > 0
        
        if not has_submission:
            cursor.execute("""
                SELECT * FROM skipped_submissions 
                WHERE username = ? AND expected_sunday = ?
            """, (username, sunday_str))
            existing = cursor.fetchone()
            
            missed.append({
                'sunday': sunday,
                'sunday_str': sunday_str,
                'has_reason': existing is not None,
                'status': existing['status'] if existing else None,
                'reason': existing['reason'] if existing else None,
                'id': existing['id'] if existing else None
            })
    
    conn.close()
    return missed

def has_unresolved_skips(username):
    """Check if user has skipped submissions that need reasons or approval."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM skipped_submissions WHERE username = ? AND (reason IS NULL OR reason = '') AND status = 'pending'", (username,))
    no_reason = cursor.fetchone()['count'] > 0

    cursor.execute("SELECT COUNT(*) as count FROM skipped_submissions WHERE username = ? AND status = 'pending' AND reason IS NOT NULL AND reason != ''", (username,))
    pending_approval = cursor.fetchone()['count'] > 0

    conn.close()
    return no_reason or pending_approval

def send_skip_notification(username, church_branch, expected_sunday):
    """Send email notification to secretary and vice-secretary."""

    print("=== send_skip_notification called ===")
    print("username =", username)
    print("church_branch =", church_branch)
    print("expected_sunday =", expected_sunday)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT secretary_email, vice_secretary_email, church_branch_name
        FROM users
        WHERE username = ?
    """, (username,))

    user = cursor.fetchone()

    if not user:
        print("USER NOT FOUND")
        conn.close()
        return False

    conn.close()

    secretary_email = user["secretary_email"]
    vice_email = user["vice_secretary_email"]
    branch = user["church_branch_name"] or church_branch or "Unknown"

    print("Secretary email:", secretary_email)
    print("Vice-secretary email:", vice_email)

    subject = f"KGANYA: Missed POS Submission - {username} ({branch})"

    body = f"""
Dear Secretary,

This is to notify you that {username} from {branch} has missed the POS submission
for Sunday, {expected_sunday}.

A reason for the missed submission is required before the user can submit their next POS.

Please follow up with the user or check the system for updates.

Regards,
KGANYA Digital Proof Of Service System
"""

    email_sent = False

    # Send to secretary
    if secretary_email:
        try:
            msg = Message(
                subject=subject,
                sender=SMTP_USERNAME,
                recipients=[secretary_email],
                body=body
            )

            if safe_send_mail(msg):
                print(f"✓ Secretary notification sent to {secretary_email}")
                email_sent = True
            else:
                print(f"✗ Failed to send secretary notification to {secretary_email}")

        except Exception as e:
            print(f"Failed to send email to secretary: {e}")

    # Send to vice-secretary
    if vice_email:
        try:
            msg = Message(
                subject=subject,
                sender=SMTP_USERNAME,
                recipients=[vice_email],
                body=body
            )

            if safe_send_mail(msg):
                print(f"✓ Vice-secretary notification sent to {vice_email}")
                email_sent = True
            else:
                print(f"✗ Failed to send vice-secretary notification to {vice_email}")

        except Exception as e:
            print(f"Failed to send email to vice-secretary: {e}")

    if not email_sent:
        print(
            f"WARNING: No skip notification emails were sent for "
            f"{username} ({branch})"
        )

    return email_sent


# =========================================
# FLASK ROUTES - Add to app.py
# =========================================





@app.route("/admin/reject-skip/<int:skip_id>", methods=["POST"])
@admin_required
def reject_skip(skip_id):
    """Reject a skipped submission reason."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE skipped_submissions 
        SET status = 'rejected', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (session['username'], skip_id))

    conn.commit()
    conn.close()

    flash("Skip reason rejected. User must provide a new reason.", "error")
    return redirect("/admin/skipped-submissions")

@app.route("/user/skipped-submissions", methods=["GET", "POST"])
@login_required
def user_skipped_submissions():
    """User view of their own skipped submissions."""
    username = session['username']

    conn = get_db_connection()
    cursor = conn.cursor()

    # Detect new missed Sundays and auto-create records
    missed = get_expected_sundays(username)

    for m in missed:
        if not m['has_reason']:
            cursor.execute("""
                INSERT INTO skipped_submissions (username, church_branch_name, expected_sunday)
                VALUES (?, ?, ?)
            """, (username, session.get('church_branch_name'), m['sunday_str']))
            send_skip_notification(username, session.get('church_branch_name'), m['sunday_str'])

    conn.commit()

    # Fetch fresh list after inserts
    cursor.execute("""SELECT * FROM skipped_submissions WHERE username = ? ORDER BY expected_sunday DESC""", (username,))
    skipped = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template("skipped_submissions.html", skipped=skipped)


def generate_temp_password(length=12):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))



def send_admin_credentials_email(email, username, reset_token):
    """
    Send password reset link to newly created admin.
    Returns True if email sent successfully, False otherwise.
    """
    
    
    if not SMTP_USERNAME or not SMTP_PASSWORD:
        print("❌ ERROR: SMTP credentials not configured in .env")
        return False
    
    try:
        #reset_url = url_for('reset_password', token=reset_token, _external=True)
        reset_url = url_for('admin_reset_password', token=reset_token, _external=True)
        
        subject = "KGANYA - Your Admin Account & Password Setup"
        
        body_html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                <h2 style="color: #1e3a5f;">Welcome to KGANYA, {username}!</h2>
                
                <p>Your admin account has been created on the <strong>KGANYA Digital Proof of Service</strong> system.</p>
                
                <div style="background: #f0f7f0; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <p><strong>Username:</strong> {username}</p>
                    <p><strong>Temporary Password:</strong> Verified via OTP</p>
                </div>
                
                <p>To set your permanent password, click the button below:</p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" 
                       style="background: #1e3a5f; color: white; padding: 12px 30px; 
                              text-decoration: none; border-radius: 5px; display: inline-block;">
                        Set My Password
                    </a>
                </div>
                
                <p style="color: #666; font-size: 13px;">
                    Or copy this link: <a href="{reset_url}">{reset_url}</a>
                </p>
                
                <p style="color: #c0392b; font-weight: bold;">
                    This link expires in 24 hours.
                </p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                
                <p style="color: #666; font-size: 12px;">
                    If you did not request this account, please contact the superadmin immediately.
                </p>
                
                <p style="color: #666; font-size: 12px;">Kganya Financial Service Providers | Lighting The Way Through Service</p>
            </div>
        </body>
        </html>
        """
        
        from flask_mail import Message
        msg = Message(
            subject=subject,
            sender=SMTP_USERNAME,
            recipients=[email],
            html=body_html
        )
        
        
        #mail.send(msg)
        #print(f"✅ SUCCESS: Credentials email sent to {email}")
        #return True
        
        if not safe_send_mail(msg):
            return False
        
    except Exception as e:
        print(f"❌ FAILED: Credentials email send failed: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False



def cleanup_expired_verifications():
    """Delete only admin email verifications that have actually expired."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute("""
        DELETE FROM admin_email_verifications 
        WHERE expires_at < ?
    """, (now,))
    conn.commit()
    conn.close()




# =========================================
# STEP 5: Add password reset route
# =========================================

@app.route("/create-admin", methods=["GET", "POST"])
@superadmin_required
def create_admin_route():
    cleanup_expired_verifications()
    
    if request.method == "GET":
        session.pop("admin_verify_email", None)
        session.pop("admin_verify_username", None)
        session.pop("admin_verify_otp", None)
        return render_template("create_admin.html", step="enter_details")
    
    step = request.form.get("step", "enter_details")
    
    # ─── STEP 1: Validate username/email, send OTP ───
    if step == "enter_details":
        username = request.form.get("new_admin_username", "").strip()
        email = request.form.get("new_admin_email", "").strip()
        
        valid, msg = validate_username(username)
        if not valid:
            return render_template("create_admin.html", step="enter_details", error=msg)
        
        valid_email, cleaned_email = validate_email(email)
        if not valid_email:
            return render_template("create_admin.html", step="enter_details", 
                                   error=f"Invalid email: {cleaned_email}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check username uniqueness
        cursor.execute("SELECT 1 FROM admins WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            return render_template("create_admin.html", step="enter_details",
                                   error=f"Username '{username}' already exists.")
        
        # Check email uniqueness across admins table
        cursor.execute("SELECT 1 FROM admins WHERE email = ?", (cleaned_email,))
        if cursor.fetchone():
            conn.close()
            return render_template("create_admin.html", step="enter_details",
                                   error="Email already registered to an admin.")
        
        # Check email uniqueness across users table
        cursor.execute("""
            SELECT 1 FROM users 
            WHERE secretary_email = ? OR vice_secretary_email = ?
        """, (cleaned_email, cleaned_email))
        if cursor.fetchone():
            conn.close()
            return render_template("create_admin.html", step="enter_details",
                                   error="Email already registered to a user.")
        
        # Generate OTP and credentials
        otp_code = ''.join(random.choices(string.digits, k=6))
        temp_password = generate_temp_password()
        reset_token = generate_reset_token()
        now = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
        
        # Clear any existing record for this email first
        cursor.execute("DELETE FROM admin_email_verifications WHERE email = ?", (cleaned_email,))
        
        # Store verification record with PLAIN temp_password
        cursor.execute("""
            INSERT INTO admin_email_verifications 
                (username, email, otp_code, temp_password, reset_token, expires_at, verified)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (username, cleaned_email, otp_code, temp_password, reset_token, expires_at))
        conn.commit()
        conn.close()
        
        # Store in session for reliable retrieval
        session["admin_verify_email"] = cleaned_email
        session["admin_verify_username"] = username
        session["admin_verify_otp"] = otp_code
        
        email_sent = send_otp_email(cleaned_email, otp_code, username)
        
        if not email_sent:
            session.pop("admin_verify_email", None)
            session.pop("admin_verify_username", None)
            session.pop("admin_verify_otp", None)
            return render_template("create_admin.html", step="enter_details",
                                   error="Failed to send OTP. Check email configuration.")
        
        return render_template("create_admin.html", 
                               step="verify_otp",
                               email=cleaned_email,
                               username=username,
                               info="OTP sent. Check your inbox and spam folder.")
    
    # ─── STEP 2: Verify OTP and create admin ───
    elif step == "verify_otp":
        email = (request.form.get("email") or session.get("admin_verify_email", "")).strip()
        username = (request.form.get("username") or session.get("admin_verify_username", "")).strip()
        otp_entered = request.form.get("otp_code", "").strip()
        
        if not email:
            session.pop("admin_verify_email", None)
            session.pop("admin_verify_username", None)
            session.pop("admin_verify_otp", None)
            return render_template("create_admin.html", step="enter_details",
                                   error="Session expired. Please start again.")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get the MOST RECENT verification record for this email
        cursor.execute("""
            SELECT username, otp_code, temp_password, reset_token, expires_at, verified 
            FROM admin_email_verifications 
            WHERE email = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (email,))
        record = cursor.fetchone()
        
        if not record:
            conn.close()
            session.pop("admin_verify_email", None)
            session.pop("admin_verify_username", None)
            session.pop("admin_verify_otp", None)
            return render_template("create_admin.html", 
                                   step="verify_otp",
                                   email=email,
                                   username=username,
                                   error="No verification found. Please start again.")
        
        # Handle both tuple and sqlite3.Row access
        if hasattr(record, 'keys'):
            db_username = record['username']
            stored_otp = record['otp_code']
            temp_password_plain = record['temp_password']
            reset_token = record['reset_token']
            expires_at = record['expires_at']
            verified = record['verified']
        else:
            db_username, stored_otp, temp_password_plain, reset_token, expires_at, verified = record
        
        # Check if username matches
        if db_username != username:
            conn.close()
            return render_template("create_admin.html", step="enter_details",
                                   error="Username mismatch. Please start again.")
        
        # Parse expires_at
        try:
            expires_dt = datetime.fromisoformat(expires_at)
        except (ValueError, TypeError):
            cursor.execute("DELETE FROM admin_email_verifications WHERE email = ?", (email,))
            conn.commit()
            conn.close()
            session.pop("admin_verify_email", None)
            session.pop("admin_verify_username", None)
            session.pop("admin_verify_otp", None)
            return render_template("create_admin.html", step="enter_details",
                                   error="OTP expired. Please start again.")
        
        if datetime.now() > expires_dt:
            conn.close()
            return render_template("create_admin.html", step="enter_details",
                                   error="OTP expired. Please start again.")
        
        if verified:
            conn.close()
            return render_template("create_admin.html", step="enter_details",
                                   error="Already verified. Please start again.")
        
        if otp_entered != stored_otp:
            conn.close()
            return render_template("create_admin.html", 
                                   step="verify_otp",
                                   email=email,
                                   username=username,
                                   error="Invalid OTP. Please try again.")
        
        # ─── DUPLICATE SUBMISSION PROTECTION ───
        # Check if admin was already created (double-click protection)
        cursor.execute("SELECT 1 FROM admins WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            session.pop("admin_verify_email", None)
            session.pop("admin_verify_username", None)
            session.pop("admin_verify_otp", None)
            return render_template("create_admin.html", 
                                   step="success",
                                   success=f"Admin '{username}' was already created successfully!")
        
        # OTP verified — create admin
        create_admin(username, temp_password_plain, role="admin", email=email)
        
        # Store reset token
        # ─── TOKEN TIME HANDLING (FIXED) ───
        now = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(hours=24)).isoformat()
        
        # Store reset token
        cursor.execute("""
            INSERT INTO password_reset_tokens (
                username,
                token,
                email,
                created_at,
                expires_at,
                used,
                user_type
            )
            VALUES (?, ?, ?, ?, ?, 0, 'admin')
        """, (
            username,
            reset_token,
            email,
            now,
            expires_at
        ))
        
        # Mark verification complete
        cursor.execute("""
            UPDATE admin_email_verifications 
            SET verified = 1 
            WHERE email = ? AND otp_code = ?
        """, (email, stored_otp))
        
        conn.commit()
        conn.close()
        
        # Clear session
        session.pop("admin_verify_email", None)
        session.pop("admin_verify_username", None)
        session.pop("admin_verify_otp", None)
        
        # Send credentials email with reset link
        email_sent = send_admin_credentials_email(email, username, reset_token)
        
        # Audit log
        log_data_change("CREATE_ADMIN", "admins", None,
                        f"Superadmin created admin '{username}' with verified email {email}",
                        new_values={"username": username, "email": email, "role": "admin"})
        
        if email_sent:
            return render_template("create_admin.html", 
                                   step="success",
                                   success=f"Admin '{username}' created successfully! "
                                           f"Password reset link sent to {email}. "
                                           f"Must set password within 24 hours.")
        else:
            return render_template("create_admin.html", 
                                   step="success",
                                   success=f"Admin '{username}' created, but email failed. "
                                           f"Manual reset token: {reset_token}")
    
    return render_template("create_admin.html", step="enter_details")

@app.route("/admin/reset-password/<token>", methods=["GET", "POST"])
def reset_admin_password(token):
    """Allow ADMIN to set permanent password using reset token."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT username, expires_at, used 
        FROM admin_password_tokens 
        WHERE token = ?
    """, (token,))
    record = cursor.fetchone()
    
    if not record:
        conn.close()
        return render_template("reset_password.html", 
                               error="Invalid or expired reset link.")
    
    username = record['username']
    expires_at = record['expires_at']
    used = record['used']
    
    if used:
        conn.close()
        return render_template("reset_password.html", 
                               error="This reset link has already been used.")
    
    try:
        expires_dt = datetime.fromisoformat(expires_at)
    except (ValueError, TypeError):
        conn.close()
        return render_template("reset_password.html", 
                               error="Invalid reset link.")
    
    if datetime.now() > expires_dt:
        conn.close()
        return render_template("reset_password.html", 
                               error="Reset link has expired. Contact superadmin.")
    
    if request.method == "POST":
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        
        if not new_password or len(new_password) < 8:
            conn.close()
            return render_template("reset_password.html", 
                                   token=token,
                                   username=username,
                                   error="Password must be at least 8 characters.")
        
        if new_password != confirm_password:
            conn.close()
            return render_template("reset_password.html", 
                                   token=token,
                                   username=username,
                                   error="Passwords do not match.")
        
        hashed_pw = generate_password_hash(new_password)
        
        cursor.execute("UPDATE admins SET password = ? WHERE username = ?", 
                       (hashed_pw, username))
        cursor.execute("UPDATE admin_password_tokens SET used = 1 WHERE token = ?", 
                       (token,))
        
        conn.commit()
        conn.close()
        
        log_data_change("ADMIN_PASSWORD_RESET", "admins", None,
                        f"Admin '{username}' set permanent password via reset token",
                        new_values={"username": username, "action": "password_reset"})
        
        return render_template("reset_password.html", 
                               success="Password set successfully! You can now log in.")
    
    conn.close()
    return render_template("reset_password.html", 
                           token=token,
                           username=username)





def cleanup_orphaned_booklet_records():
    """Remove tracking records for booklets whose user was deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find booklet IDs that don't have a valid user
    cursor.execute("""
        SELECT rb.id FROM receipt_booklets rb
        LEFT JOIN users u ON rb.user_id = u.id
        WHERE u.id IS NULL
    """)
    orphan_booklet_ids = [row['id'] for row in cursor.fetchall()]
    
    for booklet_id in orphan_booklet_ids:
        cursor.execute("DELETE FROM booklet_used_receipts WHERE booklet_id = ?", (booklet_id,))
        cursor.execute("DELETE FROM booklet_cancelled_receipts WHERE booklet_id = ?", (booklet_id,))
        cursor.execute("DELETE FROM receipt_booklets WHERE id = ?", (booklet_id,))
    
    conn.commit()
    conn.close()
    print(f"Cleaned up {len(orphan_booklet_ids)} orphaned booklets")

# Run once at startup (can remove after first run)
#cleanup_orphaned_booklet_records()



# =========================================
# FIXED: Cascade delete user booklet data to prevent future orphans
# =========================================

@app.route("/delete-user/<int:user_id>")
@superadmin_required
def delete_user(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch user BEFORE deleting
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        conn.close()
        flash("User not found.", "error")
        return redirect("/manage-users")
    
    username = user['username']
    
    # ============================================================
    # 1. GET ALL POS RECORDS FOR THIS USER (to delete files later)
    # ============================================================
    cursor.execute("SELECT id, file_path, html_file_path FROM pos_records WHERE created_by = ?", (username,))
    pos_records = cursor.fetchall()
    pos_record_ids = [r['id'] for r in pos_records]
    
    # ============================================================
    # 2. COLLECT ALL FILE PATHS TO DELETE FROM DISK
    # ============================================================
    files_to_delete = []
    
    # POS record files (PDF/HTML)
    for r in pos_records:
        if r['file_path']:
            files_to_delete.append(r['file_path'])
        if r['html_file_path']:
            files_to_delete.append(r['html_file_path'])
    
    # Upload files linked to these POS records
    if pos_record_ids:
        placeholders = ','.join('?' * len(pos_record_ids))
        cursor.execute(f"""
            SELECT file_path FROM pos_uploads 
            WHERE pos_record_id IN ({placeholders})
        """, pos_record_ids)
        for row in cursor.fetchall():
            if row['file_path']:
                files_to_delete.append(row['file_path'])
    
    # ============================================================
    # 3. DELETE POS-RELATED DATABASE RECORDS (child tables first)
    # ============================================================
    if pos_record_ids:
        placeholders = ','.join('?' * len(pos_record_ids))
        
        # pos_expenses (has FK to pos_uploads, delete first)
        cursor.execute(f"DELETE FROM pos_expenses WHERE pos_record_id IN ({placeholders})", pos_record_ids)
        
        # pos_uploads
        cursor.execute(f"DELETE FROM pos_uploads WHERE pos_record_id IN ({placeholders})", pos_record_ids)
        
        # pos_cash_rows
        cursor.execute(f"DELETE FROM pos_cash_rows WHERE pos_record_id IN ({placeholders})", pos_record_ids)
        
        # pos_cancelled_receipts
        cursor.execute(f"DELETE FROM pos_cancelled_receipts WHERE pos_record_id IN ({placeholders})", pos_record_ids)
        
        # pos_items
        cursor.execute(f"DELETE FROM pos_items WHERE pos_record_id IN ({placeholders})", pos_record_ids)
        
        # pos_records (parent)
        cursor.execute(f"DELETE FROM pos_records WHERE id IN ({placeholders})", pos_record_ids)
    
    # ============================================================
    # 4. DELETE BOOKLETS AND THEIR TRACKING RECORDS (your existing logic)
    # ============================================================
    cursor.execute("SELECT id FROM receipt_booklets WHERE user_id = ?", (user_id,))
    booklet_ids = [row['id'] for row in cursor.fetchall()]
    
    for booklet_id in booklet_ids:
        cursor.execute("DELETE FROM booklet_used_receipts WHERE booklet_id = ?", (booklet_id,))
        cursor.execute("DELETE FROM booklet_cancelled_receipts WHERE booklet_id = ?", (booklet_id,))
        cursor.execute("DELETE FROM deleted_booklets WHERE original_booklet_id = ?", (booklet_id,))
    
    cursor.execute("DELETE FROM receipt_booklets WHERE user_id = ?", (user_id,))
    
    # ============================================================
    # 5. DELETE OTHER USER-RELATED RECORDS
    # ============================================================
    cursor.execute("DELETE FROM skipped_submissions WHERE username = ?", (username,))
    cursor.execute("DELETE FROM vice_secretary_notifications WHERE username = ?", (username,))
    cursor.execute("DELETE FROM login_otp_sessions WHERE username = ?", (username,))
    cursor.execute("DELETE FROM otp_verifications WHERE identifier = ?", (username,))
    
    # ============================================================
    # 6. DELETE THE USER
    # ============================================================
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    
    # ============================================================
    # 7. DELETE FILES FROM DISK (after DB commit succeeds)
    # ============================================================
    deleted_files = 0
    failed_files = []
    for file_path in files_to_delete:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                deleted_files += 1
            except Exception as e:
                failed_files.append((file_path, str(e)))
    
    if failed_files:
        print(f"Warning: Failed to delete {len(failed_files)} files for user '{username}':")
        for path, err in failed_files:
            print(f"  - {path}: {err}")
    
    # ============================================================
    # 8. AUDIT LOG (your existing call)
    # ============================================================
    log_data_change(
        "DELETE_USER", 
        "users", 
        user_id,
        f"Superadmin deleted user '{username}' and all associated POS records, booklets, uploads, and tracking data",
        old_values=dict(user)
    )
    
    flash(
        f"User '{username}' and all associated records deleted. "
        f"{deleted_files} file(s) removed from disk.", 
        "success"
    )
    
    return redirect("/manage-users")




# =========================================
# SA BUSINESS DAY CALCULATOR (No hardcoded holidays)
# Uses cached web fetch or falls back to weekends-only
# =========================================

import json
import urllib.request
import os

SA_HOLIDAYS_CACHE_FILE = "sa_holidays_cache.json"

def fetch_sa_holidays_from_api(year):
    """
    Fetch SA public holidays from a public API.
    Returns set of "YYYY-MM-DD" strings or None if failed.
    """
    try:
        # Using Nager.Date API (free, no auth needed)
        url = f"https://date.nager.at/api/v3/publicholidays/{year}/ZA"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode())
            return {item["date"] for item in data}
    except Exception as e:
        print(f"Could not fetch SA holidays for {year}: {e}")
        return None


def get_sa_holidays(year):
    """
    Get SA holidays for a year. Uses cache if available, fetches if not.
    Falls back to empty set if offline.
    """
    # Check cache
    if os.path.exists(SA_HOLIDAYS_CACHE_FILE):
        try:
            with open(SA_HOLIDAYS_CACHE_FILE, "r") as f:
                cache = json.load(f)
            if str(year) in cache:
                return set(cache[str(year)])
        except:
            pass
    
    # Fetch from API
    holidays = fetch_sa_holidays_from_api(year)
    
    if holidays is not None:
        # Save to cache
        cache = {}
        if os.path.exists(SA_HOLIDAYS_CACHE_FILE):
            try:
                with open(SA_HOLIDAYS_CACHE_FILE, "r") as f:
                    cache = json.load(f)
            except:
                pass
        cache[str(year)] = list(holidays)
        with open(SA_HOLIDAYS_CACHE_FILE, "w") as f:
            json.dump(cache, f)
        return holidays
    
    # Fallback: no holidays known, just skip weekends
    return set()


def get_next_business_day(from_date=None):
    """
    Get next South African business day.
    Skips weekends and public holidays (fetched from API, cached locally).
    """
    if from_date is None:
        from_date = datetime.now().date()
    elif isinstance(from_date, datetime):
        from_date = from_date.date()
    
    year = from_date.year
    holidays = get_sa_holidays(year)
    
    candidate = from_date + timedelta(days=1)
    
    while True:
        date_str = candidate.strftime("%Y-%m-%d")
        weekday = candidate.weekday()  # 5=Sat, 6=Sun
        
        if weekday >= 5:
            candidate += timedelta(days=1)
            continue
        
        if date_str in holidays:
            candidate += timedelta(days=1)
            continue
        
        return candidate


# =========================================
# POS/BA NUMBER SUGGESTION HELPERS
# =========================================

def get_last_pos_numbers(username):
    """Get latest POS number and Bank Sheet number for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT pos_number, bank_sheet 
        FROM pos_records 
        WHERE created_by = ? 
        ORDER BY created_at DESC 
        LIMIT 1
    """, (username,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return row['pos_number'], row['bank_sheet']
    return None, None


def suggest_next_number(latest_value):
    """
    Extract prefix and number from strings like 'POS 4500' or 'BA 1500'.
    Returns incremented value with same prefix, or empty string.
    """
    if not latest_value:
        return ""
    
    latest_value = latest_value.strip()
    
    # Match: optional prefix (letters), optional space, then number
    match = re.match(r'^([A-Za-z]*\s*)(\d+)$', latest_value)
    if not match:
        return latest_value  # Can't parse, return as-is for user to edit
    
    prefix = match.group(1).strip()
    number = int(match.group(2))
    next_number = number + 1
    
    if prefix:
        return f"{prefix} {next_number}"
    return str(next_number)


def get_suggestions_for_user(username):
    """Bundle suggestions for template rendering."""
    latest_pos, latest_ba = get_last_pos_numbers(username)
    
    return {
        'suggested_pos': suggest_next_number(latest_pos) if latest_pos else "",
        'suggested_ba': suggest_next_number(latest_ba) if latest_ba else "",
        'banking_date': get_next_business_day(),
    }


# =========================================
# FIXED create_pos ROUTE — Preserves ALL existing functionality
# Only adds: suggested_pos, suggested_ba, banking_date
# =========================================

from itertools import groupby

from datetime import datetime
import json

# ============================================================
# ROUTE 1: create_pos (GET  shows the POS creation form)
# ============================================================
@app.route("/create-pos")
@login_required
def create_pos():
    blocked = has_unresolved_skips(session['username'])
    skip_message = ""
    if blocked:
        skip_message = "Submit your reasons for skipping submissions. If you did, contact your administrator to unlock your submission."

    products = get_products() or []

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch user's church details
    cursor.execute(
        "SELECT church_code, church_file_number, church_branch_name FROM users WHERE username = ?",
        (session["username"],)
    )
    user_church = cursor.fetchone()

    cursor.execute("SELECT id FROM users WHERE username = ?", (session["username"],))
    user_row = cursor.fetchone()
    user_id = user_row["id"] if user_row else None

    # ── BUILD booklet_map: current active booklet per product ──
    booklet_map = {}
    next_booklet_map = {}

    if user_id:
        # Get ALL active booklets ordered by booklet_number
        cursor.execute("""
            SELECT * FROM receipt_booklets
            WHERE user_id = ? AND is_active = 1
            ORDER BY product_name, CAST(booklet_number AS INTEGER) ASC
        """, (user_id,))
        active_booklets = cursor.fetchall()

        # Group by product
        for product_name, group in groupby(active_booklets, key=lambda x: x["product_name"]):
            booklets = list(group)

            # First booklet = current
            if len(booklets) >= 1:
                b = booklets[0]

                cursor.execute(
                    "SELECT MAX(receipt_to) as max_sold FROM booklet_used_receipts WHERE booklet_id = ?",
                    (b["id"],)
                )
                max_sold_row = cursor.fetchone()
                max_sold = max_sold_row["max_sold"] if max_sold_row and max_sold_row["max_sold"] is not None else b["receipt_from"] - 1

                cursor.execute(
                    "SELECT MAX(receipt_to) as max_cancelled FROM booklet_cancelled_receipts WHERE booklet_id = ?",
                    (b["id"],)
                )
                max_cancelled_row = cursor.fetchone()
                max_cancelled = max_cancelled_row["max_cancelled"] if max_cancelled_row and max_cancelled_row["max_cancelled"] is not None else b["receipt_from"] - 1

                # ── CORE MATHEMATICAL RULE ──
                max_receipt_issued = max(max_sold, max_cancelled)
                next_expected = max_receipt_issued + 1
                is_complete = next_expected > b["receipt_to"]

                booklet_map[product_name] = {
                    "booklet_id": b["id"],
                    "booklet_number": b["booklet_number"],
                    "receipt_type": b["receipt_type"],
                    "next_expected": next_expected,
                    "max_receipt_issued": max_receipt_issued,
                    "receipt_from": b["receipt_from"],
                    "receipt_to": b["receipt_to"],
                    "is_complete": is_complete
                }

            # Second booklet = next (for display in Product Information table)
            if len(booklets) > 1:
                nb = booklets[1]
                next_booklet_map[product_name] = {
                    "receipt_type": nb["receipt_type"],
                    "receipt_from": nb["receipt_from"],
                    "receipt_to": nb["receipt_to"],
                    "booklet_number": nb["booklet_number"]
                }

    # ── Get suggestions ──
    suggestions = get_suggestions_for_user(session["username"])

    # ── Build booklet_data: ALL booklets for JS engine ──
    booklet_data = {}
    if user_id:
        cursor.execute("""
            SELECT id, product_name, receipt_type, receipt_from, receipt_to, 
                   booklet_number, is_active, is_completed
            FROM receipt_booklets 
            WHERE user_id = ?
            ORDER BY product_name, CAST(booklet_number AS INTEGER) ASC
        """, (user_id,))

        all_booklets = cursor.fetchall()
        for b in all_booklets:
            product_name = b["product_name"]
            if product_name not in booklet_data:
                booklet_data[product_name] = []

            cursor.execute(
                "SELECT MAX(receipt_to) as max_sold FROM booklet_used_receipts WHERE booklet_id = ?",
                (b["id"],)
            )
            max_sold_row = cursor.fetchone()
            max_sold = max_sold_row["max_sold"] if max_sold_row and max_sold_row["max_sold"] is not None else b["receipt_from"] - 1

            cursor.execute(
                "SELECT MAX(receipt_to) as max_cancelled FROM booklet_cancelled_receipts WHERE booklet_id = ?",
                (b["id"],)
            )
            max_cancelled_row = cursor.fetchone()
            max_cancelled = max_cancelled_row["max_cancelled"] if max_cancelled_row and max_cancelled_row["max_cancelled"] is not None else b["receipt_from"] - 1

            max_receipt_issued = max(max_sold, max_cancelled)
            next_expected = max_receipt_issued + 1

            booklet_data[product_name].append({
                "id": b["id"],
                "receipt_type": b["receipt_type"],
                "receipt_from": b["receipt_from"],
                "receipt_to": b["receipt_to"],
                "next_expected": next_expected,
                "max_receipt_issued": max_receipt_issued,
                "booklet_number": b["booklet_number"],
                "is_active": b["is_active"],
                "is_completed": b["is_completed"]
            })

    conn.close()

    church_info = {
        "church_code": user_church["church_code"] if user_church else "",
        "church_file_number": user_church["church_file_number"] if user_church else "",
        "church_branch_name": user_church["church_branch_name"] if user_church else ""
    }

    return render_template("index.html",
        products=products,
        church_info=church_info,
        booklet_map=booklet_map,
        suggested_pos=suggestions['suggested_pos'],
        suggested_bank_sheet=suggestions['suggested_ba'],
        banking_date=suggestions['banking_date'].strftime('%Y-%m-%d'),
        banking_date_display=suggestions['banking_date'].strftime('%A, %d %B %Y'),
        blocked=blocked,
        skip_message=skip_message,
        booklet_data=booklet_data,
        next_booklet_map=next_booklet_map
    )



from werkzeug.utils import secure_filename
#import os

# ============================================================
# ROUTE 2: submit_pos (POST - handles POS form submission)
# ============================================================
@app.route("/submit_pos", methods=["POST"])
@login_required
def submit_pos():
    """
    Submit POS with proper booklet tracking, validation, and completion logic.
    """
    import json
    from datetime import datetime

    # ── 1. BASIC FORM DATA ──
    pos_number = request.form.get("pos_number", "").strip()
    bank_sheet = request.form.get("bank_sheet", "").strip()
    banking_date = request.form.get("banking_date", "").strip()
    depositor_name = request.form.get("depositor_name", "").strip()
    depositor_id = request.form.get("depositor_id", "").strip()
    depositor_phone = request.form.get("depositor_phone", "").strip()
    witness1 = request.form.get("witness1", "").strip()
    witness2 = request.form.get("witness2", "").strip()
    witness3 = request.form.get("witness3", "").strip()

    # ── 2. PARSE SOLD RECEIPTS ──
    product_names = request.form.getlist("product_name[]")
    service_types = request.form.getlist("service_type[]")
    from_values = request.form.getlist("from[]")
    to_values = request.form.getlist("to[]")

    sold_receipts = []
    for i in range(len(product_names)):
        product = (product_names[i] or "").strip().upper()
        receipt_type = (service_types[i] or "").strip().upper()
        f_str = (from_values[i] or "").strip()
        t_str = (to_values[i] or "").strip()

        if not product or not receipt_type or f_str == "" or t_str == "":
            continue
        try:
            f, t = int(f_str), int(t_str)
        except ValueError:
            continue
        if f < 0 or t < 0 or t < f:
            continue

        sold_receipts.append({
            "product": product,
            "type": receipt_type,
            "from": f,
            "to": t,
            "stickers": t - f + 1
        })

    # ── 3. PARSE CANCELLED RECEIPTS ──
    cancelled_json = request.form.get("cancelled_receipts_json", "[]")
    try:
        cancelled_raw = json.loads(cancelled_json)
    except:
        cancelled_raw = []

    cancelled_receipts = []
    for cr in cancelled_raw:
        product = (cr.get("product") or "").strip().upper()
        receipt_type = (cr.get("type") or "").strip().upper()
        f = cr.get("from")
        t = cr.get("to")
        if not product or not receipt_type or f is None or t is None:
            continue
        try:
            f, t = int(f), int(t)
        except:
            continue
        if f < 0 or t < 0 or t < f:
            continue
        cancelled_receipts.append({
            "product": product,
            "type": receipt_type,
            "from": f,
            "to": t,
            "manual": cr.get("manual", False),
            "stickers": t - f + 1
        })

    # ── 4. VALIDATION: Duplication within current submission ──
    sold_numbers = set()
    for sr in sold_receipts:
        for num in range(sr["from"], sr["to"] + 1):
            key = f"{sr['product']}|{sr['type']}|{num}"
            if key in sold_numbers:
                flash(f"Duplicate receipt in submission: {sr['product']}, {sr['type']}, receipt {num}", "danger")
                return redirect(url_for("create_pos"))
            sold_numbers.add(key)

    # ── 5. VALIDATION: Contradiction (sold AND cancelled) ──
    for cr in cancelled_receipts:
        for num in range(cr["from"], cr["to"] + 1):
            key = f"{cr['product']}|{cr['type']}|{num}"
            if key in sold_numbers:
                flash(f"Contradiction: {cr['product']}, {cr['type']}, receipt {num} is both sold and cancelled", "danger")
                return redirect(url_for("create_pos"))

    # ── 6. DATABASE CONNECTION ──
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM users WHERE username = ?", (session["username"],))
    user_row = cursor.fetchone()
    if not user_row:
        conn.close()
        flash("User not found", "danger")
        return redirect(url_for("create_pos"))
    user_id = user_row["id"]

    # ── 7. GET ALL ACTIVE BOOKLETS for this user ──
    cursor.execute("""
        SELECT id, product_name, receipt_type, receipt_from, receipt_to, 
               booklet_number, is_active, is_completed
        FROM receipt_booklets
        WHERE user_id = ?
        ORDER BY product_name, CAST(booklet_number AS INTEGER) ASC
    """, (user_id,))
    all_booklets = cursor.fetchall()

    # Build lookup: {(product, type): booklet_row}
    booklet_by_product_type = {}
    for b in all_booklets:
        key = (b["product_name"].upper(), b["receipt_type"].upper())
        booklet_by_product_type[key] = b

    def find_booklet(product, receipt_type, receipt_num):
        """
        Find the correct booklet for this product, type, and receipt number.
        CRITICAL: Must match BOTH product_name AND receipt_type.
        """
        key = (product.upper(), receipt_type.upper())
        if key in booklet_by_product_type:
            b = booklet_by_product_type[key]
            if b["receipt_from"] <= receipt_num <= b["receipt_to"]:
                return b
        # Fallback: search ALL active booklets matching product AND type AND range
        for b in all_booklets:
            if (b["product_name"].upper() == product.upper() and
                b["receipt_type"].upper() == receipt_type.upper() and
                b["receipt_from"] <= receipt_num <= b["receipt_to"]):
                return b
        return None

    # ── 8. PRE-VALIDATE: All sold receipts must have a valid booklet ──
    sold_by_booklet = {}
    for sr in sold_receipts:
        b = find_booklet(sr["product"], sr["type"], sr["to"])
        if not b:
            conn.close()
            flash(f"No active booklet found for {sr['product']}, {sr['type']}, receipt {sr['to']}. "
                  f"Please check that you have an active booklet for this product and type.", "danger")
            return redirect(url_for("create_pos"))

        if sr["from"] < b["receipt_from"] or sr["to"] > b["receipt_to"]:
            conn.close()
            flash(f"Range {sr['from']}-{sr['to']} exceeds booklet [{b['receipt_from']}, {b['receipt_to']}] for {sr['product']}, {sr['type']}", "danger")
            return redirect(url_for("create_pos"))

        bid = b["id"]
        if bid not in sold_by_booklet:
            sold_by_booklet[bid] = []
        sold_by_booklet[bid].append((sr["from"], sr["to"]))

    # ── 9. SAVE MAIN POS RECORD ──
    cursor.execute("""
        INSERT INTO pos_records (
            pos_number, bank_sheet, banking_date,
            created_by, created_at, year, month, month_name,
            church_name, church_code, church_file,
            depositor_name, depositor_id, depositor_phone,
            witness1, witness2, witness3,
            total_banking, total_parish, total_stickers,
            grand_total_cash, expected_total, total_outstanding,
            final_status, final_conclusion
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        pos_number, bank_sheet, banking_date,
        session["username"], datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        datetime.now().year, datetime.now().month, datetime.now().strftime("%B"),
        request.form.get("church_name", ""), request.form.get("church_code", ""), request.form.get("church_file", ""),
        depositor_name, depositor_id, depositor_phone,
        witness1, witness2, witness3,
        float(request.form.get("total_banking", 0) or 0),
        float(request.form.get("total_parish", 0) or 0),
        int(request.form.get("total_stickers", 0) or 0),
        float(request.form.get("grand_total_cash", 0) or 0),
        float(request.form.get("expected_total", 0) or 0),
        float(request.form.get("total_outstanding", 0) or 0),
        request.form.get("final_status", "DISCREPANCY"),
        request.form.get("final_conclusion", "")
    ))

    pos_record_id = cursor.lastrowid


    # ── 10. SAVE POS ITEMS with REAL PRICES ──
    # Get products lookup for pricing
    cursor.execute("SELECT name, price, deduction FROM products")
    products_lookup = {}
    for p in cursor.fetchall():
        products_lookup[p["name"].upper()] = {
            "price": float(p["price"] or 0),
            "deduction": float(p["deduction"] or 0)
        }
    
    for sr in sold_receipts:
        prod_info = products_lookup.get(sr["product"], {"price": 0.0, "deduction": 0.0})
        price = prod_info["price"]
        deduction = prod_info["deduction"]
        price_after_deduction = price # DB price is already after deduction; do NOT subtract again
        stickers = sr["stickers"]
        banking = price_after_deduction * stickers
        parish = deduction * stickers
    
        cursor.execute("""
            INSERT INTO pos_items (
                pos_record_id, product_name, product_type,
                sticker_from, sticker_to, sticker_count,
                price_per_sticker, deduction_per_sticker,
                banking_amount, parish_amount
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            pos_record_id, sr["product"], sr["type"],
            sr["from"], sr["to"], stickers,
            price_after_deduction, deduction,
            banking, parish
        ))
            
    # ── 2. PARSE SOLD RECEIPTS ──
    product_names = request.form.getlist("product_name[]")
    service_types = request.form.getlist("service_type[]")
    from_values = request.form.getlist("from[]")
    to_values = request.form.getlist("to[]")
    
    

    # ── 11. INSERT SOLD RECEIPTS into booklet_used_receipts ──
    for bid, ranges in sold_by_booklet.items():
        for rf, rt in ranges:
            cursor.execute("""
                INSERT INTO booklet_used_receipts (booklet_id, receipt_from, receipt_to, pos_record_id, used_at)
                VALUES (?, ?, ?, ?, ?)
            """, (bid, rf, rt, pos_record_id, datetime.now()))

    # ── 12. INSERT CANCELLED RECEIPTS into booklet_cancelled_receipts ──
    cancelled_by_booklet = {}
    for cr in cancelled_receipts:
        b = find_booklet(cr["product"], cr["type"], cr["to"])
        if not b:
            if cr["manual"]:
                conn.close()
                flash(f"No active booklet for cancelled {cr['product']}, {cr['type']}, {cr['to']}", "danger")
                return redirect(url_for("create_pos"))
            continue

        if cr["from"] < b["receipt_from"] or cr["to"] > b["receipt_to"]:
            if cr["manual"]:
                conn.close()
                flash(f"Cancelled range exceeds booklet for {cr['product']}, {cr['type']}", "danger")
                return redirect(url_for("create_pos"))
            continue

        bid = b["id"]
        if bid not in cancelled_by_booklet:
            cancelled_by_booklet[bid] = []
        cancelled_by_booklet[bid].append((cr["from"], cr["to"], cr["manual"]))

    for bid, ranges in cancelled_by_booklet.items():
        for rf, rt, is_manual in ranges:
            cursor.execute("""
                INSERT INTO booklet_cancelled_receipts 
                (booklet_id, receipt_from, receipt_to, cancellation_type, pos_record_id, cancelled_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (bid, rf, rt, 'manual' if is_manual else 'auto', pos_record_id, datetime.now()))

    # ── 13. SAVE POS CANCELLED RECEIPTS for audit ──
    for cr in cancelled_receipts:
        cursor.execute("""
            INSERT INTO pos_cancelled_receipts 
            (pos_record_id, product_name, product_type, sticker_from, sticker_to, sticker_count, is_manual)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (pos_record_id, cr["product"], cr["type"], cr["from"], cr["to"], cr["stickers"], 1 if cr["manual"] else 0))

    # ── 14. SAVE CASH ROWS ──
    cash_rows_json = request.form.get("cash_rows_json", "[]")
    try:
        cash_rows = json.loads(cash_rows_json)
    except:
        cash_rows = []
    for cr in cash_rows:
        cursor.execute("""
            INSERT INTO pos_cash_rows (pos_record_id, r200, r100, r50, r20, r10, coins)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (pos_record_id, cr.get("r200", 0), cr.get("r100", 0), cr.get("r50", 0),
              cr.get("r20", 0), cr.get("r10", 0), cr.get("coins", 0)))

    # ── 15. SAVE EXPENSES ──
    expense_types = request.form.getlist("expense_type[]")
    expense_amounts = request.form.getlist("expense_amount[]")
    expense_descriptions = request.form.getlist("expense_description[]")  # ← ADDED: get descriptions
    expense_receipts = request.files.getlist("expense_receipt[]")        # ← ADDED: get receipt files
    total_expenses = 0
    for i in range(len(expense_types)):
        etype = (expense_types[i] or "").strip()
        amount = float((expense_amounts[i] or "0").strip() or 0)
        description = (expense_descriptions[i] or "").strip() if i < len(expense_descriptions) else ""  
        receipt_file = expense_receipts[i] if i < len(expense_receipts) else None                    
        receipt_path = None                                                                           
        if receipt_file and receipt_file.filename:                                                    
            filename = secure_filename(f"{pos_record_id}_{i}_{receipt_file.filename}")                
            receipt_path = os.path.join("uploads", "expenses", filename)                            
            os.makedirs(os.path.dirname(receipt_path), exist_ok=True)                                
            receipt_file.save(receipt_path)                                                          
        if etype and amount > 0:
            cursor.execute("""
                INSERT INTO pos_expenses (pos_record_id, expense_type, amount, description, receipt_path) 
                VALUES (?, ?, ?, ?, ?)
            """, (pos_record_id, etype, amount, description, receipt_path))  # ← MODIFIED: added description & receipt_path
            total_expenses += amount

    cursor.execute("""
        UPDATE pos_records SET total_expenses = ? WHERE id = ?
    """, (total_expenses, pos_record_id))

    # ── 16. UPDATE BOOKLET STATUS using MATHEMATICAL RULE ──
    affected_booklet_ids = set(sold_by_booklet.keys()) | set(cancelled_by_booklet.keys())

    for bid in affected_booklet_ids:
        cursor.execute("SELECT receipt_from, receipt_to FROM receipt_booklets WHERE id = ?", (bid,))
        b = cursor.fetchone()
        if not b:
            continue

        receipt_from = b["receipt_from"]
        receipt_to = b["receipt_to"]

        cursor.execute("SELECT MAX(receipt_to) as max_sold FROM booklet_used_receipts WHERE booklet_id = ?", (bid,))
        row = cursor.fetchone()
        max_sold = row["max_sold"] if row and row["max_sold"] is not None else receipt_from - 1

        cursor.execute("SELECT MAX(receipt_to) as max_cancelled FROM booklet_cancelled_receipts WHERE booklet_id = ?", (bid,))
        row = cursor.fetchone()
        max_cancelled = row["max_cancelled"] if row and row["max_cancelled"] is not None else receipt_from - 1

        max_receipt_issued = max(max_sold, max_cancelled)
        next_expected = max_receipt_issued + 1
        is_complete = next_expected > receipt_to

        if is_complete:
            cursor.execute("""
                UPDATE receipt_booklets
                SET max_receipt_issued = ?, next_expected_receipt = ?,
                    is_completed = 1, is_active = 0, completed_at = ?
                WHERE id = ?
            """, (max_receipt_issued, next_expected, datetime.now(), bid))
        else:
            cursor.execute("""
                UPDATE receipt_booklets
                SET max_receipt_issued = ?, next_expected_receipt = ?
                WHERE id = ?
            """, (max_receipt_issued, next_expected, bid))

    # ── 17. ENSURE 2 ACTIVE BOOKLETS for products with completed booklets ──
    for bid in affected_booklet_ids:
        cursor.execute("SELECT user_id, product_name FROM receipt_booklets WHERE id = ?", (bid,))
        bk_info = cursor.fetchone()
        if bk_info:
            ensure_two_active_booklets(conn, bk_info["user_id"], bk_info["product_name"])

    conn.commit()
    conn.close()

    flash("POS submitted successfully!", "success")
    return redirect(url_for("my_pos_files"))


import os
from werkzeug.utils import secure_filename

RECEIPT_ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

def allowed_receipt_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in RECEIPT_ALLOWED_EXTENSIONS

@app.route("/upload_expense_receipt/<int:expense_id>", methods=["POST"])
@login_required
def upload_expense_receipt(expense_id):
    created_by = session["username"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Verify the expense belongs to this user's POS
    cursor.execute("""
        SELECT pe.id, pe.pos_record_id, pr.created_by 
        FROM pos_expenses pe
        JOIN pos_records pr ON pe.pos_record_id = pr.id
        WHERE pe.id = ?
    """, (expense_id,))
    expense = cursor.fetchone()
    
    if not expense:
        conn.close()
        return "Expense not found.", 404
    
    if expense["created_by"] != created_by:
        conn.close()
        return "Unauthorized.", 403
    
    # Handle file upload
    if 'receipt' not in request.files:
        conn.close()
        return "No file selected.", 400
    
    file = request.files['receipt']
    if file.filename == '':
        conn.close()
        return "No file selected.", 400
    
    if file and allowed_receipt_file(file.filename):
        # Create receipts folder
        receipt_folder = os.path.join(POS_FOLDER, "receipts")
        os.makedirs(receipt_folder, exist_ok=True)
        
        # Generate safe filename
        ext = file.filename.rsplit('.', 1)[1].lower()
        safe_filename = f"receipt_{expense_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
        file_path = os.path.join(receipt_folder, safe_filename)
        
        # Save file
        file.save(file_path)
        
        # Update database
        cursor.execute("""
            UPDATE pos_expenses 
            SET receipt_path = ? 
            WHERE id = ?
        """, (file_path, expense_id))
        conn.commit()
        
        # Log audit
        log_pos_action("UPLOAD_RECEIPT", expense["pos_record_id"],
                       f"User '{created_by}' uploaded receipt for expense #{expense_id}",
                       amount=None)
        
        conn.close()
        
        # Redirect back to view POS
        return redirect(url_for("view_pos", pos_id=expense["pos_record_id"]))
    
    conn.close()
    return "Invalid file type. Allowed: PDF, PNG, JPG, JPEG", 400


@app.route("/download-receipt/<int:expense_id>")
@login_required
def download_receipt(expense_id):
    created_by = session["username"]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT pe.receipt_path, pr.created_by 
        FROM pos_expenses pe
        JOIN pos_records pr ON pe.pos_record_id = pr.id
        WHERE pe.id = ?
    """, (expense_id,))
    expense = cursor.fetchone()
    conn.close()
    
    if not expense:
        abort(404)
    
    if session.get("role") == "user" and expense["created_by"] != created_by:
        abort(403)
    
    if not expense["receipt_path"] or not os.path.exists(expense["receipt_path"]):
        abort(404)
    
    return send_file(expense["receipt_path"], as_attachment=False)



@app.route('/check_skip_status')
def check_skip_status():
    if 'user_id' not in session:
        return jsonify({"blocked": False})

    user_id = session['user_id']

    conn = get_db()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS count
        FROM skipped_submissions
        WHERE user_id = ?
        AND (status IS NULL OR status IN ('pending', 'rejected'))
    """, (user_id,))

    result = cursor.fetchone()
    count = result["count"] if result else 0

    blocked = count > 0

    message = (
        "You are currently blocked from submitting a POS. "
        "Please submit reasons for skipped submissions and wait for admin approval."
        if blocked else ""
    )

    return jsonify({
        "blocked": blocked,
        "pending_count": count,
        "message": message
    })


@app.route('/submit-skip-reasons', methods=['GET', 'POST'])
@login_required
def submit_skip_reasons():
    username = session['username']
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == 'POST':
        skip_ids = request.form.getlist('skip_id[]')
        reasons = request.form.getlist('reason[]')
        explanations = request.form.getlist('explanation[]')
        
        for i, skip_id in enumerate(skip_ids):
            reason = reasons[i] if i < len(reasons) else ''
            explanation = explanations[i] if i < len(explanations) else ''
            
            # Build full explanation text
            if reason == 'no_service':
                full_reason = "There was no church Service"
            elif reason == 'other':
                full_reason = f"Other: {explanation}"
            else:
                full_reason = explanation
            
            cursor.execute("""
                UPDATE skipped_submissions 
                SET reason = ?, explanation = ?, status = 'pending', submitted_at = datetime('now')
                WHERE id = ? AND username = ?
            """, (reason, full_reason, skip_id, username))
        
        conn.commit()

        # === NOTIFY ADMINS & SUPERADMINS ===
        notify_admins_skip_submitted(username, skip_ids)
        
        flash("Your skip reasons have been submitted for admin approval.", "success")
        return redirect('/submit-skip-reasons')
    
    # GET: Fetch all skips for this user
    cursor.execute("""
        SELECT id, expected_sunday, status, reason, explanation
        FROM skipped_submissions
        WHERE username = ?
        ORDER BY expected_sunday DESC
    """, (username,))
    
    skips = cursor.fetchall()
    conn.close()
    
    return render_template('submit_skip_reasons.html', skips=skips)




@app.route("/admin/skipped-submissions")
@admin_required
def admin_skipped_submissions():
    """Admin/Superadmin view of all skipped submissions with reasons."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            s.id,
            s.username,
            s.expected_sunday,
            s.reason,
            s.explanation,
            s.status,
            s.created_at,
            s.submitted_at,
            s.reviewed_by,
            s.reviewed_at,
            u.church_branch_name
        FROM skipped_submissions s
        LEFT JOIN users u ON s.username = u.username
        ORDER BY 
            CASE s.status 
                WHEN 'pending' THEN 1 
                WHEN 'rejected' THEN 2 
                WHEN 'approved' THEN 3 
                ELSE 4 
            END,
            s.submitted_at DESC,
            s.created_at DESC
    """)
    skipped = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return render_template("admin_skipped_submissions.html", skipped=skipped)

@app.route("/admin/approve-skip/<int:skip_id>", methods=["POST"])
@admin_required
def approve_skip(skip_id):
    """Approve or reject a skipped submission reason."""
    action = request.form.get('action', 'approve')  # 'approve' or 'reject'
    
    conn = get_db_connection()
    cursor = conn.cursor()

    if action == 'approve':
        cursor.execute("""
            UPDATE skipped_submissions 
            SET status = 'approved', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (session['username'], skip_id))
        flash("Skip reason approved. User can now submit POS.", "success")
    else:
        cursor.execute("""
            UPDATE skipped_submissions 
            SET status = 'rejected', reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (session['username'], skip_id))
        flash("Skip reason rejected. User must resubmit.", "warning")

    conn.commit()
    conn.close()

    return redirect("/admin/skipped-submissions")


@app.route("/admin/manage-contacts", methods=["GET", "POST"])
@admin_required
def manage_contacts():
    """Admin/Superadmin: View and update secretary/vice-secretary contact details."""
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == "POST":
        username = request.form.get("username")
        secretary_email = request.form.get("secretary_email", "").strip()
        vice_secretary_email = request.form.get("vice_secretary_email", "").strip()
        secretary_phone = request.form.get("secretary_phone", "").strip()
        vice_secretary_phone = request.form.get("vice_secretary_phone", "").strip()
        
        # Get old values for audit log
        cursor.execute("""
            SELECT secretary_email, vice_secretary_email, secretary_phone, vice_secretary_phone
            FROM users WHERE username = ?
        """, (username,))
        old = cursor.fetchone()
        
        # Update
        cursor.execute("""
            UPDATE users 
            SET secretary_email = ?, vice_secretary_email = ?, 
                secretary_phone = ?, vice_secretary_phone = ?
            WHERE username = ?
        """, (secretary_email or None, vice_secretary_email or None,
              secretary_phone or None, vice_secretary_phone or None, username))
        conn.commit()
        
        # Get church name for notification
        cursor.execute("SELECT church_branch_name FROM users WHERE username = ?", (username,))
        church_row = cursor.fetchone()
        church_name = church_row['church_branch_name'] if church_row else 'your church'
        
        # Notify new secretary if email was added/changed
        if secretary_email and (not old or old['secretary_email'] != secretary_email):
            try:
                send_email(secretary_email,
                          "KGANYA: You Have Been Appointed as Secretary",
                          f"""You have been appointed as the secretary for {username} ({church_name}) on the KGANYA Digital Proof Of Service system.

Please log in and familiarize yourself with the system.

---
KGANYA Financial Service Providers""")
            except Exception as e:
                print(f"Failed to notify new secretary: {e}")
        
        # Audit log
        
        # Audit log
        log_data_change("UPDATE_CONTACTS", "users", username,
                       f"Admin {session['username']} updated contacts for {username}",
                       old_values=dict(old) if old else None,
                       new_values={
                           "secretary_email": secretary_email,
                           "vice_secretary_email": vice_secretary_email,
                           "secretary_phone": secretary_phone,
                           "vice_secretary_phone": vice_secretary_phone
                       })
        
        flash(f"Contact details updated for {username}.", "success")
        conn.close()
        return redirect("/admin/manage-contacts")
    
    # GET: List all users with their contact details
    cursor.execute("""
        SELECT username, church_branch_name, church_code,
               secretary_email, vice_secretary_email,
               secretary_phone, vice_secretary_phone,
               created_at
        FROM users
        ORDER BY church_branch_name, username
    """)
    users = cursor.fetchall()
    conn.close()
    
    return render_template("admin_manage_contacts.html", users=users)



# =========================================
# RUN APP
# =========================================

if __name__ == "__main__":
    print("Digital Proof Of Service System Running...")
    print(f"Templates folder exists: {os.path.exists('templates')}")
    app.run(debug=False, use_reloader=False)   



     
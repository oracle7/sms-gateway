import sqlite3
import sys
from datetime import datetime, timezone, timedelta
def adapt_datetime(ts):
    return ts.isoformat()

sqlite3.register_adapter(datetime, adapt_datetime)

def reset_and_seed(db_name):
    contacts = [
        ("17185550101", "John Doe (Patient)"),
        ("17185550102", "Sarah Smith (Patient)"),
        ("17185550103", "Mike Johnson (Patient)"),
        ("17185550104", "Lab Results NYC")
    ]

    now = datetime.now(timezone.utc)
    messages = [
        ("17185550101", "Hi, I have a foot pain since yesterday, can I come in?", True, now - timedelta(hours=5)),
        ("17185550101", "Hello John, please come at 2:00 PM today.", False, now - timedelta(hours=4)),
        ("17185550102", "Are the orthotics ready?", True, now - timedelta(days=1, hours=1)),
        ("17185550102", "Yes, Sarah. You can pick them up anytime.", False, now - timedelta(days=1)),
        ("17185550104", "Lab results for Mike Johnson are ready for pickup.", True, now - timedelta(days=2))
    ]

    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()

        cursor.execute("BEGIN TRANSACTION")
        
        # Truncate tables
        cursor.execute("DELETE FROM contacts")
        cursor.execute("DELETE FROM messages")
        cursor.execute("DELETE FROM messages_fts")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='messages'")

        # Seed data
        cursor.executemany("INSERT INTO contacts (phone_number, name) VALUES (?, ?)", contacts)

        cursor.executemany(
            "INSERT INTO messages (raw_number, body, is_inbound, timestamp) VALUES (?, ?, ?, ?)", 
            messages
        )

        conn.commit()
        print(f"Successfully reset and re-seeded {db_name} with test data.")
        
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 generate_prototype.py <database_name.db>")
    else:
        reset_and_seed(sys.argv[1])
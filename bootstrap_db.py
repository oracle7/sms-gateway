import sqlite3
import sys

def create_db(db_name):
    # Standard schema
    schema = """
    CREATE TABLE IF NOT EXISTS contacts (
        phone_number TEXT PRIMARY KEY,
        name TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        voipms_id TEXT UNIQUE,
        contact_phone TEXT,
        raw_number TEXT NOT NULL,
        body TEXT NOT NULL,
        is_inbound BOOLEAN NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    -- FTS5 Virtual Table
    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(body, raw_number, message_id UNINDEXED);

    -- Triggers for FTS5 synchronization
    CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
      INSERT INTO messages_fts(body, raw_number, message_id) VALUES (new.body, new.raw_number, new.id);
    END;

    CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
      INSERT INTO messages_fts(messages_fts, body, raw_number, message_id) VALUES('delete', old.body, old.raw_number, old.id);
    END;

    CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
      INSERT INTO messages_fts(messages_fts, body, raw_number, message_id) VALUES('delete', old.body, old.raw_number, old.id);
      INSERT INTO messages_fts(body, raw_number, message_id) VALUES (new.body, new.raw_number, new.id);
    END;
    """
    
    try:
        conn = sqlite3.connect(db_name)
        cursor = conn.cursor()
        cursor.executescript(schema)
        conn.commit()
        print(f"Successfully created/initialized {db_name} with FTS5.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 bootstrap_db.py <database_name.db>")
    else:
        create_db(sys.argv[1])
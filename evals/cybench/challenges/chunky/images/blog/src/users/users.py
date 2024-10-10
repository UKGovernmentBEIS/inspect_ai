import sqlite3
import hashlib
import uuid
import os

db = os.getenv("DB")


def init_table():
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            password TEXT NOT NULL
        )
    """
    )
    conn.commit()
    conn.close()


def get_conn():
    conn = sqlite3.connect(db)
    return conn


def user_exists(username):
    conn = get_conn()
    cur = conn.cursor()
    res = cur.execute("SELECT id FROM users WHERE username=?", (username,))
    result = res.fetchone() is not None
    conn.close()
    return result


def create_user(username, password):
    conn = get_conn()
    cur = conn.cursor()

    if user_exists(username):
        return None, "User already exists!"

    pwhash = hashlib.sha256(password.encode()).hexdigest()
    user_id = str(uuid.uuid4())

    cur.execute(
        "INSERT INTO users(id, username, password) VALUES(?,?,?)",
        (user_id, username, pwhash),
    )
    conn.commit()

    conn.close()

    return {
        "id": user_id,
        "username": username,
    }, None


def verify_credentials(username, password):
    conn = get_conn()
    cur = conn.cursor()

    pwhash = hashlib.sha256(password.encode()).hexdigest()

    res = cur.execute(
        "SELECT id, username FROM users WHERE username=? AND password=?",
        (username, pwhash),
    )
    result = res.fetchone()
    conn.close()

    if result is None:
        return False, None

    userid, username = result

    return True, {
        "id": userid,
        "username": username,
    }

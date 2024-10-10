import os
import uuid
import sqlite3

db = os.getenv("DB")


def init_table():
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS blog_posts (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            user_id TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """
    )
    conn.commit()
    conn.close()


def create_post(title, content, userid):
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    post_id = str(uuid.uuid4())
    cursor.execute(
        "INSERT INTO blog_posts (id, title, content, user_id) VALUES (?, ?, ?, ?)",
        (post_id, title, content, userid),
    )
    conn.commit()
    conn.close()
    return post_id


def get_post(post_id):
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT title, content FROM blog_posts WHERE id = ?", (post_id,))
    post = cursor.fetchone()
    conn.close()
    return post

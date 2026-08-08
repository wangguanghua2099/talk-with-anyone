import sqlite3
import os
import time
import secrets
from datetime import datetime


class ConversationManager:
    def __init__(self, data_dir):
        self.db_path = os.path.join(data_dir, "conversations.db")
        self.current_id = None
        self._init_db()
        self._migrate_json()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT,
                sort_order INTEGER DEFAULT 0,
                avatar TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id TEXT,
                role TEXT,
                content TEXT,
                display_name TEXT,
                timestamp TEXT,
                FOREIGN KEY (conv_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_updated ON conversations(updated_at DESC)")
        # 迁移：添加 avatar 列（如果不存在）
        try:
            conn.execute("ALTER TABLE conversations ADD COLUMN avatar TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # 迁移：添加 character_id 列（如果不存在）
        try:
            conn.execute("ALTER TABLE messages ADD COLUMN character_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        conn.commit()
        self.current_id = self._get_setting(conn, "current_id")
        conn.close()

    def _get_setting(self, conn, key):
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_setting(self, conn, key, value):
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

    def _migrate_json(self):
        json_path = os.path.join(os.path.dirname(self.db_path), "conversations.json")
        if not os.path.exists(json_path):
            return
        try:
            import json
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            conn = sqlite3.connect(self.db_path)
            sort_order = 0
            for conv in data.get("conversations", []):
                sort_order += 1
                conn.execute(
                    "INSERT OR IGNORE INTO conversations (id, title, created_at, updated_at, sort_order) VALUES (?, ?, ?, ?, ?)",
                    (conv["id"], conv.get("title", ""), conv.get("created_at", ""), conv.get("updated_at", ""), sort_order)
                )
                for msg in conv.get("messages", []):
                    conn.execute(
                        "INSERT INTO messages (conv_id, role, content, display_name, timestamp) VALUES (?, ?, ?, ?, ?)",
                        (conv["id"], msg["role"], msg["content"], msg.get("display_name"), msg.get("timestamp", ""))
                    )
            current_id = data.get("current_conversation_id")
            if current_id:
                self._set_setting(conn, "current_id", current_id)
                self.current_id = current_id
            conn.commit()
            conn.close()
            os.rename(json_path, json_path + ".bak")
        except Exception:
            pass

    def _now_str(self):
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def create(self):
        conn = sqlite3.connect(self.db_path)
        conv_id = f"conv_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
        now = self._now_str()
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) FROM conversations").fetchone()[0]
        conn.execute(
            "INSERT INTO conversations (id, title, created_at, updated_at, sort_order) VALUES (?, ?, ?, ?, ?)",
            (conv_id, "", now, now, max_order + 1)
        )
        self._set_setting(conn, "current_id", conv_id)
        self.current_id = conv_id
        conn.commit()
        conn.close()
        return {"id": conv_id, "title": "", "created_at": now, "updated_at": now, "messages": []}

    def get(self, conv_id):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT id, title, created_at, updated_at, avatar FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if not row:
            conn.close()
            return None
        conv = {"id": row[0], "title": row[1], "created_at": row[2], "updated_at": row[3], "avatar": row[4], "messages": []}
        rows = conn.execute("SELECT role, content, display_name, timestamp FROM messages WHERE conv_id=? ORDER BY id", (conv_id,)).fetchall()
        conv["messages"] = [{"role": r[0], "content": r[1], "display_name": r[2], "timestamp": r[3]} for r in rows]
        conn.close()
        return conv

    def get_current(self):
        if self.current_id:
            return self.get(self.current_id)
        return None

    def list_all(self):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT c.id, c.title, c.created_at, c.updated_at, c.avatar, COUNT(m.id)
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conv_id
            GROUP BY c.id
            ORDER BY c.sort_order DESC
        """).fetchall()
        conn.close()
        return [{"id": r[0], "title": r[1], "created_at": r[2], "updated_at": r[3], "avatar": r[4], "message_count": r[5]} for r in rows]

    def add_message(self, conv_id, role, content, display_name=None, character_id=None):
        conn = sqlite3.connect(self.db_path)
        now = self._now_str()
        conn.execute(
            "INSERT INTO messages (conv_id, role, content, display_name, timestamp, character_id) VALUES (?, ?, ?, ?, ?, ?)",
            (conv_id, role, content, display_name, now, character_id or '')
        )
        if role == "user":
            row = conn.execute("SELECT title FROM conversations WHERE id=?", (conv_id,)).fetchone()
            if row and not row[0]:
                conn.execute("UPDATE conversations SET title=?, updated_at=?, sort_order=(SELECT COALESCE(MAX(sort_order),0)+1 FROM conversations) WHERE id=?",
                             (content[:50], now, conv_id))
            else:
                conn.execute("UPDATE conversations SET updated_at=?, sort_order=(SELECT COALESCE(MAX(sort_order),0)+1 FROM conversations) WHERE id=?", (now, conv_id))
        else:
            conn.execute("UPDATE conversations SET updated_at=?, sort_order=(SELECT COALESCE(MAX(sort_order),0)+1 FROM conversations) WHERE id=?", (now, conv_id))
        self._set_setting(conn, "current_id", conv_id)
        self.current_id = conv_id
        conn.commit()
        conn.close()

    def switch_to(self, conv_id):
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT id FROM conversations WHERE id=?", (conv_id,)).fetchone()
        if not row:
            conn.close()
            return None
        self._set_setting(conn, "current_id", conv_id)
        self.current_id = conv_id
        conn.commit()
        conn.close()
        return self.get(conv_id)

    def clear_messages(self, conv_id):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (self._now_str(), conv_id))
        conn.commit()
        conn.close()

    def rename(self, conv_id, title):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, conv_id))
        conn.commit()
        conn.close()

    def delete(self, conv_id):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
        conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
        if self.current_id == conv_id:
            row = conn.execute("SELECT id FROM conversations ORDER BY sort_order DESC LIMIT 1").fetchone()
            self.current_id = row[0] if row else None
            self._set_setting(conn, "current_id", self.current_id or "")
        conn.commit()
        conn.close()
        return True

    def get_messages(self, conv_id):
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT role, content, display_name, timestamp, character_id FROM messages WHERE conv_id=? ORDER BY id", (conv_id,)).fetchall()
        conn.close()
        return [{"role": r[0], "content": r[1], "display_name": r[2], "timestamp": r[3], "character_id": r[4] or ''} for r in rows]

    def update_avatar(self, conv_id, avatar_base64):
        conn = sqlite3.connect(self.db_path)
        conn.execute("UPDATE conversations SET avatar=? WHERE id=?", (avatar_base64, conv_id))
        conn.commit()
        conn.close()

    def search(self, keyword):
        """搜索对话标题和消息内容，返回匹配的对话列表及内容片段"""
        if not keyword or not keyword.strip():
            return self.list_all()
        kw = keyword.strip()
        like_kw = f"%{kw}%"
        conn = sqlite3.connect(self.db_path)
        # 搜索标题匹配的对话
        title_matches = set()
        for row in conn.execute("SELECT id FROM conversations WHERE title LIKE ?", (like_kw,)).fetchall():
            title_matches.add(row[0])
        # 搜索消息内容匹配的对话，同时提取匹配片段
        content_matches = {}
        msg_index_map = {}  # conv_id -> [msg_index]
        for row in conn.execute("""
            SELECT m.conv_id, m.content, m.id
            FROM messages m
            WHERE m.content LIKE ?
            ORDER BY m.conv_id, m.id
        """, (like_kw,)).fetchall():
            conv_id = row[0]
            content = row[1]
            msg_id = row[2]
            if conv_id not in content_matches:
                content_matches[conv_id] = []
                msg_index_map[conv_id] = []
            # 提取关键词周围的片段（前后各30字符）
            idx = content.lower().find(kw.lower())
            while idx != -1:
                start = max(0, idx - 30)
                end = min(len(content), idx + len(kw) + 30)
                snippet = content[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(content):
                    snippet = snippet + "..."
                # 记录消息序号（用于前端定位）
                msg_count = conn.execute("SELECT COUNT(*) FROM messages WHERE conv_id=? AND id<=?", (conv_id, msg_id)).fetchone()[0]
                if snippet not in content_matches[conv_id]:
                    content_matches[conv_id].append(snippet)
                    msg_index_map[conv_id].append(msg_count - 1)
                if len(content_matches[conv_id]) >= 3:
                    break
                idx = content.lower().find(kw.lower(), idx + 1)

        all_ids = title_matches | set(content_matches.keys())
        if not all_ids:
            conn.close()
            return []
        # 查询这些对话的详细信息
        placeholders = ",".join("?" for _ in all_ids)
        rows = conn.execute(f"""
            SELECT c.id, c.title, c.created_at, c.updated_at, c.avatar, COUNT(m.id)
            FROM conversations c
            LEFT JOIN messages m ON c.id = m.conv_id
            WHERE c.id IN ({placeholders})
            GROUP BY c.id
            ORDER BY c.sort_order DESC
        """, list(all_ids)).fetchall()
        conn.close()

        results = []
        for r in rows:
            conv_id = r[0]
            match_type = "title" if conv_id in title_matches else "content"
            snippets = content_matches.get(conv_id, [])
            msg_indices = msg_index_map.get(conv_id, [])
            results.append({
                "id": conv_id, "title": r[1], "created_at": r[2],
                "updated_at": r[3], "avatar": r[4], "message_count": r[5],
                "match_type": match_type, "snippets": snippets,
                "snippet_indices": msg_indices
            })
        return results

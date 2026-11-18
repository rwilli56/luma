import contextlib
import json
import os
import sqlite3
import time


class Store:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS progress (key TEXT PRIMARY KEY, media TEXT NOT NULL, position REAL NOT NULL,
                    duration REAL NOT NULL, completed INTEGER NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS mapping (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (key TEXT PRIMARY KEY, value TEXT NOT NULL, version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS search_overrides (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def put(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)', (key, json.dumps(value), time.time()))

    def get(self, key, default=None, max_age=None):
        with self.connect() as db:
            row = db.execute('SELECT value,updated FROM cache WHERE key=?', (key,)).fetchone()
        if row is None or (max_age is not None and time.time() - row['updated'] > max_age):
            return default
        return json.loads(row['value'])

    def identify(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO mapping VALUES (?,?)', (key, json.dumps(value)))

    def mapping(self, key):
        with self.connect() as db:
            row = db.execute('SELECT value FROM mapping WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else {}

    def mappings(self):
        with self.connect() as db:
            return {row['key']: json.loads(row['value']) for row in db.execute('SELECT * FROM mapping')}

    def cache_prefix(self, prefix):
        with self.connect() as db:
            return {row['key']: json.loads(row['value']) for row in db.execute(
                'SELECT key,value FROM cache WHERE substr(key,1,?)=?', (len(prefix), prefix))}

    def clear_cache(self, prefixes):
        """Delete named cache namespaces, preserving history, mappings and outbox."""
        with self.connect() as db:
            for prefix in prefixes:
                db.execute('DELETE FROM cache WHERE substr(key,1,?)=?', (len(prefix), prefix))

    def reset(self):
        """Called only by the idle service after explicit in-app confirmation."""
        with self.connect() as db:
            for table in ('cache', 'progress', 'mapping', 'outbox', 'search_overrides'):
                db.execute('DELETE FROM ' + table)

    def search_override(self, key):
        with self.connect() as db:
            row = db.execute('SELECT value FROM search_overrides WHERE key=?', (key,)).fetchone()
        return json.loads(row['value']) if row else {}

    def save_search_override(self, key, rules):
        with self.connect() as db:
            if rules:
                db.execute('INSERT OR REPLACE INTO search_overrides VALUES (?,?)', (key, json.dumps(rules)))
            else:
                db.execute('DELETE FROM search_overrides WHERE key=?', (key,))

    def save_progress(self, media, position, duration, completed=False, updated=None):
        if duration <= 0:
            return
        position = min(duration, max(0, position))
        # Never persist signed CDN links or TorBox tokens in watch history.
        safe = {k: v for k, v in media.items() if k not in ('sources', 'url')}
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO progress VALUES (?,?,?,?,?,?)',
                       (media['key'], json.dumps(safe), position, duration, int(completed), updated or time.time()))

    def history(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM progress ORDER BY updated DESC').fetchall()
        return [dict(json.loads(row['media']), position=row['position'], duration=row['duration'],
                     completed=bool(row['completed']), updated=row['updated']) for row in rows]

    def enqueue(self, key, value):
        import uuid
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO outbox VALUES (?,?,?)', (key, json.dumps(value), uuid.uuid4().hex))

    def pending(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM outbox').fetchall()]

    def acknowledge(self, key, version):
        with self.connect() as db:
            db.execute('DELETE FROM outbox WHERE key=? AND version=?', (key, version))

    def advance(self, key, version, value):
        with self.connect() as db:
            db.execute('UPDATE outbox SET value=? WHERE key=? AND version=?', (json.dumps(value), key, version))

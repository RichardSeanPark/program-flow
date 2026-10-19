"""Tenant-scoped SQLite storage. Keep the database in private user data, not the source tree."""
import sqlite3
import threading
import time


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
                app_key BLOB, app_secret BLOB);
            CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, app_key BLOB, app_secret BLOB);
            CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                expires INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS minute_rows (user_id TEXT NOT NULL, stock_code TEXT NOT NULL,
                trade_date TEXT NOT NULL, market TEXT NOT NULL, minute TEXT NOT NULL,
                tm TEXT NOT NULL, buy_amt INTEGER NOT NULL, sell_amt INTEGER NOT NULL,
                net_amt INTEGER NOT NULL, PRIMARY KEY (user_id,stock_code,trade_date,market,minute));
            CREATE TABLE IF NOT EXISTS sync_state (user_id TEXT NOT NULL, stock_code TEXT NOT NULL,
                trade_date TEXT NOT NULL, market TEXT NOT NULL, synced_at INTEGER NOT NULL,
                PRIMARY KEY (user_id,stock_code,trade_date,market));
            CREATE TABLE IF NOT EXISTS watched_stock (user_id TEXT PRIMARY KEY,
                stock_code TEXT NOT NULL, stock_name TEXT NOT NULL);
        ''')

    def create_profile(self, user):
        with self.lock, self.conn:
            self.conn.execute('INSERT INTO profiles (id) VALUES (?)', (user,))

    def user(self, user):
        with self.lock:
            row = self.conn.execute('SELECT * FROM profiles WHERE id=?',(user,)).fetchone()
            return dict(row) if row else None

    def keyed_profiles(self):
        with self.lock:
            return [row[0] for row in self.conn.execute(
                'SELECT id FROM profiles WHERE app_key IS NOT NULL AND app_secret IS NOT NULL')]

    def set_keys(self, user, app_key, app_secret):
        with self.lock, self.conn:
            self.conn.execute('UPDATE profiles SET app_key=?,app_secret=? WHERE id=?',(app_key,app_secret,user))

    def clear_keys(self, user):
        with self.lock, self.conn:
            self.conn.execute('UPDATE profiles SET app_key=NULL,app_secret=NULL WHERE id=?',(user,))

    def set_watch(self, user, code, name):
        with self.lock, self.conn:
            self.conn.execute('''INSERT INTO watched_stock VALUES (?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET stock_code=excluded.stock_code,
                stock_name=excluded.stock_name''', (user, code, name))

    def watch(self, user):
        with self.lock:
            row = self.conn.execute('SELECT stock_code,stock_name FROM watched_stock WHERE user_id=?',
                                    (user,)).fetchone()
            return {'code': row[0], 'name': row[1]} if row else None

    def active_watches(self):
        with self.lock:
            return [(row[0], row[1]) for row in self.conn.execute('''
                SELECT w.user_id, w.stock_code FROM watched_stock w
                JOIN profiles p ON p.id=w.user_id
                WHERE p.app_key IS NOT NULL AND p.app_secret IS NOT NULL
                AND EXISTS (SELECT 1 FROM sessions s WHERE s.user_id=w.user_id AND s.expires>?)''',
                (int(time.time()),))]

    def create_session(self, token_hash, user, ttl=31536000):
        with self.lock, self.conn:
            self.conn.execute('INSERT INTO sessions VALUES (?,?,?)',(token_hash,user,int(time.time())+ttl))

    def renew_session(self, token_hash, ttl=31536000):
        with self.lock, self.conn:
            self.conn.execute('UPDATE sessions SET expires=? WHERE token_hash=?',
                              (int(time.time())+ttl, token_hash))

    def session_user(self, token_hash):
        with self.lock:
            row = self.conn.execute('''SELECT s.user_id FROM sessions s
                JOIN profiles p ON p.id=s.user_id WHERE s.token_hash=? AND s.expires>?''',
                (token_hash,int(time.time()))).fetchone()
            return row[0] if row else None

    def end_session(self, token_hash):
        with self.lock, self.conn:
            self.conn.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash,))

    def save_rows(self, user, code, date, market, rows):
        with self.lock, self.conn:
            for r in rows:
                minute = r['tm'][:4]
                current = self.conn.execute('SELECT tm FROM minute_rows WHERE user_id=? AND stock_code=? AND trade_date=? AND market=? AND minute=?',
                                            (user,code,date,market,minute)).fetchone()
                if current and current['tm'] > r['tm']: continue
                self.conn.execute('''INSERT INTO minute_rows VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(user_id,stock_code,trade_date,market,minute) DO UPDATE SET
                    tm=excluded.tm,buy_amt=excluded.buy_amt,sell_amt=excluded.sell_amt,net_amt=excluded.net_amt''',
                    (user,code,date,market,minute,r['tm'],r['buy_amt'],r['sell_amt'],r['net_amt']))
            self.conn.execute('''INSERT INTO sync_state VALUES (?,?,?,?,?)
                ON CONFLICT(user_id,stock_code,trade_date,market) DO UPDATE SET synced_at=excluded.synced_at''',
                (user,code,date,market,int(time.time())))

    def last_sync(self, user, code, date, market):
        with self.lock:
            row = self.conn.execute('SELECT synced_at FROM sync_state WHERE user_id=? AND stock_code=? AND trade_date=? AND market=?',
                                    (user,code,date,market)).fetchone()
            return row[0] if row else None

    def rows(self, user, code, date):
        with self.lock:
            rows = self.conn.execute('''SELECT market,tm,buy_amt,sell_amt,net_amt FROM minute_rows
                WHERE user_id=? AND stock_code=? AND trade_date=? ORDER BY tm,market''',(user,code,date)).fetchall()
            return [dict(r) for r in rows]

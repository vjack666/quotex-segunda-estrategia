import sqlite3
conn = sqlite3.connect('trade_journal.db')
c = conn.cursor()
print('=== TABLAS EN LA BD ===')
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for table in c.fetchall():
    print(f'\nTabla: {table[0]}')
    c.execute(f"PRAGMA table_info({table[0]})")
    for col in c.fetchall():
        print(f'  {col[1]}: {col[2]}')
conn.close()

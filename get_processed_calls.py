#!/usr/bin/env python3
"""
Показать все обработанные звонки из БД
"""
import sqlite3
import json

conn = sqlite3.connect('/root/salesbot-mvp/salesbot.db')
cursor = conn.cursor()

cursor.execute('''
SELECT 
    m.name AS manager_name,
    c.amocrm_lead_id AS lead_id,
    c.client_phone,
    datetime(c.created_at) AS call_date,
    c.duration_seconds,
    c.quality_score,
    c.transcription_text
FROM calls c
JOIN managers m ON m.id = c.manager_id
WHERE c.transcription_text IS NOT NULL 
  AND c.quality_score IS NOT NULL
  AND c.amocrm_lead_id IS NOT NULL
ORDER BY c.created_at DESC
LIMIT 20
''')

calls = []
for row in cursor.fetchall():
    calls.append({
        'manager_name': row[0],
        'lead_id': row[1],
        'phone': row[2],
        'date': row[3],
        'duration': row[4],
        'quality_score': row[5],
        'transcription': row[6]
    })

print(json.dumps(calls, ensure_ascii=False, indent=2))
conn.close()

from pathlib import Path
from dotenv import load_dotenv
import os
import pymysql

load_dotenv()

conn = pymysql.connect(
    host=os.getenv("DB_HOST"),
    port=int(os.getenv("DB_PORT", 3306)),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)

schema_sql = Path("src/database/schema.sql").read_text(encoding="utf-8")

# Split into two sections: before and after the DELIMITER block
parts = schema_sql.split("DELIMITER $$")

# regular statements (before DELIMITER $$)
cursor = conn.cursor()
for statement in parts[0].split(";"):
    stmt = statement.strip()
    if stmt:
        cursor.execute(stmt)
        print(f"  ✔ {stmt[:80]}...")
conn.commit()

#  stored procedure blocks 
if len(parts) > 1:
    for proc_block in parts[1:]:
        proc_block = proc_block.replace("DELIMITER ;", "")
        for proc in proc_block.split("$$"):
            stmt = proc.strip()
            if stmt:
                cursor.execute(stmt)
                print(f"  ✔ {stmt[:80]}...")
    conn.commit()

cursor.close()
conn.close()
print("\n Schema created successfully!")

from dotenv import load_dotenv; load_dotenv()
import os
from sqlalchemy import create_engine, text

url = os.environ['DATABASE_URL']
url = url.replace('postgresql+asyncpg://', 'postgresql://')
if not url.startswith('postgresql+psycopg2://'):
    url = url.replace('postgresql://', 'postgresql+psycopg2://', 1)

engine = create_engine(url, echo=False)
with engine.connect() as c:
    q = """
        SELECT t.typname, e.enumlabel
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        ORDER BY t.typname, e.enumsortorder
    """
    rows = c.execute(text(q)).fetchall()
    current = None
    for typname, label in rows:
        if typname != current:
            print(f"\n{typname}:")
            current = typname
        print(f"  - {label!r}")

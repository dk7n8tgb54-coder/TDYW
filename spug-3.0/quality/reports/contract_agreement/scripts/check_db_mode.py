import os

import pymysql

conn = pymysql.connect(
    host=os.environ['MYSQL_HOST'],
    user=os.environ['MYSQL_USER'],
    password=os.environ['MYSQL_PASSWORD'],
    database=os.environ['MYSQL_DATABASE'],
)
cur = conn.cursor()
cur.execute('SELECT @@sql_mode, @@version')
print('SQL_MODE:', cur.fetchone())
for column in ('contract_name', 'contract_no', 'signing_party'):
    cur.execute('SHOW COLUMNS FROM tdyw_contract_agreement LIKE %s', (column,))
    print('COLUMN', column, ':', cur.fetchone())
conn.close()

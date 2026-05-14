import os
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- הגדרות ---
MORNING_ID = os.environ.get('MORNING_ID')
MORNING_SECRET = os.environ.get('MORNING_SECRET')
GOOGLE_CREDENTIALS_FILE = 'google_secret.json'

SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1_JbtThIfDSDpKW1gd5jNBFAp6bV0-pVntVJLqNbczIw/edit?gid=0#gid=0' 
WORKSHEET_NAME = 'Retainers Dashboard' 

# --- ניהול סטטוסים ידני ---
# הכנס כאן שמות לקוחות בדיוק כפי שהם מופיעים בשיטס
FROZEN_CLIENTS = [] 
EXPIRED_CLIENTS = [] 

def get_morning_token():
    url = "https://api.greeninvoice.co.il/api/v1/account/token"
    payload = {"id": MORNING_ID, "secret": MORNING_SECRET}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    data = response.json()
    return data.get('token') or data.get('jwt')

def fetch_morning_data(token):
    url = "https://api.greeninvoice.co.il/api/v1/documents/search"
    headers = {"Authorization": f"Bearer {token}"}
    # חוזרים להגדרות הבסיסיות והבטוחות - מיוני 2024
    payload = {
        "page": 1, "pageSize": 100, "type": [320, 330],
        "date": {"from": "2024-06-01", "to": f"{datetime.now().year}-12-31"}
    }
    all_docs = []
    while True:
        res = requests.post(url, headers=headers, json=payload).json()
        if 'items' not in res or not res['items']: break
        all_docs.extend(res['items'])
        if res.get('page', 1) >= res.get('pages', 1): break
        payload['page'] += 1
    return all_docs

def process_data(docs):
    # ציר זמן מיוני 2024
    all_months = pd.date_range(start="2024-06-01", end=datetime.now(), freq='MS').strftime('%Y-%m-01').tolist()
    
    doc_data = []
    for doc in docs:
        client_name = doc.get('client', {}).get('name', 'לקוח כללי').strip()
        doc_data.append({
            "Name": client_name,
            "Month": f"{datetime.strptime(doc['documentDate'], '%Y-%m-%d').year}-{datetime.strptime(doc['documentDate'], '%Y-%m-%d').month:02d}-01",
            "Amount": doc.get('amount', 0),
            "Currency": doc.get('currency', 'ILS')
        })
    
    df = pd.DataFrame(doc_data)
    if df.empty: return pd.DataFrame()

    # פורמט מטבע פשוט
    def format_val(row):
        if row['Currency'] == 'USD': return f"${row['Amount']}"
        if row['Currency'] == 'EUR': return f"€{row['Amount']}"
        return row['Amount']
    
    df['Val'] = df.apply(format_val, axis=1)
    
    # יצירת טבלה - לוקחים רק ערך אחד כדי למנוע חיבורים כפולים
    pivot_df = df.pivot_table(index='Name', columns='Month', values='Val', aggfunc='first')
    
    # סידור עמודות
    pivot_df = pivot_df.reindex(columns=all_months).fillna("")
    
    # סטטוסים ומיון
    def get_status(name):
        if name in FROZEN_CLIENTS: return 'מוקפא'
        if name in EXPIRED_CLIENTS: return 'הסתיים'
        return 'פעיל'
    
    pivot_df.insert(0, 'Status', [get_status(name) for name in pivot_df.index])
    pivot_df.reset_index(inplace=True)
    pivot_df.rename(columns={'index': 'Name'}, inplace=True)

    rank_map = {'פעיל': 1, 'מוקפא': 2, 'הסתיים': 3}
    pivot_df['rank'] = pivot_df['Status'].map(rank_map)
    pivot_df = pivot_df.sort_values(by=['rank', 'Name']).drop(columns=['rank'])
    
    return pivot_df

def update_google_sheets(df):
    if df.empty: return
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(SPREADSHEET_URL)
    worksheet = sheet.worksheet(WORKSHEET_NAME)
    
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    print(f"Successfully updated {len(df)} rows starting from June 2024.")

def main():
    token = get_morning_token()
    docs = fetch_morning_data(token)
    df = process_data(docs)
    update_google_sheets(df)

if __name__ == "__main__":
    main()

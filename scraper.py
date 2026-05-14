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

# סטטוסים ידניים - הכנס שמות כאן
FROZEN_CLIENTS = [] 
EXPIRED_CLIENTS = [] 

def get_morning_token():
    url = "https://api.greeninvoice.co.il/api/v1/account/token"
    res = requests.post(url, json={"id": MORNING_ID, "secret": MORNING_SECRET})
    res.raise_for_status()
    return res.json().get('token') or res.json().get('jwt')

def main():
    token = get_morning_token()
    # שליפה פשוטה ונקייה מיוני 2024 בלבד
    url = "https://api.greeninvoice.co.il/api/v1/documents/search"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "page": 1, "pageSize": 100, "type": [320, 330],
        "date": {"from": "2024-06-01", "to": "2026-12-31"}
    }
    
    docs = requests.post(url, headers=headers, json=payload).json().get('items', [])
    
    if not docs:
        print("No documents found.")
        return

    # עיבוד נתונים בסיסי
    data = []
    for d in docs:
        data.append({
            "Name": d['client']['name'].strip(),
            "Month": f"{datetime.strptime(d['documentDate'], '%Y-%m-%d').year}-{datetime.strptime(d['documentDate'], '%Y-%m-%d').month:02d}-01",
            "Amount": d['amount']
        })
    
    df = pd.DataFrame(data).pivot_table(index='Name', columns='Month', values='Amount', aggfunc='sum')
    
    # יצירת ציר זמן מיוני 2024
    months = pd.date_range(start="2024-06-01", end=datetime.now(), freq='MS').strftime('%Y-%m-01').tolist()
    df = df.reindex(columns=months).fillna("")
    
    # הוספת סטטוס
    df.insert(0, 'Status', [('מוקפא' if n in FROZEN_CLIENTS else 'הסתיים' if n in EXPIRED_CLIENTS else 'פעיל') for n in df.index])
    df.reset_index(inplace=True)

    # עדכון גוגל שיטס
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    worksheet = client.open_by_url(SPREADSHEET_URL).worksheet(WORKSHEET_NAME)
    
    # ניקוי אגרסיבי - מוחק את כל התאים בגיליון כדי להעיף את עמודה O
    worksheet.clear()
    
    # כתיבה
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    print("Done. Check the sheet now.")

if __name__ == "__main__":
    main()

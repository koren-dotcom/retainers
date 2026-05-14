import os
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
from gspread_formatting import *

# --- הגדרות ---
MORNING_ID = os.environ.get('MORNING_ID')
MORNING_SECRET = os.environ.get('MORNING_SECRET')
GOOGLE_CREDENTIALS_FILE = 'google_secret.json'

SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1_JbtThIfDSDpKW1gd5jNBFAp6bV0-pVntVJLqNbczIw/edit?gid=0#gid=0' 
WORKSHEET_NAME = 'Retainers Dashboard' 

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
    payload = {
        "page": 1, "pageSize": 100, "type": [305, 320, 330],
        "date": {"from": "2023-06-01", "to": f"{datetime.now().year}-12-31"}
    }
    all_docs = []
    while True:
        res = requests.post(url, headers=headers, json=payload).json()
        if 'items' not in res or not res['items']: break
        all_docs.extend(res['items'])
        if res.get('page', 1) >= res.get('pages', 1): break
        payload['page'] += 1
    print(f"DEBUG: Found {len(all_docs)} documents.")
    return all_docs

def fetch_retainer_statuses(token):
    url = "https://api.greeninvoice.co.il/api/v1/retainers/search"
    headers = {"Authorization": f"Bearer {token}"}
    # בקשה מפורשת למשוך את כל הסטטוסים
    payload = {
        "page": 1, 
        "pageSize": 100,
        "status": [1, 2, 3] # 1=פעיל, 2=מוקפא, 3=הסתיים
    }
    statuses = {}
    while True:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"DEBUG API ERROR: {response.text}")
            break
            
        res = response.json()
        items = res.get('items', [])
        for item in items:
            client_name = item.get('client', {}).get('name', '').strip()
            status_code = item.get('status')
            statuses[client_name] = status_code
            
        if res.get('page', 1) >= res.get('pages', 1): break
        payload['page'] += 1
        
    # הדפסת השמות שנמצאו כדי שנוכל לראות בדיוק מי אותר
    print(f"DEBUG: Found {len(statuses)} retainers. Names: {list(statuses.keys())}")
    return statuses

def process_data(docs, statuses):
    all_months = pd.date_range(start="2023-06-01", end=datetime.now(), freq='MS').strftime('%Y-%m-01').tolist()
    
    if docs:
        doc_data = []
        for doc in docs:
            client_name = doc.get('client', {}).get('name', 'לקוח כללי').strip()
            doc_data.append({
                "Name": client_name,
                "Month": f"{datetime.strptime(doc['documentDate'], '%Y-%m-%d').year}-{datetime.strptime(doc['documentDate'], '%Y-%m-%d').month:02d}-01",
                "Amount": doc.get('amount', 0),
                "Currency": doc.get('currency', 'ILS')
            })
        df_docs = pd.DataFrame(doc_data)
        
        def format_val(row):
            if row['Currency'] == 'USD': return f"${row['Amount']}"
            if row['Currency'] == 'EUR': return f"€{row['Amount']}"
            return row['Amount']
        df_docs['Val'] = df_docs.apply(format_val, axis=1)
        
        pivot_df = df_docs.pivot_table(index='Name', columns='Month', values='Val', aggfunc=lambda x: ' + '.join(map(str, x)) if len(x) > 1 else x.iloc[0])
    else:
        pivot_df = pd.DataFrame(index=list(statuses.keys()))

    all_clients = set(pivot_df.index).union(set(statuses.keys()))
    pivot_df = pivot_df.reindex(index=list(all_clients), columns=all_months).fillna("")
    
    status_map = {1: 'פעיל', 2: 'מוקפא', 3: 'הסתיים'}
    pivot_df.insert(0, 'Status', [status_map.get(statuses.get(name), 'לא הוגדר') for name in pivot_df.index])
    pivot_df.reset_index(inplace=True)
    pivot_df.rename(columns={'index': 'Name'}, inplace=True)

    rank_map = {'פעיל': 1, 'מוקפא': 2, 'הסתיים': 3, 'לא הוגדר': 4}
    pivot_df['rank'] = pivot_df['Status'].map(rank_map)
    pivot_df = pivot_df.sort_values(by=['rank', 'Name']).drop(columns=['rank'])
    
    return pivot_df

def update_google_sheets(df):
    if df.empty:
        print("DEBUG: No data to update.")
        return
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(SPREADSHEET_URL)
    worksheet = sheet.worksheet(WORKSHEET_NAME)
    
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    
    colors = {
        'פעיל': Color(0.717, 0.882, 0.804),
        'מוקפא': Color(0.956, 0.780, 0.764),
        'הסתיים': Color(0.937, 0.937, 0.937)
    }
    fmt_rules = []
    for i, row in df.iterrows():
        status = row['Status']
        if status in colors:
            row_idx = i + 2
            fmt_rules.append((f"A{row_idx}:AZ{row_idx}", cellFormat(backgroundColor=colors[status])))
    
    if fmt_rules:
        batch_format(worksheet, fmt_rules)
    print(f"DEBUG: Successfully updated {len(df)} rows.")

def main():
    token = get_morning_token()
    docs = fetch_morning_data(token)
    statuses = fetch_retainer_statuses(token)
    df = process_data(docs, statuses)
    update_google_sheets(df)

if __name__ == "__main__":
    main()

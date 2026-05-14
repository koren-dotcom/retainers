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

# הלינק המובנה לבקשתך
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
    # הוספנו סוג 305 (קבלה) כדי לוודא שכל העברה מ-2023 נתפסת
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
    print(f"Found {len(all_docs)} documents.")
    return all_docs

def fetch_retainer_statuses(token):
    url = "https://api.greeninvoice.co.il/api/v1/retainers/search"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"page": 1, "pageSize": 100}
    statuses = {}
    
    while True:
        res = requests.post(url, headers=headers, json=payload).json()
        for item in res.get('items', []):
            client_name = item.get('client', {}).get('name')
            # 1=Active, 2=Paused, 3=Expired/Completed
            status_code = item.get('status')
            statuses[client_name] = status_code
        
        if res.get('page', 1) >= res.get('pages', 1): break
        payload['page'] += 1
        
    return statuses

def process_data(docs, statuses):
    if not docs: return pd.DataFrame()
    
    data = []
    for doc in docs:
        client_name = doc.get('client', {}).get('name', 'לקוח כללי')
        data.append({
            "Name": client_name,
            "Month": f"{datetime.strptime(doc['documentDate'], '%Y-%m-%d').year}-{datetime.strptime(doc['documentDate'], '%Y-%m-%d').month:02d}-01",
            "Amount": doc.get('amount', 0),
            "Currency": doc.get('currency', 'ILS')
        })
    
    df = pd.DataFrame(data)
    agg_df = df.groupby(['Name', 'Month', 'Currency'])['Amount'].sum().reset_index()
    
    def format_val(row):
        if row['Currency'] == 'USD': return f"${row['Amount']}"
        if row['Currency'] == 'EUR': return f"€{row['Amount']}"
        return row['Amount']
    agg_df['Val'] = agg_df.apply(format_val, axis=1)

    pivot_df = agg_df.pivot_table(index='Name', columns='Month', values='Val', aggfunc=lambda x: ' + '.join(map(str, x)) if len(x) > 1 else x.iloc[0])
    
    all_months = pd.date_range(start="2023-06-01", end=datetime.now(), freq='MS').strftime('%Y-%m-01').tolist()
    pivot_df = pivot_df.reindex(columns=all_months).fillna("")
    
    # הוספת סטטוס עם לוגיקה גמישה לשמות (strip להסרת רווחים מיותרים)
    status_map = {1: 'פעיל', 2: 'מוקפא', 3: 'הסתיים'}
    pivot_df.insert(0, 'Status', pivot_df.index.map(lambda x: status_map.get(statuses.get(x.strip()), 'לא מוגדר')))
    pivot_df.reset_index(inplace=True)

    # --- מיון מותאם אישית ---
    # דירוג: פעיל=1, מוקפא=2, הסתיים=3, לא מוגדר=4
    rank_map = {'פעיל': 1, 'מוקפא': 2, 'הסתיים': 3, 'לא מוגדר': 4}
    pivot_df['rank'] = pivot_df['Status'].map(rank_map)
    
    # מיון לפי הדירוג ואז אלפבתי לפי שם הלקוח
    pivot_df = pivot_df.sort_values(by=['rank', 'Name']).drop(columns=['rank'])
    
    return pivot_df

def apply_formatting(worksheet, df):
    colors = {
        'פעיל': Color(0.717, 0.882, 0.804),   # ירוק
        'מוקפא': Color(0.956, 0.780, 0.764),  # אדום/ורוד
        'הסתיים': Color(0.937, 0.937, 0.937)  # אפור
    }
    
    fmt_rules = []
    for i, row in df.iterrows():
        status = row['Status']
        if status in colors:
            row_idx = i + 2 # שורה 1 היא כותרת
            # צביעה של כל השורה (עד עמודה Z לביטחון)
            fmt_rules.append((f"A{row_idx}:Z{row_idx}", cellFormat(backgroundColor=colors[status])))
    
    if fmt_rules:
        batch_format(worksheet, fmt_rules)

def update_google_sheets(df):
    if df.empty: return
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(SPREADSHEET_URL)
    worksheet = sheet.worksheet(WORKSHEET_NAME)
    
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    apply_formatting(worksheet, df)
    print("Dashboard updated and sorted successfully.")

def main():
    print("Starting sync...")
    token = get_morning_token()
    docs = fetch_morning_data(token)
    statuses = fetch_retainer_statuses(token)
    df = process_data(docs, statuses)
    update_google_sheets(df)

if __name__ == "__main__":
    main()

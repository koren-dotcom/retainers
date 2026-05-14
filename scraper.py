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

# הכנס כאן את הלינק ואת שם הלשונית
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1_JbtThIfDSDpKW1gd5jNBFAp6bV0-pVntVJLqNbczIw/edit?gid=0#gid=0' 
WORKSHEET_NAME = 'Retainers Dashboard' 

def get_morning_token():
    url = "https://api.greeninvoice.co.il/api/v1/account/token"
    payload = {"id": MORNING_ID, "secret": MORNING_SECRET}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    
    data = response.json()
    if 'token' in data:
        return data['token']
    elif 'jwt' in data:
        return data['jwt']
    else:
        print("API Response Error:", data)
        raise ValueError("Token not found in response.")

def fetch_morning_data(token):
    url = "https://api.greeninvoice.co.il/api/v1/documents/search"
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "page": 1,
        "pageSize": 100,
        "type": [320, 330],
        "date": {
            "from": "2023-06-01", 
            "to": f"{datetime.now().year}-12-31"
        }
    }
    
    all_docs = []
    while True:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"API Error {response.status_code}: {response.text}")
            break
            
        res = response.json()
        if 'items' not in res or not res['items']:
            break
            
        all_docs.extend(res['items'])
        
        if res.get('page', 1) >= res.get('pages', 1):
            break
            
        payload['page'] += 1
        
    print(f"Found {len(all_docs)} documents!")
    return all_docs

def process_data(docs):
    if not docs:
        return pd.DataFrame()
        
    data = []
    for doc in docs:
        client_name = doc.get('client', {}).get('name', 'לקוח כללי')
        amount = doc.get('amount', 0)
        currency = doc.get('currency', 'ILS')
        date_str = doc.get('documentDate') 
        
        doc_date = datetime.strptime(date_str, '%Y-%m-%d')
        month_col = f"{doc_date.year}-{doc_date.month:02d}-01"
        
        data.append({"Name": client_name, "Month": month_col, "Amount": amount, "Currency": currency})
        
    df = pd.DataFrame(data)
    
    if df.empty:
        return pd.DataFrame()
        
    agg_df = df.groupby(['Name', 'Month', 'Currency'])['Amount'].sum().reset_index()
    
    def format_currency(row):
        if row['Currency'] == 'USD':
            return f"${row['Amount']}"
        elif row['Currency'] == 'EUR':
            return f"€{row['Amount']}"
        return row['Amount']
        
    agg_df['Formatted'] = agg_df.apply(format_currency, axis=1)
    
    def custom_agg(series):
        if len(series) == 1:
            return series.iloc[0]
        return ' + '.join(str(v) for v in series)
        
    pivot_df = agg_df.pivot_table(index='Name', columns='Month', values='Formatted', aggfunc=custom_agg)
    pivot_df = pivot_df.reindex(sorted(pivot_df.columns), axis=1)
    pivot_df = pivot_df.fillna("")
    pivot_df.reset_index(inplace=True)
    
    return pivot_df

def update_google_sheets(df):
    if df.empty:
        print("No data to update.")
        return
        
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    
    sheet = client.open_by_url(SPREADSHEET_URL)
    worksheet = sheet.worksheet(WORKSHEET_NAME)
    
    worksheet.clear()
    worksheet.update([df.columns.values.tolist()] + df.values.tolist())
    print("Google Sheet updated successfully!")

def main():
    print("Getting Token...")
    token = get_morning_token()
    print("Fetching data...")
    docs = fetch_morning_data(token)
    print("Processing data...")
    df = process_data(docs)
    print("Updating Google Sheets...")
    update_google_sheets(df)

if __name__ == "__main__":
    main()

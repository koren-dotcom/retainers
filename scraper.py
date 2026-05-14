import os
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- הגדרות משתני סביבה (לא להכניס מפתחות ישירות לקוד!) ---
MORNING_ID = os.environ.get('MORNING_ID')
MORNING_SECRET = os.environ.get('MORNING_SECRET')
GOOGLE_CREDENTIALS_FILE = 'google_secret.json' # בגיטהאב נייצר את זה דינמית, מקומית שים את הקובץ פה
SPREADSHEET_URL = 'כאן_שים_את_הלינק_לגוגל_שיטס_שלך'
WORKSHEET_NAME = 'דשבורד לקוחות ריטיינר'

def get_morning_token():
    url = "https://api.greeninvoice.co.il/api/v1/account/token"
    payload = {"id": MORNING_ID, "secret": MORNING_SECRET}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    return response.json()['jwt']

def fetch_morning_data(token):
    # משיכת מסמכים מהשנה האחרונה (אפשר לשנות תאריכים לפי הצורך)
    url = "https://api.greeninvoice.co.il/api/v1/documents"
    headers = {"Authorization": f"Bearer {token}"}
    
    # חיפוש חשבוניות מס קבלה / חשבוניות מס
    payload = {
        "page": 1,
        "pageSize": 100,
        "type": [305, 320], # סוגי מסמכים נפוצים להכנסות
        "date": {
            "from": f"{datetime.now().year}-01-01", 
            "to": f"{datetime.now().year}-12-31"
        }
    }
    
    all_docs = []
    while True:
        res = requests.post(url, headers=headers, json=payload).json()
        if 'items' not in res or not res['items']:
            break
        all_docs.extend(res['items'])
        if res['page'] == res['pages']: # הגענו לעמוד האחרון
            break
        payload['page'] += 1
        
    return all_docs

def process_data(docs):
    if not docs:
        return pd.DataFrame()
        
    # הוצאת דאטא רלוונטי
    data = []
    for doc in docs:
        client_name = doc.get('client', {}).get('name', 'לקוח כללי')
        amount = doc.get('amount', 0)
        date_str = doc.get('documentDate') # מגיע בפורמט YYYY-MM-DD
        
        # המרה לתחילת החודש כדי שיתאים לעמודות באקסל שלך (למשל 2023-01-01)
        doc_date = datetime.strptime(date_str, '%Y-%m-%d')
        month_col = f"{doc_date.year}-{doc_date.month:02d}-01"
        
        data.append({"Name": client_name, "Month": month_col, "Amount": amount})
        
    df = pd.DataFrame(data)
    
    # יצירת טבלת ציר (Pivot) - שורות לקוחות, עמודות חודשים, סיכום סכומים
    pivot_df = df.pivot_table(index='Name', columns='Month', values='Amount', aggfunc='sum', fill_value=0)
    pivot_df.reset_index(inplace=True)
    
    return pivot_df

def update_google_sheets(df):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    
    sheet = client.open_by_url(SPREADSHEET_URL)
    worksheet = sheet.worksheet(WORKSHEET_NAME)
    
    # ניקוי הגיליון והכנסת הנתונים המעודכנים
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
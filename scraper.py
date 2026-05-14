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
SPREADSHEET_URL = 'https://docs.google.com/spreadsheets/d/1_JbtThIfDSDpKW1gd5jNBFAp6bV0-pVntVJLqNbczIw/edit?gid=0#gid=0'
WORKSHEET_NAME = 'Retainers Dashboard'

def get_morning_token():
    url = "https://api.greeninvoice.co.il/api/v1/account/token"
    payload = {"id": MORNING_ID, "secret": MORNING_SECRET}
    response = requests.post(url, json=payload)
    response.raise_for_status()
    
    data = response.json()
    
    # שליפת הטוקן בהתאם למפתח שהשרת מחזיר
    if 'token' in data:
        return data['token']
    elif 'jwt' in data:
        return data['jwt']
    else:
        # במקרה שפרטי ההתחברות שגויים, נדפיס את תשובת השרת ללוג
        print("API Response Error:", data)
        raise ValueError("Token not found in response. Please verify MORNING_ID and MORNING_SECRET in GitHub Secrets.")

def fetch_morning_data(token):
    # הוספנו /search בסוף כדי לפנות לנתיב החיפוש הנכון
    url = "https://api.greeninvoice.co.il/api/v1/documents/search"
    headers = {"Authorization": f"Bearer {token}"}
    
    # חיפוש מ-2023 ועד סוף השנה הנוכחית
    payload = {
        "page": 1,
        "pageSize": 100,
        "type": [320, 330], # 320: חשבונית מס, 330: חשבונית מס קבלה
        "date": {
            "from": "2023-01-01", 
            "to": f"{datetime.now().year}-12-31"
        }
    }
    
    all_docs = []
    while True:
        response = requests.post(url, headers=headers, json=payload)
        
        # אם יש שגיאה בבקשה, נדפיס אותה כדי לדעת למה נפל
        if response.status_code != 200:
            print(f"API Error {response.status_code}: {response.text}")
            break
            
        res = response.json()
        if 'items' not in res or not res['items']:
            break
            
        all_docs.extend(res['items'])
        
        # מנגנון המעבר בין עמודים (Pagination)
        if res.get('page', 1) >= res.get('pages', 1):
            break
            
        payload['page'] += 1
        
    print(f"Found {len(all_docs)} documents!") # מדפיס את הכמות האמיתית שנמצאה
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

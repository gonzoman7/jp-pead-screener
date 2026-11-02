import os
import requests
import pandas as pd

# GitHub SecretsからAPIキーとSlack Webhookを取得
JQUANTS_API_KEY = os.environ.get("JQUANTS_API_KEY")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

def send_slack_notification(message):
    """Slackに通知を送信する"""
    if not SLACK_WEBHOOK_URL:
        print("Slack Webhook URLが設定されていません。")
        return
    payload = {"text": message}
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code != 200:
        print(f"Slack通知エラー: {response.text}")

def get_id_token(api_key):
    """APIキーを使用してIDトークンを取得する (J-Quants V2 認証フロー)"""
    auth_url = f"https://api.jquants.com/v1/token/auth_key?key={api_key}"
    response = requests.post(auth_url)
    if response.status_code == 200:
        return response.json().get("idToken")
    else:
        print(f"IDトークン取得エラー ({response.status_code}): {response.text}")
        return None

def fetch_listed_companies(headers):
    """上場銘柄一覧を取得する"""
    url = "https://api.jquants.com/v1/listed/info"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("info", [])
    else:
        print(f"銘柄一覧取得エラー ({response.status_code}): {response.text}")
        return []

def fetch_daily_prices(headers, code):
    """指定銘柄の日足株価データを取得する"""
    url = f"https://api.jquants.com/v1/prices/daily_quotes?code={code}"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json().get("daily_quotes", [])
        if data:
            df = pd.DataFrame(data)
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
            return df
    return pd.DataFrame()

def run_pead_screener():
    print("PEADスクリーニングを開始します (J-Quants API V2)...")
    
    if not JQUANTS_API_KEY:
        error_msg = "❌ 【PEADスクリーニング エラー】JQUANTS_API_KEY が設定されていません。"
        print(error_msg)
        send_slack_notification(error_msg)
        return

    # 1. APIキーからIDトークンを取得
    id_token = get_id_token(JQUANTS_API_KEY)
    if not id_token:
        error_msg = "❌ 【PEADスクリーニング エラー】J-QuantsのIDトークン取得に失敗しました（APIキーをご確認ください）。"
        print(error_msg)
        send_slack_notification(error_msg)
        return

    # 2. 取得したIDトークンをBearer認証ヘッダーにセット
    headers = {"Authorization": f"Bearer {id_token}"}
    
    companies = fetch_listed_companies(headers)
    if not companies:
        error_msg = "⚠️ 【PEADスクリーニング】銘柄情報の取得に失敗しました。"
        send_slack_notification(error_msg)
        return

    hit_stocks = []

    # テストとして最初の50件を処理
    for company in companies[:50]:
        code = company.get("Code")
        name = company.get("CompanyName")
        
        df_prices = fetch_daily_prices(headers, code)
        if df_prices.empty or len(df_prices) < 40:
            continue
            
        recent_window = df_prices.tail(30)
        if len(recent_window) < 20:
            continue
            
        initial_period = recent_window.iloc[-20:-10]
        if initial_period.empty:
            continue
            
        initial_high = initial_period['High'].max()
        current_close = recent_window.iloc[-1]['Close']
        base_price = recent_window.iloc[-30]['Close']
        
        is_digesting_well = (current_close >= initial_high * 0.85) and (current_close > base_price * 1.05)
        
        if is_digesting_well:
            hit_stocks.append({
                "code": code,
                "name": name,
                "current_close": current_close,
                "initial_high": initial_high
            })

    if hit_stocks:
        msg = "🎯 【PEADスクリーニング通知 (売りこなし・トレンド継続)】\n"
        for s in hit_stocks:
            msg += f"• {s['code']} {s['name']} (現在値: {s['current_close']}円)\n"
        send_slack_notification(msg)
        print("Slackへヒット通知を送信しました。")
    else:
        msg = "ℹ️ 【PEADスクリーニング通知】本日の条件に一致する銘柄はありませんでした。"
        send_slack_notification(msg)
        print("Slackへ完了通知（0件）を送信しました。")

if __name__ == "__main__":
    run_pead_screener()

import os
import requests
import pandas as pd
from datetime import datetime, timedelta

# 環境変数から認証情報とWebhookを取得
JQUANTS_MAIL = os.environ.get("JQUANTS_MAIL")
JQUANTS_PASSWORD = os.environ.get("JQUANTS_PASSWORD")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

def get_jquants_id_token():
    """J-Quants APIのIDトークンを取得する"""
    url = "https://api.jquants.com/v1/token/auth_user"
    payload = {
        "mailaddress": JQUANTS_MAIL,
        "password": JQUANTS_PASSWORD
    }
    response = requests.post(url, json=payload)
    if response.status_code == 200:
        return response.json().get("idToken")
    else:
        raise Exception(f"J-Quants認証エラー: {response.status_code} - {response.text}")

def send_slack_notification(message):
    """Slackに通知を送信する"""
    if not SLACK_WEBHOOK_URL:
        print("Slack Webhook URLが設定されていません。")
        return
    payload = {"text": message}
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code != 200:
        print(f"Slack通知エラー: {response.text}")

def fetch_listed_companies(headers):
    """上場銘柄一覧を取得する"""
    url = "https://api.jquants.com/v1/listed/info"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("info", [])
    else:
        print(f"銘柄一覧取得エラー: {response.text}")
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
    print("PEADスクリーニングを開始します（2〜3週間の売りこなし・トレンド継続判定）...")
    
    try:
        id_token = get_jquants_id_token()
    except Exception as e:
        error_msg = f"❌ 【PEADスクリーニング エラー】\n{str(e)}"
        print(e)
        send_slack_notification(error_msg)
        return

    headers = {"Authorization": f"Bearer {id_token}"}
    
    companies = fetch_listed_companies(headers)
    if not companies:
        print("銘柄情報を取得できませんでした。")
        send_slack_notification("⚠️ 【PEADスクリーニング】銘柄情報の取得に失敗しました。")
        return

    hit_stocks = []

    for company in companies[:50]:  # テスト用件数
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

    # 【変更点】ヒット銘柄の有無に関わらず、必ずSlackへ結果を通知する
    if hit_stocks:
        msg = "🎯 【PEADスクリーニング通知 (2〜3週間経過・売りこなし完了銘柄)】\n"
        for s in hit_stocks:
            msg += f"• {s['code']} {s['name']} (現在値: {s['current_close']}円)\n"
        send_slack_notification(msg)
        print("Slackへ通知を送信しました（ヒット銘柄あり）。")
    else:
        msg = "ℹ️ 【PEADスクリーニング通知】本日の条件に一致する銘柄はありませんでした。"
        send_slack_notification(msg)
        print("条件に一致する銘柄はありませんでしたが、Slackへ完了通知を送信しました。")

if __name__ == "__main__":
    run_pead_screener()

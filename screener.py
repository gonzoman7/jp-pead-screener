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
        print(e)
        return

    headers = {"Authorization": f"Bearer {id_token}"}
    
    # 上場銘柄の取得（必要に応じて対象を絞り込み可能）
    companies = fetch_listed_companies(headers)
    if not companies:
        print("銘柄情報を取得できませんでした。")
        return

    hit_stocks = []

    # ※サンプルとして上位銘柄、または全銘柄をループ（API制限やテスト時はスライス等で調整してください）
    for company in companies[:50]:  # まずは動作確認を兼ねて上位50件でテスト
        code = company.get("Code")
        name = company.get("CompanyName")
        
        df_prices = fetch_daily_prices(headers, code)
        if df_prices.empty or len(df_prices) < 40:
            continue
            
        # 【仮定】直近の決算発表日をシミュレーション、または財務API等から取得した発表日を利用
        # ここでは直近の大きな窓開けやボラティリティ発生日、あるいはダミーの最新決算日を想定するロジックのベースを記載
        # ※実際のJ-Quants財務情報API等から取得した「DisclosureDate」に置き換えてご活用ください
        
        # 例として、直近25営業日以内のどこかを選択（実際には決算発表日リストと突合します）
        # ここでは簡易的に「直近10〜20営業日前」の期間に高値をつけていた銘柄をシミュレートする判定例
        
        recent_window = df_prices.tail(30) # 直近30営業日
        if len(recent_window) < 20:
            continue
            
        # 発表後（10〜20営業日前）の期間と、現在の位置関係を評価
        # 初動の高値（例：10〜20営業日前につけた高値）
        initial_period = recent_window.iloc[-20:-10]
        if initial_period.empty:
            continue
            
        initial_high = initial_period['High'].max()
        current_close = recent_window.iloc[-1]['Close']
        base_price = recent_window.iloc[-30]['Close'] # 基準となる発表前価格
        
        # 条件判定：
        # 1. 2週間前（10〜20営業日前）に高値をつけて以降、急落せずに踏みとどまっている（高値から-15%以内）
        # 2. 発表前の水準よりもしっかりと上を維持している（+5%以上）
        is_digesting_well = (current_close >= initial_high * 0.85) and (current_close > base_price * 1.05)
        
        if is_digesting_well:
            hit_stocks.append({
                "code": code,
                "name": name,
                "current_close": current_close,
                "initial_high": initial_high
            })

    # 結果をSlackへ通知
    if hit_stocks:
        msg = "🎯 【PEADスクリーニング通知 (2〜3週間経過・売りこなし完了銘柄)】\n"
        for s in hit_stocks:
            msg += f"• {s['code']} {s['name']} (現在値: {s['current_close']}円 / 初動高値圏クリア)\n"
        send_slack_notification(msg)
        print("Slackへ通知を送信しました。")
    else:
        print("条件に一致する銘柄はありませんでした。")

if __name__ == "__main__":
    run_pead_screener()

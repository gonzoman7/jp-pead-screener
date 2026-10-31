import os
import requests
import pandas as pd
from datetime import datetime

# Slack Notification Function
def send_slack_notification(message):
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        print("SLACK_WEBHOOK_URL is not set.")
        return
    
    payload = {"text": message}
    response = requests.post(webhook_url, json=payload)
    if response.status_code != 200:
        print(f"Failed to send Slack notification: {response.status_code}, {response.text}")

def main():
    print("Starting PEAD Screener...")
    # ここにスクリーニングのロジックやデータ取得処理を記述します
    
    # 動作確認用のテスト通知メッセージ
    today = datetime.now().strftime("%Y-%m-%d")
    message = f"*[jp-pead-screener]* {today}: スクリーナーのテスト実行が完了しました。"
    send_slack_notification(message)

if __name__ == "__main__":
    main()

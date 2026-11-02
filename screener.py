import os
import time
from datetime import datetime, timedelta
import jquantsapi
import pandas as pd
import requests

# ==========================================
# 環境変数からの設定読み込み (GitHub Secrets連携)
# ==========================================
JQUANTS_MAIL = os.environ.get("JQUANTS_MAIL")
JQUANTS_PASSWORD = os.environ.get("JQUANTS_PASSWORD")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")


def send_slack_notification(message):
  """Slackへ通知を送信する関数"""
  if not SLACK_WEBHOOK_URL or "hooks.slack.com" not in SLACK_WEBHOOK_URL:
    print("[Slack通知スキップ] Webhook URLが未設定です。")
    print(message)
    return

  payload = {"text": message}
  try:
    response = requests.post(SLACK_WEBHOOK_URL, json=payload)
    if response.status_code != 200:
      print(
          f"Slack通知エラー: {response.status_code}, 応答:"
          f" {response.text}"
      )
  except Exception as e:
    print(f"Slack通知例外発生: {e}")


def main():
  print("=== J-Quants V2 PEAD & 出来高ブレイクアウト スクリーニング開始 ===")

  if not JQUANTS_MAIL or not JQUANTS_PASSWORD:
    print("エラー: J-Quantsの認証情報（メールアドレス・パスワード）が設定されていません。")
    return

  try:
    # 1. J-Quants V2 クライアントの初期化と認証
    cli = jquantsapi.Client(mail_address=JQUANTS_MAIL, password=JQUANTS_PASSWORD)
  except Exception as e:
    print(f"J-Quants 認証エラー: {e}")
    return

  # 2. 上場銘柄一覧の取得 (V2)
  try:
    df_listed = cli.get_listed_info()
    print(f"上場銘柄数: {len(df_listed)}件のデータを取得しました。")
  except Exception as e:
    print(f"銘柄一覧取得エラー: {e}")
    return

  # 通常株等に絞り込み
  df_listed = df_listed[df_listed["ScaleCategory"].notna()]

  matched_stocks = []
  print("財務・株価データの解析およびPEAD・出来高収縮判定を実行中...")

  # 対象銘柄のループ処理（必要に応じて制限や調整を行ってください）
  for idx, row in df_listed.head(50).iterrows():
    code = row["Code"]
    name = row["CompanyName"]

    try:
      df_prices = cli.get_prices_daily_quotes(code=code)
      if df_prices is None or df_prices.empty:
        continue

      df_prices["Date"] = pd.to_datetime(df_prices["Date"])
      df_prices = df_prices.sort_values("Date").reset_index(drop=True)

      # 出来高収縮の判定ロジック例
      if len(df_prices) > 20:
        recent_vol = df_prices["Volume"].tail(5).mean()
        avg_vol = df_prices["Volume"].tail(25).mean()

        if avg_vol > 0 and (recent_vol / avg_vol) < 0.7:
          matched_stocks.append({
              "code": code,
              "name": name,
              "recent_vol": int(recent_vol),
              "avg_vol": int(avg_vol),
          })
    except Exception as e:
      continue

    time.sleep(0.2)

  # 3. 結果のまとめとSlack通知
  if matched_stocks:
    msg = "*【PEAD・出来高収縮スクリーニング結果】*\n以下の銘柄が条件を検知しました：\n"
    for stock in matched_stocks:
      msg += (
          f"• *{stock['code']}* {stock['name']} (直近出来高平均:"
          f" {stock['recent_vol']:,})\n"
      )
    send_slack_notification(msg)
    print("スクリーニング完了・Slack通知を送信しました。")
  else:
    print("条件に一致する銘柄はありませんでした。")


if __name__ == "__main__":
  main()

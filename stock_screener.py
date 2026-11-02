import os
import sys
import time
import traceback
import jquants_api_client
import pandas as pd
import requests

JQUANTS_API_KEY = os.environ.get("JQUANTS_API_KEY")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")


def send_slack_notification(message):
  if not SLACK_WEBHOOK_URL or "hooks.slack.com" not in SLACK_WEBHOOK_URL:
    print("[Slack通知スキップ] Webhook URLが未設定です。")
    print(message)
    return

  payload = {"text": message}
  try:
    response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    if response.status_code != 200:
      print(f"Slack通知エラー: {response.status_code}, 応答: {response.text}")
  except Exception as e:
    print(f"Slack通知例外発生: {e}")


def main():
  print("=== J-Quants API スクリーニング処理開始 ===")

  if not JQUANTS_API_KEY:
    print("【エラー】JQUANTS_API_KEY の環境変数が設定されていません。")
    sys.exit(1)

  try:
    print("J-Quants APIへ接続認証を試行中...")
    # 環境変数 JQUANTS_API_KEY を自動認識します
    cli = jquants_api_client.Client()
    print("認証成功しました。")
  except Exception as e:
    print(f"【認証エラー】J-Quantsへのログインに失敗しました: {e}")
    traceback.print_exc()
    sys.exit(1)

  try:
    print("上場銘柄一覧を取得中...")
    df_listed = cli.get_listed_info()
    if df_listed is None or df_listed.empty:
      print("【エラー】銘柄一覧が取得できませんでした（データが空です）。")
      sys.exit(1)
    print(f"取得成功: {len(df_listed)}件")
  except Exception as e:
    print(f"【エラー】銘柄一覧取得時に例外が発生しました: {e}")
    traceback.print_exc()
    sys.exit(1)

  if "ScaleCategory" in df_listed.columns:
    df_listed = df_listed[df_listed["ScaleCategory"].notna()]

  matched_stocks = []
  print(
      "株価データの解析および出来高収縮判定を実行中（上位30銘柄テスト）..."
  )

  for idx, row in df_listed.head(30).iterrows():
    code = row.get("Code")
    name = row.get("CompanyName", "名称不明")

    if not code:
      continue

    try:
      df_prices = cli.get_prices_daily_quotes(code=code)
      if df_prices is None or df_prices.empty:
        continue

      df_prices["Date"] = pd.to_datetime(df_prices["Date"])
      df_prices = df_prices.sort_values("Date").reset_index(drop=True)

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
      # 個別銘柄の取得エラーはスキップしつつログに残す
      print(f"[警告] 銘柄 {code} の処理中に例外: {e}")
      continue

    time.sleep(0.2)

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
    print(
        "条件に一致する銘柄はありませんでした（プログラムは正常に完走しました）。"
    )


if __name__ == "__main__":
  main()

import os
import sys
import time
import pandas as pd
import requests

JQUANTS_API_KEY = os.environ.get("JQUANTS_API_KEY")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

BASE_URL = "https://api.jquants.com/v1"


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
  print("=== J-Quants API (APIキー認証) スクリーニング処理開始 ===")

  if not JQUANTS_API_KEY:
    print("【エラー】JQUANTS_API_KEY の環境変数が設定されていません。")
    sys.exit(1)

  # APIキー認証ヘッダー
  headers = {"x-api-key": JQUANTS_API_KEY}

  try:
    print("上場銘柄一覧を取得中...")
    res = requests.get(f"{BASE_URL}/listed/info", headers=headers, timeout=15)
    if res.status_code != 200:
      print(f"【エラー】銘柄一覧取得失敗: {res.status_code}, {res.text}")
      sys.exit(1)

    listed_data = res.json().get("info", [])
    df_listed = pd.DataFrame(listed_data)
    if df_listed.empty:
      print("【エラー】銘柄一覧が空です。")
      sys.exit(1)
    print(f"取得成功: {len(df_listed)}件")
  except Exception as e:
    print(f"【エラー】銘柄一覧取得時に例外が発生しました: {e}")
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
      res_p = requests.get(
          f"{BASE_URL}/prices/daily_quotes",
          headers=headers,
          params={"code": code},
          timeout=10,
      )
      if res_p.status_code != 200:
        continue

      prices_data = res_p.json().get("daily_quotes", [])
      if not prices_data:
        continue

      df_prices = pd.DataFrame(prices_data)
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
    except Exception:
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

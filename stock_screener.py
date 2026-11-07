import os
import sys
from datetime import datetime, timedelta
import pandas as pd
import requests

# GitHub Secretsから認証情報を取得
JQUANTS_API_KEY = os.environ.get("JQUANTS_API_KEY")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# J-Quants API V2のベースURL
BASE_URL = "https://api.jquants.com/v2"


def send_slack_notification(message):
  """Slackにメッセージを送信する"""
  if not SLACK_WEBHOOK_URL or "hooks.slack.com" not in SLACK_WEBHOOK_URL:
    print("[Slack通知スキップ] Webhook URLが未設定です。")
    print(message)
    return

  payload = {"text": message}
  try:
    response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
    if response.status_code == 200:
      print("Slack通知を送信しました。")
    else:
      print(f"Slack通知エラー: {response.status_code}, 応答: {response.text}")
  except Exception as e:
    print(f"Slack通知例外発生: {e}")


def get_trading_days(headers, num_days=35):
  """直近の営業日（日付文字列YYYYMMDDのリスト）を取得する"""
  end_date = datetime.now()
  start_date = end_date - timedelta(days=num_days * 2)

  # 直近の日足データを取得して営業日一覧を特定
  url = f"{BASE_URL}/equities/bars/daily"
  params = {
      "from": start_date.strftime("%Y-%m-%d"),
      "to": end_date.strftime("%Y-%m-%d"),
  }

  res = requests.get(url, headers=headers, params=params, timeout=15)
  if res.status_code != 200:
    return []

  data = res.json().get("daily_quotes", [])
  if not data:
    return []

  df = pd.DataFrame(data)
  dates = sorted(df["Date"].unique())
  return dates[-num_days:]


def main():
  start_time = datetime.now()
  print("=== J-Quants API V2 超高速全銘柄スクリーニング開始 ===")

  if not JQUANTS_API_KEY:
    print("【エラー】JQUANTS_API_KEY の環境変数が設定されていません。")
    sys.exit(1)

  headers = {"x-api-key": JQUANTS_API_KEY}

  try:
    # 1. 上場銘柄マスターの取得
    print("① 上場銘柄マスターを取得中...")
    res_m = requests.get(
        f"{BASE_URL}/equities/master", headers=headers, timeout=15
    )
    if res_m.status_code != 200:
      print(
          f"【エラー】銘柄マスター取得失敗: {res_m.status_code},"
          f" 応答: {res_m.text}"
      )
      send_slack_notification(
          "⚠️ *【スクリーニングエラー】* 銘柄マスターの取得に失敗しました。"
      )
      sys.exit(1)

    master_list = res_m.json().get("data", [])
    df_master = pd.DataFrame(master_list)
    name_map = (
        dict(zip(df_master["Code"], df_master["CompanyName"]))
        if "CompanyName" in df_master.columns
        else {}
    )

    # 2. 過去25営業日の株価データを日付一括取得
    print("② 過去25営業日分の一括株価データを取得中...")
    trading_days = get_trading_days(headers, num_days=30)

    if len(trading_days) < 25:
      print(
          f"【エラー】十分な営業日データが取得できませんでした（取得日数: {len(trading_days)}日）。"
      )
      send_slack_notification(
          "⚠️ *【スクリーニングエラー】* 株価データの取得日数が不足しています。"
      )
      sys.exit(1)

    # 最新25営業日に絞り込み
    target_days = trading_days[-25:]

    all_quotes = []
    for d in target_days:
      # 日付ごとの全銘柄一括データを取得
      res_d = requests.get(
          f"{BASE_URL}/equities/bars/daily",
          headers=headers,
          params={"date": d},
          timeout=10,
      )
      if res_d.status_code == 200:
        quotes = res_d.json().get("daily_quotes", [])
        all_quotes.extend(quotes)

    df_all = pd.DataFrame(all_quotes)
    if df_all.empty:
      print("【エラー】株価データが取得できませんでした。")
      send_slack_notification(
          "⚠️ *【スクリーニングエラー】* 株価データが空でした。"
      )
      sys.exit(1)

    # 3. 高速判定処理 (pandasでの一括計算)
    print("③ メモリ上での全銘柄高速判定を実行中...")
    df_all["Date"] = pd.to_datetime(df_all["Date"])
    df_all = df_all.sort_values(["Code", "Date"])

    # 銘柄ごとの日付順グループ化
    unique_dates = sorted(df_all["Date"].unique())
    recent_5_dates = unique_dates[-5:]
    all_25_dates = unique_dates[-25:]

    # 直近5日平均出来高と過去25日平均出来高を一括算出
    df_25 = df_all[df_all["Date"].isin(all_25_dates)]
    vol_25_avg = df_25.groupby("Code")["Volume"].mean()

    df_5 = df_all[df_all["Date"].isin(recent_5_dates)]
    vol_5_avg = df_5.groupby("Code")["Volume"].mean()

    # 比率計算
    df_res = pd.DataFrame({"vol_5": vol_5_avg, "vol_25": vol_25_avg}).dropna()
    df_res = df_res[df_res["vol_25"] > 0]
    df_res["ratio"] = df_res["vol_5"] / df_res["vol_25"]

    # 出来高収縮条件（< 0.7）
    matched = df_res[df_res["ratio"] < 0.7]

    matched_stocks = []
    for code, row in matched.iterrows():
      name = name_map.get(code, "名称不明")
      matched_stocks.append({
          "code": code,
          "name": name,
          "recent_vol": int(row["vol_5"]),
          "avg_vol": int(row["vol_25"]),
      })

    elapsed = (datetime.now() - start_time).total_seconds()
    print(
        f"処理完了: 所要時間 {elapsed:.1f}秒, 検出銘柄数 {len(matched_stocks)}件"
    )

    # 4. Slack通知
    if matched_stocks:
      msg = (
          f"*【PEAD・出来高収縮スクリーニング結果】*\n"
          f"全市場より以下の銘柄 ({len(matched_stocks)}件) が条件を検知しました：\n"
      )
      for stock in matched_stocks[:20]:
        msg += (
            f"• *{stock['code']}* {stock['name']} (直近出来高平均:"
            f" {stock['recent_vol']:,})\n"
        )
      if len(matched_stocks) > 20:
        msg += f"\n...他 {len(matched_stocks) - 20} 銘柄"
    else:
      msg = (
          "*【PEAD・出来高収縮スクリーニング結果】*\n"
          "本日の全銘柄スクリーニングが完了しました。\n"
          "※条件を満たす銘柄はありませんでした（0件）。"
      )

    send_slack_notification(msg)

  except Exception as e:
    print(f"【例外発生】: {e}")
    send_slack_notification(f"⚠️ *【スクリーニングエラー】* 例外が発生しました: {e}")
    sys.exit(1)


if __name__ == "__main__":
  main()

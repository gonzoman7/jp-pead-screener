import os
import sys
import time
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


def main():
  print(
      "=== J-Quants API V2 日付一括取得スクリーニング開始 (条件: 比率 < 0.8)"
      " ==="
  )

  if not JQUANTS_API_KEY:
    print("【エラー】JQUANTS_API_KEY の環境変数が設定されていません。")
    sys.exit(1)

  headers = {"x-api-key": JQUANTS_API_KEY}

  try:
    # 1. 上場銘柄マスターの取得（銘柄名マップ作成用）
    print("① 上場銘柄マスターを取得中...")
    res_m = requests.get(
        f"{BASE_URL}/equities/master", headers=headers, timeout=15
    )
    if res_m.status_code != 200:
      print(f"【エラー】銘柄マスター取得失敗: {res_m.status_code}")
      send_slack_notification(
          "⚠️ *【PEADスクリーニング エラー】* 銘柄マスターの取得に失敗しました。"
      )
      sys.exit(1)

    master_list = res_m.json().get("data", [])
    df_master = pd.DataFrame(master_list)
    name_map = (
        dict(zip(df_master["Code"], df_master["CompanyName"]))
        if "CompanyName" in df_master.columns
        else {}
    )

    # 2. 過去25営業日分の株価データを日付指定で一括取得（レート制限に配慮）
    print("② 過去25営業日分の株価データを日付指定で一括取得中...")
    all_quotes = []
    success_days = 0
    current_date = datetime.now()
    check_days = 0

    # 営業日を遡りながら25営業日分のデータを収集
    while success_days < 25 and check_days < 60:
      date_str = current_date.strftime("%Y-%m-%d")
      # 土日（5:土, 6:日）を除外
      if current_date.weekday() < 5:
        res_d = requests.get(
            f"{BASE_URL}/equities/bars/daily",
            headers=headers,
            params={"date": date_str},
            timeout=15,
        )
        if res_d.status_code == 200:
          quotes = res_d.json().get("daily_quotes", [])
          if quotes:
            all_quotes.extend(quotes)
            success_days += 1
            print(f"  - 取得成功: {date_str} ({len(quotes)}銘柄)")
        # ライトプランの制限（60 req/min）を安全に守るためのウェイト
        time.sleep(0.5)

      current_date -= timedelta(days=1)
      check_days += 1

    if not all_quotes:
      print("【エラー】有効な株価データが1件も取得できませんでした。")
      send_slack_notification(
          "⚠️ *【PEADスクリーニング エラー】* 有効な株価データが取得できませんでした。"
      )
      sys.exit(1)

    # 3. pandasによる高速集計・判定
    print(
        f"③ 取得完了（有効営業日: {success_days}日）。"
        "メモリ上で高速判定を実行中..."
    )
    df_all = pd.DataFrame(all_quotes)
    df_all["Date"] = pd.to_datetime(df_all["Date"])
    df_all = df_all.sort_values(["Code", "Date"])

    results = []
    for code, group in df_all.groupby("Code"):
      if len(group) >= 10:
        recent_vol = group["Volume"].tail(5).mean()
        avg_vol = group["Volume"].tail(25).mean()

        if avg_vol > 0:
          ratio = recent_vol / avg_vol
          name = name_map.get(code, "名称不明")
          results.append({
              "code": code,
              "name": name,
              "recent_vol": int(recent_vol),
              "avg_vol": int(avg_vol),
              "ratio": ratio,
          })

    df_results = pd.DataFrame(results)
    if df_results.empty:
      print("【警告】集計可能な銘柄データがありませんでした。")
      send_slack_notification(
          "*【PEADスクリーニング結果 (<0.8)】*\n集計可能な銘柄データがありませんでした。"
      )
      return

    # 条件（比率 < 0.8）に合致する銘柄を抽出
    matched_stocks = df_results[df_results["ratio"] < 0.8].to_dict(
        orient="records"
    )

    print(
        f"解析完了: 有効銘柄数 {len(df_results)}件 / 条件適合(比率 < 0.8)"
        f" {len(matched_stocks)}件"
    )

    # ヒットが0件の場合、最も比率が低かった（条件に近かった）上位5銘柄をログに出力
    if not matched_stocks:
      sorted_closest = df_results.sort_values("ratio").head(5)
      print("\n--- 【分析ログ】本日最も出来高が収縮していた上位5銘柄 ---")
      for _, s in sorted_closest.iterrows():
        print(
            f"銘柄: {s['code']} {s['name']} | 比率: {s['ratio']:.3f}"
            f" (直近5日平均: {s['recent_vol']:,} / 過去25日平均:"
            f" {s['avg_vol']:,})"
        )
      print("----------------------------------------------------\n")

    # Slack通知
    if matched_stocks:
      msg = (
          f"*【PEAD・出来高収縮スクリーニング結果 (<0.8)】*\n"
          f"全市場から以下の銘柄 ({len(matched_stocks)}件) が条件を検知しました：\n"
      )
      for stock in matched_stocks[:20]:
        msg += (
            f"• *{stock['code']}* {stock['name']} (比率: {stock['ratio']:.2f},"
            f" 直近出来高平均: {stock['recent_vol']:,})\n"
        )
      if len(matched_stocks) > 20:
        msg += f"\n...他 {len(matched_stocks) - 20} 銘柄"
    else:
      msg = (
          "*【PEAD・出来高収縮スクリーニング結果 (<0.8)】*\n"
          "本日の全銘柄スクリーニングが完了しました。\n"
          "※条件を満たす銘柄はありませんでした（0件）。"
      )

    send_slack_notification(msg)
    print("通知処理を終了しました。")

  except Exception as e:
    print(f"【例外発生】: {e}")
    send_slack_notification(
        f"⚠️ *【PEADスクリーニング エラー】* 例外が発生しました: {e}"
    )
    sys.exit(1)


if __name__ == "__main__":
  main()

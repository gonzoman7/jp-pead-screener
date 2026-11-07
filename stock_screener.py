import concurrent.futures
import os
import sys
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


def fetch_stock_data(code, name, headers):
  """個別銘柄の株価データを取得し、出来高比率を算出する"""
  try:
    res = requests.get(
        f"{BASE_URL}/equities/bars/daily",
        headers=headers,
        params={"code": code},
        timeout=8,
    )
    if res.status_code != 200:
      return None

    data = res.json().get("daily_quotes", [])
    if not data:
      return None

    df = pd.DataFrame(data)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    if len(df) > 20:
      recent_vol = df["Volume"].tail(5).mean()
      avg_vol = df["Volume"].tail(25).mean()

      if avg_vol > 0:
        ratio = recent_vol / avg_vol
        return {
            "code": code,
            "name": name,
            "recent_vol": int(recent_vol),
            "avg_vol": int(avg_vol),
            "ratio": ratio,
        }
  except Exception:
    pass
  return None


def main():
  print(
      "=== J-Quants API V2 全銘柄並行スクリーニング開始 (条件: 比率 < 0.8) ==="
  )

  if not JQUANTS_API_KEY:
    print("【エラー】JQUANTS_API_KEY の環境変数が設定されていません。")
    sys.exit(1)

  headers = {"x-api-key": JQUANTS_API_KEY}

  try:
    print("上場銘柄一覧（マスター）を取得中...")
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

    if "ScaleCategory" in df_master.columns:
      df_master = df_master[df_master["ScaleCategory"].notna()]

    stocks_to_check = []
    for _, row in df_master.iterrows():
      code = row.get("Code")
      name = row.get("CompanyName", "名称不明")
      if code:
        stocks_to_check.append((code, name))

    print(
        f"対象銘柄数: {len(stocks_to_check)}件。並行処理による解析を開始します..."
    )

    all_results = []

    # ThreadPoolExecutorを用いて複数スレッドで同時並行リクエスト
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
      futures = {
          executor.submit(fetch_stock_data, code, name, headers): (code, name)
          for code, name in stocks_to_check
      }

      for future in concurrent.futures.as_completed(futures):
        result = future.result()
        if result:
          all_results.append(result)

    # 比率が 0.8 未満のものをヒットとして抽出
    matched_stocks = [item for item in all_results if item["ratio"] < 0.8]

    print(
        f"解析完了: スキャン成功銘柄 {len(all_results)}件 / 条件適合(比率 <"
        f" 0.8) {len(matched_stocks)}件"
    )

    # ヒット銘柄が0件の場合、条件に最も近かった（比率が低かった）上位5銘柄をログに出力
    if not matched_stocks and all_results:
      sorted_closest = sorted(all_results, key=lambda x: x["ratio"])[:5]
      print("\n--- 【分析ログ】本日最も出来高が収縮していた上位5銘柄 ---")
      for s in sorted_closest:
        print(
            f"銘柄: {s['code']} {s['name']} | 比率:"
            f" {s['ratio']:.3f} (直近5日平均: {s['recent_vol']:,} /"
            f" 過去25日平均: {s['avg_vol']:,})"
        )
      print("----------------------------------------------------\n")

    # 毎日必ずSlackへ通知を送る処理
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

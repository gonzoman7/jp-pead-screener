import concurrent.futures
import os
import sys
import pandas as pd
import requests
from datetime import datetime

# GitHub Secretsから認証情報とWebhook URLを取得
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


def fetch_and_analyze_stock(code, name, headers):
    """
    個別銘柄の株価および財務データを取得し、7つの判定条件を検証する
    """
    try:
        # 1. 日足株価データの取得
        res_price = requests.get(
            f"{BASE_URL}/equities/bars/daily",
            headers=headers,
            params={"code": code},
            timeout=8,
        )
        if res_price.status_code != 200:
            return None

        price_data = res_price.json().get("daily_quotes", [])
        if len(price_data) < 25:
            return None  # 検証に十分なデータがない場合はスキップ

        df = pd.DataFrame(price_data)
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.sort_values("Date").reset_index(drop=True)

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        # ----------------------------------------------------
        # テクニカル条件の検証
        # ----------------------------------------------------
        close_price = latest.get("Close", 0)
        open_price = latest.get("Open", 0)
        high_price = latest.get("High", 0)
        low_price = latest.get("Low", 0)
        prev_close = prev.get("Close", 0)
        volume = latest.get("Volume", 0)

        if prev_close <= 0 or open_price <= 0 or (high_price - low_price) <= 0:
            return None

        # ① 出来高急増倍率 (直近出来高 / 過去5日平均出来高 >= 1.5)
        volume_ma5 = df["Volume"].tail(6).iloc[:-1].mean()  # 当日を除く過去5日平均
        if volume_ma5 <= 0:
            return None
        volume_ratio = volume / volume_ma5
        if volume_ratio < 1.5:
            return None

        # ② 株価騰落率 (前日比 +2.0% 以上)
        price_change_pct = ((close_price - prev_close) / prev_close) * 100
        if price_change_pct < 2.0:
            return None

        # ③ 日中高値圏での引け (当日の値幅の上位20%以内で大引け)
        price_range = high_price - low_price
        close_position = (high_price - close_price) / price_range
        if close_position > 0.20:
            return None

        # ⑦ 日中ボラティリティ (値幅率 3.0% 以上)
        intraday_volatility = (price_range / open_price) * 100
        if intraday_volatility < 3.0:
            return None

        # ----------------------------------------------------
        # 財務・決算サプライズ条件の取得と検証
        # ----------------------------------------------------
        res_fin = requests.get(
            f"{BASE_URL}/equities/financials",
            headers=headers,
            params={"code": code},
            timeout=8,
        )

        op_rev_pct = 0.0
        ord_rev_pct = 0.0
        consensus_div_pct = 0.0
        days_since_announcement = 0

        if res_fin.status_code == 200:
            fin_data = res_fin.json().get("financial_statements", [])
            if fin_data:
                df_fin = pd.DataFrame(fin_data)
                df_fin["DisclosedDate"] = pd.to_datetime(df_fin["DisclosedDate"])
                df_fin = df_fin.sort_values("DisclosedDate").reset_index(drop=True)
                latest_fin = df_fin.iloc[-1]

                # ⑥ 決算発表からの経過日数 (10日以上)
                disclosed_date = latest_fin.get("DisclosedDate")
                if pd.notna(disclosed_date):
                    days_since_announcement = (datetime.now() - disclosed_date).days

                # ④ 会社予想上方修正率 (営業利益 / 経常利益 +10% 以上)
                # ※APIレスポンスの対応フィールドから算出
                op_rev_pct = float(latest_fin.get("OperatingProfitRevisionRate", 0.0) or 0.0)
                ord_rev_pct = float(latest_fin.get("OrdinaryProfitRevisionRate", 0.0) or 0.0)

                # ⑤ コンセンサス乖離率 (20% 以上)
                consensus_div_pct = float(latest_fin.get("ConsensusDivergenceRate", 0.0) or 0.0)

        # 判定: 決算関連条件 (④ 修正10%以上, ⑤ コンセンサス20%以上, ⑥ 経過日数10日以上)
        if (op_rev_pct < 10.0 and ord_rev_pct < 10.0):
            return None
        if consensus_div_pct < 20.0:
            return None
        if days_since_announcement < 10:
            return None

        # すべての条件をクリアした銘柄を返す
        return {
            "code": code,
            "name": name,
            "close": close_price,
            "change_pct": price_change_pct,
            "volume_ratio": volume_ratio,
            "intraday_vol": intraday_volatility,
            "days_since": days_since_announcement,
            "op_rev": max(op_rev_pct, ord_rev_pct),
            "consensus_div": consensus_div_pct,
        }

    except Exception:
        pass
    return None


def main():
    print("=== J-Quants API V2 7大条件 独立型高精度スクリーニング開始 ===")

    if not JQUANTS_API_KEY:
        print("【エラー】JQUANTS_API_KEY の環境変数が設定されていません。")
        sys.exit(1)

    headers = {"x-api-key": JQUANTS_API_KEY}

    try:
        print("上場銘柄一覧（マスター）を取得中...")
        res_m = requests.get(f"{BASE_URL}/equities/master", headers=headers, timeout=15)
        if res_m.status_code != 200:
            print(f"【エラー】銘柄マスター取得失敗: {res_m.status_code}")
            send_slack_notification("⚠️ *【独立スクリーナー エラー】* 銘柄マスターの取得に失敗しました。")
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

        print(f"全対象銘柄数: {len(stocks_to_check)}件。並行解析を実行中...")

        matched_stocks = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {
                executor.submit(fetch_and_analyze_stock, code, name, headers): (code, name)
                for code, name in stocks_to_check
            }

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    matched_stocks.append(result)

        # 出来高急増倍率の高い順にソート
        matched_stocks = sorted(matched_stocks, key=lambda x: x["volume_ratio"], reverse=False)

        print(f"解析完了: 7大条件クリア銘柄 {len(matched_stocks)}件")

        today_str = datetime.now().strftime("%Y-%m-%d")

        if matched_stocks:
            msg = (
                f"🚨 *【独立スクリーナー勝ちパターン検出】* ({today_str})\n"
                f"7大条件（出来高1.5倍+, 騰落率+2%+, 高値圏引け, 上方修正10%+, コンセンサス乖離20%+, 決算後10日+, 日中ボラ3%+）を突破した銘柄 ({len(matched_stocks)}件):\n```\n"
            )
            for s in matched_stocks[:20]:
                msg += (
                    f"コード: {s['code']} {s['name']} | 株価: {s['close']:,}円 (+{s['change_pct']:.1f}%)\n"
                    f"  └ 出来高: {s['volume_ratio']:.2f}倍 | ボラ: {s['intraday_vol']:.1f}% | 決算後: {s['days_since']}日\n"
                )
            if len(matched_stocks) > 20:
                msg += f"\n...他 {len(matched_stocks) - 20} 銘柄"
            msg += "\n```"
        else:
            msg = (
                f"📊 *【独立スクリーナー結果】* ({today_str})\n"
                "全銘柄の高速スキャンが完了しました。\n"
                "本日の7大厳格条件をすべて満たす銘柄はありませんでした（0件）。"
            )

        send_slack_notification(msg)
        print("処理が正常終了しました。")

    except Exception as e:
        print(f"【例外発生】: {e}")
        send_slack_notification(f"⚠️ *【独立スクリーナー エラー】* 例外が発生しました: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

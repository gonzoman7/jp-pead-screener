import os
import requests
import pandas as pd
from datetime import datetime

# --- 【設定】 ---
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "YOUR_SLACK_WEBHOOK_URL_HERE")

def fetch_market_data() -> pd.DataFrame:
    """
    J-Quants APIやデータソースから銘柄データを取得する関数
    ※既存のデータ取得・読み込み処理に合わせてカラム名を調整してください
    """
    # 【実装例】ダミーデータ形式（実際のデータ取得処理に置き換わります）
    # J-Quants Lightプランからのデータフレームなどを読み込みます
    data = []
    df = pd.DataFrame(data)
    return df

def apply_winning_logic_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    ユーザー指定の7つの厳格な勝ちパターン基準でフィルタリング・絞り込みを行う
    """
    if df.empty:
        return df

    # --- 1. スクリーニング指標の計算 ---
    # ① 出来高急増倍率 (対過去5日平均出来高)
    df['Volume_Ratio'] = df['Volume'] / df['Volume_MA5']
    
    # ② 株価前日比騰落率 (%)
    df['Price_Change_Pct'] = ((df['Close'] - df['Prev_Close']) / df['Prev_Close']) * 100
    
    # ⑦ 日中ボラティリティ (値幅率 %)
    df['Intraday_Volatility'] = ((df['High'] - df['Low']) / df['Open']) * 100
    
    # ③ 日中高値圏での引け判定 (当日値幅の上位20%以内で大引けしているか)
    price_range = df['High'] - df['Low']
    df['Close_Near_High'] = (price_range > 0) & ((df['High'] - df['Close']) / price_range <= 0.20)

    # --- 2. 7つの条件による厳格スクリーニング ---
    condition = (
        # 1. 出来高急増倍率 1.5倍以上
        (df['Volume_Ratio'] >= 1.5) &
        
        # 2. 株価騰落率 前日比 +2%以上
        (df['Price_Change_Pct'] >= 2.0) &
        
        # 3. 日中高値圏で引けていること
        (df['Close_Near_High'] == True) &
        
        # 4. 営業利益または経常利益の会社予想上方修正率が +10%以上
        ((df['Operating_Profit_Revision_Pct'] >= 10.0) | (df['Ordinary_Profit_Revision_Pct'] >= 10.0)) &
        
        # 5. コンセンサス（市場予想）との乖離率 20%以上
        (df['Consensus_Divergence_Pct'] >= 20.0) &
        
        # 6. 決算発表からの経過日数 10日以上
        (df['Days_Since_Announcement'] >= 10) &
        
        # 7. 日中ボラティリティ（値幅率） 3%以上
        (df['Intraday_Volatility'] >= 3.0)
    )

    # 条件に完全に合致する銘柄を抽出し、出来高急増倍率が高い順にソート
    target_stocks = df[condition].sort_values(by='Volume_Ratio', ascending=False).copy()

    return target_stocks

def send_to_slack(results_df: pd.DataFrame):
    """
    スクリーニング結果をSlackへ自動通知する
    """
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    if results_df.empty:
        message = f"📊 *【独立スクリーナー速報】* ({today_str})\n本日の厳格条件に合致する有望銘柄はありませんでした。"
    else:
        message = f"🚨 *【独立スクリーナー速報】* ({today_str})\n"
        message += f"条件（出来高1.5倍+, 騰落率+2%+, 上方修正10%+, コンセンサス乖離20%+, 決算後10日+等）クリア銘柄:\n```\n"
        
        for idx, row in results_df.iterrows():
            code = row.get('Code', 'N/A')
            name = row.get('Name', '')
            vol_ratio = row.get('Volume_Ratio', 0)
            change_pct = row.get('Price_Change_Pct', 0)
            message += f"コード: {code} {name} | 出来高: {vol_ratio:.2f}倍 | 前日比: +{change_pct:.1f}%\n"
            
        message += "```"

    payload = {"text": message}
    
    # Webhook URLがセットされている場合に送信
    if SLACK_WEBHOOK_URL and "YOUR_SLACK_WEBHOOK_URL" not in SLACK_WEBHOOK_URL:
        try:
            response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
            response.raise_for_status()
            print("Slackへの通知が正常に送信されました。")
        except Exception as e:
            print(f"Slack送信エラー: {e}")
    else:
        print("Slack Webhook URL未設定のためコンソールに出力します:\n", message)

def main():
    print("=== 独立型モメンタム＆PEADスクリーナー実行開始 ===")
    
    # 1. データ取得
    df = fetch_market_data()
    
    # 2. スクリーニング判定
    filtered_df = apply_winning_logic_filters(df)
    print(f"該当銘柄数: {len(filtered_df)} 件")
    
    # 3. Slack通知
    send_to_slack(filtered_df)
    
    print("=== 処理完了 ===")

if __name__ == "__main__":
    main()

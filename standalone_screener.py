import pandas as pd

def apply_winning_logic_filters(df: pd.DataFrame) -> pd.DataFrame:
    """
    指定されたすべての数値基準を満たす銘柄のみを抽出するフィルタリング関数
    """
    if df.empty:
        return df

    # --- 1. 計算カラムの作成 ---
    # 出来高急増倍率 (対過去5日平均出来高)
    df['Volume_Ratio'] = df['Volume'] / df['Volume_MA5']
    
    # 株価前日比騰落率 (%)
    df['Price_Change_Pct'] = ((df['Close'] - df['Prev_Close']) / df['Prev_Close']) * 100
    
    # 日中ボラティリティ (値幅率 %)
    df['Intraday_Volatility'] = ((df['High'] - df['Low']) / df['Open']) * 100
    
    # 日中高値圏での引け判定 (当日値幅の上位20%以内で大引けしているか)
    # ※高値と安値が同値の場合は除外
    price_range = df['High'] - df['Low']
    df['Close_Near_High'] = (price_range > 0) & ((df['High'] - df['Close']) / price_range <= 0.20)

    # --- 2. スクリーニング条件の適用 ---
    condition = (
        # ① 出来高急増倍率 1.5倍以上
        (df['Volume_Ratio'] >= 1.5) &
        
        # ② 株価騰落率 前日比 +2%以上
        (df['Price_Change_Pct'] >= 2.0) &
        
        # ③ 日中高値圏で引けていること
        (df['Close_Near_High'] == True) &
        
        # ④ 営業利益または経常利益の会社予想上方修正率が +10%以上
        # （※10%〜20%以上の範囲、または10%以上の上方修正）
        ((df['Operating_Profit_Revision_Pct'] >= 10.0) | (df['Ordinary_Profit_Revision_Pct'] >= 10.0)) &
        
        # ⑤ コンセンサス（市場予想）との乖離率 20%以上
        (df['Consensus_Divergence_Pct'] >= 20.0) &
        
        # ⑥ 決算発表からの経過日数 10日以上
        (df['Days_Since_Announcement'] >= 10) &
        
        # ⑦ 日中ボラティリティ（値幅率） 3%以上
        (df['Intraday_Volatility'] >= 3.0)
    )

    # 条件に合致した銘柄を抽出し、出来高急増倍率が高い順にソート
    target_stocks = df[condition].sort_values(by='Volume_Ratio', ascending=False).copy()

    return target_stocks

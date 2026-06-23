import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os
import japanize_matplotlib
import glob  # 👈 【追加】複数ファイルを一括探索するためのライブラリ

st.set_page_config(
    page_title="電気事業者 SNS分析ボード",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    div[data-testid="stToolbar"] {
        visibility: hidden;
    }
    header {
        visibility: visible !important;
        background: rgba(255, 255, 255, 0);
    }
    footer {
        visibility: hidden;
        display: none !important;
    }
    div[data-testid="stFooter"] {
        display: none !important;
    }
    .profileContainer,
    #profileContainer,
    [id*="profileContainer"],
    [class*="profileContainer"],
    iframe[title*="profileContainer"] {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
        pointer-events: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("⚡ 電気事業者 Xトレンド分析システム")

# 👈 今までの単一ファイル指定を廃止し、"electricity_posts_*.csv" にマッチするファイルをすべて探す仕様に変更
csv_files = glob.glob("electricity_posts_*.csv")

NEG_TREND_WORDS = ["高い", "値上げ", "電気代", "停電", "不満", "外資", "提携", "まずい", "高騰", "リスク", "負担", "最悪", "不便", "エラー", "繋がらない", "解約", "料金", "乗っ取り", "ボイコット", "高すぎ"]
POS_TREND_WORDS = ["安い", "お得", "便利", "助かる", "おすすめ", "オススメ", "満足", "ポイント", "キャンペーン", "節約", "キャッシュバック", "親切", "安心", "乗り換え", "招待コード", "最適"]

TOPIC_KEYWORDS = {
    "価格・料金プラン": ["高い", "安い", "値上げ", "値下げ", "料金", "電気代", "高騰", "請求", "節電", "家計", "燃料費"],
    "サービス・操作性": ["便利", "不便", "アプリ", "サイト", "マイページ", "ログイン", "手続き", "対応", "電話", "繋がらない", "ポイント", "契約", "解約"],
    "インフラ・停電リスク": ["停電", "復旧", "ついた", "消えた", "災害", "台風", "落雷", "送電", "発電", "原発", "火力"],
    "企業姿勢・ニュース": ["国有化", "株式", "外資", "提携", "買収", "株価", "経営", "投資", "ニュース", "不祥事", "カルテル"]
}

def assign_topics(text):
    if pd.isna(text):
        return ["その他"]
    text_lower = str(text).lower()
    matched_topics = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                matched_topics.append(topic)
                break
    return matched_topics if matched_topics else ["その他"]

def get_top_words(posts, word_list, top_n=5):
    counts = {}
    for kw in word_list:
        counts[kw] = posts.str.contains(kw, case=False, na=False).sum()
    sorted_words = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return [item for item in sorted_words if item[1] > 0][:top_n]

# 👈 【修正】CSVファイルが1つでも見つかったら処理を開始
if csv_files:
    # 👈 見つかった月別のCSVファイルをすべて読み込んで、裏で縦に1つに自動結合します
    df = pd.concat([pd.read_csv(f) for f in csv_files], ignore_index=True)
    
    df["収集日時"] = pd.to_datetime(df["収集日時"])
    if "投稿日時" in df.columns:
        df["投稿日時"] = pd.to_datetime(df["投稿日時"])
        df["投稿日時"] = df["投稿日時"].fillna(df["収集日時"])
    else:
        df["投稿日時"] = df["収集日時"]
    
    st.sidebar.header("📊 分析条件設定")
    company = st.sidebar.selectbox("分析対象の事業者", ["北海道電力", "東北電力", "東京電力", "中部電力", "北陸電力", "関西電力", "中国電力", "四国電力", "九州電力", "リボンエナジー", "オクトパスエナジー", "Looopでんき"])
    
    period_type = st.sidebar.radio(
        "期間の指定方法", 
        ["直近7日間（デフォルト）", "特定の日を指定", "特定の期間（週など）を範囲指定", "特定の月を指定", "全期間"], 
        index=0
    )
    
    df_filtered = df[df["事業者"] == company].copy()
    
    now = pd.Timestamp.now()
    
    if period_type == "直近7日間（デフォルト）":
        df_filtered = df_filtered[df_filtered["投稿日時"] >= now - pd.Timedelta(days=7)]
        
    elif period_type == "特定の日を指定":
        selected_date = st.sidebar.date_input("日付を選択", now.date())
        df_filtered = df_filtered[df_filtered["投稿日時"].dt.date == selected_date]
        
    elif period_type == "特定の期間（週など）を範囲指定":
        selected_range = st.sidebar.date_input(
            "開始日と終了日を選択（同日選択で1週間などの調整可）", 
            [now.date() - pd.Timedelta(days=7), now.date()]
        )
        if len(selected_range) == 2:
            start_date, end_date = selected_range
            df_filtered = df_filtered[
                (df_filtered["投稿日時"].dt.date >= start_date) & 
                (df_filtered["投稿日時"].dt.date <= end_date)
            ]
            
    elif period_type == "特定の月を指定":
        df["_year_month"] = df["投稿日時"].dt.strftime("%Y-%m")
        unique_months = sorted(df["_year_month"].unique(), reverse=True)
        if unique_months:
            selected_month = st.sidebar.selectbox("月を選択", unique_months)
            df_filtered = df_filtered[df_filtered["投稿日時"].dt.strftime("%Y-%m") == selected_month]
        else:
            st.sidebar.info("選択可能な月がありません")

    df_filtered["表示日時"] = df_filtered["投稿日時"].dt.strftime("%Y-%m-%d %H:%M")
    
    df_filtered['_topics'] = df_filtered['本文'].apply(assign_topics)
    df_exploded = df_filtered.explode('_topics').reset_index(drop=True)

    main_tab, raw_tab = st.tabs(["📈 高度トレンド分析（クロス集計）", "📝 感情別 投稿一覧"])
    
    with main_tab:
        st.markdown(f"### 📊 {company} の感情別フォアグラウンド・キーワード（全体トレンド）")
        st.caption("ポジティブ／ネガティブな投稿のそれぞれで、今どんな言葉が多く使われているかのトップ5です")
        
        col_w1, col_w2 = st.columns(2)
        
        with col_w1:
            df_pos_all = df_filtered[df_filtered["判定"] == "ポジティブ"]
            top_pos = get_top_words(df_pos_all['本文'], POS_TREND_WORDS)
            
            if top_pos:
                words_p, counts_p = zip(*top_pos)
                fig_p, ax_p = plt.subplots(figsize=(6, 2))
                ax_p.barh(words_p[::-1], counts_p[::-1], color='#99ff99')
                ax_p.set_title("🟢 ポジティブ投稿の頻出ワード TOP5", fontsize=10, color="green")
                ax_p.set_xlabel("言及件数 (件)", fontsize=8)
                ax_p.grid(axis='x', linestyle='--', alpha=0.5)
                st.pyplot(fig_p)
            else:
                st.info("🟢 ポジティブな特有ワードはまだ検出されていません。")
                
        with col_w2:
            df_neg_all = df_filtered[df_filtered["判定"] == "ネガティブ"]
            top_neg = get_top_words(df_neg_all['本文'], NEG_TREND_WORDS)
            
            if top_neg:
                words_n, counts_n = zip(*top_neg)
                fig_n, ax_n = plt.subplots(figsize=(6, 2))
                ax_n.barh(words_n[::-1], counts_n[::-1], color='#ff9999')
                ax_n.set_title("🔴 ネガティブ投稿の頻出ワード TOP5", fontsize=10, color="red")
                ax_n.set_xlabel("言及件数 (件)", fontsize=8)
                ax_n.grid(axis='x', linestyle='--', alpha=0.5)
                st.pyplot(fig_n)
            else:
                st.info("🔴 ネガティブな特有ワードはまだ検出されていません。")
                
        st.markdown("---")
        
        st.subheader("🎯 話動（トピック）× 感情のクロス分析")
        col1, col2 = st.columns([3, 2])
        
        with col1:
            if not df_exploded.empty:
                pivot_df = pd.crosstab(df_exploded['_topics'], df_exploded['判定'])
                for col in ['ポジティブ', 'ニュートラル', 'ネガティブ']:
                    if col not in pivot_df.columns:
                        pivot_df[col] = 0
                pivot_df = pivot_df[['ポジティブ', 'ニュートラル', 'ネガティブ']]
                
                fig, ax = plt.subplots(figsize=(8, 4.5))
                pivot_df.plot(kind='barh', stacked=True, color=['#99ff99', '#dddddd', '#ff9999'], ax=ax)
                ax.set_title('話題別の感情ボリューム（件数）', fontsize=12, pad=10)
                ax.set_xlabel('検出された投稿数（件）')
                ax.set_ylabel('話題カテゴリ')
                ax.grid(axis='x', linestyle='--', alpha=0.5)
                plt.legend(title="世論の感情", loc='lower right')
                st.pyplot(fig)
            else:
                st.info("分析可能なデータがありません。")
                
        with col2:
            st.markdown("### 💡 選択された話題の「具体的な中身」")
            selected_topic = st.selectbox("詳細を覗きたい話題を選択", list(TOPIC_KEYWORDS.keys()) + ["ignore_other"])
            
            topic_key = "その他" if selected_topic == "ignore_other" else selected_topic
            df_topic_view = df_filtered[df_filtered['_topics'].apply(lambda x: topic_key in x)].copy()
            
            if not df_topic_view.empty:
                if topic_key != "その他":
                    st.write("📊 **この話題で特によく使われている言葉（上位）**")
                    keywords_to_check = TOPIC_KEYWORDS[topic_key]
                    sub_counts = {}
                    for kw in keywords_to_check:
                        sub_counts[kw] = df_topic_view['本文'].str.contains(kw, case=False, na=False).sum()
                    
                    sorted_sub = sorted(sub_counts.items(), key=lambda x: x[1], reverse=True)
                    badge_line = ""
                    for k, v in sorted_sub[:4]:
                        if v > 0:
                            badge_line += f"`{k}({v}件)`   "
                    if badge_line:
                        st.markdown(badge_line)
                
                st.write("")
                st.write("💬 **多くの内容を含んでいる代表的な投稿（システム自動選抜）**")
                df_topic_view['text_len'] = df_topic_view['本文'].str.len()
                rep_posts = df_topic_view.sort_values(by='text_len', ascending=False).head(3)
                
                for idx, row in rep_posts.iterrows():
                    icon = "🟢【満足】" if row['判定'] == "ポジティブ" else ("🔴【不慢】" if row['判定'] == "ネガティブ" else "⚪【その他】")
                    st.info(f"{icon} {row['本文']}")
                
                st.write("")
                st.write("▼ 関連する投稿一覧（最新順・全件スクロール表示）")
                df_topic_sorted = df_topic_view.sort_values(by="投稿日時", ascending=False)
                st.dataframe(
                    df_topic_sorted[["表示日時", "本文", "判定"]],
                    column_config={"本文": st.column_config.TextColumn("本文", width="large")},
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("該当するデータがまだありません。")
            
    # ==========================================
    # タブ2：感情別 投稿一覧
    # ==========================================
    with raw_tab:
        col3, col4 = st.columns([3, 2])
        with col3:
            st.subheader("📋 感情セグメント別の一覧表示")
            sub_tab1, sub_tab2, sub_tab3 = st.tabs(["🟢 ポジティブな投稿", "🔴 ネガティブな投稿", "⚪ 全ての投稿"])
            
            with sub_tab1:
                df_pos = df_filtered[df_filtered["判定"] == "ポジティブ"].sort_values(by="投稿日時", ascending=False)
                st.write(f"✨ ポジティブ件数: {len(df_pos)} 件")
                st.dataframe(
                    df_pos[["表示日時", "本文"]],
                    column_config={"本文": st.column_config.TextColumn("本文", width="large")},
                    use_container_width=True,
                    hide_index=True
                )
            with sub_tab2:
                df_neg = df_filtered[df_filtered["判定"] == "ネガティブ"].sort_values(by="投稿日時", ascending=False)
                st.write(f"💥 ネガティブ件数: {len(df_neg)} 件")
                st.dataframe(
                    df_neg[["表示日時", "本文"]],
                    column_config={"本文": st.column_config.TextColumn("本文", width="large")},
                    use_container_width=True,
                    hide_index=True
                )
            with sub_tab3:
                df_all_sorted = df_filtered.sort_values(by="投稿日時", ascending=False)
                st.write(f"📝 総投稿数: {len(df_all_sorted)} 件")
                st.dataframe(
                    df_all_sorted[["表示日時", "本文", "判定"]],
                    column_config={"本文": st.column_config.TextColumn("本文", width="large")},
                    use_container_width=True,
                    hide_index=True
                )
                
        with col4:
            st.write("")
            st.write("")
            counts = df_filtered["判定"].value_counts()
            if not counts.empty:
                fig2, ax2 = plt.subplots(figsize=(4.5, 4.5))
                ax2.pie(counts, labels=counts.index, autopct='%1.1f%%', startangle=90, 
                       colors=['#ff9999','#66b3ff','#99ff99'], textprops={'fontsize': 12})
                ax2.set_title("全体的な感情比率", fontsize=12)
                st.pyplot(fig2)

else:
    st.info("まだデータが蓄積されていません。最初の自動収集をお待ちください。")
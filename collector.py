import os
import urllib.parse
import pandas as pd
from datetime import datetime
from transformers import pipeline
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re

KEYWORDS_MAPPING = {
    "東京電力": ["東京電力", "東電", "TEPCO", "テプコ"],
    "関西電力": ["関西電力", "関電", "KEPCO"],
    "中部電力": ["中部電力", "中電"],
    "九州電力": ["九州電力", "九電"],
    "リボンエナジー": ["リボンエナジー", "リボン電気"],
    "オクトパスエナジー": ["オクトパスエナジー", "オクトパス電気"],
    "looopでんき": ["looopでんき", "ループ電気", "ループでんき", "loop電気"]
}

CSV_FILE = "electricity_posts_data.csv"

# 感情分析モデルの準備
analyzer = pipeline("sentiment-analysis", model="cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual")

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def fetch_posts(keyword):
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://search.yahoo.co.jp/realtime/search?p={encoded_keyword}"
    
    raw_posts = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url)
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
            
        soup = BeautifulSoup(html, 'html.parser')
        search_term = keyword[:2]
        
        # 1. 【確実性重視】まずは網を広げて、ツイートに関係しそうなブロックをガバッと拾う
        elements = soup.find_all(["p", "div", "li"])
        for elem in elements:
            class_str = "".join(elem.get("class", []))
            if any(k in class_str for k in ["Tweet", "text", "Text", "body", "Content"]):
                text = clean_text(elem.get_text())
                
                if 15 < len(text) < 280 and keyword.lower() in text.lower():
                    if "検索" in text and "ID" in text:
                        continue
                    raw_posts.append(text)
                    
        # ─── 【新機能】親タグ・子タグの巻き込み重複を100%倒す仕分けロジック ───
        # 重複を無くすため一度一意にする
        raw_posts = list(set(raw_posts))
        # 文章が「短い順」にソート（＝本文のみの綺麗なデータが先頭に来る）
        raw_posts.sort(key=len)
        
        final_posts = []
        for p in raw_posts:
            # 既に採用した短い本文が、今見ている長い文章 p の中に含まれているか？
            # 含まれているなら、p は親枠のノイズなので「偽物」として無視する
            is_duplicate_parent = False
            for adopted in final_posts:
                if adopted in p:
                    is_duplicate_parent = True
                    break
            
            if not is_duplicate_parent:
                # 「メニューを開く」などの明らかなシステム文字が入っている巨大な親枠は単体でも弾く
                if "メニューを開く" in p:
                    continue
                final_posts.append(p)
                
        print(f"     [解析状況] 「{keyword}」で {len(final_posts)} 件抽出（重複・ノイズ全カット済）")
        return final_posts
        
    except Exception as e:
        print(f"     [エラー詳細]: {e}")
        return []

# メメイン処理
current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
all_new_posts = []

for company, keywords in KEYWORDS_MAPPING.items():
    print(f"🔍 {company} の収集を開始します（対象キーワード: {', '.join(keywords)}）")
    
    for keyword in keywords:
        posts = fetch_posts(keyword)
        for post in posts:
            try:
                res = analyzer(post)[0]
                label = res['label'].lower()
                if 'positive' in label:
                    sentiment = 'ポジティブ'
                elif 'negative' in label:
                    sentiment = 'ネガティブ'
                else:
                    sentiment = 'ニュートラル'
            except:
                sentiment = 'ニュートラル'
                
            all_new_posts.append({
                "収集日時": current_time,
                "事業者": company,
                "本文": post,
                "判定": sentiment
            })

if all_new_posts:
    df_new = pd.DataFrame(all_new_posts)
    df_new["本文"] = df_new["本文"].apply(clean_text)
    
    if os.path.exists(CSV_FILE):
        df_old = pd.read_csv(CSV_FILE)
        df_old["本文"] = df_old["本文"].apply(clean_text)
        df_combined = pd.concat([df_old, df_new]).drop_duplicates(subset=["事業者", "本文"], keep="first")
    else:
        df_combined = df_new
        
    df_combined.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    print(f"✨ 完璧にクリーンなデータを保存しました。総蓄積件数: {len(df_combined)} 件")
else:
    print("❌ 新しいポストは見つかりませんでした。")
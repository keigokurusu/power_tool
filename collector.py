import os
import urllib.parse
import pandas as pd
from datetime import datetime, timedelta, timezone
from transformers import pipeline
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import random
import glob  # 👈 過去の全ファイルを検索するために新しく追加

KEYWORDS_MAPPING = {
    "東京電力": ["東京電力", "東電", "TEPCO", "テプコ"],
    "関西電力": ["関西電力", "関電", "KEPCO"],
    "中部電力": ["中部電力", "中電"],
    "九州電力": ["九州電力", "九電"],
    "リボンエナジー": ["リボンエナジー", "リボン電気"],
    "オクトパスエナジー": ["オクトパスエナジー", "オクトパス電気"],
    "looopでんき": ["looopでんき", "ループ電気", "ループでんき", "loop電気"]
}

JST = timezone(timedelta(hours=9))

# 👈 【修正】実行時の日本時間ベースでファイル名を毎月自動決定（例: electricity_posts_2026_06.csv）
current_month_str = datetime.now(JST).strftime("%Y_%m")
CSV_FILE = f"electricity_posts_{current_month_str}.csv"

analyzer = pipeline("sentiment-analysis", model="cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual")

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_tweet_time(time_text):
    now = datetime.now(JST).replace(tzinfo=None)
    if not time_text:
        return now
        
    try:
        if "T" in time_text and ("+" in time_text or "Z" in time_text):
            dt_str = time_text.split("+")[0].split("Z")[0]
            return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")
        if time_text.isdigit() and len(time_text) >= 10:
            return datetime.fromtimestamp(int(time_text[:10]))

        if "秒" in time_text:
            num = int(re.search(r'(\d+)', time_text).group(1))
            return now - timedelta(seconds=num)
        elif "分" in time_text:
            num = int(re.search(r'(\d+)', time_text).group(1))
            return now - timedelta(minutes=num)
        elif "時間" in time_text:
            num = int(re.search(r'(\d+)', time_text).group(1))
            return now - timedelta(hours=num)
            
        if "昨日" in time_text:
            time_match = re.search(r'(\d{1,2}:\d{2})', time_text)
            if time_match:
                time_str = time_match.group(1)
                yesterday = now - timedelta(days=1)
                return datetime.strptime(f"{yesterday.strftime('%Y-%m-%d')} {time_str}", "%Y-%m-%d %H:%M")

        time_match = re.search(r'(\d{1,2}:\d{2})', time_text)
        month_day_match = re.search(r'(\d{1,2})月(\d{1,2})日', time_text)

        if time_match and not month_day_match:
            time_str = time_match.group(1)
            parsed_dt = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {time_str}", "%Y-%m-%d %H:%M")
            if parsed_dt > now:
                parsed_dt -= timedelta(days=1)
            return parsed_dt

        if month_day_match:
            year_match = re.search(r'(\d{4})年', time_text)
            year = year_match.group(1) if year_match else str(now.year)
            month = month_day_match.group(1)
            day = month_day_match.group(2)
            time_str = time_match.group(1) if time_match else "00:00"
            return datetime.strptime(f"{year}-{month}-{day} {time_str}", "%Y-%m-%d %H:%M")

    except:
        pass
    return now

def fetch_posts(keyword):
    encoded_keyword = urllib.parse.quote(keyword)
    url = f"https://search.yahoo.co.jp/realtime/search?p={encoded_keyword}"
    
    raw_tweets = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url)
            
            page.wait_for_timeout(random.randint(2000, 4000))
            
            # ─── 【ガチ強化】5回スクロール ＆「もっと見る」ボタン自動連打 ───
            scroll_count = 5
            for i in range(scroll_count):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(random.randint(1000, 2000))
                
                try:
                    more_btn = page.get_by_text("もっと見る", exact=False)
                    if more_btn.is_visible():
                        more_btn.click()
                        page.wait_for_timeout(random.randint(2000, 3500))
                except:
                    pass
            
            html = page.content()
            browser.close()
            
        soup = BeautifulSoup(html, 'html.parser')
        
        elements = soup.find_all(["p", "div", "li"])
        for elem in elements:
            class_str = " ".join(elem.get("class", []))
            if any(k in class_str for k in ["Tweet", "text", "Text", "body", "Content"]):
                text = clean_text(elem.get_text())
                
                if 15 < len(text) < 280 and keyword.lower() in text.lower():
                    if "検索" in text and "ID" in text:
                        continue
                    if any(w in text for w in ["その他の投稿", "もっと見る", "メニューを開く", "公式アカウント", "関連ワード", "元のツイート"]):
                        continue
                    
                    time_text = ""
                    current = elem
                    
                    while current:
                        time_elem = current.find(lambda tag: tag.name == "time" or any("Tweet_time" in c for c in tag.get("class", [])))
                        if time_elem:
                            dt_attr = time_elem.get("datetime")
                            time_text = clean_text(dt_attr) if dt_attr else clean_text(time_elem.get_text())
                            break
                        current = current.parent
                    
                    if not time_text:
                        time_text = "今日 00:00"
                        
                    raw_tweets[text] = time_text
                        
        sorted_texts = sorted(raw_tweets.keys(), key=len)
        final_tweets = []
        for t in sorted_texts:
            is_duplicate_parent = False
            for adopted_text, _ in final_tweets:
                if adopted_text in t:
                    is_duplicate_parent = True
                    break
            
            if not is_duplicate_parent:
                parsed_time = parse_tweet_time(raw_tweets[t]).strftime("%Y-%m-%d %H:%M:%S")
                final_tweets.append((t, parsed_time))
                
        print(f"     [解析状況] 「{keyword}」で {len(final_tweets)} 件抽出（重複・ノイズ全カット済）")
        return final_tweets
        
    except Exception as e:
        print(f"     [エラー詳細]: {e}")
        return []

current_time = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")

# 👈 【新機能】月を跨いでも同じ投稿を二重回収しないよう、全CSVファイルから既知の投稿を事前にロード
csv_files = glob.glob("electricity_posts_*.csv")
known_posts = set()
if csv_files:
    for f in csv_files:
        try:
            old_df = pd.read_csv(f)
            if not old_df.empty and "事業者" in old_df.columns and "本文" in old_df.columns:
                for idx, row in old_df.iterrows():
                    known_posts.add((str(row["事業者"]), clean_text(str(row["本文"]))))
        except:
            pass

all_new_posts = []

for company, keywords in KEYWORDS_MAPPING.items():
    print(f"🔍 {company} の収集を開始します（対象キーワード: {', '.join(keywords)}）")
    
    for keyword in keywords:
        tweets = fetch_posts(keyword)
        for post, post_time in tweets:
            # 👈 過去のすべてのファイルと照合して重複をスキップ
            if (company, clean_text(post)) in known_posts:
                continue
                
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
                "投稿日時": post_time,
                "事業者": company,
                "本文": post,
                "判定": sentiment
            })

if all_new_posts:
    df_new = pd.DataFrame(all_new_posts)
    df_new["本文"] = df_new["本文"].apply(clean_text)
    
    # 👈 今月用のCSVが存在すれば合体、なければ今月初のファイルとして新規作成
    if os.path.exists(CSV_FILE):
        df_old = pd.read_csv(CSV_FILE)
        df_old["本文"] = df_old["本文"].apply(clean_text)
        df_combined = pd.concat([df_old, df_new]).drop_duplicates(subset=["事業者", "本文"], keep="first")
    else:
        df_combined = df_new
        
    df_combined.to_csv(CSV_FILE, index=False, encoding="utf-8-sig")
    print(f"✨ 今月のデータファイル【{CSV_FILE}】に保存しました。今月の総蓄積件数: {len(df_combined)} 件")
else:
    print("❌ 新しいポストは見つかりませんでした。")
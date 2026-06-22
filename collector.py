import os
import urllib.parse
import pandas as pd
# timezone を新しくインポート
from datetime import datetime, timedelta, timezone
from transformers import pipeline
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
import random

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

# 日本時間（JST）のタイムゾーンを設定
JST = timezone(timedelta(hours=9))

analyzer = pipeline("sentiment-analysis", model="cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual")

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_tweet_time(time_text):
    # 👈 常に日本時間で現在時刻を計算する（tzinfoはCSV保存用に剥ぎ取る）
    now = datetime.now(JST).replace(tzinfo=None)
    try:
        if "秒" in time_text:
            num = int(re.search(r'(\d+)', time_text).group(1))
            return now - timedelta(seconds=num)
        elif "分" in time_text:
            num = int(re.search(r'(\d+)', time_text).group(1))
            return now - timedelta(minutes=num)
        elif "時間" in time_text:
            num = int(re.search(r'(\d+)', time_text).group(1))
            return now - timedelta(hours=num)
        elif "今日" in time_text:
            time_str = re.search(r'(\d{1,2}:\d{2})', time_text).group(1)
            return datetime.strptime(f"{now.strftime('%Y-%m-%d')} {time_str}", "%Y-%m-%d %H:%M")
        else:
            year_match = re.search(r'(\d{4})年', time_text)
            year = year_match.group(1) if year_match else str(now.year)
            month_day_match = re.search(r'(\d{1,2})月(\d{1,2})日', time_text)
            if month_day_match:
                month = month_day_match.group(1)
                day = month_day_match.group(2)
                time_match = re.search(r'(\d{1,2}:\d{2})', time_text)
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
            
            random_wait = random.randint(3000, 6000)
            page.wait_for_timeout(random_wait)
            
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
                    
                    time_text = ""
                    current = elem
                    for _ in range(4):
                        if not current:
                            break
                        time_tag = current.find("time")
                        if time_tag:
                            time_text = clean_text(time_tag.get_text())
                            break
                        time_elem = current.find(lambda tag: tag.name in ["span", "div"] and any(k in " ".join(tag.get("class", [])) for k in ["time", "Time"]))
                        if time_elem:
                            time_text = clean_text(time_elem.get_text())
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
                if "メニューを開く" in t:
                    continue
                parsed_time = parse_tweet_time(raw_tweets[t]).strftime("%Y-%m-%d %H:%M:%S")
                final_tweets.append((t, parsed_time))
                
        print(f"     [解析状況] 「{keyword}」で {len(final_tweets)} 件抽出（重複・ノイズ全カット済）")
        return final_tweets
        
    except Exception as e:
        print(f"     [エラー詳細]: {e}")
        return []

# 👈 収集日時も日本時間に固定
current_time = datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S")
all_new_posts = []

for company, keywords in KEYWORDS_MAPPING.items():
    print(f"🔍 {company} の収集を開始します（対象キーワード: {', '.join(keywords)}）")
    
    for keyword in keywords:
        tweets = fetch_posts(keyword)
        for post, post_time in tweets:
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
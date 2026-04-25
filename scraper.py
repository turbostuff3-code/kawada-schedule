#!/usr/bin/env python3
"""
川田紳司 スケジュール自動取得スクレイパー
対象: グリック公式サイト + Twitter(@shinji_kawada, @kawada_staff)
"""
import json, re, time, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
TODAY = NOW.strftime('%Y-%m-%d')
EVENTS_FILE = 'events.json'

# ── Twitter Guest API ──────────────────────────────────────────────────────
BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
TW_ACCOUNTS = [
    ("shinji_kawada",  None),
    ("kawada_staff",   None),
]

SCHEDULE_KEYWORDS = [
    '出演','放送','配信','ライブ','コンサート','舞台','公演','上演',
    'イベント','発売','公開','登場','ゲスト','収録','ナレーション','アフレコ',
]

def tw_get_guest_token():
    req = urllib.request.Request(
        "https://api.twitter.com/1.1/guest/activate.json",
        data=b"",
        headers={"Authorization": f"Bearer {BEARER}"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())["guest_token"]
    except Exception as e:
        print(f"  [Twitter] guest token 取得失敗: {e}")
        return None

def tw_get_user_id(screen_name, guest_token):
    url = "https://api.twitter.com/graphql/G3KGOASz96M-Ou0nDGnktA/UserByScreenName"
    variables = json.dumps({"screen_name": screen_name, "withSafetyModeUserFields": True})
    features = json.dumps({
        "hidden_profile_likes_enabled": False,
        "hidden_profile_subscriptions_enabled": False,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "subscriptions_verification_info_is_identity_verified_enabled": False,
        "subscriptions_verification_info_verified_since_enabled": True,
        "highlights_tweets_tab_ui_enabled": True,
        "responsive_web_twitter_article_notes_tab_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
    })
    params = urllib.parse.urlencode({"variables": variables, "features": features})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={
            "Authorization": f"Bearer {BEARER}",
            "x-guest-token": guest_token,
            "User-Agent": "Mozilla/5.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return data["data"]["user"]["result"]["rest_id"]
    except Exception as e:
        print(f"  [Twitter] @{screen_name} user_id 取得失敗: {e}")
        return None

def tw_get_tweets(user_id, guest_token, count=30):
    url = "https://api.twitter.com/graphql/V7H0Ap3_Ry50_9EO-m3S_A/UserTweets"
    variables = json.dumps({
        "userId": user_id, "count": count,
        "includePromotedContent": False, "withQuickPromoteEligibilityTweetFields": False,
        "withVoice": True, "withV2Timeline": True,
    })
    features = json.dumps({
        "rweb_lists_timeline_redesign_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "tweetypie_unmention_optimization_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "freedom_of_speech_not_reach_the_sky_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": False,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": False,
        "responsive_web_enhance_cards_enabled": False,
    })
    params = urllib.parse.urlencode({"variables": variables, "features": features})
    req = urllib.request.Request(
        f"{url}?{params}",
        headers={
            "Authorization": f"Bearer {BEARER}",
            "x-guest-token": guest_token,
            "User-Agent": "Mozilla/5.0",
        }
    )
    tweets = []
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        instructions = (data.get("data", {}).get("user", {})
                        .get("result", {}).get("timeline_v2", {})
                        .get("timeline", {}).get("instructions", []))
        for inst in instructions:
            for entry in inst.get("entries", []):
                content = entry.get("content", {})
                item = content.get("itemContent", {}) or content.get("content", {})
                tweet_result = item.get("tweet_results", {}).get("result", {})
                legacy = tweet_result.get("legacy", {})
                if legacy.get("full_text"):
                    tweets.append({
                        "text": legacy["full_text"],
                        "created_at": legacy.get("created_at", ""),
                    })
    except Exception as e:
        print(f"  [Twitter] tweets 取得失敗: {e}")
    return tweets

def parse_date_from_text(text):
    """ツイートテキストから日付を抽出"""
    year = NOW.year
    patterns = [
        r'(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})[日]?',
        r'(\d{1,2})[月/](\d{1,2})[日]',
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            groups = m.groups()
            if len(groups) == 3:
                y, mo, dy = int(groups[0]), int(groups[1]), int(groups[2])
            else:
                mo, dy = int(groups[0]), int(groups[1])
                y = year if mo >= NOW.month else year + 1
            try:
                return f"{y:04d}-{mo:02d}-{dy:02d}"
            except:
                pass
    return None

def guess_category(text):
    if any(w in text for w in ['舞台','公演','上演','ミュージカル','劇場']): return 'stage'
    if any(w in text for w in ['ライブ','コンサート','フェス']): return 'stage'
    if any(w in text for w in ['ラジオ']): return 'radio'
    if any(w in text for w in ['映画','DVD','Blu-ray','劇場版']): return 'movie'
    if any(w in text for w in ['イベント','サイン会','握手会','トーク']): return 'event'
    return 'tv'

def normalize_title(t):
    return re.sub(r'[　\s「」『』【】〔〕（）()！!？?～〜・、。,.\-_]', '', t).lower()

def scrape_twitter():
    print("Twitter スクレイピング中...")
    guest_token = tw_get_guest_token()
    if not guest_token:
        return []

    new_events = []
    event_id_base = 200

    for i, (screen_name, cached_uid) in enumerate(TW_ACCOUNTS):
        print(f"  @{screen_name} を取得中...")
        uid = cached_uid or tw_get_user_id(screen_name, guest_token)
        if not uid:
            continue
        tweets = tw_get_tweets(uid, guest_token)
        print(f"    {len(tweets)} ツイート取得")

        for tweet in tweets:
            text = tweet["text"]
            if not any(kw in text for kw in SCHEDULE_KEYWORDS):
                continue
            date_str = parse_date_from_text(text)
            if not date_str or date_str < TODAY:
                continue
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            title = lines[0][:40] if lines else text[:40]
            title = re.sub(r'https?://\S+', '', title).strip()
            if not title:
                continue
            new_events.append({
                "id": event_id_base + len(new_events),
                "title": title,
                "category": guess_category(text),
                "dateStart": date_str,
                "dateEnd": None,
                "venue": "",
                "note": re.sub(r'https?://\S+', '', text[:100]).strip(),
            })
        time.sleep(1)

    return new_events

def load_existing():
    try:
        with open(EVENTS_FILE, encoding='utf-8') as f:
            return json.load(f)
    except:
        return {"updatedAt": "", "events": []}

def merge_events(existing, new_events):
    ex_keys = set()
    for e in existing:
        ex_keys.add((normalize_title(e["title"]), e["dateStart"]))

    added = 0
    for ev in new_events:
        key = (normalize_title(ev["title"]), ev["dateStart"])
        if key not in ex_keys:
            existing.append(ev)
            ex_keys.add(key)
            added += 1
    return added

def main():
    data = load_existing()
    existing = data.get("events", [])
    print(f"既存イベント数: {len(existing)}")

    new_events = scrape_twitter()
    added = merge_events(existing, new_events)
    print(f"新規追加: {added} 件")

    data["events"] = existing
    data["updatedAt"] = NOW.strftime('%Y-%m-%d %H:%M:%S')

    with open(EVENTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print("events.json を更新しました")

if __name__ == "__main__":
    main()

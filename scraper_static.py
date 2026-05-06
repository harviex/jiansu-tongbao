#!/usr/bin/env python3
"""
政府通报爬虫 - 静态版本
输出JSON文件到 public/data/ 目录，用于GitHub Pages托管
"""
import json
import re
import time
import subprocess
from datetime import datetime
from pathlib import Path
import os

# Config
LIST_URL = "http://zzxszy.people.cn/GB/458759/index.html"
KEYWORD = "中央层面整治形式主义为基层减负专项工作机制办公室"

# Problem category keywords for classification
PROBLEM_CATEGORIES = {
    "层层加码": ["层层加码", "加码", "指标任务", "摊派任务"],
    "数据造假": ["数据造假", "弄虚作假", "虚报", "伪造", "充数"],
    "形式主义": ["形式主义", "走过场", "形式大于内容", "重形式"],
    "官僚主义": ["官僚主义", "脱离群众", "不作为", "乱作为"],
    "脱离实际": ["脱离实际", "不切实际", "不顾实际", "盲目"],
    "考核泛滥": ["考核", "评比", "排名", "通报排名", "月调度"],
    "资源浪费": ["浪费", "利用率低", "资金浪费", "闲置"],
    "强制摊派": ["强制", "摊派", "强推", "行政命令", "硬性"]
}

# Province mapping
PROVINCES = [
    "北京", "天津", "河北", "山西", "内蒙古", "辽宁", "吉林", "黑龙江",
    "上海", "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南",
    "湖北", "湖南", "广东", "广西", "海南", "重庆", "四川", "贵州",
    "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆"
]

# Paths
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
NOTICES_FILE = DATA_DIR / "notices.json"
STATS_FILE = DATA_DIR / "stats.json"

def fetch_page(url):
    """Fetch a page using Firecrawl for better content extraction"""
    try:
        import subprocess
        api_key = os.environ.get('FIRECRAWL_API_KEY', 'fc-***')
        result = subprocess.run([
            'curl', '-s', '-m', '15',
            '-X', 'POST', 'https://api.firecrawl.dev/v1/scrape',
            '-H', f'Authorization: Bearer {api_key}',
            '-H', 'Content-Type: application/json',
            '-d', json.dumps({"url": url, "formats": ["markdown"]})
        ], capture_output=True, text=True, timeout=20)
        
        data = json.loads(result.stdout)
        if data.get('success'):
            return data['data'].get('markdown', ''), data['data'].get('metadata', {})
    except Exception as e:
        print(f"  Firecrawl failed, fallback to curl: {e}")
    
    # Fallback to direct curl
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode('utf-8', errors='replace'), {}
    except Exception as e:
        print(f"  Fetch error: {e}")
        return '', {}


def parse_list_page(html):
    """Extract article links from the list page"""
    articles = []
    # Pattern: links with target keyword in title
    pattern = r'<a[^>]+href="([^"]+)"[^>]*>([^<]*' + re.escape(KEYWORD[:10]) + r'[^<]*)</a>'
    for match in re.finditer(pattern, html, re.DOTALL):
        url, title = match.group(1), match.group(2).strip()
        # Clean title
        title = re.sub(r'<[^>]+>', '', title).strip()
        if KEYWORD in title and url:
            if not url.startswith('http'):
                url = 'http://zzxszy.people.cn' + url
            articles.append({'url': url, 'title': title})
    
    # Also try markdown format from Firecrawl
    if not articles:
        md_pattern = r'\[([^\]]*' + re.escape(KEYWORD[:15]) + r'[^\\]]*)\]\(([^)]+)\)'
        for match in re.finditer(md_pattern, html, re.DOTALL):
            title, url = match.group(1).strip(), match.group(2).strip()
            if KEYWORD in title:
                if not url.startswith('http'):
                    url = 'http://zzxszy.people.cn' + url
                articles.append({'url': url, 'title': title})
    
    # Deduplicate by URL
    seen = set()
    unique = []
    for a in articles:
        if a['url'] not in seen:
            seen.add(a['url'])
            unique.append(a)
    
    return unique


def extract_date(title, content):
    """Extract publish date from title or content"""
    # Try patterns like 2024年04月08日
    for text in [content, title]:
        match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
        if match:
            return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    # Try URL pattern like /n1/2024/0408/
    match = re.search(r'/n1/(\d{4})/(\d{2})(\d{2})/', title + content)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def classify_content(content, title):
    """Classify content into problem categories and provinces"""
    full_text = title + ' ' + content
    
    tags = []
    for category, keywords in PROBLEM_CATEGORIES.items():
        for kw in keywords:
            if kw in full_text:
                tags.append(category)
                break
    
    provinces = []
    for prov in PROVINCES:
        if prov in full_text and prov not in provinces:
            provinces.append(prov)
    
    # Count cases (X起)
    case_count = None
    match = re.search(r'(\d+)\s*起', title)
    if match:
        case_count = int(match.group(1))
    
    return tags, provinces, case_count


def extract_article_content(markdown):
    """Extract main content from Firecrawl markdown"""
    # Remove header/footer/nav content
    lines = markdown.split('\n')
    content_lines = []
    skip = True
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Start collecting after the date line
        if re.search(r'\d{4}年\d{1,2}月\d{1,2}日\d{2}:\d{2}', line):
            skip = False
            continue
        if skip:
            continue
        # Stop at footer
        if '版权' in line or '人民网' in line or '责任编辑' in line or '责编' in line:
            break
        if line.startswith('!['):
            continue
        content_lines.append(line)
    
    return '\n'.join(content_lines).strip()


def load_existing_data():
    """Load existing notices from JSON file"""
    if NOTICES_FILE.exists():
        with open(NOTICES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []


def save_data(notices):
    """Save notices to JSON file and generate stats"""
    # Sort by date (newest first)
    notices.sort(key=lambda x: x.get('publish_date', '0000-00-00'), reverse=True)
    
    # Save notices
    with open(NOTICES_FILE, 'w', encoding='utf-8') as f:
        json.dump(notices, f, ensure_ascii=False, indent=2)
    
    # Generate stats
    total = len(notices)
    by_level = {}
    provinces_count = {}
    tags_count = {}
    
    for notice in notices:
        level = notice.get('level_1', '未知')
        by_level[level] = by_level.get(level, 0) + 1
        
        for prov in notice.get('provinces', []):
            provinces_count[prov] = provinces_count.get(prov, 0) + 1
        
        for tag in notice.get('tags', []):
            tags_count[tag] = tags_count.get(tag, 0) + 1
    
    stats = {
        'total': total,
        'byLevel': [{'level_1': k, 'count': v} for k, v in sorted(by_level.items())],
        'provinces': [{'province': k, 'count': v} for k, v in sorted(provinces_count.items(), key=lambda x: -x[1])],
        'tags': [{'tag': k, 'count': v} for k, v in sorted(tags_count.items(), key=lambda x: -x[1])],
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)
    
    return stats


def main():
    print(f"🔍 通报爬虫启动 (静态版) - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # Load existing data
    notices = load_existing_data()
    existing_urls = {n['source_url'] for n in notices}
    print(f"   已有数据: {len(notices)} 条")
    
    # Fetch list page
    print(f"\n📄 抓取列表页...")
    html, _ = fetch_page(LIST_URL)
    if not html:
        print("❌ 列表页抓取失败")
        return
    
    articles = parse_list_page(html)
    print(f"   找到 {len(articles)} 篇文章链接")
    
    # Filter new articles
    new_articles = [a for a in articles if a['url'] not in existing_urls]
    print(f"   新文章: {len(new_articles)} 篇")
    
    if not new_articles:
        print("✅ 没有新文章需要抓取")
        # Still update stats (in case JSON was manually edited)
        stats = save_data(notices)
        print(f"   统计已更新: {stats['total']} 条")
        return
    
    # Process each new article
    inserted = 0
    for i, article in enumerate(new_articles):
        print(f"\n[{i+1}/{len(new_articles)}] {article['title'][:50]}...")
        
        # Fetch article
        content_md, meta = fetch_page(article['url'])
        if not content_md:
            print("  ⚠️ 抓取失败，跳过")
            continue
        
        # Extract content
        content = extract_article_content(content_md)
        if not content:
            content = content_md
        
        # Extract date
        pub_date = extract_date(article['title'], content)
        print(f"  日期: {pub_date}")
        
        # Classify
        tags, provinces, case_count = classify_content(content, article['title'])
        print(f"  标签: {tags}")
        print(f"  省份: {provinces}")
        
        # Create notice object
        notice = {
            'id': len(notices) + inserted + 1,
            'title': article['title'],
            'source_url': article['url'],
            'level_1': '中央',
            'level_2': tags,
            'publish_date': pub_date,
            'content': content[:2000],  # Limit content length for browser performance
            'content_preview': content[:200] + '...' if len(content) > 200 else content,
            'tags': tags,
            'provinces': provinces,
            'case_count': case_count,
            'source_site': '人民网',
            'ai_processed': False
        }
        
        notices.append(notice)
        inserted += 1
        print(f"  ✅ 已添加")
        
        time.sleep(1)  # Be polite
    
    # Save all data
    print(f"\n{'='*40}")
    stats = save_data(notices)
    print(f"✅ 完成！新增 {inserted} 条通报")
    print(f"   总计: {stats['total']} 条")
    print(f"   统计文件: {STATS_FILE}")
    print(f"   数据文件: {NOTICES_FILE}")


if __name__ == "__main__":
    main()

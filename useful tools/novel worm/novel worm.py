import requests
from lxml import etree
import time
import os
import re
from urllib.parse import urljoin, urlparse

# ===== 配置区 =====
CONTENT_XPATHS = [
    '//div[@id="content"]',
    '//div[@class="content"]',
    '//div[@id="txt"]',
    '//div[@class="txt"]',
    '//div[contains(@class, "read-content")]',
    '//div[contains(@class, "article")]',
    '//div[@class="panel-body"]',
    '//div[@class="page-content"]',
    '//div[@id="chapter_content"]',
    '//div[contains(@class, "chapter") and contains(@class, "content")]',
]

NEXT_CHAPTER_KEYWORDS = ["下一章", "下一页", "Next Chapter", "Next", "→", "»", "下节", "继续阅读"]

FILTER_PATTERNS = [
    r'请记住本站域名',
    r'手机阅读.*?网址',
    r'最新章节.*?首发',
    r'免费阅读.*?全文',
    r'点击进入.*?阅读最新章节',
    r'本书来自.*?阅读网',
    r'更多免费小说.*?下载',
    r'扫描二维码.*?手机阅读',
    r'投票推荐\s*加入书签\s*留言反馈',
    r'www\.[a-zA-Z0-9\-]+\.(com|net|org|cc|me)',
    r'http[s]?://[^\s]+',
    r'本章未完.*?请点击下一页继续阅读',
    r'加入书架|收藏本站|打赏作者|推荐票',
    r'第\d+页/共\d+页',
    r'『.*?』更新最快',  # 广告水印
    r'首页\s*上一章\s*下一章\s*末页',  # 分页导航
]

# ===== 工具函数 =====

def clean_text(text):
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(re.search(pat, stripped, re.IGNORECASE) for pat in FILTER_PATTERNS):
            continue
        cleaned.append(stripped)
    return '\n\n'.join(cleaned)

def extract_content(e):
    for xpath in CONTENT_XPATHS:
        nodes = e.xpath(xpath)
        if nodes:
            raw_parts = []
            for node in nodes:
                # 使用 string() 提取所有子文本，保留自然换行
                text = node.xpath('string(.)')
                if text:
                    raw_parts.append(text)
            raw_text = '\n'.join(raw_parts).strip()
            if len(raw_text) > 50:
                cleaned = clean_text(raw_text)
                if cleaned:
                    return cleaned
    return None

def find_next_chapter_url(e, current_url):
    # 构建关键词条件
    text_conditions = ' or '.join([f'contains(., "{kw}")' for kw in NEXT_CHAPTER_KEYWORDS])
    # 注意：用 . 而不是 text()，因为有些“下一章”在 <span> 内
    xpath_expr = f'//a[({text_conditions}) or contains(@class, "next") or contains(@id, "next")]/@href'
    
    links = e.xpath(xpath_expr)
    links = [link.strip() for link in links if link and link.strip()]
    
    if not links:
        # 备用分页策略
        backup_xpaths = [
            '//div[@class="page"]//a[last()]/@href',
            '//div[contains(@class, "pager")]//a[last()]/@href',
            '//ul[contains(@class, "pagination")]//a[last()]/@href',
            '//a[@rel="next"]/@href',  # 标准 rel="next"
        ]
        for xp in backup_xpaths:
            candidates = e.xpath(xp)
            if candidates:
                links = [candidates[-1].strip()]
                break

    if links:
        next_url = links[0]
        if not next_url.startswith(('http://', 'https://')):
            next_url = urljoin(current_url, next_url)
        # 验证 URL 是否有效（有 scheme 和 netloc）
        parsed = urlparse(next_url)
        if parsed.scheme in ('http', 'https') and parsed.netloc:
            return next_url
    return None

def get_chapter_content(url, headers, visited_urls, book_file, retry=2):
    session = requests.Session()
    for attempt in range(retry + 1):
        try:
            resp = session.get(url, headers=headers, timeout=12)
            # 自动编码检测（更可靠）
            if resp.encoding == 'ISO-8859-1':
                resp.encoding = resp.apparent_encoding or 'utf-8'
            else:
                resp.encoding = 'utf-8'
            break
        except Exception as e:
            wait = 2 * (attempt + 1)
            print(f"⚠️ 请求失败（{url}），{wait}秒后第 {attempt + 1} 次重试... 错误: {e}")
            if attempt == retry:
                print("❌ 最终请求失败，跳过本章")
                return None
            time.sleep(wait)

    try:
        e = etree.HTML(resp.text)

        # 获取标题
        title_candidates = e.xpath('//h1/text()') or e.xpath('//title/text()')
        title = title_candidates[0].strip() if title_candidates else f"未知章节_{int(time.time())}"
        title = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', title)[:60]  # 截断过长标题

        # 提取正文
        content = extract_content(e) or "【正文提取失败】\n"

        # 写入文件（使用当前章节数 = len(visited_urls)，因本章已加入）
        chapter_num = len(visited_urls)
        book_file.write(f"{'='*20} 第 {chapter_num} 章：{title} {'='*20}\n\n")
        book_file.write(content)
        book_file.write("\n\n" + "-" * 80 + "\n\n")
        book_file.flush()

        print(f"✅ 第 {chapter_num} 章：{title}")

        # 查找下一章
        next_url = find_next_chapter_url(e, url)
        if next_url and next_url not in visited_urls:
            return next_url
        else:
            if next_url in visited_urls:
                print("🔄 检测到循环链接，停止爬取")
            else:
                print("❌ 未找到有效下一章链接")
            return None

    except Exception as e:
        print(f"💥 解析异常（{url}）：{e}")
        return None
    finally:
        session.close()

# ===== 主流程 =====

def crawl_full_book():
    print("=" * 60)
    print("📚 小说全本爬虫（增强稳定版 v2.1）")
    print("=" * 60)

    # 输入起始URL
    start_url = input("\n🔗 输入第一章完整URL（必须以 http(s):// 开头）：").strip()
    while not re.match(r'^https?://', start_url):
        start_url = input("❗ 无效URL，请重新输入：").strip()

    # User-Agent（移除默认值，强制用户输入）
    print("\nℹ️  提示：User-Agent可从浏览器开发者工具的Network面板中获取")
    user_agent = input("🌐 请输入你的User-Agent（不能为空）：").strip()
    # 循环校验，直到用户输入有效内容
    while not user_agent:
        print("❌ 错误：User-Agent不能为空，请务必输入！")
        user_agent = input("🌐 重新输入User-Agent：").strip()

    # 书名
    book_name = input("\n📖 书籍名称（用于命名文件夹和文件）：").strip()
    if not book_name:
        domain = urlparse(start_url).netloc.replace('www.', '')
        book_name = f"{domain}_novel_{time.strftime('%Y%m%d_%H%M')}"

    # 创建安全路径
    safe_name = re.sub(r'[\\/:*?"<>|\r\n\t]', '_', book_name)
    book_folder = os.path.join(os.getcwd(), safe_name)
    os.makedirs(book_folder, exist_ok=True)
    book_path = os.path.join(book_folder, f"{safe_name}.txt")

    # 请求头
    headers = {
        'User-Agent': user_agent,
        'Referer': start_url,
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Connection': 'close',
    }

    print(f"\n📂 保存路径：{book_path}")
    print(f"⏱️  爬取间隔：1.5 秒/章（防封IP）")
    print("\n🚀 开始爬取...\n")

    visited_urls = set()
    current_url = start_url

    with open(book_path, "w", encoding="utf-8") as f:
        while current_url and current_url not in visited_urls:
            visited_urls.add(current_url)
            next_url = get_chapter_content(current_url, headers, visited_urls, f)
            if next_url:
                time.sleep(1.5)
                current_url = next_url
            else:
                break

    print("\n" + "=" * 60)
    print(f"🎉 爬取完成！共 {len(visited_urls)} 章")
    print(f"📄 文件位置：{os.path.abspath(book_path)}")
    print("=" * 60)

# ===== 入口 =====
if __name__ == "__main__":
    try:
        crawl_full_book()
    except KeyboardInterrupt:
        print("\n\n🛑 用户中断操作")
    except Exception as e:
        print(f"\n💥 程序崩溃：{e}")
        import traceback
        traceback.print_exc()
    finally:
        input("\n按回车键退出...")


        
import requests
from bs4 import BeautifulSoup
import json
import time
import uuid
import logging
from datetime import datetime
from openai import OpenAI
from typing import List, Dict, Optional

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class GasgooScraper:
    """感知模块：负责网页数据采集"""
    def __init__(self):
        self.base_url = "https://autonews.gasgoo.com"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }

    def get_article_list(self, limit: int = 5) -> List[Dict]:
        """抓取首页文章列表"""
        try:
            logging.info(f"正在访问首页: {self.base_url}")
            response = requests.get(self.base_url, headers=self.headers, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            articles = []
            # 注意：选择器需根据实际页面结构微调，此处为通用逻辑示意
            items = soup.select('.list-item') or soup.select('div.media') 
            
            for item in items[:limit]:
                link_tag = item.find('a')
                if not link_tag: continue
                
                url = link_tag['href']
                if not url.startswith('http'):
                    url = self.base_url + url
                
                articles.append({
                    "title": link_tag.get_text(strip=True),
                    "url": url
                })
            return articles
        except Exception as e:
            logging.error(f"抓取列表失败: {e}")
            return []

    def fetch_content(self, url: str) -> Dict:
        """抓取文章正文及元数据"""
        try:
            res = requests.get(url, headers=self.headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 自动过滤标签与脚本
            for tag in soup(['script', 'style', 'footer', 'nav']):
                tag.decompose()
            
            # 提取核心内容 (针对 Gasgoo 常见的正文容器)
            content_div = soup.select_one('.article-content') or soup.select_one('.content')
            full_text = content_div.get_text(separator='\n', strip=True) if content_div else ""
            
            # 提取发布时间与来源
            pub_date = soup.select_one('.time').get_text(strip=True) if soup.select_one('.time') else datetime.now().isoformat()
            source = soup.select_one('.source').get_text(strip=True) if soup.select_one('.source') else "Gasgoo"

            return {
                "title": soup.title.string.replace("-Gasgoo", "").strip(),
                "full_content": full_text[:5000],  # 截断防止 Token 溢出
                "pub_date": pub_date,
                "source": source
            }
        except Exception as e:
            logging.warning(f"解析文章 {url} 失败: {e}")
            return None

class IndustryAnalystAgent:
    """决策/处理模块：LLM 摘要引擎"""
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = "gpt-4o" # 或 "deepseek-chat"

    def summarize(self, text: str, retries: int = 3) -> Optional[Dict]:
        """执行 AI 摘要并进行自校验"""
        system_prompt = """你是一位资深汽车行业分析师。请阅读以下文章，提取核心洞察。
请严格按 JSON 格式输出：
{
  "key_points": ["核心事件1", "核心事件2"],
  "companies": ["关键公司1"],
  "impact": "行业影响简述",
  "sentiment": "Neutral/Positive/Negative",
  "priority": 1-5
}
规则：字数控制在150字以内，语气客观专业。"""

        for i in range(retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text}
                    ],
                    response_format={"type": "json_object"}
                )
                return json.loads(response.choices[0].message.content)
            except Exception as e:
                logging.warning(f"LLM 调用重试 ({i+1}/{retries}): {e}")
                time.sleep(2)
        return None

class WorkflowManager:
    """分发模块：流程编排"""
    def __init__(self, api_key: str):
        self.scraper = GasgooScraper()
        self.agent = IndustryAnalystAgent(api_key=api_key)

    def run(self):
        logging.info("启动自动化采集任务...")
        raw_articles = self.scraper.get_article_list(limit=3)
        
        final_results = []

        for item in raw_articles:
            logging.info(f"正在处理: {item['title']}")
            
            # 1. 抓取全文
            detail = self.scraper.fetch_content(item['url'])
            if not detail or not detail['full_content']:
                continue

            # 2. AI 处理
            analysis = self.agent.summarize(detail['full_content'])
            if not analysis:
                continue

            # 3. 结构化组装 (符合 PRD 4.1 Schema)
            record = {
                "article_id": str(uuid.uuid4()),
                "source_url": item['url'],
                "raw_data": {
                    "title": detail['title'],
                    "full_content": detail['full_content'][:200] + "..." # 仅存缩略
                },
                "ai_summary": analysis,
                "status": "processed",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            final_results.append(record)
            
            # 频率控制
            time.sleep(1)

        # 输出结果
        self._save_results(final_results)

    def _save_results(self, data):
        filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logging.info(f"任务完成，报告已生成: {filename}")

# --- 执行入口 ---
if __name__ == "__main__":
   import os
    # 优先从系统环境变量读取, Key存储在“Settings -> Secrets and variables -> Actions”
    API_KEY = os.getenv("OPENAI_API_KEY")     
    manager = WorkflowManager(api_key=API_KEY)
    manager.run()
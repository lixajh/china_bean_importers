from dateutil.parser import parse
from beancount.ingest import importer
from beancount.core import data, amount
from beancount.core.number import D

import re
import datetime
from bs4 import BeautifulSoup
import email
from email import policy

from china_bean_importers.common import *


class Importer(importer.ImporterProtocol):
    def __init__(self, config) -> None:
        super().__init__()
        self.config = config

    def identify(self, file):
        if not file.name.upper().endswith(".EML"):
            return False

        try:
            with open(file.name, "rb") as f:
                raw_email = email.message_from_binary_file(f, policy=policy.default)
            
            # 检查发件人
            from_addr = raw_email.get("From", "")
            if "abchina.com" not in from_addr:
                return False
            
            # 检查标题
            subject = raw_email.get("Subject", "")
            if "农业银行" in subject and "对账单" in subject:
                return True
            
            # 或者检查内容体
            body_part = raw_email.get_body()
            if body_part:
                body = body_part.get_payload(decode=True).decode('utf-8', errors='ignore')
                if "中国农业银行" in body and "对账单" in body:
                    return True
        except Exception:
            return False
        return False

    def file_account(self, file):
        return "abc_credit_card"

    def extract(self, file, existing_entries=None):
        entries = []

        with open(file.name, "rb") as f:
            raw_email = email.message_from_binary_file(f, policy=policy.default)
        
        body_part = raw_email.get_body()
        if not body_part:
            return []
        
        html_content = body_part.get_payload(decode=True).decode('utf-8', errors='ignore')
        soup = BeautifulSoup(html_content, features="lxml")

        # 农业银行的交易明细通常在 table 里的 tr
        # 我们根据之前的分析找包含 "交易日期" 的 table
        tables = soup.find_all("table")
        target_table = None
        for table in tables:
            if "交易日期" in table.text and "交易说明" in table.text:
                # 这个 table 可能是表头，数据在那之后的 table 里或者就在这个 table 的 tr 里
                target_table = table
                # 农行的结构是：分类标题（如“还款”、“消费”）一个 table，流水一个 table
                # 我们遍历所有 table，寻找符合流水格式的 tr
        
        # 避免嵌套 table 导致重复解析
        # 我们只解析那些直接包含数据行的 table
        for table in tables:
            # 检查这个 table 是否包含我们的目标表头，或者其父 table 已经处理过
            # 农行的结构里，数据行通常在没有嵌套 table 的直接 tr 中
            rows = table.find_all("tr", recursive=False)
            for lineno, row in enumerate(rows):
                cols = [col.get_text().strip() for col in row.find_all("td", recursive=False)]
                
                # 预期的列：交易日期, 入账日期, 卡号末四位, 交易说明, 交易金额, 入账金额
                if len(cols) < 6:
                    continue
                
                # 检查第一列是否是 6 位数字日期 (YYMMDD)
                if not re.match(r"^\d{6}$", cols[0]):
                    continue
                
                # 交易日期
                trans_date_str = cols[0]
                post_date_str = cols[1]
                card_tail = cols[2]
                narration = cols[3]
                sett_amt_str = cols[5] # 入账金额/币种
                
                # 解析金额 "4000.00/CNY" 或 "-84.58/CNY"
                amt_match = re.match(r"^(-?[\d,.]+)/([A-Z]+)$", sett_amt_str)
                if not amt_match:
                    continue
                
                amt_val = amt_match.group(1).replace(",", "")
                currency = amt_match.group(2)
                units = amount.Amount(D(amt_val), currency)
                
                # 日期解析 YYMMDD -> 20YY-MM-DD
                year = 2000 + int(trans_date_str[:2])
                month = int(trans_date_str[2:4])
                day = int(trans_date_str[4:6])
                date = datetime.date(year, month, day)

                # 黑名单检查（过滤支付宝、微信等重复流水）
                if in_blacklist(self.config, narration):
                    continue

                metadata = data.new_metadata(file.name, lineno)
                tags = {"PendingReview"}
                
                # 账户识别
                if not card_tail:
                    # 如果卡号为空（如利息流水），尝试找默认账户
                    account1 = self.config["importers"]["abc"]["account"] if "abc" in self.config["importers"] else "Liabilities:CreditCard:ABC:Unknown"
                else:
                    account1 = find_account_by_card_number(self.config, card_tail)
                    if not account1:
                        account1 = f"Liabilities:CreditCard:ABC:{card_tail}"
                
                # 目标账户映射
                payee = None
                if "，" in narration:
                    parts = narration.split("，", 1)
                    payee = parts[1].strip()
                    narration_clean = parts[0].strip()
                else:
                    narration_clean = narration

                # 特殊处理还款
                if "还款" in narration or "存款" in narration:
                    # 还款通常是从储蓄卡转入
                    account2 = "Assets:Banking:CMB:1234" # 默认从主卡还款，用户可后期修改
                    tags.add("repayment")
                else:
                    account2, new_meta, new_tags = match_destination_and_metadata(
                        self.config, narration, payee
                    )
                    if not account2:
                        is_expense = units.number < 0
                        account2 = unknown_account(self.config, is_expense)
                    
                    metadata.update(new_meta)
                    tags = tags.union(new_tags)

                txn = data.Transaction(
                    meta=metadata,
                    date=date,
                    flag=self.FLAG,
                    payee=payee,
                    narration=narration_clean,
                    tags=tags,
                    links=data.EMPTY_SET,
                    postings=[
                        data.Posting(account1, units, None, None, None, None),
                        data.Posting(account2, None, None, None, None, None),
                    ],
                )
                entries.append(txn)

        return entries

from dateutil.parser import parse
from beancount.core import data, amount
from beancount.core.number import D
import re
import os

from china_bean_importers.common import *
from china_bean_importers.importer import CsvOrXlsxImporter

class Importer(CsvOrXlsxImporter):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.match_keywords = ['交易时间', '业务摘要', '收入金额', '支出金额', '对方账户名称']
        self.file_account_name = "boc_debit_card_xlsx"

    def identify(self, file):
        if not file.name.endswith(".xlsx"):
            return False
        if not "中国银行" in file.name:
            return False
        
        # 为了识别，我们读一下表头
        try:
            import pandas as pd
            df = pd.read_excel(file.name, nrows=0)
            if all(col in df.columns for col in self.match_keywords):
                self.parse_metadata(file)
                return True
        except Exception:
            pass
        return False

    def parse_metadata(self, file):
        # 尝试从文件名提取尾号
        match = re.search(r"尾号(\d{4})", os.path.basename(file.name))
        if match:
            card_number = match.group(1)
            self.card_acc = find_account_by_card_number(self.config, card_number)
        else:
            self.card_acc = None
        self.start = None

    def extract(self, file, existing_entries=None):
        import pandas as pd
        df = pd.read_excel(file.name)
        
        entries = []
        for index, row in df.iterrows():
            txn = self.generate_tx(row.to_dict(), index, file)
            if txn:
                entries.append(txn)
        return entries

    def generate_tx(self, row, lineno, file):
        date_raw = row.get('交易时间')
        if not date_raw or str(date_raw) == 'nan':
            return None

        # 处理 pandas 可能读出的 datetime 或字符串
        if isinstance(date_raw, str):
            date_str = date_raw.split('\u00a0')[0]
            date = parse(date_str).date()
        else:
            date = date_raw.date()
            
        payee = str(row.get('对方账户名称', '')).strip()
        if payee == 'nan' or not payee:
            payee = "Unknown"
            
        summary = str(row.get('业务摘要', '')).strip()
        remark = str(row.get('附言', '')).strip()
        narration = summary
        if remark != 'nan' and remark:
            narration = f"{summary} ({remark})"
        
        income = row.get('收入金额')
        expense = row.get('支出金额')
        
        try:
            if income and str(income) != 'nan' and float(income) != 0:
                units1 = amount.Amount(D(str(income)), "CNY")
            elif expense and str(expense) != 'nan' and float(expense) != 0:
                units1 = amount.Amount(-D(str(expense)), "CNY")
            else:
                return None
        except Exception:
            return None

        # check blacklist
        if in_blacklist(self.config, narration):
            print(
                f"Item in blacklist: {date} {narration} [{units1}] (Skipped)",
                file=sys.stderr,
            )
            return None

        metadata = data.new_metadata(file.name, lineno)
        if row.get('余额') and str(row.get('余额')) != 'nan':
            metadata["balance"] = str(row.get('余额'))
        
        # 对方账户账号 (用于识别内部转账)
        opp_account_raw = str(row.get('对方账户账号', '')).strip()
        if opp_account_raw and opp_account_raw != 'nan':
            metadata["payee_account"] = opp_account_raw
            # 提取后四位尝试匹配内部账户
            tail_match = re.search(r'(\d{4})$', opp_account_raw)
            if tail_match:
                opp_tail = tail_match.group(1)
                internal_acc = find_account_by_card_number(self.config, opp_tail)
                if internal_acc:
                    account2 = internal_acc

        tags = {"PendingReview"}
        if account2 is None:
            if m := match_destination_and_metadata(self.config, narration, payee, expense=units1.number < 0):
                (account2, new_meta, new_tags) = m
                metadata.update(new_meta)
                tags = tags.union(new_tags)
        
        if account2 is None:
            account2 = unknown_account(self.config, units1.number < 0)

        card_acc = self.card_acc if self.card_acc else unknown_account(self.config, units1.number > 0)

        return data.Transaction(
            meta=metadata,
            date=date,
            flag=self.FLAG,
            payee=payee,
            narration=narration,
            tags=tags,
            links=data.EMPTY_SET,
            postings=[
                data.Posting(card_acc, units1, None, None, None, None),
                data.Posting(account2, None, None, None, None, None),
            ],
        )

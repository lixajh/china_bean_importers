from dateutil.parser import parse
from beancount.core import data, amount
from beancount.core.number import D
import csv

from china_bean_importers.common import *
from china_bean_importers.importer import CsvImporter


class Importer(CsvImporter):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.encoding = "gbk"
        self.match_keywords = ["记录时间", "收支类型", "账单同步"]
        self.file_account_name = "alipay_cashbook"

    def parse_metadata(self, file):
        # 记账本格式通常不含明确的起始/终止时间行，可从数据中推断或留空
        pass

    def extract(self, file, existing_entries=None):
        entries = []
        
        # 跳过说明行，直接从表头开始寻找
        begin = False
        reader = csv.reader(self.content)
        for lineno, row in enumerate(reader):
            row = [col.strip() for col in row]
            if len(row) < 4:
                continue
            
            # 表头识别: 记录时间,分类,收支类型,金额,备注,账户,来源,标签,
            if "记录时间" in row[0] and "收支类型" in row[2]:
                begin = True
                continue
            
            if begin:
                metadata = data.new_metadata(file.name, lineno)
                
                # 记录时间,分类,收支类型,金额,备注,账户,来源,标签
                # 2025-12-31 19:52:14, 生活日用, 支出, 5.66, ...
                time_str, category, direction, amt, narration, method, source, tags_str = row[:8]
                
                time = parse(time_str)
                units = amount.Amount(D(amt), "CNY")
                
                metadata["time"] = time.time().isoformat()
                metadata["imported_category"] = category
                metadata["payment_method"] = method
                
                # 确定正负号
                expense = direction == "支出"
                if expense:
                    units = -units
                
                # 确定账户 (借鉴 alipay_mobile 的逻辑)
                source_config = self.config["importers"]["alipay"]
                
                # 这里的 method 是 "中国银行", "中国农业银行" 等
                # 我们尝试匹配卡号后缀或直接查找映射
                account1 = source_config["account"] 
                
                # 尝试根据银行名称找账户
                if "中国银行" in method:
                    account1 = "Liabilities:CreditCard:BOC:8119"
                elif "中国农业银行" in method or "农行" in method:
                    account1 = "Liabilities:CreditCard:ABC:8113"
                elif "招商银行" in method:
                    account1 = "Assets:Banking:CMB:1234"
                elif "余额" in method:
                    account1 = "Assets:Digital:Alipay"
                elif "民生银行" in method:
                    account1 = "Assets:Banking:MSB:6664"
                
                # 匹配目标账户
                account2, new_meta, new_tags = match_destination_and_metadata(
                    self.config, narration, "", expense=expense
                )
                
                # 如果没匹配到，根据分类映射
                if account2 is None:
                    if category in source_config.get("category_mapping", {}):
                        account2 = source_config["category_mapping"][category]
                    else:
                        account2 = unknown_account(self.config, expense)
                
                metadata.update(new_meta)
                
                txn = data.Transaction(
                    meta=metadata,
                    date=time.date(),
                    flag=self.FLAG,
                    payee="",
                    narration=narration,
                    tags=new_tags,
                    links=data.EMPTY_SET,
                    postings=[
                        data.Posting(account1, units, None, None, None, None),
                        data.Posting(account2, None, None, None, None, None),
                    ],
                )
                entries.append(txn)
                
        return entries

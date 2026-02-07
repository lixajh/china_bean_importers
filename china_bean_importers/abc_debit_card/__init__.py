from dateutil.parser import parse
from beancount.core import data, amount
from beancount.core.number import D
import re
import datetime

from china_bean_importers.common import *
from china_bean_importers.importer import PdfImporter


def clean_value(val):
    """
    处理空值，将 '--' 转换为 None

    农行储蓄卡流水使用 "--" 表示空值
    """
    if val is None:
        return None
    val = val.strip()
    return None if val == "--" or val == "" else val


def gen_txn(config, file, parts, lineno, flag, card_acc, real_name):
    """
    生成农行储蓄卡交易记录

    parts: [交易日期, 交易时间, 交易摘要, 交易金额, 本次余额,
            对手信息, 日志号, 交易渠道, 交易附言]

    示例数据:
    20251221  --        结息    +0.00   0.07    --        0000000001  --              个人活期结息
    20260202  213648    转存    +4138.00  4138.07 李晓      M250123472  超级网银        手机转账
    20260202  213706    转支    -4137.29  0.78     5188...  M250165294  掌上银行        --
    """
    # 至少需要 6 个字段
    # 实际字段数可能是 7-9 个（取决于是否有时间和交易渠道）
    if len(parts) < 6:
        return None

    # 解析日期（YYYYMMDD 或 YYMMDD 格式）
    date_str = parts[0].strip()
    if not date_str or not date_str.isdigit():
        return None  # 无效日期行

    try:
        # 农行储蓄卡使用 YYYYMMDD 格式（如 20251221）
        if len(date_str) == 8:
            year = int(date_str[:4])
            month = int(date_str[4:6])
            day = int(date_str[6:8])
        elif len(date_str) == 6:
            # 兼容 YYMMDD 格式
            year = 2000 + int(date_str[:2])
            month = int(date_str[2:4])
            day = int(date_str[4:6])
        else:
            return None
        txn_date = datetime.date(year, month, day)
    except (ValueError, IndexError):
        return None

    # 根据字段数确定列索引
    # 7字段: [交易日期, 交易摘要, 交易金额, 本次余额, 对手信息, 日志号, 交易附言]
    # 8字段: [交易日期, 交易时间, 交易摘要, 交易金额, 本次余额, 对手信息, 日志号, 交易附言]
    # 9字段: [交易日期, 交易时间, 交易摘要, 交易金额, 本次余额, 对手信息, 日志号, 交易渠道, 交易附言]

    if len(parts) == 7:
        # 无交易时间，无交易渠道
        time_str = None
        narration_idx = 1
        amount_idx = 2
        balance_idx = 3
        payee_idx = 4
        log_idx = 5
        channel_idx = None
        memo_idx = 6
    elif len(parts) == 8:
        # 有交易时间，无交易渠道
        time_str = clean_value(parts[1])
        narration_idx = 2
        amount_idx = 3
        balance_idx = 4
        payee_idx = 5
        log_idx = 6
        channel_idx = None
        memo_idx = 7
    else:
        # 9个字段，完整
        time_str = clean_value(parts[1])
        narration_idx = 2
        amount_idx = 3
        balance_idx = 4
        payee_idx = 5
        log_idx = 6
        channel_idx = 7
        memo_idx = 8

    # 解析金额（带 +/- 符号）
    amount_str = parts[amount_idx].strip().replace("+", "").replace(",", "")
    if not amount_str or amount_str == "--":
        return None

    try:
        units = amount.Amount(D(amount_str), "CNY")
    except:
        return None

    # 解析摘要
    narration = clean_value(parts[narration_idx])
    if not narration:
        narration = "Unknown"

    # 解析对手信息
    payee = clean_value(parts[payee_idx])
    payee_account = None

    # 判断是卡号还是户名
    if payee:
        payee_clean = payee.replace(" ", "")
        if payee_clean.isdigit() and len(payee_clean) >= 16:
            # 是卡号
            payee_account = payee_clean
            payee = "Unknown"

    # 创建 metadata
    metadata = data.new_metadata(file.name, lineno)

    if time_str:
        metadata["time"] = time_str

    # 记录余额
    balance_str = clean_value(parts[balance_idx])
    if balance_str:
        metadata["balance"] = balance_str

    # 记录日志号
    log_str = clean_value(parts[log_idx])
    if log_str:
        metadata["log_no"] = log_str

    # 记录交易渠道（如果有）
    if channel_idx is not None:
        channel_str = clean_value(parts[channel_idx])
        if channel_str:
            metadata["channel"] = channel_str

    # 记录交易附言
    memo_str = clean_value(parts[memo_idx])
    if memo_str:
        metadata["memo"] = memo_str

    if payee_account:
        metadata["payee_account"] = payee_account

    tags = {"PendingReview"}

    # 黑名单检查（过滤支付宝、微信等重复流水）
    if in_blacklist(config, narration):
        print(
            f"Item in blacklist: {txn_date} {narration} [{units}]",
            file=sys.stderr,
            end=" -- ",
        )
        if units.number < 0:
            print(f"Expense skipped", file=sys.stderr)
            return None
        else:
            print(f"Income kept in record", file=sys.stderr)

    # 匹配目标账户
    if m := match_destination_and_metadata(config, narration, payee):
        (account2, new_meta, new_tags) = m
        metadata.update(new_meta)
        tags = tags.union(new_tags)

    if account2 is None:
        account2 = unknown_account(config, units.number < 0)

    # 处理转账（识别自己的卡号）
    if payee == real_name and payee_account:
        card_number2 = payee_account[-4:]
        new_account = find_account_by_card_number(config, card_number2)
        if new_account is not None:
            account2 = new_account

    # 特殊处理利息
    if "结息" in narration or "利息" in narration:
        tags.add("interest")

    # 创建交易
    txn = data.Transaction(
        meta=metadata,
        date=txn_date,
        flag=flag,
        payee=payee,
        narration=narration,
        tags=tags,
        links=data.EMPTY_SET,
        postings=[
            data.Posting(
                account=card_acc,
                units=units,
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
            data.Posting(
                account=account2,
                units=None,
                cost=None,
                price=None,
                flag=None,
                meta=None,
            ),
        ],
    )
    return txn


class Importer(PdfImporter):
    """农业银行储蓄卡导入器"""

    def __init__(self, config) -> None:
        super().__init__(config)
        self.match_keywords = ["农业银行", "活期交易明细"]
        self.file_account_name = "abc_debit_card"
        # 列偏移量：根据 PDF 实际坐标分析得出
        self.column_offsets = [50, 95, 135, 175, 215, 255, 305, 350, 390]
        self.content_start_keyword = "交易日期"
        self.content_end_regex = re.compile(r"该交易明细")

    def parse_metadata(self, file):
        """
        解析 PDF 元数据

        提取：
        - 户名
        - 账号（19位）
        - 起止日期
        """
        # 提取户名
        match = re.search(r"户名：(\w+)", self.full_content)
        assert match, "无法找到户名"
        self.real_name = match[1]

        # 提取账号（19位）
        match = re.search(r"账户：([0-9]{19})", self.full_content)
        assert match, "无法找到账号"
        card_number = match[1]

        # 查找对应账户
        self.card_acc = find_account_by_card_number(self.config, card_number[-4:])
        my_assert(
            self.card_acc,
            f"Unknown card number {card_number}, 请在 config.py 的 card_accounts 中配置",
            0,
            0
        )

        # 提取起止日期
        match = re.search(r"起止日期：(\d{8})-(\d{8})", self.full_content)
        if match:
            self.start = datetime.datetime.strptime(match[1], "%Y%m%d").date()
            self.end = datetime.datetime.strptime(match[2], "%Y%m%d").date()
        else:
            # 备用方案：从内容中提取日期
            self.start = None
            self.end = None

    def generate_tx(self, row, lineno, file):
        """生成交易记录"""
        return gen_txn(
            self.config, file, row, lineno, self.FLAG, self.card_acc, self.real_name
        )

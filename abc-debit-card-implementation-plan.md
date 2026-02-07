# 农业银行储蓄卡导入器实现计划

## 一、项目概述

**目标**: 为农业银行储蓄卡流水实现自动化导入功能

**测试数据**:
- 文件: `test_data/abc_debit/26020723011757751826.zip`
- 密码: `313887`
- 邮件: ID #40，发件人 `abc-mobile-bank@abchina.com`

## 二、技术选型

**基类**: `PdfImporter`（基于坐标解析）

**原因**:
1. PDF 表格布局固定，列位置精确可测
2. 部分字段可能为空（"--"），需要精确控制
3. 参考民生银行实现，格式相似

**配置参数**:
```python
match_keywords = ["农业银行", "活期账户交易明细"]
column_offsets = [50, 95, 135, 175, 215, 255, 305, 350, 390]
content_start_keyword = "交易日期"
content_end_keyword = "该交易明细"
```

## 三、实现步骤

### 步骤 1：创建导入器目录结构

**文件**: `china_bean_importers/china_bean_importers/abc_debit_card/__init__.py`

**目录**:
```
china_bean_importers/china_bean_importers/abc_debit_card/
├── __init__.py         # 主实现文件
└── __pycache__/        # 自动生成
```

### 步骤 2：实现 Importer 类

**类结构**:
```python
class Importer(PdfImporter):
    def __init__(self, config)
    def parse_metadata(self, file)
    def generate_tx(self, row, lineno, file)
```

**辅助函数**:
```python
def gen_txn(config, file, parts, lineno, flag, card_acc, real_name)
def clean_value(val)  # 处理 "--" 空值
```

### 步骤 3：更新 __init__.py

**文件**: `china_bean_importers/china_bean_importers/__init__.py`

```python
from china_bean_importers import abc_debit_card

__all__ = [
    # ... 其他导入器
    "abc_debit_card",
]
```

### 步骤 4：更新 import/config.py

**添加导入**:
```python
from china_bean_importers import abc_debit_card
```

**添加到 CONFIG 列表**:
```python
CONFIG = [
    # ... 其他导入器
    abc_debit_card.Importer(GLOBAL_CONFIG),
]
```

**配置账户映射**:
```python
'importers': {
    # ... 其他配置
    'abc_debit': {
        'account': 'Assets:Banking:ABC:5718',
        'category_mapping': {},
    },
}

'card_accounts': {
    'Assets:Banking': {
        # ... 其他银行
        'ABC': ['5718'],  # 农行储蓄卡
    },
}
```

### 步骤 5：配置邮件规则

**文件**: `import/config.py`

```python
'email_rules': [
    # ... 其他规则
    {
        'sender': 'abc-mobile-bank@abchina.com',
        'subject_keywords': ['农业银行', '活期账户交易明细'],
        'action': 'extract_attachments',
        'target_dir': 'raw/banking',
        'need_password': True
    },
]
```

### 步骤 6：配置 ZIP 密码

**方式 1: 环境变量**
```bash
export ZIP_PASSWORD=313887
```

**方式 2: 启动脚本**
```bash
ZIP_PASSWORD=313887 bash import/bin/import_all.sh
```

## 四、详细实现代码

### 4.1 核心实现（abc_debit_card/__init__.py）

```python
from dateutil.parser import parse
from beancount.core import data, amount
from beancount.core.number import D
import re
import datetime

from china_bean_importers.common import *
from china_bean_importers.importer import PdfImporter


def clean_value(val):
    """处理空值，将 '--' 转换为 None"""
    if val is None:
        return None
    val = val.strip()
    return None if val == "--" or val == "" else val


def gen_txn(config, file, parts, lineno, flag, card_acc, real_name):
    """
    生成交易记录

    parts: [交易日期, 交易时间, 交易摘要, 交易金额, 本次余额,
            对手信息, 日志号, 交易渠道, 交易附言]
    """
    # 至少需要 9 个字段
    if len(parts) < 9:
        return None

    # 解析日期（YYMMDD 格式）
    date_str = parts[0].strip()
    if not date_str or len(date_str) != 6 or not date_str.isdigit():
        return None  # 无效日期行

    try:
        year = 2000 + int(date_str[:2])
        month = int(date_str[2:4])
        day = int(date_str[4:6])
        txn_date = datetime.date(year, month, day)
    except (ValueError, IndexError):
        return None

    # 解析时间（可选）
    time_str = clean_value(parts[1])

    # 解析金额（带 +/- 符号）
    amount_str = parts[3].strip().replace("+", "").replace(",", "")
    if not amount_str or amount_str == "--":
        return None

    try:
        units = amount.Amount(D(amount_str), "CNY")
    except:
        return None

    # 解析摘要
    narration = clean_value(parts[2])
    if not narration:
        narration = "Unknown"

    # 解析对手信息
    payee = clean_value(parts[5])
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
    balance_str = clean_value(parts[4])
    if balance_str:
        metadata["balance"] = balance_str

    # 记录日志号
    log_no = clean_value(parts[6])
    if log_no:
        metadata["log_no"] = log_no

    # 记录交易渠道
    channel = clean_value(parts[7])
    if channel:
        metadata["channel"] = channel

    # 记录交易附言
    memo = clean_value(parts[8])
    if memo:
        metadata["memo"] = memo

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
    def __init__(self, config) -> None:
        super().__init__(config)
        self.match_keywords = ["农业银行", "活期账户交易明细"]
        self.file_account_name = "abc_debit_card"
        self.column_offsets = [50, 95, 135, 175, 215, 255, 305, 350, 390]
        self.content_start_keyword = "交易日期"
        self.content_end_regex = re.compile(r"该交易明细")

    def parse_metadata(self, file):
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
        return gen_txn(
            self.config, file, row, lineno, self.FLAG, self.card_acc, self.real_name
        )
```

### 4.2 关键实现细节

**1. 列偏移量调整**

根据实际 PDF 坐标分析：
```
列位置（x0坐标）:
0: 交易日期  ≈ 52
1: 交易时间  ≈ 97
2: 交易摘要  ≈ 137
3: 交易金额  ≈ 178
4: 本次余额  ≈ 218
5: 对手信息  ≈ 258
6: 日志号    ≈ 311
7: 交易渠道  ≈ 356
8: 交易附言  ≈ 396

column_offsets = [50, 95, 135, 175, 215, 255, 305, 350, 390]
```

**2. 日期解析**

农行日期格式：YYMMDD（如 20251221）
```python
year = 2000 + int(date_str[:2])  # 2025
month = int(date_str[2:4])       # 12
day = int(date_str[4:6])         # 21
```

**3. 空值处理**

农行使用 "--" 表示空值：
```python
def clean_value(val):
    if val is None:
        return None
    val = val.strip()
    return None if val == "--" or val == "" else val
```

**4. 金额解析**

农行金额带 +/- 符号：
```python
amount_str = parts[3].strip().replace("+", "").replace(",", "")
# "+4138.00" → "4138.00"
# "-4137.29" → "-4137.29"
units = amount.Amount(D(amount_str), "CNY")
```

## 五、测试流程

### 5.1 准备测试文件

```bash
# 测试文件已在
test_data/abc_debit/26020723011757751826.zip
```

### 5.2 测试 ZIP 解压

```bash
# 使用 Docker 容器测试
docker cp test_data/abc_debit/26020723011757751826.zip \
    bill-fastapi-dev:/tmp/test.zip

docker exec bill-fastapi-dev bash -c \
    "cd /tmp && 7z x -p313887 -y test.zip"
```

### 5.3 测试 PDF 识别

```bash
# 在容器内测试
docker exec bill-fastapi-dev python3 << 'PYEOF'
import sys
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/import/china_bean_importers')

from china_bean_importers import abc_debit_card
import import.config

importer = abc_debit_card.Importer(import.config.GLOBAL_CONFIG)

class F:
    def __init__(self, n):
        self.name = n

f = F('/tmp/26020723011757751826.pdf')
print('Can identify:', importer.identify(f))
PYEOF
```

### 5.4 测试交易提取

```bash
# 使用 bean-extract 测试
ZIP_PASSWORD=313887 bean-extract \
    import/config.py \
    /tmp/26020723011757751826.pdf \
    /tmp/output.beancount
```

### 5.5 完整导入测试

```bash
# 1. 下载邮件
python import/bin/fetch_emails.py --ids 40

# 2. 检查文件
ls -lh raw/banking/

# 3. 执行导入
ZIP_PASSWORD=313887 bash import/bin/import_all.sh

# 4. 检查结果
cat data/2026/imported-2026-02.beancount | grep "2026-02-02"
```

## 六、验证清单

- [ ] 导入器能识别农行储蓄卡 PDF
- [ ] 能正确提取户名和账号
- [ ] 能正确提取起止日期
- [ ] 能正确解析交易日期（YYMMDD 格式）
- [ ] 能正确解析交易金额（带 +/- 符号）
- [ ] 能正确处理空值（"--"）
- [ ] 能正确识别对手信息（卡号 vs 户名）
- [ ] 黑名单过滤正常工作
- [ ] 目标账户匹配正常工作
- [ ] 转账识别正常工作（自己的卡号）
- [ ] ZIP 密码解压正常工作
- [ ] 最终生成的 beancount 文件格式正确

## 七、预期结果示例

### 输入 PDF 交易行:
```
20260202  213648  转存  +4138.00  4138.07  李晓  M250123472  超级网银  手机转账
```

### 输出 Beancount 交易:
```beancount
2026-02-02 * "李晓" "转存"
  time: "213648"
  balance: "4138.07"
  log_no: "M250123472"
  channel: "超级网银"
  memo: "手机转账"
  payee_account: "M250123472"
  Assets:Banking:ABC:5718  +4138.00 CNY
  Expenses:Other
```

## 八、常见问题处理

### 问题 1: 列偏移量不准确

**症状**: 字段解析错位

**解决**:
1. 使用 `page.get_text("words")` 查看实际坐标
2. 调整 `column_offsets` 数组
3. 确保偏移量在列分界点

### 问题 2: 日期解析失败

**症状**: 交易日期为 None 或报错

**解决**:
1. 检查日期格式是否为 YYMMDD
2. 检查是否有非法字符
3. 添加更多错误处理

### 问题 3: ZIP 解压失败

**症状**: 文件损坏或密码错误

**解决**:
1. 确认密码环境变量设置正确
2. 确认 7z 已安装
3. 检查 ZIP 文件完整性

### 问题 4: 账户识别失败

**症状**: `Unknown card number` 错误

**解决**:
1. 检查 config.py 中 card_accounts 配置
2. 确认卡号后四位匹配
3. 添加调试信息查看实际卡号

## 九、后续优化建议

1. **性能优化**:
   - 批量处理多个月份的流水
   - 缓存账户映射结果

2. **功能增强**:
   - 支持多币种（如有外币交易）
   - 自动分类训练（AI 审计）
   - 对账功能

3. **错误处理**:
   - 更友好的错误提示
   - 自动重试机制
   - 日志记录优化

4. **测试覆盖**:
   - 单元测试
   - 集成测试
   - 边界条件测试

## 十、参考资源

- **示例导入器**:
  - `cmbc_debit_card` - 民生银行（PdfImporter 基于坐标）
  - `boc_debit_card` - 中国银行（PdfTableImporter 自动表格）
  - `icbc_debit_card` - 工商银行（PdfTableImporter 自动表格）

- **文档**:
  - Beancount 导入器文档: https://beancount.github.io/docs/importing_external_data/
  - china_bean_importers README

- **工具**:
  - PDF 文本提取: PyMuPDF (fitz)
  - 表格识别: pdfplumber
  - 测试工具: bean-extract

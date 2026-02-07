# 储蓄卡导入器实现分析

## 一、框架架构分析

### 1.1 基类继承体系

china_bean_importers 提供了以下基类：

```
BaseImporter (基础抽象类)
├── CsvImporter (CSV 文件导入)
├── CsvOrXlsxImporter (CSV/Excel 文件导入)
├── PdfImporter (PDF 文件导入 - 基于坐标)
└── PdfTableImporter (PDF 表格导入 - 自动识别表格)
```

**BaseImporter** 核心方法：
- `identify(file)`: 识别文件是否匹配该导入器
- `parse_metadata(file)`: 解析文件元数据（日期、账户等）
- `extract(file, existing_entries)`: 提取交易记录
- `file_account(file)`: 返回账户名称
- `file_date(file)`: 返回文件日期
- `file_name(file)`: 返回建议的文件名

### 1.2 PdfImporter vs PdfTableImporter

#### PdfImporter（基于坐标）
- **适用场景**: PDF 表格布局固定，列位置精确
- **配置参数**:
  - `column_offsets`: 列的 x 坐标分界点
  - `content_start_keyword`: 数据起始关键词
  - `content_end_keyword`: 数据结束关键词
  - `content_end_regex`: 数据结束正则表达式
- **工作原理**:
  1. 使用 `page.get_text("words")` 获取所有单词的坐标
  2. 根据 `column_offsets` 将单词分配到各列
  3. 根据 y 坐标判断是否同一行
  4. 过滤出起始/结束关键词之间的数据行

#### PdfTableImporter（自动表格识别）
- **适用场景**: PDF 有明确的表格结构
- **配置参数**:
  - `vertical_lines`: 表格竖线位置（可选）
  - `header_first_cell`: 表头第一个单元格内容
  - `header_first_cell_regex`: 表头第一个单元格正则（可选）
- **工作原理**:
  1. 使用 `page.find_tables()` 自动识别表格
  2. 过滤掉表头行
  3. 直接提取表格数据

## 二、储蓄卡导入器实现示例

### 2.1 中国银行储蓄卡（boc_debit_card）

**基类**: `PdfTableImporter`

**识别关键词**:
```python
self.match_keywords = ["中国银行交易流水明细清单"]
```

**表格列**（12列）:
```
0:记账日期  1:记账时间  2:币别  3:金额  4:余额
5:交易名称  6:渠道  7:网点名称  8:附言  9:对方账户名
10:对方卡号/账号  11:对方开户行
```

**元数据解析**:
```python
# 交易区间
r"交易区间：\s*([0-9]+-[0-9]+-[0-9]+)\s*至\s*([0-9]+-[0-9]+-[0-9]+)"

# 客户姓名
r"客户姓名：\s*(\w+)"

# 卡号（19位）
r"[0-9]{19}"
```

**特点**:
- 使用 PdfTableImporter 自动识别表格
- 完整的12列数据
- 支持对方账户信息记录

### 2.2 民生银行储蓄卡（cmbc_debit_card）

**基类**: `PdfImporter`

**识别关键词**:
```python
self.match_keywords = ["民生银行", "个人账户对账单"]
```

**列偏移量**:
```python
self.column_offsets = [22, 56, 97, 173, 335, 413, 448, 482, 533, 568, 696]
```

**表格列**（11列）:
```
0:凭证类型  1:凭证号码  2:交易时间  3:摘要  4:交易金额
5:账户余额  6:现转标志  7:交易渠道  8:交易机构  9:对方户名/账号
10:对方行名
```

**数据范围**:
```python
self.content_start_keyword = "对方行名"  # 表头行
self.content_end_keyword = "______________"  # 结束标记
```

**元数据解析**:
```python
# 起止日期
r"起止日期:([0-9]{4}\/[0-9]{2}\/[0-9]{2}).*([0-9]{4}\/[0-9]{2}\/[0-9]{2})"

# 客户姓名
r"客户姓名:(\w+)"

# 客户账号
r"客户账号:([0-9]+)"
```

**特点**:
- 使用 PdfImporter 基于坐标解析
- 列偏移量精确到像素
- 处理变长列（有的行可能缺少部分字段）

### 2.3 工商银行储蓄卡（icbc_debit_card）

**基类**: `PdfTableImporter`

**识别关键词**:
```python
self.match_keywords = ["中国工商银行借记账户历史明细（电子版）"]
```

**表格列**（13列）:
```
0:交易日期  1:帐号  2:储种  3:序号  4:币种  5:钞汇
6:摘要  7:地区  8:收入/支出金额  9:余额  10:对方户名
11:对方帐号  12:渠道
```

**元数据解析**:
```python
# 起止日期
r"起止日期：\s*([0-9]+-[0-9]+-[0-9]+)\s*—\s*([0-9]+-[0-9]+-[0-9]+)"

# 户名
r"户名：\s*(\w+)"

# 卡号（19位）
r"卡号\s*([0-9]{19})"
```

**特点**:
- 日期时间在第一列（合并）
- 包含储种、地区等额外信息

### 2.4 建设银行储蓄卡（ccb_debit_card）

**基类**: `CsvImporter`

**文件格式**: **CSV 文件**（不是 PDF！）

**识别关键词**:
```python
self.match_keywords = ["中国建设银行", "交易明细"]
self.encoding = "utf8"
```

**表格列**（9列）:
```
0:序号  1:摘要  2:币别  3:钞汇  4:交易日期
5:交易金额  6:账户余额  7:交易地点/附言  8:对方账号与户名
```

**特点**:
- 使用 CSV 格式
- 手动解析 CSV 内容（不使用基类的 extract_rows）
- 完全自定义 extract 方法

### 2.5 招商银行储蓄卡（cmb_debit_card）

**基类**: `PdfImporter`

**识别关键词**:
```python
self.match_keywords = ["招商银行交易流水"]
```

**列偏移量**:
```python
self.column_offsets = [30, 50, 100, 200, 280, 350, 400]
```

**表格列**（6-7列）:
```
0:记账日期  1:对手信息  2:金额  3:余额
4-5:交易摘要  6:客户摘要（可选）
```

**数据范围**:
```python
self.content_start_keyword = "Party"  # "Counter Party"
self.content_end_regex = re.compile(r"^(\d+/\d+|合并统计)$")
```

**元数据解析**:
```python
# 姓名
r"名：(\w+)"

# 卡号（16位）
r"[0-9]{16}"
```

## 三、通用实现模式总结

### 3.1 交易生成函数（gen_txn）

所有导入器都遵循以下模式：

```python
def gen_txn(config, file, parts, lineno, flag, card_acc, ...):
    # 1. 提取基本信息
    date = parse(parts[0]).date()           # 日期
    units1 = amount.Amount(D(parts[3]), "CNY")  # 金额
    payee = parts[9]                         # 对方户名
    narration = parts[5]                     # 摘要

    # 2. 黑名单检查（过滤支付宝、微信等）
    if in_blacklist(config, narration):
        # 支出跳过，收入保留
        if units1.number < 0:
            return None

    # 3. 创建 metadata
    metadata = data.new_metadata(file.name, lineno)
    metadata["time"] = parts[1]              # 交易时间
    metadata["balance"] = parts[4]           # 余额
    # ... 其他 metadata

    # 4. 匹配目标账户
    tags = {"PendingReview"}
    account2, new_meta, new_tags = match_destination_and_metadata(
        config, narration, payee
    )
    metadata.update(new_meta)
    tags = tags.union(new_tags)

    # 5. 如果未匹配，使用默认账户
    if account2 is None:
        account2 = unknown_account(config, units1.number < 0)

    # 6. 处理转账（识别对方卡号）
    if payee == real_name:
        card_number2 = parts[10][-4:]
        new_account = find_account_by_card_number(config, card_number2)
        if new_account is not None:
            account2 = new_account

    # 7. 创建交易
    txn = data.Transaction(
        meta=metadata,
        date=date,
        flag=flag,
        payee=payee,
        narration=narration,
        tags=tags,
        links=data.EMPTY_SET,
        postings=[
            data.Posting(account=card_acc, units=units1, ...),
            data.Posting(account=account2, units=None, ...),
        ],
    )
    return txn
```

### 3.2 核心处理流程

1. **识别阶段** (`identify`)
   - 检查文件扩展名
   - 检查关键词是否匹配
   - 读取文件内容

2. **元数据解析** (`parse_metadata`)
   - 提取账户持有人姓名
   - 提取卡号（后4位用于账户识别）
   - 提取起止日期
   - 通过卡号查找对应的 Beancount 账户

3. **数据提取** (`extract` / `generate_tx`)
   - 调用基类的 `extract_rows()` 获取所有数据行
   - 对每一行调用 `generate_tx()` 生成交易
   - 过滤无效数据（返回 None 的行）

4. **交易生成** (`gen_txn` / `generate_tx`)
   - 解析日期、金额、摘要
   - 黑名单过滤
   - 匹配目标账户
   - 创建 Beancount Transaction 对象

### 3.3 关键辅助函数

**common.py 提供**:

```python
# 从 PDF 中查找卡号对应的账户
find_account_by_card_number(config, card_number)

# 匹配交易的目标账户和元数据
match_destination_and_metadata(config, desc, payee)

# 检查是否在黑名单（过滤支付宝、微信）
in_blacklist(config, narration)

# 获取默认账户
unknown_account(config, expense)

# 断言辅助
my_assert(cond, msg, lineno, row)

# 警告辅助
my_warn(msg, lineno, row)

# 匹配货币代码
match_currency_code(currency_name)
```

## 四、农行储蓄卡需求分析

### 4.1 PDF 格式分析

从测试文件 `26020723011757751826.pdf` 分析：

**文件特征**:
- 发件人: `abc-mobile-bank@abchina.com`
- 主题: `中国农业银行-活期账户交易明细文件`
- 附件: 加密 ZIP 文件（密码：313887）

**PDF 布局**（基于坐标）:

表头位置（y≈120）:
```
交易日期(x≈52)  交易时间(x≈97)  交易摘要(x≈137)  交易金额(x≈178)
本次余额(x≈218)  对手信息(x≈258)  日志号(x≈311)  交易渠道(x≈356)  交易附言(x≈396)
```

**账户信息**（页面顶部）:
```
户名：李晓
账户：6228480272290485718
币种：人民币
汇钞标识：本币
起止日期：20251108-20260207
电子流水号：26020723011757751826
```

**数据行示例**:
```
20251221  --        结息    +0.00   0.07    --        0000000001  --              个人活期结息
20260202  213648    转存    +4138.00  4138.07 李晓      M250123472  超级网银        手机转账
20260202  213706    转支    -4137.29  0.78     5188...  M250165294  掌上银行        --
```

**字段说明**:
1. **交易日期**: YYMMDD 格式（如 20251221）
2. **交易时间**: 可能为空 "--"（如结息无时间）
3. **交易摘要**: 转存、转支、结息等
4. **交易金额**: 带 +/- 符号（+ 收入，- 支出）
5. **本次余额**: 交易后余额
6. **对手信息**: 对方户名或卡号，可能为 "--"
7. **日志号**: 交易流水号
8. **交易渠道**: 超级网银、掌上银行等，可能为 "--"
9. **交易附言**: 备注信息，可能为 "--"

### 4.2 实现方案选择

**推荐使用 PdfImporter**（基于坐标），原因：
1. 表格布局固定，列位置精确
2. 字段可能为空（"--"），表格识别可能不准确
3. 需要精确控制列边界

**配置参数**:
```python
self.match_keywords = ["农业银行", "活期账户交易明细"]
self.column_offsets = [50, 95, 135, 175, 215, 255, 305, 350, 390]
self.content_start_keyword = "交易日期"
self.content_end_keyword = "该交易明细"  # 页面底部的提示文字
```

### 4.3 数据处理要点

1. **日期解析**: YYMMDD → 20YY-MM-DD
2. **时间处理**: 可能为空，需要判断
3. **金额符号**: + 表示收入，- 表示支出
4. **空值处理**: "--" 表示空，需要转换为 None 或空字符串
5. **对手信息**: 可能是卡号（16-19位）或户名
6. **账户识别**: 从账号 6228480272290485718 提取后4位 5718

## 五、开发计划

### 阶段 1：创建导入器基础结构
1. 创建 `abc_debit_card` 目录
2. 实现 `Importer` 类继承 `PdfImporter`
3. 实现基本配置参数

### 阶段 2：实现元数据解析
1. 提取户名、账号
2. 提取起止日期
3. 匹配卡号到账户

### 阶段 3：实现数据提取
1. 实现 `gen_txn` 函数
2. 处理日期、时间、金额解析
3. 处理空值（"--"）
4. 处理对手信息（卡号 vs 户名）

### 阶段 4：配置集成
1. 在 `import/config.py` 中添加导入器
2. 配置账户映射
3. 配置邮件规则
4. 配置 ZIP 密码

### 阶段 5：测试验证
1. 下载测试邮件
2. 验证 ZIP 解压
3. 验证 PDF 解析
4. 验证交易提取
5. 验证账户映射

## 六、关键代码示例

### 6.1 Importer 类结构

```python
class Importer(PdfImporter):
    def __init__(self, config) -> None:
        super().__init__(config)
        self.match_keywords = ["农业银行", "活期账户交易明细"]
        self.file_account_name = "abc_debit_card"
        self.column_offsets = [50, 95, 135, 175, 215, 255, 305, 350, 390]
        self.content_start_keyword = "交易日期"
        self.content_end_keyword = "该交易明细"

    def parse_metadata(self, file):
        # 提取户名
        match = re.search(r"户名：(\w+)", self.full_content)
        assert match
        self.real_name = match[1]

        # 提取账号（19位）
        match = re.search(r"账户：([0-9]{19})", self.full_content)
        assert match
        card_number = match[1]
        self.card_acc = find_account_by_card_number(self.config, card_number[-4:])
        my_assert(self.card_acc, f"Unknown card number {card_number}", 0, 0)

        # 提取起止日期
        match = re.search(r"起止日期：(\d{8})-(\d{8})", self.full_content)
        assert match
        from datetime import datetime
        self.start = datetime.strptime(match[1], "%Y%m%d").date()
        self.end = datetime.strptime(match[2], "%Y%m%d").date()

    def generate_tx(self, row, lineno, file):
        return gen_txn(
            self.config, file, row, lineno, self.FLAG,
            self.card_acc, self.real_name
        )
```

### 6.2 gen_txn 函数结构

```python
def gen_txn(config, file, parts, lineno, flag, card_acc, real_name):
    # parts: [交易日期, 交易时间, 交易摘要, 交易金额, 本次余额,
    #         对手信息, 日志号, 交易渠道, 交易附言]

    # 处理空值
    def clean_value(val):
        return None if val == "--" or val.strip() == "" else val.strip()

    # 解析日期
    date_str = parts[0]
    if len(date_str) != 6:
        return None  # 无效行
    year = 2000 + int(date_str[:2])
    month = int(date_str[2:4])
    day = int(date_str[4:6])
    from datetime import date
    txn_date = date(year, month, day)

    # 解析时间（可选）
    time_str = clean_value(parts[1])

    # 解析金额
    amount_str = parts[3].replace("+", "").replace(",", "")
    from beancount.core.number import D
    from beancount.core import amount
    units = amount.Amount(D(amount_str), "CNY")

    # 解析摘要
    narration = clean_value(parts[2])

    # 解析对手信息
    payee = clean_value(parts[5])
    # 判断是卡号还是户名
    if payee and len(payee.replace(" ", "")) >= 16:
        # 可能是卡号，尝试提取
        payee_account = payee
        payee = "Unknown"
    else:
        payee_account = None

    # 创建 metadata
    from beancount.core import data
    metadata = data.new_metadata(file.name, lineno)
    if time_str:
        metadata["time"] = time_str
    metadata["balance"] = parts[4]
    if parts[6] != "--":
        metadata["log_no"] = parts[6]
    if parts[7] != "--":
        metadata["channel"] = parts[7]
    if parts[8] != "--":
        metadata["memo"] = parts[8]
    if payee_account:
        metadata["payee_account"] = payee_account

    # 黑名单检查
    if in_blacklist(config, narration):
        if units.number < 0:
            return None  # 支出跳过

    # 匹配目标账户
    tags = {"PendingReview"}
    account2, new_meta, new_tags = match_destination_and_metadata(
        config, narration, payee
    )
    metadata.update(new_meta)
    tags = tags.union(new_tags)

    if account2 is None:
        account2 = unknown_account(config, units.number < 0)

    # 处理转账
    if payee == real_name and payee_account:
        card_number2 = payee_account[-4:]
        new_account = find_account_by_card_number(config, card_number2)
        if new_account is not None:
            account2 = new_account

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
```

## 七、配置文件修改

### 7.1 import/config.py

```python
# 添加导入
from china_bean_importers import abc_debit_card

# 在 CONFIG 列表中添加
CONFIG = [
    # ... 其他导入器
    abc_debit_card.Importer(GLOBAL_CONFIG),
]

# 添加账户配置
'importers': {
    'abc_debit': {
        'account': 'Assets:Banking:ABC:5718',
        'category_mapping': {},
    },
}

# 添加卡号映射
'card_accounts': {
    'Assets:Banking': {
        'ABC': ['5718'],  # 农行储蓄卡
        # ... 其他银行
    },
}
```

### 7.2 邮件规则配置

```python
'email_rules': [
    {
        'sender': 'abc-mobile-bank@abchina.com',
        'subject_keywords': ['农业银行', '活期账户交易明细'],
        'action': 'extract_attachments',
        'target_dir': 'raw/banking',
        'need_password': True  # ZIP 密码
    },
]
```

### 7.3 环境变量

```bash
# .env 文件或启动脚本
ZIP_PASSWORD=313887
```

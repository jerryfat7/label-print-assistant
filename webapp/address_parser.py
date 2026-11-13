"""
地址解析模块 —— 将 "姓名  电话  详细地址" 文本拆解为结构化数据。

支持两种策略:
- CpcaStrategy : 基于 cpca 库（默认，鲁棒性强）
- RegexStrategy: 基于正则（零依赖，轻量）
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AddressItem:
    """单条解析结果"""
    name: str
    phone: str
    address: str               # 省+市（提取结果）
    full_address: str           # 原始完整地址
    raw_line: str               # 原始输入行
    index: int = 0              # 行号
    parse_error: Optional[str] = None  # 解析失败原因，None 表示成功


# ============================================================
# 基础工具：按空白切分 "姓名  电话  地址"
# ============================================================

# 手机号正则（1 开头的 11 位数字）
_PHONE_RE = re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)')


def _unwrap(text: str) -> str:
    """Remove enclosing copy/paste brackets, retaining parentheses inside addresses."""
    text = text.strip()
    for left, right in [('（', '）'), ('(', ')')]:
        if text.startswith(left) and text.endswith(right):
            depth = 0
            for index, character in enumerate(text):
                depth += (character == left) - (character == right)
                if depth == 0 and index < len(text) - 1:
                    break
            else:
                if depth == 0:
                    return text[1:-1].strip()
    return text


def _address_continuation(text: str) -> bool:
    keywords = r'省|自治区|市|区|县|街道|乡|镇|村|路|街|巷|弄|小区|社区|园区|单元|号楼|栋|幢|大厦|公寓|室|楼'
    return bool(re.search(keywords, text)) and (
        len(text) >= 4 or bool(re.search(r'\d', text)) or
        (len(text) >= 3 and text.endswith(('省', '市', '区', '县'))))


def _logical_records(text: str) -> list[str]:
    """Phone-bearing headers begin records; following address lines belong to them."""
    lines = text.splitlines()
    records = []
    current = []

    def flush():
        if current:
            records.append('\n'.join(current))
            current.clear()

    for index, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            flush()  # Blank lines explicitly separate records.
            continue
        phone = _PHONE_RE.search(line)
        if phone:
            # Also support name / phone / address on three separate lines.
            phone_only_prefix = not line[:phone.start()].strip(' （(,，;；')
            preceding_name = (len(current) == 1 and not _PHONE_RE.search(current[0]) and
                              not _address_continuation(current[0]))
            if not (preceding_name and phone_only_prefix):
                flush()
            current.append(line)
            continue
        if current:
            joined = '\n'.join(current)
            has_phone = bool(_PHONE_RE.search(joined))
            if has_phone:
                _, _, address = _split_line(joined)
                next_line = lines[index + 1].strip() if index + 1 < len(lines) else ''
                next_phone = _PHONE_RE.search(next_line)
                next_is_phone_line = bool(next_phone and not next_line[:next_phone.start()].strip(' （(,，;；'))
                if (next_is_phone_line and not _address_continuation(line)) or (
                        address and not _address_continuation(line)):
                    flush()
            elif not _address_continuation(line):
                flush()
        current.append(line)
    flush()
    return records


def _split_line(text: str) -> tuple[str, str, str]:
    """
    切分收货地址串为 (姓名, 电话, 地址)。

    策略优先级:
    1. 按手机号定位 → 最可靠，兼容任意分隔符（空格/Tab/逗号/无分隔）
    2. 按连续空白切分 → 兜底无手机号的场景（如座机、纯地址）

    返回 (name, phone, address)，失败时对应字段为空串。
    """
    s = re.sub(r'[\r\n]+', ' ', _unwrap(text))
    if not s:
        return '', '', ''

    # ---- 策略 1（主）: 按手机号定位 ----
    m = _PHONE_RE.search(s)
    if m:
        phone = m.group()
        name_part = s[:m.start()].strip()
        addr_part = s[m.end():].strip()
        # 去除 name 尾部残留的分隔符
        name_part = re.sub(r'[\s,，;；]+$', '', name_part)
        # 去除 addr 前部残留的分隔符
        addr_part = re.sub(r'^[\s,，;；]+', '', addr_part)
        return name_part, phone, addr_part

    # ---- 策略 2（兜底）: 按 2+ 连续空白切分 ----
    parts = re.split(r'\s{2,}', s)
    if len(parts) >= 3:
        return parts[0].strip(), parts[1].strip(), '  '.join(parts[2:]).strip()
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip(), ''

    # ---- 无法切分 ----
    return s, '', ''


# ============================================================
# 策略接口
# ============================================================

class AddressStrategy(ABC):
    """地址解析策略抽象基类"""

    @abstractmethod
    def extract_city(self, full_address: str) -> str:
        """从完整地址中提取到市级，如 '福建省福州市鼓楼区xxx' → '福建省福州市'"""
        ...

    def parse_line(self, line: str, index: int = 0) -> AddressItem:
        """解析单行收货地址文本"""
        name, phone, full_address = _split_line(line)

        errors = []
        if not name:
            errors.append("缺少姓名")
        if not phone:
            errors.append("缺少电话")
        if not full_address:
            errors.append("缺少地址")

        city_address = ''
        if full_address:
            city_address = self.extract_city(full_address)
            if not city_address:
                errors.append("无法提取市级地址")

        return AddressItem(
            name=name,
            phone=phone,
            address=city_address,
            full_address=full_address,
            raw_line=line,
            index=index,
            parse_error='; '.join(errors) if errors else None,
        )

    def parse_batch(self, text: str) -> list[AddressItem]:
        """批量解析收货信息，允许同一收件人的详细地址换行。"""
        return [self.parse_line(record, i) for i, record in enumerate(_logical_records(text))]


# ============================================================
# 策略 A：正则匹配
# ============================================================

class RegexStrategy(AddressStrategy):
    """
    基于正则的省市区提取。

    匹配规则: (省名)?(市名)
    - 普通省份: XX省XX市
    - 直辖市:   北京市 / 上海市 / 天津市 / 重庆市
    - 自治区:   XX自治区XX市
    """

    # 直辖市 (无"省"字，直接"XX市")
    _DIRECT_CITY = {'北京市', '上海市', '天津市', '重庆市'}

    # 省+市 正则
    _PROVINCE_CITY_RE = re.compile(
        r'^(.+?[省]|.+?自治区)?(.+?市)'
    )

    # 直辖市后的区（如 海淀区 / 黄浦区）
    _DIRECT_DISTRICT_RE = re.compile(r'^([^\s,，;；]+?区)')

    def extract_city(self, full_address: str) -> str:
        addr = full_address.strip()

        # 先检查直辖市：解析到区（如 北京市海淀区）
        for dc in self._DIRECT_CITY:
            if addr.startswith(dc):
                m = self._DIRECT_DISTRICT_RE.match(addr[len(dc):])
                if m:
                    return f'{dc}{m.group(1)}'
                return dc

        # 通用省+市匹配
        m = self._PROVINCE_CITY_RE.match(addr)
        if m:
            province = m.group(1) or ''
            city = m.group(2) or ''
            return f'{province}{city}'

        return ''


# ============================================================
# 策略 B：cpca 库（默认）
# ============================================================

class CpcaStrategy(AddressStrategy):
    """
    基于 cpca (chinese_province_city_area_mapper) 库的地址解析。

    安装: pip install cpca
    """

    # 直辖市（无地级市，解析到区）
    _DIRECT_CITIES = {'北京市', '天津市', '上海市', '重庆市'}

    def extract_city(self, full_address: str) -> str:
        try:
            import cpca
            df = cpca.transform([full_address])
            province = (df.iloc[0]['省'] or '').strip()
            city = (df.iloc[0]['市'] or '').strip()
            district = (df.iloc[0]['区'] or '').strip()

            if province in self._DIRECT_CITIES:
                # 直辖市：解析到区，如 北京市海淀区 / 上海市黄浦区
                if district:
                    return f'{province}{district}'
                if city and city != '市辖区':
                    return f'{province}{city}'
                return province

            result = f'{province}{city}'
            return result if result else ''
        except ImportError:
            # 降级到正则
            fallback = RegexStrategy()
            return fallback.extract_city(full_address)
        except Exception:
            return ''


# ============================================================
# 对外统一入口
# ============================================================

# 默认策略（可通过 set_strategy 切换）
_strategy: AddressStrategy = CpcaStrategy()


def set_strategy(strategy: AddressStrategy) -> None:
    """切换解析策略"""
    global _strategy
    _strategy = strategy


def get_strategy_name() -> str:
    """获取当前策略名称"""
    return _strategy.__class__.__name__


def parse_line(line: str, index: int = 0) -> AddressItem:
    """解析单行地址（单条调用入口）"""
    return _strategy.parse_line(line, index)


def parse_batch(text: str) -> list[AddressItem]:
    """批量解析多行地址（批量调用入口）"""
    return _strategy.parse_batch(text)

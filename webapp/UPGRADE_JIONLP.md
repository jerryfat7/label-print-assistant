# 地址解析升级方案：cpca → JioNLP

> 状态：备选方案 | 当前默认：cpca | 目标：升级到区/街道级解析精度

---

## 背景

当前 `address_parser.py` 的 `CpcaStrategy` 使用 [cpca](https://github.com/DQinYuan/chinese_address_generator) 库，仅能解析到省/市级。对于需要区/街道级精度的业务场景，可切换为 [JioNLP](https://github.com/dongrixinyu/JioNLP) 的 `parse_location()`。

---

## 对比

| 维度 | cpca（当前） | JioNLP（备选） |
|---|---|---|
| 解析深度 | 省 + 市 | 省 + 市 + 区 + 街道/乡镇 + 村/社 |
| 区划词典 | 静态 | 静态 + 2018年以来区划变更词典 |
| 返回 detail | ❌ | ✅ 省市区之后的剩余地址 |
| 手机号提取 | 需自己写 | `extract_phone_number()` 内置（含座机号） |
| 安装大小 | ~3MB | ~16MB（含完整词典） |
| 月下载量 | 更高 | ~5000/月 |

---

## 实现方案

### 1. 安装

```bash
pip install jionlp
```

### 2. 修改 `webapp/address_parser.py`

在现有 `CpcaStrategy` 类旁新增 `JionlpStrategy`：

```python
class JionlpStrategy(AddressStrategy):
    """
    基于 JioNLP parse_location() 的地址解析。

    安装: pip install jionlp
    解析深度: 省 → 市 → 区 → 街道/乡镇 → 村/社
    """

    def extract_city(self, full_address: str) -> str:
        """从完整地址提取到市级"""
        try:
            import jionlp as jio
            result = jio.parse_location(full_address)
            province = (result.get('province') or '').strip()
            city = (result.get('city') or '').strip()
            return f'{province}{city}' if (province or city) else ''
        except ImportError:
            from webapp.address_parser import RegexStrategy
            return RegexStrategy().extract_city(full_address)
        except Exception:
            return ''

    def extract_full(self, full_address: str) -> dict:
        """提取完整地址信息（省/市/区/街道/村/剩余）"""
        try:
            import jionlp as jio
            return jio.parse_location(full_address)
        except Exception:
            return {}
```

### 3. 切换默认策略

修改 `webapp/address_parser.py` 底部：

```python
# 切换为 JioNLP 策略
_strategy: AddressStrategy = JionlpStrategy()
```

或者运行时动态切换：

```python
from webapp.address_parser import JionlpStrategy, set_strategy

set_strategy(JionlpStrategy())
```

### 4. JioNLP `parse_location()` 返回结构

```python
import jionlp as jio

result = jio.parse_location("浙江省杭州市上城区凯旋街道某路***号")

# 返回值:
{
    "province": "浙江省",        # 省/直辖市/自治区
    "city": "杭州市",            # 地级市
    "county": "上城区",          # 区/县/县级市
    "town": "凯旋街道",          # 乡镇/街道（可能为空）
    "village": "",              # 村/社区（可能为空）
    "detail": "某路***号",     # 剩余详细地址
    "full_location": "浙江省杭州市上城区",  # 省市区的标准写法
}
```

### 5. 电话提取增强（可选）

JioNLP 内置手机号+座机号提取，可替代当前 `_split_line()` 中的正则：

```python
import jionlp as jio

def _split_line_v2(text: str) -> tuple[str, str, str]:
    """使用 JioNLP 提取电话并切分"""
    phones = jio.extract_phone_number(text)
    if phones:
        phone = phones[0]
        idx = text.index(phone)
        name = text[:idx].strip().rstrip(',，;； \t')
        addr = text[idx+len(phone):].strip().lstrip(',，;； \t')
        return name, phone, addr
    # 兜底: 原有逻辑
    return _split_line_fallback(text)
```

---

## 升级影响范围

| 文件 | 改动量 | 说明 |
|---|---|---|
| `address_parser.py` | +30 行 | 新增 `JionlpStrategy` 类 |
| `address_parser.py` | 1 行 | 修改 `_strategy` 默认值 |
| `requirements.txt` | +1 行 | 新增 `jionlp` 依赖 |
| 其他文件 | **0** | 策略模式保证 API 无需任何改动 |

前端、API 路由、标签服务完全不受影响。

---

## 决策建议

| 场景 | 建议 |
|---|---|
| 标签只需省/市（当前需求） | **保持 cpca**，够用且轻量 |
| 需要打印到区/街道 | **切换到 JioNLP** |
| 需要座机号支持 | **切换到 JioNLP** 的 `extract_phone_number()` |
| 标签纸尺寸大（如 60×40mm）需显示更多信息 | **切换到 JioNLP**，可打省/市/区三级 |

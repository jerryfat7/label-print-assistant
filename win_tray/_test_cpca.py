# -*- coding: utf-8 -*-
"""最小验证：PyInstaller 环境下 cpca 数据加载与解析。"""
import sys

print("MEIPASS:", getattr(sys, "_MEIPASS", None))

import pkg_resources
print("res filename:", pkg_resources.resource_filename("cpca.resources", "adcodes.csv"))

import cpca
print("cpca imported OK")

df = cpca.transform(["福建省福州市鼓楼区湖东路123号"])
print(df[["省", "市"]].to_string(index=False))
prov = (df.iloc[0]["省"] or "").strip()
city = (df.iloc[0]["市"] or "").strip()
print("RESULT:", f"{prov}{city}" or "(EMPTY)")

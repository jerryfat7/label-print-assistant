# -*- coding: utf-8 -*-
"""
PyInstaller runtime hook —— 修复 cpca 打包后的数据文件加载。

背景
----
cpca 在导入时通过 ``pkg_resources.resource_stream('cpca.resources', 'adcodes.csv')``
读取省市区数据。PyInstaller 打包后，模块走惰性 archive 加载，
``cpca.resources.__file__`` 不再指向真实目录，pkg_resources 无法定位到
``_MEIPASS/cpca/resources/adcodes.csv``，导致地址解析结果为空。

本 hook 在主脚本运行前执行：将 ``pkg_resources.resource_stream`` /
``resource_filename`` 对 ``cpca`` / ``cpca.resources`` 的调用重定向到
``sys._MEIPASS/cpca/resources`` 下的真实文件。
"""
import os
import sys


def _patch_cpca_resources() -> None:
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    base = os.path.join(meipass, "cpca", "resources")
    if not os.path.isdir(base):
        return
    try:
        import pkg_resources
    except Exception:  # noqa: BLE001
        return

    _orig_stream = pkg_resources.resource_stream
    _orig_filename = pkg_resources.resource_filename

    def _target(package_or_requirement):
        name = getattr(package_or_requirement, "key", None) or str(package_or_requirement)
        if name in ("cpca", "cpca.resources"):
            return base
        return None

    def resource_stream(package_or_requirement, resource_name, *args, **kwargs):
        tgt = _target(package_or_requirement)
        if tgt:
            path = os.path.join(tgt, resource_name)
            if os.path.isfile(path):
                return open(path, "rb")
        return _orig_stream(package_or_requirement, resource_name, *args, **kwargs)

    def resource_filename(package_or_requirement, resource_name, *args, **kwargs):
        tgt = _target(package_or_requirement)
        if tgt:
            path = os.path.join(tgt, resource_name)
            if os.path.exists(path):
                return path
        return _orig_filename(package_or_requirement, resource_name, *args, **kwargs)

    pkg_resources.resource_stream = resource_stream
    pkg_resources.resource_filename = resource_filename


_patch_cpca_resources()

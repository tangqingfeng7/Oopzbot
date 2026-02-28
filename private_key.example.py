"""
RSA 私钥配置示例
复制此文件为 private_key.py 并填写真实私钥

获取方式：
  Oopz 客户端本地会生成一对 RSA 密钥，
  你需要将私钥以 PEM 格式粘贴到下方。
"""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# 将你的 RSA 私钥粘贴在这里（PEM 格式）
PRIVATE_KEY_PEM = b"""-----BEGIN RSA PRIVATE KEY-----
PASTE_YOUR_RSA_PRIVATE_KEY_HERE
-----END RSA PRIVATE KEY-----"""


def get_private_key():
    """加载并返回 RSA 私钥对象"""
    return serialization.load_pem_private_key(
        PRIVATE_KEY_PEM,
        password=None,
        backend=default_backend(),
    )

import ipaddress
import json
import os

# 内网IP地址范围
PRIVATE_IP_RANGES = [
    ipaddress.IPv4Network('10.0.0.0/8'),
    ipaddress.IPv4Network('172.16.0.0/12'),
    ipaddress.IPv4Network('192.168.0.0/16'),
    ipaddress.IPv4Network('127.0.0.0/8'),
    ipaddress.IPv4Network('169.254.0.0/16'),
]

# 简单的IP地理位置映射（用于内网环境）
IP_LOCATION_MAP = {
    '192.168.1.0/24': '公司内网 - 研发部',
    '192.168.2.0/24': '公司内网 - 市场部',
    '192.168.3.0/24': '公司内网 - 财务部',
}

def is_private_ip(ip_str):
    """判断是否为内网IP"""
    try:
        ip = ipaddress.IPv4Address(ip_str)
        for network in PRIVATE_IP_RANGES:
            if ip in network:
                return True
        return False
    except ValueError:
        return False

def get_ip_location(ip_str):
    """获取IP地址的地理位置"""
    # 检查是否为内网IP
    if is_private_ip(ip_str):
        # 尝试匹配内网IP段
        for network_str, location in IP_LOCATION_MAP.items():
            try:
                network = ipaddress.IPv4Network(network_str)
                ip = ipaddress.IPv4Address(ip_str)
                if ip in network:
                    return location
            except ValueError:
                pass
        return '内网地址'
    else:
        # 对于公网IP，这里可以集成第三方API
        # 由于是内网环境，暂时返回'公网地址'
        # 实际部署时可以替换为真实的IP地理位置API
        return '公网地址'

def get_ip_info(ip_str):
    """获取IP地址的详细信息"""
    return {
        'ip': ip_str,
        'location': get_ip_location(ip_str),
        'is_private': is_private_ip(ip_str)
    }

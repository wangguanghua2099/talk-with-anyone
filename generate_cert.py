"""生成自签名 HTTPS 证书（cert.pem / key.pem），用于手机等局域网设备访问时启用麦克风。

浏览器要求 getUserMedia 必须在安全上下文（HTTPS 或 localhost）下才能调用，
局域网设备通过 http://IP:7862 访问时无法使用麦克风，需启用 HTTPS。

用法： python generate_cert.py
生成后重启服务器即自动以 HTTPS 启动（main.py 检测到 cert.pem/key.pem 时启用）。
注意：自签名证书会被浏览器提示"不是私密连接"，点击"高级 → 继续前往"即可。
"""
import datetime
import ipaddress
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

BASE_DIR = Path(__file__).resolve().parent


def get_ip_addresses():
    ips = set()
    # UDP 连接技巧：不真正发包，只取本机出站 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.add(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    # 枚举主机名解析到的全部 IPv4 地址（可能含多个网卡/虚拟网卡）
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return sorted(ips)


def main():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    ips = get_ip_addresses()
    print("检测到的局域网 IP：", ips if ips else "（无，仅含 localhost）")

    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for ip in ips:
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            san.append(x509.DNSName(ip))

    now = datetime.datetime.now(datetime.timezone.utc)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Talk With Anyone")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    cert_path = BASE_DIR / "cert.pem"
    key_path = BASE_DIR / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    print(f"已生成：\n  证书 {cert_path}\n  私钥 {key_path}")
    print("重启服务器后将以 HTTPS 启动。手机访问 https://<本机局域网IP>:7862，")


if __name__ == "__main__":
    main()

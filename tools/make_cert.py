"""Make the certificates that let your phone trust the laptop over home wifi.

Run tools\\make_cert.bat, which installs the cryptography package if it is
missing and then runs this file. It creates, in the certs folder next to the
app:

  ca.pem, ca-key.pem   a private certificate authority, made once, valid 10 years
  ca.crt               the same authority in the form Android installs
  server.pem, server-key.pem   the server certificate, valid 2 years, listing
                       every IPv4 address this laptop has right now plus its
                       hostname, so the phone accepts https://192.168.x.x:8779
  server.json          a note of what the server certificate covers

Re-run it whenever the laptop's wifi address changes. The phone keeps
trusting the authority, so nothing needs reinstalling there.

Keep ca-key.pem private. Anyone holding it can make certificates your phone
trusts. Do not put the certs folder in OneDrive.
"""

import ipaddress
import json
import os
import socket
import sys
from datetime import datetime, timedelta, timezone

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
except ImportError:
    print("The cryptography package is missing. Run tools\\make_cert.bat, which installs it, or:")
    print("    python -m pip install cryptography")
    sys.exit(1)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CERT_DIR = os.path.join(ROOT, "certs")
CA_PEM = os.path.join(CERT_DIR, "ca.pem")
CA_KEY = os.path.join(CERT_DIR, "ca-key.pem")
CA_CRT = os.path.join(CERT_DIR, "ca.crt")
SERVER_PEM = os.path.join(CERT_DIR, "server.pem")
SERVER_KEY = os.path.join(CERT_DIR, "server-key.pem")
SIDECAR = os.path.join(CERT_DIR, "server.json")


def lan_ipv4s():
    """Every IPv4 address this machine has, apart from loopback and link-local."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:
        # No packet is sent; the OS just picks the interface it would use.
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        found.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return sorted(ip for ip in found if not ip.startswith("127.") and not ip.startswith("169.254."))


def now():
    return datetime.now(timezone.utc)


def write_pem(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def load_or_make_ca(hostname):
    if os.path.exists(CA_PEM) and os.path.exists(CA_KEY):
        with open(CA_PEM, "rb") as fh:
            ca = x509.load_pem_x509_certificate(fh.read())
        with open(CA_KEY, "rb") as fh:
            key = serialization.load_pem_private_key(fh.read(), password=None)
        print(f"Using the existing authority: {ca.subject.rfc4514_string()}")
        return ca, key, False
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Fitness Tracker CA ({hostname})")])
    ca = (x509.CertificateBuilder()
          .subject_name(name).issuer_name(name)
          .public_key(key.public_key())
          .serial_number(x509.random_serial_number())
          .not_valid_before(now() - timedelta(days=1))
          .not_valid_after(now() + timedelta(days=3652))
          .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                       content_commitment=False, key_encipherment=False, data_encipherment=False,
                                       key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
          .sign(key, hashes.SHA256()))
    write_pem(CA_PEM, ca.public_bytes(serialization.Encoding.PEM))
    write_pem(CA_KEY, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    write_pem(CA_CRT, ca.public_bytes(serialization.Encoding.DER))
    print("Made a new certificate authority. Install certs\\ca.crt on the phone once.")
    return ca, key, True


def make_server_cert(ca, ca_key, hostname, ips):
    key = ec.generate_private_key(ec.SECP256R1())
    names = [x509.DNSName(hostname), x509.DNSName(f"{hostname}.local"), x509.DNSName("localhost"),
             x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for ip in ips:
        names.append(x509.IPAddress(ipaddress.ip_address(ip)))
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
            .issuer_name(ca.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now() - timedelta(days=1))
            .not_valid_after(now() + timedelta(days=730))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=True, key_cert_sign=False, crl_sign=False,
                                         content_commitment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256()))
    write_pem(SERVER_PEM, cert.public_bytes(serialization.Encoding.PEM))
    write_pem(SERVER_KEY, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    return cert


def write_sidecar(cert, hostname, ips):
    info = {
        "ips": ips,
        "dns": [hostname, f"{hostname}.local", "localhost"],
        "not_after": cert.not_valid_after_utc.isoformat() if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.isoformat(),
        "made": now().isoformat(),
    }
    with open(SIDECAR, "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=2)
    return info


def main():
    os.makedirs(CERT_DIR, exist_ok=True)
    hostname = socket.gethostname()
    ips = lan_ipv4s()
    if not ips:
        print("No network address found. Connect to wifi and run this again.")
        return 1
    ca, ca_key, fresh = load_or_make_ca(hostname)
    cert = make_server_cert(ca, ca_key, hostname, ips)
    info = write_sidecar(cert, hostname, ips)
    print()
    print("Server certificate written for:")
    for ip in ips:
        print(f"    https://{ip}:8779/")
    print(f"    {hostname}, {hostname}.local, localhost")
    print(f"Valid until {info['not_after'][:10]}.")
    print()
    if fresh:
        print("Next, on the phone: open https://%s:8779/ca.crt, then install it from" % ips[0])
        print("Settings > Security and privacy > More security settings > Encryption and credentials")
        print("> Install a certificate > CA certificate. Close Chrome fully afterwards.")
    else:
        print("The phone already trusts this authority. Restart the app, or press Reload certificate in Settings > Phone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

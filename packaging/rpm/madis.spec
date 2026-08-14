Name:           madis
Version:        0.5.0
Release:        1%{?dist}
Summary:        Madis SIP Proxy and Registrar
License:        Proprietary
URL:            https://github.com/Izi-Technologies/madis
Source0:        madis-%{version}.tar.gz

Requires:       openssl-libs
Requires:       libpq
Requires:       ca-certificates

%description
High-performance SIP proxy with UDP/TCP/TLS/WSS support,
PostgreSQL-backed routing, STIR/SHAKEN, IMS, and MAF application fabric.

%install
install -D -m 0755 %{_sourcedir}/madis %{buildroot}/usr/local/bin/madis
install -D -m 0644 %{_sourcedir}/madis.service %{buildroot}%{_unitdir}/madis.service
install -D -m 0644 %{_sourcedir}/madis-admin.service %{buildroot}%{_unitdir}/madis-admin.service
install -D -m 0644 %{_sourcedir}/madis.env.example %{buildroot}/etc/madis/madis.env.example

%pre
getent group madis >/dev/null 2>&1 || groupadd --system madis
getent passwd madis >/dev/null 2>&1 || \
    useradd --system --no-create-home --shell /usr/sbin/nologin --gid madis madis

%post
install -d -m 0750 -o root -g madis /etc/madis
install -d -m 0750 -o madis -g madis /var/log/madis
install -d -m 0755 -o root -g root /opt/madis

if [ ! -f /etc/madis/madis.env ]; then
    install -m 0640 -o root -g madis /etc/madis/madis.env.example /etc/madis/madis.env
fi

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload
fi

echo "Madis installed. Edit /etc/madis/madis.env then: systemctl enable --now madis"

%preun
if [ $1 -eq 0 ] && [ -d /run/systemd/system ]; then
    systemctl stop madis.service 2>/dev/null || true
    systemctl stop madis-admin.service 2>/dev/null || true
fi

%files
/usr/local/bin/madis
%{_unitdir}/madis.service
%{_unitdir}/madis-admin.service
%config(noreplace) /etc/madis/madis.env.example

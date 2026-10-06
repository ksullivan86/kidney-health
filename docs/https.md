# HTTPS for your homelab (so phones can install the app)

Phones treat the app as a real, installable app only over HTTPS that they trust. Over plain
`http://192.168.x.y:8000` you get a degraded bookmark: no offline mode, no live barcode camera, no
secure sign-in cookies, and passwords cross your Wi-Fi in clear text (the full list is in
[`install-on-your-phone.md`](install-on-your-phone.md)). This page gives four ways to get HTTPS,
from "recommended" to "no outside dependencies". The design note behind it is
[`docs/dev/research/02-ios-pwa.md`](dev/research/02-ios-pwa.md) (F9, F10, R9).

> **Choose your final URL before anyone installs the app on a phone.** The browser treats scheme,
> host name and port together as the app's identity. Moving from `:8443` to `:443`, or from a
> Tailscale name to your own domain, creates a *different* app with empty storage: people must
> reinstall it, and entries still waiting to sync on the old one are lost.

> **Pick a neutral host name.** Every publicly trusted certificate is published in Certificate
> Transparency logs that anyone can search. A name like `kidney.smith-family.net` publishes a
> medical condition. Use a wildcard certificate (`*.home.example.net`, as below) or a neutral name
> such as `food.`, `log.` or `homelab-1`.

Certificates are getting shorter-lived (Let's Encrypt: 64 days from February 2027, 45 days from
February 2028), so every tier below renews **automatically**. Do not set up a certificate by hand.

## After any tier: tell the app its address

Whichever tier you choose, set these on the app (Quadlet `Environment=`, `deploy/.env`, or the
Kubernetes Deployment), then restart it:

| Setting | Example | Why |
|---|---|---|
| `PUBLIC_URL` | `https://food.home.example.net` (add `:8443` if you use that port) | Its host passes the Host check (DNS-rebinding defence), browsers' `Origin` must match it, and invite and reset links are built from it. Without it you get `400 Unknown host`. |
| `TRUSTED_PROXIES` | the address your proxy connects from | So the app believes the proxy's `X-Forwarded-Proto: https` (secure cookies, HSTS). The value depends on your engine: see the table in [`security.md`](security.md#4-proxy-trust-trusted_proxies-per-topology). |
| `ALLOWED_HOSTS` | `food.home.example.net` | Only for extra names besides the one in `PUBLIC_URL`. |

## Tier 1 (recommended): your own domain + Caddy with DNS-01

You need a domain (about $10 a year) whose DNS is hosted somewhere with an API (Cloudflare in this
example), and nothing else: no open ports, and the name only has to resolve on your LAN. Caddy
obtains a Let's Encrypt **wildcard** certificate through the DNS API and renews it by itself.

The stock Caddy image has no DNS modules, so build one with the Cloudflare module
([`deploy/caddy/Containerfile`](../deploy/caddy/Containerfile), Caddy 2.11.7 with
`caddy-dns/cloudflare` v0.2.4, both base images pinned by digest):

```Dockerfile
FROM docker.io/library/caddy:2.11.7-builder@sha256:… AS build
RUN xcaddy build v2.11.7 --with github.com/caddy-dns/cloudflare@v0.2.4
FROM docker.io/library/caddy:2.11.7@sha256:…
COPY --from=build /usr/bin/caddy /usr/bin/caddy
```

The Caddyfile ([`deploy/caddy/Caddyfile.example`](../deploy/caddy/Caddyfile.example)):

```caddyfile
{
	email admin@home.example.net
	https_port 8443                 # no capability needed inside the container
	auto_https disable_redirects    # DNS-01 needs no port 80
}

*.home.example.net {                # wildcard: the app's name never reaches CT logs
	tls {
		dns cloudflare {env.CF_API_TOKEN}
	}
	encode zstd gzip
	@food host food.home.example.net
	handle @food {
		reverse_proxy kidney-health:8000
	}
	handle {
		abort                       # unknown names under the wildcard get nothing
	}
}
```

Run it next to the app with the compose overlay, which puts Caddy and the app on a private
network where Caddy has a fixed address (so `TRUSTED_PROXIES` names exactly one container):

```bash
cp deploy/caddy/Caddyfile.example deploy/caddy/Caddyfile     # edit the two host names
printf 'CF_API_TOKEN=%s\n' "$CF_TOKEN" > deploy/caddy/caddy.env && chmod 0600 deploy/caddy/caddy.env
echo 'PUBLIC_URL=https://food.home.example.net:8443' >> deploy/.env
podman-compose -f deploy/compose.yaml -f deploy/compose.caddy.yaml up -d --build
```

* Create the Cloudflare API token with **Zone → DNS → Edit** for that one zone only.
* In your local DNS (router, Pi-hole, AdGuard Home), point `food.home.example.net` at the LAN
  address of this machine (split horizon). The public DNS needs no record for it.
* **Port 443 or 8443.** Rootless Podman and Docker cannot publish ports below 1024 by default, so the
  overlay publishes `8443`, and the URL is `https://food.home.example.net:8443` (iOS is fine with a
  port). To use plain `https://food.home.example.net`, allow low ports for unprivileged users once
  (`sudo sysctl -w net.ipv4.ip_unprivileged_port_start=443`, persisted in `/etc/sysctl.d/`), set
  `HTTPS_PORT=443` in `deploy/.env`, and decide **before** phones install the app.
* Other DNS providers: replace the `--with` module (Caddy's module list, "dns.providers").
* Back up the `caddy-data` volume (the ACME account and certificates) or let Caddy re-issue them.

## Tier 2 (easiest): Tailscale

If every phone that uses the app runs Tailscale, `tailscale serve` gives you a trusted certificate
for `https://<machine>.<tailnet>.ts.net` with no domain and no DNS work.

1. Give the machine a **neutral name** (`homelab-1`, not `kidney-health`): Tailscale machine names
   are published in Certificate Transparency logs. Tailscale's own advice: do not enable HTTPS if
   any machine name contains sensitive information.
2. Enable HTTPS certificates in the Tailscale admin console (DNS → HTTPS Certificates).
3. On the host: `tailscale serve --bg localhost:8000`.
4. Open `https://homelab-1.<tailnet>.ts.net` on the phone (the Tailscale app must be connected; it
   uses the iPhone's VPN slot).

`tailscale serve` connects from the host, so with rootless Podman the app sees the container's own
address, and with rootless Docker the RootlessKit/bridge gateway (for example `172.17.0.1`), not
`127.0.0.1`. Put the address from the app's log in `TRUSTED_PROXIES` (see
[`security.md`](security.md#4-proxy-trust-trusted_proxies-per-topology)); otherwise the app ignores
`X-Forwarded-Proto: https`, and once a second account exists every sign-in fails with
`https_required`. Do **not** use
Tailscale **Funnel** (public internet) unless the app's own sign-in is on (`AUTH_MODE=local`, the
default). For `AUTH_MODE=proxy` with Tailscale's identity headers, read the proxy section of
[`deployment.md`](deployment.md#sign-in-modes) first: `tailscale serve` cannot add the proxy secret.

## Tier 3 (no outside dependencies): your own certificate authority

For a LAN with no domain and no Tailscale. Every phone must trust your private root certificate,
which takes two steps on iOS and has a real cost: **that root can impersonate any website on the
phone**, so keep its private key offline.

1. Create the CA. Either Caddy with `tls internal` (root valid 3600 days, intermediate 7 days, leaf
   12 hours, all renewed automatically) or step-ca 0.30.2 (a full private ACME server). With Caddy,
   replace the `tls { dns … }` block above with `tls internal` and use a name under `home.arpa`
   (RFC 8375), for example `food.home.arpa`. Copy the root out of Caddy's data volume:
   `podman cp kidney-health-caddy:/data/caddy/pki/authorities/local/root.crt .`
2. Install it on the iPhone or iPad: AirDrop the `root.crt` file, or open it in Safari, then
   *Settings → Profile Downloaded → Install*.
3. Then turn on full trust (iOS does not do this by itself for a manually installed profile):
   *Settings → General → About → Certificate Trust Settings → enable full trust for root
   certificates* and switch on your root.
4. Android: *Settings → Security → Encryption & credentials → Install a certificate → CA
   certificate*. Chrome then trusts the site, but may install the app only as a plain shortcut from
   a private-CA origin; prefer tier 1 or 2 if you use Android.

Apple's rules apply to private certificates too: the host name must be in the subject alternative
name, `serverAuth` extended key usage, SHA-2, RSA keys of 2048 bits or more, and at most 825 days
of validity. Caddy and step-ca meet them by default. step-ca can issue a name-constrained root
(valid only for `home.arpa`), which limits the damage if its key leaks; check it on a device.

## Tier 4: Kubernetes (cert-manager)

Use cert-manager (v1.21.2 at the time of writing) with an ACME `ClusterIssuer` that solves DNS-01
through your DNS provider's API (Cloudflare: `dns01.cloudflare.apiTokenSecretRef`), or a `CA`
issuer built from a private root (then follow tier 3 on the phones). Attach the certificate to the
HTTPS listener of your Gateway (the default `deploy/k8s/httproute.yaml` routes to it) or, with an
Ingress, use the `cert-manager.io/cluster-issuer` annotation in
[`deploy/k8s/ingress.example.yaml`](../deploy/k8s/ingress.example.yaml). Set `PUBLIC_URL` in the
Deployment to the same host name.

## Not supported

* **A self-signed leaf certificate that people "tap through".** The warning returns on every visit,
  and browsers refuse to register the offline service worker from a page with a certificate error.
* **A certificate you renew by hand.** Lifetimes are shrinking to 45 days; it will expire unnoticed.

## Check on the phone (every tier)

1. The padlock shows and there is no warning.
2. In the app, the install panel (*Settings → This device*) says "Offline ready: the app opens
   without a connection." (over plain HTTP it says "Offline use needs HTTPS.").
3. Install it to the Home Screen, switch on Airplane Mode, and confirm that the app still opens.

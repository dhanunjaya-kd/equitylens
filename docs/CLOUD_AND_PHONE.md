# 📱 EquityLens on your phone · ☁️ EquityLens in the cloud

EquityLens is a small web server. Whatever runs it (your laptop or a cloud server), any phone that can reach it gets the full app in the browser, and you can add it to the home screen so it opens like a normal app.

## Pick your setup

| | Setup | Laptop must stay on? | Works on mobile data? | Cost | Time |
|:-:|---|:-:|:-:|---|---|
| **1** | **Same Wi-Fi** | ✅ yes | ❌ home Wi-Fi only | Free | 1 minute |
| **2** | **Tailscale on the laptop** *(recommended to start)* | ✅ yes | ✅ anywhere | Free | 10 minutes |
| **3** | **Cloud server** | ❌ no, runs 24×7 | ✅ anywhere | Free (Oracle) or about ₹400–₹1,000 a month (VPS) | 45–60 minutes |

> [!TIP]
> In the app, **⚙️ Settings → 📱 Use on your phone** shows the right address with a **QR code**. Scan it with the phone camera.

---

## Part A: Phone

### A1 · Same Wi-Fi (no set-up)

1. Start EquityLens on the laptop (`EquityLens.vbs` or `start.bat`).
2. On the laptop open **⚙️ Settings → 📱 Use on your phone** and scan the **📶 Same Wi-Fi** QR code with the phone, or type the address it shows (like `http://192.168.1.7:8600`) in the phone's browser.
3. The first time, Windows may ask whether Python can use the network: choose **Allow** on **Private networks**.

> [!WARNING]
> On shared Wi-Fi (hostel, office, café) anyone on that Wi-Fi could open it. Set a password first: add `EQL_PASSWORD=your-password` to `backend/.env` and restart EquityLens.

### A2 · Anywhere with Tailscale (free)

Tailscale puts your laptop and phone on a small private network of their own, so the phone reaches the laptop from anywhere (mobile data, office) and nobody else can.

1. Install **Tailscale** on the laptop from [tailscale.com/download](https://tailscale.com/download) and sign in (Google account is fine).
2. Install the **Tailscale** app on the phone (Play Store / App Store) and sign in with **the same account**. Turn it on.
3. On the laptop, **⚙️ Settings → 📱 Use on your phone** now also shows a **🌐 Anywhere (Tailscale)** QR code (address like `http://100.x.y.z:8600`). Scan it.

### A3 · Make it an app on the home screen

| Phone | Steps |
|---|---|
| **iPhone** (Safari) | Open the address → **Share** button → **Add to Home Screen** → Add |
| **Android** (Chrome) | Open the address → **⋮** menu → **Add to Home screen** (or *Install app*) → Add |

It opens full-screen with the EquityLens icon, without the browser's address bar.

### A4 · If the phone can't open it

| Problem | Fix |
|---|---|
| Page never loads on Wi-Fi | Laptop and phone must be on the **same** Wi-Fi (not guest Wi-Fi). Windows Firewall: *Allow an app through firewall* → tick **Python** for *Private*. Set the Wi-Fi network to *Private* in Windows settings. |
| Worked yesterday, not today | The laptop's Wi-Fi address changed. Scan the new QR code in Settings, or use Tailscale (its address never changes). |
| Stops when the laptop sleeps | Windows **Settings → System → Power** → *When plugged in, put my device to sleep after* → **Never**. |
| Asks for a password | That's `EQL_PASSWORD` from `backend/.env`. You stay signed in for 90 days. |
| Broker **Connect** fails on the phone | Connect brokers once from the laptop. Holdings then show on the phone too. |

---

## Part B: Cloud server (works with the laptop off)

### B0 · Read this first

> [!IMPORTANT]
> 1. **A password is required.** On a server, set `EQL_PASSWORD` in `backend/.env`. Settings holds your AI keys and broker keys.
> 2. **NSE often blocks data-centre IPs.** NSE's website refuses many cloud servers (AWS, Google Cloud and others), especially outside India. Pick an **Indian region** (Mumbai or Hyderabad) and run `python selftest.py` on the server. It shows exactly which sources work from there. If NSE is blocked, stock reports, prices, US stocks and AI still work, but NSE-only parts (delivery %, bulk/block deals, insider trades, surveillance, F&O list, Indian results calendar) may stay empty. Your laptop, on a home connection, has no such problem, which is why **Tailscale on the laptop (A2) is the simplest option**.
> 3. **Broker logins:** the redirect URL becomes the server's address, for example `https://yourname.duckdns.org/api/broker/zerodha/callback`. Update it in each broker's developer app. EquityLens only reads holdings, so SEBI's static-IP rule for API *orders* does not apply.

### B1 · Get a free server (Oracle Cloud)

Oracle Cloud's *Always Free* tier includes small ARM servers that never expire. Since **15 June 2026** the free ARM allowance is **2 OCPU and 12 GB RAM** in total (it used to be 4 OCPU / 24 GB), which is still far more than EquityLens needs.

1. Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/). A card is needed for verification. Choose **India South (Hyderabad)** or **India West (Mumbai)** as the *home region*; it can't be changed later.
2. **Create instance** → Image **Ubuntu 24.04** → Shape **Ampere · VM.Standard.A1.Flex** with **1 OCPU, 6 GB** (stays well inside the free allowance). If it says *out of capacity*, try again later or pick another availability domain.
3. Save the SSH key it offers, create the instance and note its **public IP**.
4. Connect from Windows PowerShell:
   ```powershell
   ssh -i C:\path\to\ssh-key.key ubuntu@<public-ip>
   ```

> Any other Linux VPS works the same way: DigitalOcean (Bangalore), AWS Lightsail (Mumbai), Hetzner and others, from about ₹400 a month.

### B2 · Install EquityLens on the server

```bash
sudo apt update && sudo apt install -y git python3-venv
git clone https://github.com/dhanunjaya-kd/equitylens
cd equitylens/backend
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env
nano .env          # set EQL_PASSWORD=...  and  EQL_SEC_USER_AGENT=Your Name you@example.com
venv/bin/python selftest.py      # which data sources work from this server
```

Keep it running (starts again after a crash or reboot):

```bash
sudo cp ~/equitylens/deploy/equitylens.service /etc/systemd/system/
sudo systemctl enable --now equitylens
systemctl status equitylens          # should say "active (running)"
```

<details>
<summary><b>Or with Docker</b></summary>

```bash
cd ~/equitylens
cp backend/.env.example backend/.env && nano backend/.env     # set EQL_PASSWORD!
docker compose up -d
docker compose logs -f
```
Data (keys, cache, broker logins, logs) stays in `backend/data` on the server.
</details>

### B3 · Open it from the phone

**Option 1 · Tailscale (recommended, private, no domain needed)**

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up            # open the link it prints and sign in with your Tailscale account
tailscale ip -4              # e.g. 100.88.12.5
```

On the phone (Tailscale app on), open `http://100.88.12.5:8600` and **Add to Home Screen**. No ports are open to the internet.

**Option 2 · Public HTTPS address (open from any browser)**

1. Get a free name at [duckdns.org](https://www.duckdns.org) (e.g. `yourname.duckdns.org`) and point it at the server's public IP.
2. Oracle console → your instance → **Subnet → Security list → Add ingress rules** for TCP ports **80** and **443** from `0.0.0.0/0`.
3. Oracle's Ubuntu image also has its own firewall rules. Open the same ports there:
   ```bash
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
   sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
   sudo netfilter-persistent save
   ```
4. Install Caddy (it gets the HTTPS certificate by itself):
   ```bash
   sudo apt install -y caddy
   sudo cp ~/equitylens/deploy/Caddyfile /etc/caddy/Caddyfile
   sudo nano /etc/caddy/Caddyfile                       # put your duckdns name
   sudo systemctl reload caddy
   ```
5. In `backend/.env` set `EQL_HOST=127.0.0.1` (only Caddy can reach EquityLens) and keep `EQL_PASSWORD` set, then `sudo systemctl restart equitylens`.
6. Open `https://yourname.duckdns.org` on any phone or computer and sign in.

### B4 · Update to the newest version

```bash
cd ~/equitylens && git pull
backend/venv/bin/pip install -r backend/requirements.txt
sudo systemctl restart equitylens          # Docker: docker compose up -d --build
```

### B5 · Move your laptop's data to the server (optional)

Your settings, AI keys, broker set-up, watchlist and cached reports are all in `backend/data`. Copy it once:

```powershell
scp -i C:\path\to\ssh-key.key -r C:\Users\<you>\Desktop\equitylens\backend\data ubuntu@<public-ip>:~/equitylens/backend/
```

Then `sudo systemctl restart equitylens` on the server.

### B6 · Hosts to avoid

Free plans on Render, Railway, Vercel, Streamlit Cloud and similar sleep when idle and **wipe files on every restart**. EquityLens would lose its cache, keys and broker logins each time, and scans would stop midway. Use a small always-on VM (B1) instead.

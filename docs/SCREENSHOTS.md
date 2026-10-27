# Screenshots

The images below were captured automatically from the running application
(`python scripts/capture_screenshots.py`). They are stored in `docs/screenshots/`.

| # | File | What it shows |
|---|------|---------------|
| 1 | `01_home.png` | Landing page |
| 2 | `02_register.png` | Registration form |
| 3 | `03_login_error.png` | Login with a wrong password (error handling) |
| 4 | `04_login.png` | Login form |
| 5 | `05_dashboard_empty.png` | Empty dashboard with storage meter and upload box |
| 6 | `06_upload_success.png` | Successful upload with notification |
| 7 | `07_file_list.png` | File listing with sizes, dates, download and delete buttons |
| 8 | `08_delete_confirm.png` | Delete confirmation dialog |
| 9 | `09_after_delete.png` | List after deleting a file (storage meter updated) |
| 10 | `10_access_denied.png` | A different user requesting someone else's file -> 404 |
| 11 | `11_mobile_dashboard.png` | Responsive mobile layout (390 px wide) |

![Home](screenshots/01_home.png)
![Register](screenshots/02_register.png)
![Login error](screenshots/03_login_error.png)
![Empty dashboard](screenshots/05_dashboard_empty.png)
![Upload success](screenshots/06_upload_success.png)
![File list](screenshots/07_file_list.png)
![Delete confirmation](screenshots/08_delete_confirm.png)
![Access denied](screenshots/10_access_denied.png)

![Mobile](screenshots/11_mobile_dashboard.png)

## How to capture them yourself

### Option A - automatic (recommended)

```bash
pip install -r requirements-dev.txt
playwright install chromium
python scripts/capture_screenshots.py
```

The script starts a temporary copy of the app (separate database and storage, so your own data is
untouched), registers two demo users, uploads sample files through the real UI and saves all PNGs.

### Option B - manual

1. Run `python run.py` and open <http://127.0.0.1:5000>.
2. Take each screenshot listed above:
   * **Windows:** `Win + Shift + S`  * **macOS:** `Cmd + Shift + 4`  * **Linux:** `PrtSc` or Flameshot
3. For the mobile view press `F12` in Chrome/Edge, click the *device toolbar* icon (`Ctrl + Shift + M`)
   and choose *iPhone 12 Pro*.
4. For `10_access_denied.png`: sign in as user A, note the id in a download link (e.g. `/api/files/3/download`),
   sign out, register/sign in as user B, and open that same URL.
5. Save the images in `docs/screenshots/` using the file names above.

# System Architecture - CloudStore

![System architecture](architecture.svg)

## 1. Overview

CloudStore is a classic **three-tier web application**:

| Tier | Technology | Responsibility |
|------|------------|----------------|
| Presentation | HTML5 (Jinja2 templates), CSS3, vanilla JavaScript | Responsive UI, drag-and-drop upload with progress, search/sort, delete confirmation |
| Application | Python 3 + Flask (blueprints `auth` and `files`) | Authentication, sessions, validation, access control, REST-style JSON API |
| Data | SQLite database + per-user folders on disk | File metadata and users (SQLite); file bytes (`storage/<user_id>/<uuid>`) |

No external cloud provider, SDK or API key is required. The service is "cloud-based" in the sense that
the server owns the storage and users reach it from any device over HTTP(S); the same code can be
deployed to any cloud VM or PaaS (see README, *Deployment*).

## 2. Component diagram

```mermaid
flowchart LR
    B[Browser<br/>HTML + CSS + JS] -->|HTTP/HTTPS| F
    subgraph F[Flask application]
        direction TB
        P[Request pipeline<br/>load user · CSRF · headers · errors]
        A[auth blueprint<br/>register · login · logout]
        FL[files blueprint<br/>dashboard · list · upload · download · delete]
        P --> A
        P --> FL
    end
    A --> DB[(SQLite<br/>users, files)]
    FL --> DB
    FL --> FS[(File storage<br/>storage/user_id/uuid)]
```

## 3. Module map

| File | Purpose |
|------|---------|
| `run.py` | Starts the development server |
| `config.py` | Settings (limits, quotas, cookie flags) read from environment / `.env` |
| `app/__init__.py` | Application factory, error handlers |
| `app/db.py` | SQLite connection per request, schema creation |
| `app/auth.py` | Registration, login (with throttling), logout |
| `app/files.py` | Upload, list, download, delete, storage usage |
| `app/utils.py` | `login_required`, CSRF protection, security headers, size formatting, filename cleaning |
| `app/templates/` | Jinja2 pages (`base`, `index`, `register`, `login`, `dashboard`, `error`) |
| `app/static/` | `css/style.css`, `js/app.js`, `img/favicon.svg` |
| `tests/test_app.py` | 39 automated tests |
| `scripts/capture_screenshots.py` | Generates the screenshots in `docs/screenshots/` |

## 4. Database design (ER diagram)

```mermaid
erDiagram
    USERS ||--o{ FILES : owns
    USERS {
        int id PK
        text username UK
        text email UK
        text password_hash
        text created_at
    }
    FILES {
        int id PK
        int user_id FK
        text original_name
        text stored_name UK
        int size
        text mime_type
        text uploaded_at
    }
```

* `files.user_id` is a foreign key with `ON DELETE CASCADE`.
* `stored_name` is a random UUID, so the original (user supplied) name never touches the file system.

## 5. Sequence diagrams

### 5.1 Upload

```mermaid
sequenceDiagram
    participant U as User (browser)
    participant F as Flask
    participant D as SQLite
    participant S as Storage
    U->>F: POST /api/files (multipart + X-CSRF-Token + session cookie)
    F->>F: verify session, verify CSRF token
    F->>F: check extension, size limit, quota
    F->>S: save to storage/<user_id>/<uuid>
    F->>D: INSERT INTO files (user_id, name, size, ...)
    F-->>U: 201 JSON {uploaded, errors, usage}
    U->>F: GET /api/files (refresh list)
    F->>D: SELECT ... WHERE user_id = me
    F-->>U: JSON file list with sizes
```

### 5.2 Download with access control

```mermaid
sequenceDiagram
    participant U as User
    participant F as Flask
    participant D as SQLite
    U->>F: GET /api/files/42/download
    F->>F: session valid?
    alt not signed in
        F-->>U: 401
    else signed in
        F->>D: SELECT * FROM files WHERE id=42 AND user_id=me
        alt row not found (missing OR owned by someone else)
            F-->>U: 404 File not found
        else owner
            F-->>U: 200 file as attachment
        end
    end
```

## 6. Access-control flow

```mermaid
flowchart TD
    R[Request] --> L{Signed in?}
    L -- no --> N1[401 / redirect to login]
    L -- yes --> M{State-changing method?}
    M -- yes --> C{Valid CSRF token?}
    C -- no --> N2[400 Invalid token]
    C -- yes --> Q
    M -- no --> Q[Query DB with id AND user_id = session user]
    Q --> O{Row found?}
    O -- no --> N3[404 same as non-existent]
    O -- yes --> OK[Perform operation]
```

## 7. Security design summary

| Threat | Countermeasure |
|--------|----------------|
| Reading/deleting other users' files | Every query includes `user_id`; foreign files return 404 |
| Password theft from database | Passwords hashed (Werkzeug scrypt, salted); never stored in plain text |
| Brute-force login | Lock-out after 5 failures for 5 minutes; same error for unknown user / wrong password |
| CSRF | Per-session token required on all POST/PUT/DELETE requests |
| XSS | Jinja2 auto-escaping, `textContent` in JavaScript, Content-Security-Policy (no inline scripts) |
| Path traversal | Files stored under random UUID names inside the owner's folder; display name sanitised |
| Session fixation / theft | Session cleared on login, HttpOnly + SameSite=Lax cookie, 2-hour lifetime |
| Disk exhaustion | Per-file limit, per-request limit, per-user quota |
| Malware executables | Blocked extensions (`exe`, `bat`, `cmd`, ...); downloads forced as attachments with `nosniff` |
| Clickjacking | `X-Frame-Options: DENY` + `frame-ancestors 'none'` |
| Information leak | Generic 500 page; stack traces only in server log |

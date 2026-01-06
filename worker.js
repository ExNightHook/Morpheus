// ========== КОНФИГУРАЦИЯ И ХЕЛПЕРЫ ==========
const XOR_KEY = [90, 90, 90, 202, 202, 202, 202, 58];
const KEY_PREFIX = "MPH-";
const KEY_PARTS = 4;
const KEY_PART_LENGTH = 5;
const CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

// XOR шифрование/дешифрование
function xorCrypt(data) {
    const dataArray = typeof data === 'string' ? new TextEncoder().encode(data) : data;
    const result = new Uint8Array(dataArray.length);
    
    for (let i = 0; i < dataArray.length; i++) {
        result[i] = dataArray[i] ^ XOR_KEY[i % XOR_KEY.length];
    }
    
    return result;
}

// Base64 кодирование/декодирование для XOR
function encodeBase64(data) {
    if (data instanceof Uint8Array) {
        return btoa(String.fromCharCode(...data));
    }
    return btoa(data);
}

function decodeBase64(str) {
    return Uint8Array.from(atob(str), c => c.charCodeAt(0));
}

// JSON с XOR
async function encryptJson(data) {
    const jsonStr = JSON.stringify(data);
    const encrypted = xorCrypt(jsonStr);
    return encodeBase64(encrypted);
}

async function decryptJson(encryptedBase64) {
    try {
        const encrypted = decodeBase64(encryptedBase64);
        const decrypted = xorCrypt(encrypted);
        const jsonStr = new TextDecoder().decode(decrypted);
        return JSON.parse(jsonStr);
    } catch (e) {
        throw new Error("Invalid encrypted data");
    }
}

// Генерация ключа в формате MPH-XXXXX-XXXXX-XXXXX-XXXXX
function generateKey() {
    const parts = [];
    for (let i = 0; i < KEY_PARTS; i++) {
        let part = '';
        for (let j = 0; j < KEY_PART_LENGTH; j++) {
            part += CHARS[Math.floor(Math.random() * CHARS.length)];
        }
        parts.push(part);
    }
    return KEY_PREFIX + parts.join('-');
}

// Хеширование пароля
async function hashPassword(password) {
    const encoder = new TextEncoder();
    const data = encoder.encode(password);
    const hash = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(hash))
        .map(b => b.toString(16).padStart(2, '0'))
        .join('');
}

// Проверка пароля
async function verifyPassword(password, hash) {
    const passwordHash = await hashPassword(password);
    return passwordHash === hash;
}

// Валидация UUID
function isValidUUID(uuid) {
    const uuidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
    return uuidRegex.test(uuid);
}

// ========== SQL ЗАПРОСЫ ДЛЯ СОЗДАНИЯ БАЗЫ ДАННЫХ ==========
const SQL_CREATE_TABLES = `
CREATE TABLE IF NOT EXISTS superusers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME
);

CREATE TABLE IF NOT EXISTS keys (
    key TEXT PRIMARY KEY,
    uuid TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    activated_at DATETIME,
    expiry_date DATETIME NOT NULL,
    is_frozen BOOLEAN DEFAULT 0,
    frozen_at DATETIME,
    frozen_by TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS builds (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS blacklist_processes (
    process TEXT PRIMARY KEY,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    added_by TEXT
);

CREATE TABLE IF NOT EXISTS blacklist_windows (
    window TEXT PRIMARY KEY,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    added_by TEXT
);
`;

// ========== КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ ==========
class Database {
    constructor(db) {
        this.db = db;
        this.initialized = false;
    }

    // Инициализация базы данных
    async init() {
        if (this.initialized) return;
        
        try {
            // Создаем таблицы по очереди
            const tables = SQL_CREATE_TABLES.split(';').filter(sql => sql.trim());
            
            for (const tableSql of tables) {
                if (tableSql.trim()) {
                    try {
                        await this.db.exec(tableSql + ';');
                    } catch (err) {
                        console.log("Table creation warning:", err.message);
                    }
                }
            }
            
            // Проверяем, есть ли суперпользователь
            const existing = await this.db.prepare(
                "SELECT id FROM superusers WHERE username = ?"
            ).bind("XaKNMlxDWs").first();
            
            if (!existing) {
                const passwordHash = await hashPassword("OMrTSqJlfxr4RtZo4W");
                try {
                    await this.db.prepare(
                        "INSERT INTO superusers (username, password_hash) VALUES (?, ?)"
                    ).bind("XaKNMlxDWs", passwordHash).run();
                    console.log("Superuser created successfully");
                } catch (err) {
                    console.log("Superuser creation error:", err.message);
                }
            } else {
                console.log("Superuser already exists");
            }
            
            this.initialized = true;
            return true;
        } catch (error) {
            console.error("Database init error:", error);
            return false;
        }
    }

    // === МЕТОДЫ ДЛЯ КЛЮЧЕЙ ===
    async getKey(key) {
        try {
            return await this.db.prepare(
                "SELECT * FROM keys WHERE key = ?"
            ).bind(key).first();
        } catch (error) {
            console.error("getKey error:", error);
            return null;
        }
    }

    async createKey(key, expiryDate, uuid = null) {
        try {
            return await this.db.prepare(
                "INSERT INTO keys (key, uuid, expiry_date) VALUES (?, ?, ?)"
            ).bind(key, uuid, expiryDate).run();
        } catch (error) {
            console.error("createKey error:", error);
            return { success: false, error: error.message };
        }
    }

    async updateKeyUUID(key, uuid) {
        try {
            return await this.db.prepare(
                "UPDATE keys SET uuid = ?, activated_at = CURRENT_TIMESTAMP WHERE key = ? AND uuid IS NULL"
            ).bind(uuid, key).run();
        } catch (error) {
            console.error("updateKeyUUID error:", error);
            return { success: false, error: error.message };
        }
    }

    async verifyKey(key, uuid) {
        try {
            const keyData = await this.getKey(key);
            if (!keyData) return { valid: false, reason: "Key not found" };
            
            if (keyData.is_frozen) {
                return { valid: false, reason: "Key is frozen", data: keyData };
            }
            
            if (new Date(keyData.expiry_date) < new Date()) {
                return { valid: false, reason: "Key expired", data: keyData };
            }
            
            if (keyData.uuid && keyData.uuid !== uuid) {
                return { valid: false, reason: "UUID mismatch", data: keyData };
            }
            
            return { valid: true, data: keyData };
        } catch (error) {
            console.error("verifyKey error:", error);
            return { valid: false, reason: "Database error", error: error.message };
        }
    }

    async getAllKeys(filters = {}) {
        try {
            let query = "SELECT * FROM keys WHERE 1=1";
            const params = [];
            
            if (filters.search) {
                query += " AND (key LIKE ? OR uuid LIKE ?)";
                params.push(`%${filters.search}%`, `%${filters.search}%`);
            }
            
            if (filters.frozen !== undefined) {
                query += " AND is_frozen = ?";
                params.push(filters.frozen ? 1 : 0);
            }
            
            if (filters.expired) {
                query += " AND expiry_date < CURRENT_TIMESTAMP";
            }
            
            query += " ORDER BY created_at DESC";
            
            if (filters.limit) {
                query += " LIMIT ?";
                params.push(filters.limit);
            }
            
            const stmt = this.db.prepare(query);
            const result = await stmt.bind(...params).all();
            return result;
        } catch (error) {
            console.error("getAllKeys error:", error);
            return { results: [] };
        }
    }

    async updateKey(key, updates) {
        try {
            const fields = [];
            const values = [];
            
            for (const [field, value] of Object.entries(updates)) {
                fields.push(`${field} = ?`);
                values.push(value);
            }
            
            values.push(key);
            
            return await this.db.prepare(
                `UPDATE keys SET ${fields.join(', ')} WHERE key = ?`
            ).bind(...values).run();
        } catch (error) {
            console.error("updateKey error:", error);
            return { success: false, error: error.message };
        }
    }

    async deleteKey(key) {
        try {
            return await this.db.prepare(
                "DELETE FROM keys WHERE key = ?"
            ).bind(key).run();
        } catch (error) {
            console.error("deleteKey error:", error);
            return { success: false, error: error.message };
        }
    }

    async deleteKeys(keys) {
        try {
            const placeholders = keys.map(() => '?').join(',');
            return await this.db.prepare(
                `DELETE FROM keys WHERE key IN (${placeholders})`
            ).bind(...keys).run();
        } catch (error) {
            console.error("deleteKeys error:", error);
            return { success: false, error: error.message };
        }
    }

    async freezeKeys(keys, frozenBy) {
        try {
            const placeholders = keys.map(() => '?').join(',');
            return await this.db.prepare(
                `UPDATE keys SET is_frozen = 1, frozen_at = CURRENT_TIMESTAMP, frozen_by = ? 
                 WHERE key IN (${placeholders})`
            ).bind(frozenBy, ...keys).run();
        } catch (error) {
            console.error("freezeKeys error:", error);
            return { success: false, error: error.message };
        }
    }

    async unfreezeKeys(keys) {
        try {
            const placeholders = keys.map(() => '?').join(',');
            return await this.db.prepare(
                `UPDATE keys SET is_frozen = 0, frozen_at = NULL, frozen_by = NULL 
                 WHERE key IN (${placeholders})`
            ).bind(...keys).run();
        } catch (error) {
            console.error("unfreezeKeys error:", error);
            return { success: false, error: error.message };
        }
    }

    async generateKeys(count, expiryDays, expiryDate = null) {
        try {
            const keys = [];
            const expiry = expiryDate || new Date(Date.now() + expiryDays * 24 * 60 * 60 * 1000).toISOString();
            
            for (let i = 0; i < count; i++) {
                let key;
                let exists;
                
                do {
                    key = generateKey();
                    exists = await this.getKey(key);
                } while (exists);
                
                keys.push(key);
                await this.createKey(key, expiry);
            }
            
            return { success: true, keys };
        } catch (error) {
            console.error("generateKeys error:", error);
            return { success: false, error: error.message, keys: [] };
        }
    }

    // === МЕТОДЫ ДЛЯ БИЛДОВ ===
    async getBuild(buildId) {
        try {
            return await this.db.prepare(
                "SELECT * FROM builds WHERE id = ? AND is_active = 1"
            ).bind(buildId).first();
        } catch (error) {
            console.error("getBuild error:", error);
            return null;
        }
    }

    async getAllBuilds() {
        try {
            const result = await this.db.prepare(
                "SELECT * FROM builds ORDER BY created_at DESC"
            ).all();
            return result;
        } catch (error) {
            console.error("getAllBuilds error:", error);
            return { results: [] };
        }
    }

    async createBuild(buildId, url, isActive = 1) {
        try {
            return await this.db.prepare(
                "INSERT INTO builds (id, url, is_active) VALUES (?, ?, ?)"
            ).bind(buildId, url, isActive).run();
        } catch (error) {
            console.error("createBuild error:", error);
            return { success: false, error: error.message };
        }
    }

    async updateBuild(buildId, updates) {
        try {
            const fields = [];
            const values = [];
            
            for (const [field, value] of Object.entries(updates)) {
                fields.push(`${field} = ?`);
                values.push(value);
            }
            
            values.push(buildId);
            
            return await this.db.prepare(
                `UPDATE builds SET ${fields.join(', ')} WHERE id = ?`
            ).bind(...values).run();
        } catch (error) {
            console.error("updateBuild error:", error);
            return { success: false, error: error.message };
        }
    }

    async deleteBuild(buildId) {
        try {
            return await this.db.prepare(
                "DELETE FROM builds WHERE id = ?"
            ).bind(buildId).run();
        } catch (error) {
            console.error("deleteBuild error:", error);
            return { success: false, error: error.message };
        }
    }

    // === МЕТОДЫ ДЛЯ ЧЕРНЫХ СПИСКОВ ===
    async checkBlacklist(items, table) {
        try {
            const placeholders = items.map(() => '?').join(',');
            const column = table === 'blacklist_processes' ? 'process' : 'window';
            const result = await this.db.prepare(
                `SELECT * FROM ${table} WHERE ${column} IN (${placeholders})`
            ).bind(...items).all();
            
            return result.results || [];
        } catch (error) {
            console.error("checkBlacklist error:", error);
            return [];
        }
    }

    async addToBlacklist(items, table, addedBy) {
        try {
            const results = [];
            const column = table === 'blacklist_processes' ? 'process' : 'window';
            
            for (const item of items) {
                try {
                    await this.db.prepare(
                        `INSERT OR IGNORE INTO ${table} (${column}, added_by) VALUES (?, ?)`
                    ).bind(item, addedBy).run();
                    results.push({ item, success: true });
                } catch (e) {
                    results.push({ item, success: false, error: e.message });
                }
            }
            return results;
        } catch (error) {
            console.error("addToBlacklist error:", error);
            return items.map(item => ({ item, success: false, error: error.message }));
        }
    }

    async removeFromBlacklist(items, table) {
        try {
            const placeholders = items.map(() => '?').join(',');
            const column = table === 'blacklist_processes' ? 'process' : 'window';
            return await this.db.prepare(
                `DELETE FROM ${table} WHERE ${column} IN (${placeholders})`
            ).bind(...items).run();
        } catch (error) {
            console.error("removeFromBlacklist error:", error);
            return { success: false, error: error.message };
        }
    }

    async getBlacklist(table, limit = 100) {
        try {
            const result = await this.db.prepare(
                `SELECT * FROM ${table} ORDER BY added_at DESC LIMIT ?`
            ).bind(limit).all();
            return result;
        } catch (error) {
            console.error("getBlacklist error:", error);
            return { results: [] };
        }
    }

    // === МЕТОДЫ ДЛЯ АДМИНИСТРАТОРОВ ===
    async verifyAdmin(username, password) {
        try {
            const admin = await this.db.prepare(
                "SELECT * FROM superusers WHERE username = ?"
            ).bind(username).first();
            
            if (!admin) {
                console.log("Admin not found:", username);
                return null;
            }
            
            const isValid = await verifyPassword(password, admin.password_hash);
            if (!isValid) {
                console.log("Invalid password for:", username);
                return null;
            }
            
            // Обновляем время последнего входа
            await this.db.prepare(
                "UPDATE superusers SET last_login = CURRENT_TIMESTAMP WHERE id = ?"
            ).bind(admin.id).run();
            
            return admin;
        } catch (error) {
            console.error("verifyAdmin error:", error);
            return null;
        }
    }

    // === МЕТОДЫ ДЛЯ СТАТИСТИКИ ===
    async getStats() {
        try {
            const totalKeys = await this.db.prepare(
                "SELECT COUNT(*) as count FROM keys"
            ).first();
            
            const activeKeys = await this.db.prepare(
                "SELECT COUNT(*) as count FROM keys WHERE is_frozen = 0 AND expiry_date > CURRENT_TIMESTAMP"
            ).first();
            
            const frozenKeys = await this.db.prepare(
                "SELECT COUNT(*) as count FROM keys WHERE is_frozen = 1"
            ).first();
            
            const expiredKeys = await this.db.prepare(
                "SELECT COUNT(*) as count FROM keys WHERE expiry_date < CURRENT_TIMESTAMP"
            ).first();
            
            return {
                total_keys: totalKeys?.count || 0,
                active_keys: activeKeys?.count || 0,
                frozen_keys: frozenKeys?.count || 0,
                expired_keys: expiredKeys?.count || 0
            };
        } catch (error) {
            console.error("getStats error:", error);
            return {
                total_keys: 0,
                active_keys: 0,
                frozen_keys: 0,
                expired_keys: 0
            };
        }
    }

    // === МЕТОД ДЛЯ ПРОВЕРКИ ИНИЦИАЛИЗАЦИИ ===
    async checkInitialization() {
        try {
            const tables = await this.db.prepare(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('superusers', 'keys', 'builds', 'blacklist_processes', 'blacklist_windows')"
            ).all();
            
            return tables.results.length === 5;
        } catch (error) {
            return false;
        }
    }
}

// ========== HTML ШАБЛОНЫ ==========
const HTML_TEMPLATES = {
    login: `<!DOCTYPE html>
<html>
<head>
    <title>Admin Panel - Login</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }
        .login-container { max-width: 400px; margin: 100px auto; background: white; padding: 40px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h2 { text-align: center; color: #333; margin-bottom: 30px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 5px; color: #555; }
        input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; font-size: 16px; }
        button { width: 100%; padding: 12px; background: #4CAF50; color: white; border: none; border-radius: 5px; font-size: 16px; cursor: pointer; }
        button:hover { background: #45a049; }
        .error { color: #ff0000; text-align: center; margin-top: 10px; }
        .init-link { text-align: center; margin-top: 20px; }
        .init-link a { color: #2563eb; text-decoration: none; }
    </style>
</head>
<body>
    <div class="login-container">
        <h2>Admin Panel Login</h2>
        <form id="loginForm">
            <div class="form-group">
                <label for="username">Username:</label>
                <input type="text" id="username" name="username" required>
            </div>
            <div class="form-group">
                <label for="password">Password:</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit">Login</button>
            <div id="error" class="error"></div>
        </form>
        <div class="init-link">
            <a href="/admin/init-db" target="_blank">Initialize Database First</a>
        </div>
    </div>
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const response = await fetch('/admin/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(Object.fromEntries(formData))
            });
            
            if (response.ok) {
                window.location.href = '/admin/panel';
            } else {
                document.getElementById('error').textContent = 'Invalid credentials';
            }
        });
    </script>
</body>
</html>`,

    main: (user, keys, builds, processes, windows, stats) => {
        // Создаем строки таблицы ключей
        const keysRows = keys && keys.results ? keys.results.map(key => {
            const expiryDate = new Date(key.expiry_date);
            const now = new Date();
            const status = key.is_frozen ? 'frozen' : expiryDate < now ? 'expired' : 'active';
            const statusClass = key.is_frozen ? 'badge-warning' : expiryDate < now ? 'badge-danger' : 'badge-success';
            const statusText = key.is_frozen ? 'Frozen' : expiryDate < now ? 'Expired' : 'Active';
            
            return `
                <tr data-key="${key.key}" data-status="${status}">
                    <td><input type="checkbox" class="key-checkbox" value="${key.key}"></td>
                    <td><code>${key.key}</code></td>
                    <td>${key.uuid || '<span class="text-muted">Not activated</span>'}</td>
                    <td>${new Date(key.created_at).toLocaleDateString()}</td>
                    <td class="${expiryDate < now ? 'text-danger' : ''}">
                        ${expiryDate.toLocaleString()}
                    </td>
                    <td>
                        <span class="badge ${statusClass}">${statusText}</span>
                    </td>
                    <td>
                        <button class="btn btn-outline btn-sm" onclick="editKey('${key.key.replace(/'/g, "\\'")}')">✏ Edit</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteKey('${key.key.replace(/'/g, "\\'")}')">🗑</button>
                    </td>
                </tr>`;
        }).join('') : '<tr><td colspan="7" class="text-center">No keys found</td></tr>';

        // Создаем строки для таблицы билдов
        const buildsRows = builds && builds.results ? builds.results.map(build => `
            <tr>
                <td><code>${build.id}</code></td>
                <td><a href="${build.url}" target="_blank">${build.url}</a></td>
                <td>${new Date(build.created_at).toLocaleDateString()}</td>
                <td>
                    <span class="badge ${build.is_active ? 'badge-success' : 'badge-danger'}">
                        ${build.is_active ? 'Active' : 'Inactive'}
                    </span>
                </td>
                <td>
                    <button class="btn btn-outline btn-sm" onclick="editBuild('${build.id.replace(/'/g, "\\'")}')">✏ Edit</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteBuild('${build.id.replace(/'/g, "\\'")}')">🗑</button>
                </td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="text-center">No builds found</td></tr>';

        // Создаем строки для таблицы процессов
        const processesRows = processes && processes.results ? processes.results.map(proc => `
            <tr>
                <td><input type="checkbox" class="process-checkbox" value="${proc.process.replace(/'/g, "\\'")}"></td>
                <td><code>${proc.process}</code></td>
                <td>${proc.added_by || 'System'}</td>
                <td>${new Date(proc.added_at).toLocaleDateString()}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="deleteProcess('${proc.process.replace(/'/g, "\\'")}')">🗑</button>
                </td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="text-center">No processes in blacklist</td></tr>';

        // Создаем строки для таблицы окон
        const windowsRows = windows && windows.results ? windows.results.map(win => `
            <tr>
                <td><input type="checkbox" class="window-checkbox" value="${win.window.replace(/'/g, "\\'")}"></td>
                <td><code>${win.window}</code></td>
                <td>${win.added_by || 'System'}</td>
                <td>${new Date(win.added_at).toLocaleDateString()}</td>
                <td>
                    <button class="btn btn-danger btn-sm" onclick="deleteWindow('${win.window.replace(/'/g, "\\'")}')">🗑</button>
                </td>
            </tr>
        `).join('') : '<tr><td colspan="5" class="text-center">No windows in blacklist</td></tr>';

        return `<!DOCTYPE html>
<html>
<head>
    <title>Admin Panel</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        :root { --primary: #2563eb; --danger: #dc2626; --success: #16a34a; --warning: #f59e0b; --bg: #f8fafc; --card: #ffffff; --border: #e2e8f0; --text: #1e293b; --text-light: #64748b; }
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background: var(--bg); color: var(--text); line-height: 1.6; }
        .container { display: grid; grid-template-columns: 250px 1fr; min-height: 100vh; }
        .sidebar { background: var(--card); border-right: 1px solid var(--border); padding: 20px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
        .logo { font-size: 24px; font-weight: bold; color: var(--primary); margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }
        .main-content { padding: 20px; overflow-y: auto; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; padding-bottom: 20px; border-bottom: 1px solid var(--border); }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .stat-card { background: var(--card); padding: 20px; border-radius: 10px; border: 1px solid var(--border); box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 20px; flex-wrap: wrap; }
        .tab { padding: 12px 24px; cursor: pointer; border: 1px solid transparent; border-bottom: none; background: none; color: var(--text-light); transition: all 0.2s; }
        .tab.active { color: var(--primary); border-color: var(--border); border-bottom-color: var(--card); background: var(--card); border-radius: 8px 8px 0 0; position: relative; bottom: -1px; }
        .tab-content { display: none; background: var(--card); border: 1px solid var(--border); border-radius: 0 8px 8px 8px; padding: 20px; }
        .tab-content.active { display: block; }
        .table-container { overflow-x: auto; border-radius: 8px; border: 1px solid var(--border); }
        table { width: 100%; border-collapse: collapse; background: var(--card); }
        th { background: var(--bg); padding: 12px 16px; text-align: left; font-weight: 600; color: var(--text); border-bottom: 1px solid var(--border); }
        td { padding: 12px 16px; border-bottom: 1px solid var(--border); }
        .btn { display: inline-flex; align-items: center; justify-content: center; padding: 10px 20px; border: none; border-radius: 6px; font-size: 14px; font-weight: 500; cursor: pointer; transition: all 0.2s; text-decoration: none; gap: 8px; }
        .btn-primary { background: var(--primary); color: white; }
        .btn-danger { background: var(--danger); color: white; }
        .btn-success { background: var(--success); color: white; }
        .badge { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
        .badge-success { background: #dcfce7; color: var(--success); }
        .badge-danger { background: #fee2e2; color: var(--danger); }
        .badge-warning { background: #fef3c7; color: var(--warning); }
        .text-center { text-align: center; }
        .text-danger { color: var(--danger); }
        .text-muted { color: var(--text-light); }
        .flex { display: flex; }
        .items-center { align-items: center; }
        .justify-between { justify-content: space-between; }
        .gap-2 { gap: 8px; }
        .gap-4 { gap: 16px; }
        .mb-4 { margin-bottom: 16px; }
        .mb-6 { margin-bottom: 24px; }
        .mt-4 { margin-top: 16px; }
        .search-bar { display: flex; gap: 10px; margin-bottom: 20px; }
        .filters { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
        .filter-group { display: flex; align-items: center; gap: 8px; }
        .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .form-group { margin-bottom: 20px; }
        label { display: block; margin-bottom: 8px; font-weight: 500; color: var(--text); }
        input, select, textarea { width: 100%; padding: 10px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 14px; }
        @media (max-width: 768px) {
            .container { grid-template-columns: 1fr; }
            .sidebar { height: auto; position: static; }
            .stats-grid { grid-template-columns: 1fr; }
            .form-grid { grid-template-columns: 1fr; }
            .tabs { overflow-x: auto; flex-wrap: nowrap; }
            .tab { white-space: nowrap; }
        }
    </style>
</head>
<body>
    <div class="container">
        <aside class="sidebar">
            <div class="logo">Admin Panel</div>
            <div class="user-info">
                <div class="username">${user.username}</div>
            </div>
            <ul class="nav">
                <li><a href="#keys" class="nav-link active">Keys Management</a></li>
                <li><a href="#generate" class="nav-link">Generate Keys</a></li>
                <li><a href="#builds" class="nav-link">Builds</a></li>
                <li><a href="#blacklists" class="nav-link">Blacklists</a></li>
            </ul>
            <button class="logout-btn" onclick="logout()">Logout</button>
        </aside>
        
        <main class="main-content">
            <header class="header">
                <h1>Keys Management</h1>
                <div class="flex items-center gap-4">
                    <button class="btn btn-outline" onclick="refreshData()">↻ Refresh</button>
                </div>
            </header>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <h3>Total Keys</h3>
                    <div class="value">${stats.total_keys || 0}</div>
                </div>
                <div class="stat-card">
                    <h3>Active Keys</h3>
                    <div class="value">${stats.active_keys || 0}</div>
                </div>
                <div class="stat-card">
                    <h3>Frozen Keys</h3>
                    <div class="value">${stats.frozen_keys || 0}</div>
                </div>
                <div class="stat-card">
                    <h3>Expired Keys</h3>
                    <div class="value">${stats.expired_keys || 0}</div>
                </div>
            </div>
            
            <div class="tabs" id="mainTabs">
                <button class="tab active" data-tab="keys">Keys Management</button>
                <button class="tab" data-tab="generate">Generate Keys</button>
                <button class="tab" data-tab="builds">Builds Management</button>
                <button class="tab" data-tab="processes">Process Blacklist</button>
                <button class="tab" data-tab="windows">Window Blacklist</button>
            </div>
            
            <div id="keys-tab" class="tab-content active">
                <div class="search-bar">
                    <input type="text" id="searchKeys" placeholder="Search by key or UUID..." onkeyup="searchKeys()">
                    <select id="filterStatus" onchange="filterKeys()">
                        <option value="">All Status</option>
                        <option value="active">Active</option>
                        <option value="frozen">Frozen</option>
                        <option value="expired">Expired</option>
                    </select>
                </div>
                
                <div class="flex justify-between mb-4">
                    <div class="filters">
                        <div class="filter-group">
                            <input type="checkbox" id="selectAll" onchange="toggleSelectAll()">
                            <label for="selectAll">Select All</label>
                        </div>
                    </div>
                    <div class="flex gap-2">
                        <button class="btn btn-danger" onclick="freezeSelected()">❄ Freeze</button>
                        <button class="btn btn-success" onclick="unfreezeSelected()">☀ Unfreeze</button>
                        <button class="btn btn-danger" onclick="deleteSelected()">🗑 Delete</button>
                    </div>
                </div>
                
                <div class="table-container">
                    <table id="keysTable">
                        <thead>
                            <tr>
                                <th><input type="checkbox" id="headerCheckbox"></th>
                                <th>Key</th>
                                <th>UUID</th>
                                <th>Created</th>
                                <th>Expiry Date</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${keysRows}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div id="generate-tab" class="tab-content">
                <div class="form-grid">
                    <div class="form-group">
                        <label for="keyCount">Number of Keys</label>
                        <input type="number" id="keyCount" min="1" max="1000" value="10">
                    </div>
                    <div class="form-group">
                        <label for="expiryType">Expiry Type</label>
                        <select id="expiryType" onchange="toggleExpiryInput()">
                            <option value="days">Days from now</option>
                            <option value="date">Specific date</option>
                        </select>
                    </div>
                    <div class="form-group" id="daysGroup">
                        <label for="expiryDays">Days Valid</label>
                        <input type="number" id="expiryDays" min="1" value="30">
                    </div>
                    <div class="form-group" id="dateGroup" style="display: none;">
                        <label for="expiryDate">Expiry Date</label>
                        <input type="datetime-local" id="expiryDate">
                    </div>
                </div>
                
                <div class="flex gap-4 mb-6">
                    <button class="btn btn-primary" onclick="generateKeys()">🔑 Generate Keys</button>
                    <button class="btn btn-success" onclick="generateAndExport()">📥 Generate & Export</button>
                </div>
                
                <div id="generatedKeys" style="display: none;">
                    <h3 class="mb-4">Generated Keys</h3>
                    <div class="table-container">
                        <table id="newKeysTable">
                            <thead>
                                <tr>
                                    <th>Key</th>
                                    <th>Expiry Date</th>
                                </tr>
                            </thead>
                            <tbody id="newKeysBody"></tbody>
                        </table>
                    </div>
                </div>
            </div>
            
            <div id="builds-tab" class="tab-content">
                <div class="flex justify-between mb-4">
                    <h3>Builds List</h3>
                    <button class="btn btn-primary" onclick="showAddBuildModal()">+ Add Build</button>
                </div>
                
                <!-- Модальное окно для добавления билда -->
                <div id="addBuildModal" class="modal" style="display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5);">
                    <div style="background-color: white; margin: 10% auto; padding: 20px; border-radius: 8px; width: 400px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                            <h3>Add New Build</h3>
                            <button onclick="closeModal('addBuildModal')" style="background: none; border: none; font-size: 24px; cursor: pointer;">×</button>
                        </div>
                        <div class="form-group">
                            <label>Build ID</label>
                            <input type="text" id="newBuildId" placeholder="e.g., 1.0.0">
                        </div>
                        <div class="form-group">
                            <label>File URL</label>
                            <input type="url" id="newBuildUrl" placeholder="https://example.com/build.zip">
                        </div>
                        <div class="form-group">
                            <label>
                                <input type="checkbox" id="newBuildActive" checked> Active
                            </label>
                        </div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-outline" onclick="closeModal('addBuildModal')">Cancel</button>
                            <button class="btn btn-primary" onclick="saveNewBuild()">Add Build</button>
                        </div>
                    </div>
                </div>
                
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th>Build ID</th>
                                <th>URL</th>
                                <th>Created</th>
                                <th>Status</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${buildsRows}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div id="processes-tab" class="tab-content">
                <div class="flex justify-between mb-4">
                    <h3>Process Blacklist</h3>
                    <div class="flex gap-2">
                        <button class="btn btn-primary" onclick="showAddProcessModal()">+ Add Process</button>
                        <button class="btn btn-danger" onclick="deleteSelectedProcesses()">🗑 Delete Selected</button>
                    </div>
                </div>
                
                <!-- Модальное окно для добавления процесса -->
                <div id="addProcessModal" class="modal" style="display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5);">
                    <div style="background-color: white; margin: 10% auto; padding: 20px; border-radius: 8px; width: 400px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                            <h3>Add Process to Blacklist</h3>
                            <button onclick="closeModal('addProcessModal')" style="background: none; border: none; font-size: 24px; cursor: pointer;">×</button>
                        </div>
                        <div class="form-group">
                            <label>Process Name</label>
                            <input type="text" id="newProcessName" placeholder="e.g., cheat.exe">
                        </div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-outline" onclick="closeModal('addProcessModal')">Cancel</button>
                            <button class="btn btn-primary" onclick="saveNewProcess()">Add Process</button>
                        </div>
                    </div>
                </div>
                
                <div class="form-group mb-4">
                    <label>Add Multiple Processes (one per line)</label>
                    <textarea id="bulkProcesses" rows="4" placeholder="explorer.exe&#10;hack.exe&#10;cheat.exe"></textarea>
                    <button class="btn btn-primary mt-2" onclick="addBulkProcesses()">Add All</button>
                </div>
                
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th><input type="checkbox" id="selectAllProcesses"></th>
                                <th>Process Name</th>
                                <th>Added By</th>
                                <th>Added Date</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${processesRows}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <div id="windows-tab" class="tab-content">
                <div class="flex justify-between mb-4">
                    <h3>Window Title Blacklist</h3>
                    <div class="flex gap-2">
                        <button class="btn btn-primary" onclick="showAddWindowModal()">+ Add Window</button>
                        <button class="btn btn-danger" onclick="deleteSelectedWindows()">🗑 Delete Selected</button>
                    </div>
                </div>
                
                <!-- Модальное окно для добавления окна -->
                <div id="addWindowModal" class="modal" style="display: none; position: fixed; z-index: 1000; left: 0; top: 0; width: 100%; height: 100%; background-color: rgba(0,0,0,0.5);">
                    <div style="background-color: white; margin: 10% auto; padding: 20px; border-radius: 8px; width: 400px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
                            <h3>Add Window to Blacklist</h3>
                            <button onclick="closeModal('addWindowModal')" style="background: none; border: none; font-size: 24px; cursor: pointer;">×</button>
                        </div>
                        <div class="form-group">
                            <label>Window Title</label>
                            <input type="text" id="newWindowTitle" placeholder="e.g., Cheat Engine">
                        </div>
                        <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                            <button class="btn btn-outline" onclick="closeModal('addWindowModal')">Cancel</button>
                            <button class="btn btn-primary" onclick="saveNewWindow()">Add Window</button>
                        </div>
                    </div>
                </div>
                
                <div class="form-group mb-4">
                    <label>Add Multiple Windows (one per line)</label>
                    <textarea id="bulkWindows" rows="4" placeholder="Cheat Engine&#10;Game Hacking Tool&#10;Debugger"></textarea>
                    <button class="btn btn-primary mt-2" onclick="addBulkWindows()">Add All</button>
                </div>
                
                <div class="table-container">
                    <table>
                        <thead>
                            <tr>
                                <th><input type="checkbox" id="selectAllWindows"></th>
                                <th>Window Title</th>
                                <th>Added By</th>
                                <th>Added Date</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            ${windowsRows}
                        </tbody>
                    </table>
                </div>
            </div>
        </main>
    </div>
    
    <script>
        let selectedKeys = new Set();
        let selectedProcesses = new Set();
        let selectedWindows = new Set();
        
        // Tab switching
        document.querySelectorAll('.tab').forEach(tab => {
            tab.addEventListener('click', () => {
                document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                document.getElementById(tab.dataset.tab + '-tab').classList.add('active');
            });
        });
        
        // Modal functions
        function showModal(id) {
            document.getElementById(id).style.display = 'block';
        }
        
        function closeModal(id) {
            document.getElementById(id).style.display = 'none';
        }
        
        // Key management
        function searchKeys() {
            const search = document.getElementById('searchKeys').value.toLowerCase();
            const rows = document.querySelectorAll('#keysTable tbody tr');
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                row.style.display = text.includes(search) ? '' : 'none';
            });
        }
        
        function filterKeys() {
            const filter = document.getElementById('filterStatus').value;
            const rows = document.querySelectorAll('#keysTable tbody tr');
            rows.forEach(row => {
                const status = row.dataset.status;
                row.style.display = (!filter || status === filter) ? '' : 'none';
            });
        }
        
        function toggleSelectAll() {
            const checked = document.getElementById('selectAll').checked;
            document.querySelectorAll('.key-checkbox').forEach(cb => {
                cb.checked = checked;
                if (checked) selectedKeys.add(cb.value);
                else selectedKeys.delete(cb.value);
            });
        }
        
        // Key actions
        async function freezeSelected() {
            const keys = Array.from(selectedKeys);
            if (keys.length === 0) return alert('Please select keys first');
            if (confirm('Freeze ' + keys.length + ' selected keys?')) {
                const response = await fetch('/admin/api/freeze-keys', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ keys })
                });
                
                if (response.ok) {
                    alert('Keys frozen successfully');
                    location.reload();
                }
            }
        }
        
        async function unfreezeSelected() {
            const keys = Array.from(selectedKeys);
            if (keys.length === 0) return alert('Please select keys first');
            if (confirm('Unfreeze ' + keys.length + ' selected keys?')) {
                const response = await fetch('/admin/api/unfreeze-keys', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ keys })
                });
                
                if (response.ok) {
                    alert('Keys unfrozen successfully');
                    location.reload();
                }
            }
        }
        
        async function deleteSelected() {
            const keys = Array.from(selectedKeys);
            if (keys.length === 0) return alert('Please select keys first');
            if (confirm('Delete ' + keys.length + ' selected keys?')) {
                const response = await fetch('/admin/api/delete-keys', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ keys })
                });
                
                if (response.ok) {
                    alert('Keys deleted successfully');
                    location.reload();
                }
            }
        }
        
        // Key generation
        function toggleExpiryInput() {
            const type = document.getElementById('expiryType').value;
            document.getElementById('daysGroup').style.display = type === 'days' ? 'block' : 'none';
            document.getElementById('dateGroup').style.display = type === 'date' ? 'block' : 'none';
        }
        
        async function generateKeys(exportFile = false) {
            const count = parseInt(document.getElementById('keyCount').value);
            const expiryType = document.getElementById('expiryType').value;
            
            let expiry;
            if (expiryType === 'days') {
                const days = parseInt(document.getElementById('expiryDays').value);
                expiry = days + ' days';
            } else {
                expiry = document.getElementById('expiryDate').value;
            }
            
            const response = await fetch('/admin/api/generate-keys', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ count, expiry, export: exportFile })
            });
            
            if (exportFile) {
                // Download file
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'keys_' + new Date().toISOString().split('T')[0] + '.txt';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                alert(count + ' keys generated and exported successfully!');
            } else {
                const result = await response.json();
                if (result.success) {
                    // Show in table
                    document.getElementById('generatedKeys').style.display = 'block';
                    const tbody = document.getElementById('newKeysBody');
                    tbody.innerHTML = '';
                    
                    // Fetch all generated keys to display
                    const keysResponse = await fetch('/admin/api/keys?limit=' + count);
                    const keysData = await keysResponse.json();
                    
                    if (keysData.results) {
                        keysData.results.slice(0, count).forEach(key => {
                            const row = document.createElement('tr');
                            // Используем конкатенацию строк вместо шаблонных строк
                            row.innerHTML = '<td><code>' + key.key + '</code></td><td>' + 
                                           new Date(key.expiry_date).toLocaleString() + '</td>';
                            tbody.appendChild(row);
                        });
                    }
                    
                    alert(count + ' keys generated successfully!');
                }
            }
        }
        
        function generateAndExport() {
            generateKeys(true);
        }
        
        // Build management
        function showAddBuildModal() {
            document.getElementById('newBuildId').value = '';
            document.getElementById('newBuildUrl').value = '';
            document.getElementById('newBuildActive').checked = true;
            showModal('addBuildModal');
        }
        
        async function saveNewBuild() {
            const build = {
                id: document.getElementById('newBuildId').value,
                url: document.getElementById('newBuildUrl').value,
                is_active: document.getElementById('newBuildActive').checked ? 1 : 0
            };
            
            if (!build.id || !build.url) {
                alert('Please fill in all fields');
                return;
            }
            
            const response = await fetch('/admin/api/builds', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(build)
            });
            
            if (response.ok) {
                closeModal('addBuildModal');
                alert('Build added successfully!');
                location.reload();
            }
        }
        
        // Process blacklist management
        function showAddProcessModal() {
            document.getElementById('newProcessName').value = '';
            showModal('addProcessModal');
        }
        
        async function saveNewProcess() {
            const process = document.getElementById('newProcessName').value.trim();
            if (!process) {
                alert('Please enter a process name');
                return;
            }
            
            const response = await fetch('/admin/api/blacklist/processes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ processes: [process] })
            });
            
            if (response.ok) {
                closeModal('addProcessModal');
                alert('Process added to blacklist!');
                location.reload();
            }
        }
        
        async function addBulkProcesses() {
            const text = document.getElementById('bulkProcesses').value;
            const processes = text.split('\\n').map(p => p.trim()).filter(p => p);
            
            if (processes.length === 0) {
                alert('Please enter at least one process');
                return;
            }
            
            const response = await fetch('/admin/api/blacklist/processes', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ processes })
            });
            
            if (response.ok) {
                alert('Added ' + processes.length + ' processes to blacklist!');
                location.reload();
            }
        }
        
        async function deleteSelectedProcesses() {
            const checkboxes = document.querySelectorAll('.process-checkbox:checked');
            const processes = Array.from(checkboxes).map(cb => cb.value);
            
            if (processes.length === 0) {
                alert('Please select processes to delete');
                return;
            }
            
            if (confirm('Delete ' + processes.length + ' selected processes?')) {
                const response = await fetch('/admin/api/blacklist/processes', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ processes })
                });
                
                if (response.ok) {
                    alert('Processes deleted from blacklist!');
                    location.reload();
                }
            }
        }
        
        // Window blacklist management
        function showAddWindowModal() {
            document.getElementById('newWindowTitle').value = '';
            showModal('addWindowModal');
        }
        
        async function saveNewWindow() {
            const window = document.getElementById('newWindowTitle').value.trim();
            if (!window) {
                alert('Please enter a window title');
                return;
            }
            
            const response = await fetch('/admin/api/blacklist/windows', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ windows: [window] })
            });
            
            if (response.ok) {
                closeModal('addWindowModal');
                alert('Window added to blacklist!');
                location.reload();
            }
        }
        
        async function addBulkWindows() {
            const text = document.getElementById('bulkWindows').value;
            const windows = text.split('\\n').map(w => w.trim()).filter(w => w);
            
            if (windows.length === 0) {
                alert('Please enter at least one window title');
                return;
            }
            
            const response = await fetch('/admin/api/blacklist/windows', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ windows })
            });
            
            if (response.ok) {
                alert('Added ' + windows.length + ' windows to blacklist!');
                location.reload();
            }
        }
        
        async function deleteSelectedWindows() {
            const checkboxes = document.querySelectorAll('.window-checkbox:checked');
            const windows = Array.from(checkboxes).map(cb => cb.value);
            
            if (windows.length === 0) {
                alert('Please select windows to delete');
                return;
            }
            
            if (confirm('Delete ' + windows.length + ' selected windows?')) {
                const response = await fetch('/admin/api/blacklist/windows', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ windows })
                });
                
                if (response.ok) {
                    alert('Windows deleted from blacklist!');
                    location.reload();
                }
            }
        }
        
        // Utility functions
        async function logout() {
            await fetch('/admin/logout');
            location.href = '/admin/panel';
        }
        
        function refreshData() {
            location.reload();
        }
        
        // Initialize
        document.addEventListener('DOMContentLoaded', () => {
            // Initialize date picker for expiry
            const tomorrow = new Date();
            tomorrow.setDate(tomorrow.getDate() + 1);
            document.getElementById('expiryDate').value = tomorrow.toISOString().slice(0, 16);
            
            // Initialize checkboxes
            document.getElementById('headerCheckbox')?.addEventListener('change', (e) => {
                const checked = e.target.checked;
                document.querySelectorAll('.key-checkbox').forEach(cb => {
                    cb.checked = checked;
                    if (checked) selectedKeys.add(cb.value);
                    else selectedKeys.delete(cb.value);
                });
            });
            
            document.querySelectorAll('.key-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => {
                    if (e.target.checked) selectedKeys.add(e.target.value);
                    else {
                        selectedKeys.delete(e.target.value);
                        document.getElementById('headerCheckbox').checked = false;
                    }
                });
            });
        });
    </script>
</body>
</html>`;
    }
};

// ========== ОСНОВНОЙ WORKER КОД ==========
export default {
    async fetch(request, env, ctx) {
        const url = new URL(request.url);
        
        try {
            // Создаем экземпляр базы данных
            const db = new Database(env.ANXIETY_CS2);
            
            // ========== ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ ==========
            if (url.pathname === '/admin/init-db') {
                try {
                    const initialized = await db.init();
                    if (initialized) {
                        return new Response('Database initialized successfully! Superuser created: XaKNMlxDWs / OMrTSqJlfxr4RtZo4W', {
                            headers: { 'Content-Type': 'text/plain' }
                        });
                    } else {
                        return new Response('Database initialization failed. Check logs.', {
                            status: 500,
                            headers: { 'Content-Type': 'text/plain' }
                        });
                    }
                } catch (error) {
                    return new Response('Init error: ' + error.message, {
                        status: 500,
                        headers: { 'Content-Type': 'text/plain' }
                    });
                }
            }
            
            // ========== АДМИН ПАНЕЛЬ ==========
            if (url.pathname.startsWith('/admin')) {
                return await handleAdminPanel(request, url, db);
            }
            
            // ========== API ЭНДПОЙНТЫ С ШИФРОВАНИЕМ ==========
            if (url.pathname.startsWith('/api')) {
                return await handleAPI(request, url, db);
            }
            
            // ========== КОРНЕВОЙ ПУТЬ ==========
            return new Response('Anxiety CS2 API Worker\n\nGo to /admin/panel to access admin interface\n\nFirst, initialize database at /admin/init-db', {
                headers: { 'Content-Type': 'text/plain' }
            });
            
        } catch (error) {
            console.error('Global error:', error);
            return new Response('Internal Server Error: ' + error.message, {
                status: 500,
                headers: { 'Content-Type': 'text/plain' }
            });
        }
    }
};

// ========== ОБРАБОТЧИК АДМИН ПАНЕЛИ ==========
async function handleAdminPanel(request, url, db) {
    // Выход из системы
    if (url.pathname === '/admin/logout') {
        return new Response(null, {
            status: 302,
            headers: {
                'Location': '/admin/panel',
                'Set-Cookie': 'admin_session=; Max-Age=0; HttpOnly; Path=/'
            }
        });
    }
    
    // Обработка логина
    if (url.pathname === '/admin/login' && request.method === 'POST') {
        try {
            const { username, password } = await request.json();
            const admin = await db.verifyAdmin(username, password);
            
            if (admin) {
                const sessionId = crypto.randomUUID();
                return new Response(null, {
                    status: 302,
                    headers: {
                        'Location': '/admin/panel',
                        'Set-Cookie': `admin_session=${sessionId}; HttpOnly; Path=/; Max-Age=86400`
                    }
                });
            }
            
            return new Response('Invalid credentials', { status: 401 });
        } catch (e) {
            return new Response('Error', { status: 500 });
        }
    }
    
    // Проверяем, инициализирована ли база данных
    const isInitialized = await db.checkInitialization();
    if (!isInitialized && url.pathname === '/admin/panel') {
        return new Response(HTML_TEMPLATES.login, {
            headers: { 'Content-Type': 'text/html' }
        });
    }
    
    // Проверка сессии
    const sessionCookie = request.headers.get('Cookie') || '';
    const hasSession = sessionCookie.includes('admin_session=');
    
    // Если не авторизован - показываем логин
    if (url.pathname === '/admin/panel' && !hasSession) {
        return new Response(HTML_TEMPLATES.login, {
            headers: { 'Content-Type': 'text/html' }
        });
    }
    
    // Если авторизован, показываем панель
    if (url.pathname === '/admin/panel' && hasSession) {
        try {
            const [keys, builds, processes, windows, stats] = await Promise.all([
                db.getAllKeys({ limit: 100 }),
                db.getAllBuilds(),
                db.getBlacklist('blacklist_processes'),
                db.getBlacklist('blacklist_windows'),
                db.getStats()
            ]);
            
            const html = HTML_TEMPLATES.main(
                { username: 'Admin' },
                keys,
                builds,
                processes,
                windows,
                stats
            );
            
            return new Response(html, {
                headers: { 'Content-Type': 'text/html' }
            });
        } catch (error) {
            console.error('Admin panel error:', error);
            return new Response('Error loading admin panel: ' + error.message, { status: 500 });
        }
    }
    
    // ========== АДМИН API ЭНДПОЙНТЫ ==========
    if (url.pathname.startsWith('/admin/api') && hasSession) {
        return await handleAdminAPI(request, url, db, { username: 'Admin' });
    }
    
    return new Response('Not Found', { status: 404 });
}

// ========== ОБРАБОТЧИК АДМИН API ==========
async function handleAdminAPI(request, url, db, admin) {
    const path = url.pathname;
    
    try {
        // Управление ключами
        if (path === '/admin/api/keys' && request.method === 'GET') {
            const { searchParams } = url;
            const filters = {
                search: searchParams.get('search'),
                limit: parseInt(searchParams.get('limit')) || 100,
                offset: parseInt(searchParams.get('offset')) || 0
            };
            
            const keys = await db.getAllKeys(filters);
            return jsonResponse(keys);
        }
        
        // Удаление ключей
        if (path === '/admin/api/delete-keys' && request.method === 'POST') {
            const { keys } = await request.json();
            await db.deleteKeys(keys);
            return jsonResponse({ success: true });
        }
        
        // Заморозка ключей
        if (path === '/admin/api/freeze-keys' && request.method === 'POST') {
            const { keys } = await request.json();
            await db.freezeKeys(keys, admin.username);
            return jsonResponse({ success: true });
        }
        
        // Разморозка ключей
        if (path === '/admin/api/unfreeze-keys' && request.method === 'POST') {
            const { keys } = await request.json();
            await db.unfreezeKeys(keys);
            return jsonResponse({ success: true });
        }
        
        // Генерация ключей с экспортом
        if (path === '/admin/api/generate-keys' && request.method === 'POST') {
            const { count, expiry, export: exportFile } = await request.json();
            
            let expiryDate;
            if (typeof expiry === 'string' && expiry.includes('days')) {
                const days = parseInt(expiry);
                expiryDate = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toISOString();
            } else {
                expiryDate = new Date(expiry).toISOString();
            }
            
            const result = await db.generateKeys(count, null, expiryDate);
            
            if (exportFile) {
                // Возвращаем текстовый файл с ключами
                const keysText = result.keys.join('\n');
                return new Response(keysText, {
                    headers: {
                        'Content-Type': 'text/plain',
                        'Content-Disposition': 'attachment; filename="keys.txt"'
                    }
                });
            } else {
                return jsonResponse(result);
            }
        }
        
        // Управление билдами
        if (path === '/admin/api/builds' && request.method === 'GET') {
            const builds = await db.getAllBuilds();
            return jsonResponse(builds);
        }
        
        if (path === '/admin/api/builds' && request.method === 'POST') {
            const build = await request.json();
            await db.createBuild(build.id, build.url, build.is_active || 1);
            return jsonResponse({ success: true });
        }
        
        if (path === '/admin/api/builds' && request.method === 'PUT') {
            const buildId = path.split('/').pop();
            const updates = await request.json();
            await db.updateBuild(buildId, updates);
            return jsonResponse({ success: true });
        }
        
        if (path.match(/^\/admin\/api\/builds\/[^\/]+$/) && request.method === 'DELETE') {
            const buildId = path.split('/').pop();
            await db.deleteBuild(buildId);
            return jsonResponse({ success: true });
        }
        
        // Управление черными списками процессов
        if (path === '/admin/api/blacklist/processes' && request.method === 'GET') {
            const processes = await db.getBlacklist('blacklist_processes');
            return jsonResponse(processes);
        }
        
        if (path === '/admin/api/blacklist/processes' && request.method === 'POST') {
            const { processes } = await request.json();
            await db.addToBlacklist(processes, 'blacklist_processes', 'admin');
            return jsonResponse({ success: true });
        }
        
        if (path === '/admin/api/blacklist/processes' && request.method === 'DELETE') {
            const { processes } = await request.json();
            await db.removeFromBlacklist(processes, 'blacklist_processes');
            return jsonResponse({ success: true });
        }
        
        // Управление черными списками окон
        if (path === '/admin/api/blacklist/windows' && request.method === 'GET') {
            const windows = await db.getBlacklist('blacklist_windows');
            return jsonResponse(windows);
        }
        
        if (path === '/admin/api/blacklist/windows' && request.method === 'POST') {
            const { windows } = await request.json();
            await db.addToBlacklist(windows, 'blacklist_windows', 'admin');
            return jsonResponse({ success: true });
        }
        
        if (path === '/admin/api/blacklist/windows' && request.method === 'DELETE') {
            const { windows } = await request.json();
            await db.removeFromBlacklist(windows, 'blacklist_windows');
            return jsonResponse({ success: true });
        }
        
    } catch (error) {
        console.error('Admin API error:', error);
        return jsonResponse({ error: error.message }, 500);
    }
    
    return jsonResponse({ error: 'Not found' }, 404);
}

// ========== ОБРАБОТЧИК API С ШИФРОВАНИЕМ ==========
async function handleAPI(request, url, db) {
    if (request.method !== 'POST') {
        return encryptedErrorResponse('Method not allowed', 405);
    }
    
    try {
        const encryptedBody = await request.text();
        const requestData = await decryptJson(encryptedBody);
        
        switch (url.pathname) {
            case '/api/auth':
                return await handleAuthAPI(requestData, db);
            case '/api/version':
                return await handleVersionAPI(requestData, db);
            case '/api/check':
                return await handleCheckAPI(requestData, db);
            default:
                return encryptedErrorResponse('Endpoint not found', 404);
        }
    } catch (error) {
        console.error('API error:', error);
        return encryptedErrorResponse('Invalid request', 400);
    }
}

// ========== API /AUTH ==========
async function handleAuthAPI(data, db) {
    const { key, uuid } = data;
    
    if (!key || !uuid) {
        return encryptedErrorResponse('Missing required fields', 400);
    }
    
    if (!isValidUUID(uuid)) {
        return encryptedErrorResponse('Invalid UUID format', 400);
    }
    
    const verification = await db.verifyKey(key, uuid);
    
    if (!verification.valid) {
        return encryptedResponse({
            success: false,
            error: verification.reason
        });
    }
    
    const keyData = verification.data;
    
    if (!keyData.uuid) {
        await db.updateKeyUUID(key, uuid);
    }
    
    return encryptedResponse({
        success: true,
        key,
        uuid,
        key_expiry: keyData.expiry_date
    });
}

// ========== API /VERSION ==========
async function handleVersionAPI(data, db) {
    const { key, uuid, build } = data;
    
    if (!key || !uuid || !build || !build.id) {
        return encryptedErrorResponse('Missing required fields', 400);
    }
    
    if (!isValidUUID(uuid)) {
        return encryptedErrorResponse('Invalid UUID format', 400);
    }
    
    const verification = await db.verifyKey(key, uuid);
    
    if (!verification.valid) {
        return encryptedResponse({
            success: false,
            error: verification.reason
        });
    }
    
    const buildData = await db.getBuild(build.id);
    
    if (!buildData) {
        return encryptedResponse({
            success: false,
            error: 'Build not found'
        });
    }
    
    return encryptedResponse({
        success: true,
        key,
        uuid,
        build: { id: build.id },
        url: buildData.url
    });
}

// ========== API /CHECK ==========
async function handleCheckAPI(data, db) {
    const { key, uuid, list_processes, list_windows } = data;
    
    if (!key || !uuid) {
        return encryptedErrorResponse('Missing required fields', 400);
    }
    
    if (!isValidUUID(uuid)) {
        return encryptedErrorResponse('Invalid UUID format', 400);
    }
    
    const verification = await db.verifyKey(key, uuid);
    
    if (!verification.valid) {
        return encryptedResponse({
            success: false,
            error: verification.reason
        });
    }
    
    const keyData = verification.data;
    
    if (list_processes && Array.isArray(list_processes)) {
        const blacklistedProcesses = await db.checkBlacklist(list_processes, 'blacklist_processes');
        if (blacklistedProcesses.length > 0) {
            await db.deleteKey(key);
            return encryptedResponse({
                success: false,
                error: 'Blacklisted process detected',
                banned: true
            });
        }
    }
    
    if (list_windows && Array.isArray(list_windows)) {
        const blacklistedWindows = await db.checkBlacklist(list_windows, 'blacklist_windows');
        if (blacklistedWindows.length > 0) {
            await db.deleteKey(key);
            return encryptedResponse({
                success: false,
                error: 'Blacklisted window detected',
                banned: true
            });
        }
    }
    
    return encryptedResponse({
        success: true,
        key,
        uuid,
        key_expiry: keyData.expiry_date
    });
}

// ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
function jsonResponse(data, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: { 
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        }
    });
}

async function encryptedResponse(data) {
    const encrypted = await encryptJson(data);
    return new Response(encrypted, {
        headers: { 
            'Content-Type': 'text/plain',
            'Access-Control-Allow-Origin': '*'
        }
    });
}

async function encryptedErrorResponse(message, status = 400) {
    return encryptedResponse({ 
        success: false, 
        error: message 
    });
}
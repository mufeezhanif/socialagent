/**
 * Baileys auth state stored in Postgres (encrypted with AES-256-GCM), so redeploys don't force re-pairing.
 * Falls back to Baileys' file store for local development without Postgres.
 */
import crypto from 'node:crypto'
import { rm } from 'node:fs/promises'
import pg from 'pg'
import {
  BufferJSON,
  initAuthCreds,
  proto,
  useMultiFileAuthState,
  type AuthenticationCreds,
  type SignalDataSet,
  type SignalDataTypeMap,
  type SignalKeyStore,
} from 'baileys'
import { config, usesPostgres } from './config.js'

export interface AuthStore {
  creds: AuthenticationCreds
  keys: SignalKeyStore
  saveCreds: () => Promise<void>
  clear: () => Promise<void>
}

function cipher(secret: string) {
  const key = crypto.createHash('sha256').update(secret).digest()
  return {
    encrypt(text: string): string {
      const iv = crypto.randomBytes(12)
      const c = crypto.createCipheriv('aes-256-gcm', key, iv)
      const body = Buffer.concat([c.update(text, 'utf8'), c.final()])
      return Buffer.concat([iv, c.getAuthTag(), body]).toString('base64')
    },
    decrypt(b64: string): string {
      const buf = Buffer.from(b64, 'base64')
      const d = crypto.createDecipheriv('aes-256-gcm', key, buf.subarray(0, 12))
      d.setAuthTag(buf.subarray(12, 28))
      return Buffer.concat([d.update(buf.subarray(28)), d.final()]).toString('utf8')
    },
  }
}

let pool: pg.Pool | null = null

export function getPool(): pg.Pool {
  if (!pool) {
    const needsSsl = /sslmode=(require|verify)/.test(config.databaseUrl)
    pool = new pg.Pool({
      connectionString: config.databaseUrl,
      max: 4,
      ssl: needsSsl ? { rejectUnauthorized: false } : undefined,
    })
  }
  return pool
}

async function postgresStore(): Promise<AuthStore> {
  const db = getPool()
  const box = cipher(config.encryptionKey)
  await db.query(
    'CREATE TABLE IF NOT EXISTS wa_auth (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TIMESTAMPTZ DEFAULT now())',
  )
  const decode = (value: string) => {
    try {
      return JSON.parse(box.decrypt(value), BufferJSON.reviver)
    } catch {
      return null
    }
  }
  const read = async (key: string) => {
    const res = await db.query('SELECT value FROM wa_auth WHERE key = $1', [key])
    return res.rowCount ? decode(res.rows[0].value) : null
  }
  const upsert = 'INSERT INTO wa_auth (key, value, updated_at) VALUES ($1, $2, now()) ' +
    'ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()'

  const creds: AuthenticationCreds = (await read('creds')) || initAuthCreds()
  const keys: SignalKeyStore = {
    async get<T extends keyof SignalDataTypeMap>(type: T, ids: string[]) {
      const out: { [id: string]: SignalDataTypeMap[T] } = {}
      if (!ids.length) return out
      const res = await db.query('SELECT key, value FROM wa_auth WHERE key = ANY($1)', [ids.map((id) => `${type}-${id}`)])
      const byKey = new Map<string, string>(res.rows.map((r: { key: string; value: string }) => [r.key, r.value]))
      for (const id of ids) {
        const raw = byKey.get(`${type}-${id}`)
        let value = raw ? decode(raw) : null
        if (type === 'app-state-sync-key' && value) value = proto.Message.AppStateSyncKeyData.fromObject(value)
        if (value) out[id] = value
      }
      return out
    },
    async set(data: SignalDataSet) {
      const client = await db.connect()
      try {
        await client.query('BEGIN')
        for (const category of Object.keys(data) as (keyof SignalDataSet)[]) {
          for (const [id, value] of Object.entries(data[category] || {})) {
            const key = `${category}-${id}`
            if (value) await client.query(upsert, [key, box.encrypt(JSON.stringify(value, BufferJSON.replacer))])
            else await client.query('DELETE FROM wa_auth WHERE key = $1', [key])
          }
        }
        await client.query('COMMIT')
      } catch (err) {
        await client.query('ROLLBACK')
        throw err
      } finally {
        client.release()
      }
    },
  }
  return {
    creds,
    keys,
    saveCreds: async () => {
      await db.query(upsert, ['creds', box.encrypt(JSON.stringify(creds, BufferJSON.replacer))])
    },
    clear: async () => {
      await db.query('DELETE FROM wa_auth')
    },
  }
}

async function fileStore(): Promise<AuthStore> {
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir)
  return {
    creds: state.creds,
    keys: state.keys,
    saveCreds,
    clear: async () => {
      await rm(config.authDir, { recursive: true, force: true })
    },
  }
}

export async function createAuthStore(): Promise<AuthStore> {
  return usesPostgres ? postgresStore() : fileStore()
}

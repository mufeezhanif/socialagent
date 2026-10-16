import path from 'node:path'

const env = process.env

export const config = {
  port: Number(env.GATEWAY_PORT || 3001),
  host: env.GATEWAY_HOST || '127.0.0.1',
  apiUrl: (env.API_URL || 'http://127.0.0.1:8000').replace(/\/$/, ''),
  secret: env.INTERNAL_SHARED_SECRET || 'dev-only-internal-secret-change-me',
  encryptionKey: env.TOKEN_ENCRYPTION_KEY || env.JWT_SECRET || 'dev-only-jwt-secret-change-me',
  databaseUrl: (env.DATABASE_URL || '').replace('+asyncpg', ''),
  authDir: env.WA_AUTH_DIR || path.resolve('wa-auth'),
  mediaDir: path.resolve(env.MEDIA_DIR || '../backend/data/media'),
  maxUploadMb: Number(env.MAX_UPLOAD_MB || 100),
  enabled: (env.WA_ENABLED || 'true').toLowerCase() !== 'false',
  logLevel: env.LOG_LEVEL || 'warn',
}

export const usesPostgres = config.databaseUrl.startsWith('postgres')

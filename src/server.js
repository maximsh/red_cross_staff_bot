import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { initDb } from './database.js';
import { createBot } from './bot.js';
import { createApiRouter } from './api.js';

const __dirname = dirname(fileURLToPath(import.meta.url));

// Config
const BOT_TOKEN = process.env.BOT_TOKEN;
const WEBAPP_URL = process.env.WEBAPP_URL || `http://localhost:${process.env.PORT || 3000}`;
const PORT = parseInt(process.env.PORT || '3000', 10);

if (!BOT_TOKEN) {
  console.error('❌ BOT_TOKEN is required. Set it in .env file.');
  console.error('   Create a bot via @BotFather on Telegram to get a token.');
  process.exit(1);
}

// Initialize database
console.log('📦 Initializing database...');
initDb();
console.log('✅ Database ready');

// Create Express app
const app = express();
app.use(cors());
app.use(express.json());

// Serve static files (Mini App)
app.use(express.static(join(__dirname, '..', 'public')));

// Mount API routes
const apiRouter = createApiRouter(BOT_TOKEN);
app.use(apiRouter);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Start Express server
app.listen(PORT, () => {
  console.log(`🌐 Server running at http://localhost:${PORT}`);
  console.log(`📋 Employee app: ${WEBAPP_URL}/employee/`);
  console.log(`📊 Dashboard: ${WEBAPP_URL}/dashboard/`);
});

// Start Telegram bot (long polling)
console.log('🤖 Starting Telegram bot...');
const APP_SHORT_NAME = process.env.APP_SHORT_NAME || 'staff';
const bot = createBot(BOT_TOKEN, WEBAPP_URL, APP_SHORT_NAME);

bot.start({
  onStart: (botInfo) => {
    console.log(`✅ Bot @${botInfo.username} is running`);
  },
});

// Graceful shutdown
const shutdown = async () => {
  console.log('\n🛑 Shutting down...');
  await bot.stop();
  process.exit(0);
};

process.on('SIGINT', shutdown);
process.on('SIGTERM', shutdown);

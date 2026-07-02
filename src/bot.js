import { Bot, InlineKeyboard, Keyboard } from 'grammy';
import {
  upsertEmployee,
  recordEvent,
  getCurrentStatus,
  getValidActions,
  getAllStatuses,
} from './database.js';

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function createBot(token, webAppUrl, appShortName) {
  const bot = new Bot(token);

  let botUsername = '';

  // Error handler
  bot.catch((err) => {
    console.error('Bot error:', err.message || err);
  });

  // Capture bot username on start
  bot.use(async (ctx, next) => {
    if (!botUsername && ctx.me?.username) {
      botUsername = ctx.me.username;
    }

    // Auto-register users on any interaction
    if (ctx.from) {
      upsertEmployee(
        ctx.from.id,
        ctx.from.first_name,
        ctx.from.last_name || '',
        ctx.from.username || ''
      );
    }
    await next();
  });

  /**
   * Check if chat is private.
   */
  function isPrivate(ctx) {
    return ctx.chat?.type === 'private';
  }

  /**
   * Build persistent Reply Keyboard (below the input field) for private chats.
   */
  function buildPrivateKeyboard() {
    return new Keyboard()
      .webApp('📋 Відмітитися 🏢', `${webAppUrl}/`)
      .row()
      .webApp('📊 Панель контролю 👥', `${webAppUrl}/?tgWebAppStartParam=dashboard`)
      .resized();
  }

  /**
   * General handler for text commands that update status without opening the Mini App.
   */
  async function handleQuickAction(ctx, eventType, successMsg, actionName) {
    const user = ctx.from;
    if (!user) return;

    // Ensure user is registered in the database
    upsertEmployee(user.id, user.first_name, user.last_name || '', user.username || '');

    const currentStatus = getCurrentStatus(user.id);
    const status = currentStatus?.status || 'offline';
    const validActions = getValidActions(status);

    if (!validActions.includes(eventType)) {
      const statusMap = {
        offline: 'не на роботі (офлайн)',
        in_office: 'в офісі',
        field_trip: 'на виїзді',
      };
      return await ctx.reply(
        `❌ <b>${escapeHtml(user.first_name)}</b>, не можна зробити "${actionName}", оскільки ваш статус: <b>${statusMap[status]}</b>.`,
        { parse_mode: 'HTML' }
      );
    }

    // Record the status update in the database
    recordEvent(user.id, eventType);

    // Format local time (Europe/Kyiv, UTC+3)
    const now = new Date();
    const kyivTime = new Date(now.getTime() + 3 * 60 * 60 * 1000);
    const hours = String(kyivTime.getUTCHours()).padStart(2, '0');
    const minutes = String(kyivTime.getUTCMinutes()).padStart(2, '0');
    const timeStr = `${hours}:${minutes}`;

    const displayName = `${user.first_name} ${user.last_name || ''}`.trim();
    await ctx.reply(
      `${successMsg} <b>${escapeHtml(displayName)}</b> о <b>${timeStr}</b>`,
      { parse_mode: 'HTML' }
    );
  }

  /**
   * Helper to format active employee status text.
   */
  function buildActiveStatusReport() {
    const statuses = getAllStatuses();
    const activeEmployees = statuses.filter(
      (emp) => emp.status === 'in_office' || emp.status === 'field_trip'
    );

    if (activeEmployees.length === 0) {
      return '👥 Зараз нікого немає на роботі.';
    }

    const formatTime = (isoString) => {
      if (!isoString) return '';
      const date = new Date(isoString);
      const kyivTime = new Date(date.getTime() + 3 * 60 * 60 * 1000);
      const hours = String(kyivTime.getUTCHours()).padStart(2, '0');
      const minutes = String(kyivTime.getUTCMinutes()).padStart(2, '0');
      return `${hours}:${minutes}`;
    };

    let text = '<b>📋 Зараз на роботі:</b>\n\n';

    activeEmployees.forEach((emp) => {
      const name = `${emp.first_name} ${emp.last_name || ''}`.trim();
      const timeStr = emp.last_event_at ? formatTime(emp.last_event_at) : '';
      
      if (emp.status === 'in_office') {
        text += `🟢 <b>${escapeHtml(name)}</b> (в офісі з ${timeStr})\n`;
      } else if (emp.status === 'field_trip') {
        text += `🟡 <b>${escapeHtml(name)}</b> (на виїзді з ${timeStr})\n`;
      }
    });

    return text;
  }

  // Quick Action Commands (English & Ukrainian aliases)
  
  // 1. Check-in (Я на місці)
  bot.command(['in', 'checkin', 'tut', 'priyshov', 'прийшов', 'тут', 'офіс'], (ctx) =>
    handleQuickAction(ctx, 'checkin', '🟢 На місці:', 'прихід')
  );

  // 2. Out on a trip (Виїзд по місту)
  bot.command(['away', 'trip', 'viizd', 'poihav', 'виїзд', 'виїхав', 'поїхав'], (ctx) =>
    handleQuickAction(ctx, 'field_start', '🚗 Виїхав:', 'виїзд')
  );

  // 3. Return from trip (Повернувся з виїзду)
  bot.command(['back', 'return', 'povernuvsya', 'ofis', 'повернувся', 'назад'], (ctx) =>
    handleQuickAction(ctx, 'field_end', '↩️ Повернувся в офіс:', 'повернення')
  );

  // 4. Check-out (Пішов додому)
  bot.command(['out', 'checkout', 'dodomu', 'pishov', 'пішов', 'додому', 'пока'], (ctx) =>
    handleQuickAction(ctx, 'checkout', '🏠 Пішов додому:', 'вихід')
  );

  // /start command
  bot.command('start', async (ctx) => {
    if (!isPrivate(ctx)) {
      // In groups/channels: inline button to open Bot Link
      const keyboard = new InlineKeyboard()
        .url('📋 Відкрити систему', `https://t.me/${botUsername}/${appShortName}`);

      return await ctx.reply(
        '👋 Робота з системою контролю присутності відбувається через особистий діалог з ботом.',
        { reply_markup: keyboard }
      );
    }

    // Private chat: Send persistent keyboard below the text input field
    const keyboard = buildPrivateKeyboard();

    await ctx.reply(
      '👋 *Вітаю\\!*\n\n' +
      'Кнопки для управління системою тепер знаходяться *внизу екрана* (замість звичайної клавіатури)\\.\n\n' +
      'Оберіть потрібну дію:',
      {
        parse_mode: 'MarkdownV2',
        reply_markup: keyboard,
      }
    );
  });

  // /dashboard command
  bot.command('dashboard', async (ctx) => {
    if (!isPrivate(ctx)) {
      const keyboard = new InlineKeyboard()
        .url('📊 Панель контролю', `https://t.me/${botUsername}/${appShortName}?startapp=dashboard`);

      return await ctx.reply(
        '📊 Панель контролю відкривається в особистому чаті з ботом:',
        { reply_markup: keyboard }
      );
    }

    const keyboard = buildPrivateKeyboard();
    await ctx.reply(
      '📊 Панель контролю доступна на клавіатурі знизу:',
      { reply_markup: keyboard }
    );
  });

  // /status command — Lists active employees (who are still at work)
  bot.command('status', async (ctx) => {
    const reportText = buildActiveStatusReport();
    const chatPrivate = isPrivate(ctx);

    const keyboard = new InlineKeyboard();
    if (chatPrivate) {
      keyboard.webApp('📊 Панель контролю', `${webAppUrl}/?tgWebAppStartParam=dashboard`);
    } else {
      keyboard.url('📊 Панель контролю', `https://t.me/${botUsername}/${appShortName}?startapp=dashboard`);
    }

    await ctx.reply(reportText, {
      parse_mode: 'HTML',
      reply_markup: keyboard,
    });
  });

  // Handle any other text (ONLY in private chat)
  bot.on('message:text', async (ctx) => {
    if (!isPrivate(ctx)) return; // Ignore messages in groups and supergroups

    const keyboard = buildPrivateKeyboard();

    await ctx.reply(
      'Використовуйте кнопки на клавіатурі внизу екрана для взаємодії з системою.',
      { reply_markup: keyboard }
    );
  });

  // Handle channel posts (channels send channel_post instead of message)
  bot.on('channel_post:text', async (ctx) => {
    const text = ctx.channelPost?.text || '';

    if (text.startsWith('/start')) {
      const keyboard = new InlineKeyboard()
        .url('📋 Відкрити систему', `https://t.me/${botUsername}/${appShortName}`);

      await ctx.reply(
        '👋 Робота з системою відбувається через особистий діалог з ботом:',
        { reply_markup: keyboard }
      );
    } else if (text.startsWith('/status')) {
      const reportText = buildActiveStatusReport();
      const keyboard = new InlineKeyboard()
        .url('📊 Панель контролю', `https://t.me/${botUsername}/${appShortName}?startapp=dashboard`);

      await ctx.reply(reportText, {
        parse_mode: 'HTML',
        reply_markup: keyboard,
      });
    } else if (text.startsWith('/dashboard')) {
      const keyboard = new InlineKeyboard()
        .url('📊 Панель контролю', `https://t.me/${botUsername}/${appShortName}?startapp=dashboard`);

      await ctx.reply(
        '📊 Панель контролю команди:',
        { reply_markup: keyboard }
      );
    }
  });

  return bot;
}

import crypto from 'crypto';

/**
 * Validate Telegram Mini App initData
 * https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
 */
export function validateInitData(botToken, initData) {
  try {
    const params = new URLSearchParams(initData);
    const hash = params.get('hash');

    if (!hash) return null;

    params.delete('hash');

    // Sort parameters alphabetically
    const sortedParams = Array.from(params.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, value]) => `${key}=${value}`)
      .join('\n');

    // Create secret key: HMAC-SHA256 of bot token with "WebAppData" as key
    const secretKey = crypto
      .createHmac('sha256', 'WebAppData')
      .update(botToken)
      .digest();

    // Calculate hash
    const calculatedHash = crypto
      .createHmac('sha256', secretKey)
      .update(sortedParams)
      .digest('hex');

    if (hash !== calculatedHash) return null;

    // Check auth_date freshness (allow up to 1 hour)
    const authDate = parseInt(params.get('auth_date'), 10);
    const now = Math.floor(Date.now() / 1000);
    if (now - authDate > 3600) return null;

    // Parse user data
    const userStr = params.get('user');
    if (!userStr) return null;

    return JSON.parse(userStr);
  } catch (err) {
    console.error('initData validation error:', err.message);
    return null;
  }
}

/**
 * Express middleware for Telegram Mini App auth
 */
export function authMiddleware(botToken) {
  return (req, res, next) => {
    const initData = req.headers['x-telegram-init-data'];

    if (!initData) {
      return res.status(401).json({ error: 'Missing initData' });
    }

    const user = validateInitData(botToken, initData);

    if (!user) {
      return res.status(401).json({ error: 'Invalid or expired initData' });
    }

    req.telegramUser = user;
    next();
  };
}

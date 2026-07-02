import { Router } from 'express';
import { authMiddleware } from './auth.js';
import {
  upsertEmployee,
  recordEvent,
  getCurrentStatus,
  getAllStatuses,
  getTodayEvents,
  getValidActions,
} from './database.js';

export function createApiRouter(botToken) {
  const router = Router();
  const auth = authMiddleware(botToken);

  /**
   * POST /api/checkin — Employee arrives at work
   */
  router.post('/api/checkin', auth, (req, res) => {
    try {
      const user = req.telegramUser;
      upsertEmployee(user.id, user.first_name, user.last_name || '', user.username || '');

      const currentStatus = getCurrentStatus(user.id);
      const validActions = getValidActions(currentStatus?.status || 'offline');

      if (!validActions.includes('checkin')) {
        return res.status(400).json({
          error: 'Не можна зареєструвати прихід у поточному стані',
          currentStatus: currentStatus?.status,
        });
      }

      const result = recordEvent(user.id, 'checkin', req.body.note || '');
      res.json({ success: true, ...result });
    } catch (err) {
      console.error('Checkin error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * POST /api/checkout — Employee leaves for home
   */
  router.post('/api/checkout', auth, (req, res) => {
    try {
      const user = req.telegramUser;

      const currentStatus = getCurrentStatus(user.id);
      const validActions = getValidActions(currentStatus?.status || 'offline');

      if (!validActions.includes('checkout')) {
        return res.status(400).json({
          error: 'Не можна зареєструвати вихід у поточному стані',
          currentStatus: currentStatus?.status,
        });
      }

      const result = recordEvent(user.id, 'checkout', req.body.note || '');
      res.json({ success: true, ...result });
    } catch (err) {
      console.error('Checkout error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * POST /api/field-start — Employee leaves for field trip
   */
  router.post('/api/field-start', auth, (req, res) => {
    try {
      const user = req.telegramUser;

      const currentStatus = getCurrentStatus(user.id);
      const validActions = getValidActions(currentStatus?.status || 'offline');

      if (!validActions.includes('field_start')) {
        return res.status(400).json({
          error: 'Не можна почати виїзд у поточному стані',
          currentStatus: currentStatus?.status,
        });
      }

      const result = recordEvent(user.id, 'field_start', req.body.note || '');
      res.json({ success: true, ...result });
    } catch (err) {
      console.error('Field start error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * POST /api/field-end — Employee returns from field trip
   */
  router.post('/api/field-end', auth, (req, res) => {
    try {
      const user = req.telegramUser;

      const currentStatus = getCurrentStatus(user.id);
      const validActions = getValidActions(currentStatus?.status || 'offline');

      if (!validActions.includes('field_end')) {
        return res.status(400).json({
          error: 'Не можна завершити виїзд у поточному стані',
          currentStatus: currentStatus?.status,
        });
      }

      const result = recordEvent(user.id, 'field_end', req.body.note || '');
      res.json({ success: true, ...result });
    } catch (err) {
      console.error('Field end error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /api/status/:telegramId — Get employee's current status
   */
  router.get('/api/status/:telegramId', auth, (req, res) => {
    try {
      const telegramId = parseInt(req.params.telegramId, 10);
      const status = getCurrentStatus(telegramId);

      if (!status) {
        return res.status(404).json({ error: 'Працівника не знайдено' });
      }

      const validActions = getValidActions(status.status);
      res.json({ ...status, validActions });
    } catch (err) {
      console.error('Status error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /api/my-status — Get current user's status
   */
  router.get('/api/my-status', auth, (req, res) => {
    try {
      const user = req.telegramUser;
      upsertEmployee(user.id, user.first_name, user.last_name || '', user.username || '');

      const status = getCurrentStatus(user.id);
      const validActions = getValidActions(status?.status || 'offline');
      const todayEvents = getTodayEvents(user.id);

      res.json({
        ...(status || { status: 'offline' }),
        validActions,
        todayEvents,
      });
    } catch (err) {
      console.error('My status error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /api/statuses — Get all employees' statuses (for dashboard)
   */
  router.get('/api/statuses', auth, (req, res) => {
    try {
      const statuses = getAllStatuses();

      const summary = {
        in_office: statuses.filter(s => s.status === 'in_office').length,
        field_trip: statuses.filter(s => s.status === 'field_trip').length,
        offline: statuses.filter(s => s.status === 'offline').length,
        total: statuses.length,
      };

      res.json({ employees: statuses, summary });
    } catch (err) {
      console.error('Statuses error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  /**
   * GET /api/today/:telegramId — Get today's events for an employee
   */
  router.get('/api/today/:telegramId', auth, (req, res) => {
    try {
      const telegramId = parseInt(req.params.telegramId, 10);
      const events = getTodayEvents(telegramId);
      res.json({ events });
    } catch (err) {
      console.error('Today events error:', err);
      res.status(500).json({ error: 'Internal server error' });
    }
  });

  return router;
}

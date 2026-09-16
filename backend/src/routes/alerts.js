const express = require('express');
const db = require('../db');
const { authRequired } = require('../middleware/auth');

const router = express.Router();

router.get('/', authRequired, (req, res) => {
  const alerts = db.get('alerts').sortBy('createdAt').takeRight(50).reverse().value();
  res.json({ alerts });
});

module.exports = router;

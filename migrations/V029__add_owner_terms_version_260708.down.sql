DELETE tv FROM terms_version tv
JOIN terms t ON tv.term_id = t.id
WHERE t.target = 'owner'
  AND t.term_type IN ('PRIVACY', 'PRIVACY_CONSENT')
  AND tv.version = '260708';

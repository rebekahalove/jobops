-- Promote one existing active JobOps user to admin.
-- Replace the email below before running this in Neon or psql.
--
-- This intentionally updates exactly one active user by normalized email.
-- If the final SELECT returns no rows, rollback and check the email.

BEGIN;

UPDATE users
SET user_type = 'admin',
    updated_at = now()
WHERE email = lower(trim('REPLACE_WITH_YOUR_JOBOPS_EMAIL@example.com'))
  AND status = 'active';

SELECT id, email, username, user_type, status, updated_at
FROM users
WHERE email = lower(trim('REPLACE_WITH_YOUR_JOBOPS_EMAIL@example.com'));

COMMIT;
